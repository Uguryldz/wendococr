"""
OCR Worker Pool — n8n tarzı main/worker ayrımı.

REDIS_URL boşsa  → Local mod: ProcessPoolExecutor (tek makine).
REDIS_URL doluysa → Redis mod: main sadece kuyruğa atar, worker'lar işler.

Main (API):
    docker compose up wendococr
    - HTTP alır, Redis kuyruğuna atar, sonucu bekler, döner.
    - OCR yapmaz, hafif container (512MB yeter).

Worker:
    docker compose up --scale wendococr-worker=5
    - Redis'ten iş alır, OCR yapar, sonucu Redis'e yazar.
    - İstediğin kadar scale et.

    python -m app.core.worker_pool
"""
import asyncio
import json
import logging
import os
import signal
import time
import base64
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from app.config import (
    OCR_MAX_WORKERS,
    OCR_QUEUE_MAX_SIZE,
    OCR_QUEUE_TIMEOUT,
    REDIS_URL,
    REDIS_QUEUE_NAME,
    REDIS_RESULT_TTL,
    JOB_FILE_INLINE,
    REAPER_INTERVAL_SEC,
    JOB_HARD_MAX_SEC,
    UPLOAD_DIR,
)

logger = logging.getLogger("wendococr.pool")

WORKER_HEARTBEAT_KEY = "wendococr:workers"
WORKER_HEARTBEAT_TTL = 30  # saniye — 30s heartbeat gelmezse ölü sayılır
# Payload'a gömülü dosyanın args içindeki yer tutucusu (worker kendi yerel yoluyla değiştirir)
_FILE_PLACEHOLDER = "__WENDOCOCR_FILE__"
PROCESSING_META_KEY = f"{REDIS_QUEUE_NAME}:processing_meta"  # job_id -> {worker_id, started_at}

# GUVENLIK (K1): Worker, kuyruktan gelen iste GÖRE rastgele fonksiyon CAGIRMAZ.
# Sadece bu allowlist'teki güvenli fonksiyonlar çalıştırılabilir. Job, fonksiyonu
# "module.qualname" yerine bu sözlükteki KISA ANAHTAR ile referans verir.
# Boylece Redis'e zararli payload yazan biri (auth + JSON sayesinde zaten zor)
# os.system gibi keyfi cagri yaptiramaz. Kuyruk JSON tasir (pickle RCE kapatildi).
_ALLOWED_FUNCTIONS: dict[str, str] = {
    "process_document": "app.core.router:process_document",
}
_FN_CACHE: dict[str, Callable] = {}


def _resolve_allowed(fn_key: str) -> Callable:
    """Allowlist anahtarini gercek fonksiyona cevirir; bilinmeyen anahtar reddedilir."""
    if fn_key not in _ALLOWED_FUNCTIONS:
        raise ValueError(f"İzin verilmeyen fonksiyon: {fn_key!r}")
    if fn_key in _FN_CACHE:
        return _FN_CACHE[fn_key]
    import importlib
    module_path, _, name = _ALLOWED_FUNCTIONS[fn_key].partition(":")
    fn = getattr(importlib.import_module(module_path), name)
    _FN_CACHE[fn_key] = fn
    return fn


def _fn_key_for(fn: Callable) -> str:
    """Bir fonksiyonun allowlist anahtarini bulur; allowlist disiysa hata verir."""
    target = f"{fn.__module__}:{fn.__qualname__}"
    for key, path in _ALLOWED_FUNCTIONS.items():
        if path == target:
            return key
    raise ValueError(f"Allowlist disi fonksiyon submit edilemez: {target}")


def _redis_client():
    """
    Tüm Redis bağlantıları buradan. FAILOVER SERTLEŞTİRMESİ (aktif-aktif, önde VIP/proxy):
    VIP yeni master'a geçince eski bağlantı kopar; bu komutu 500'e düşürmek yerine üstel
    bekleme ile yeniden dene (~0.1s..2s, 5 deneme). Replica yeni master olurken kısa süre
    LOADING döner -> BusyLoadingError da yeniden denenir. health_check_interval: boşta
    kalmış bağlantıyı kullanmadan önce PING ile yoklar, ölüyse sessizce yeniler.

    TimeoutError BİLEREK retry DIŞINDA: bu kodda blocking pop'un (brpoplpush/blpop)
    normal "iş yok" sinyali. Varsayılan Retry onu da deniyor; buraya girerse worker
    döngüsünün heartbeat/reaper zamanlaması bozulur. Kendi Retry'ımız onu kapsamaz.
    """
    import redis
    from redis.backoff import ExponentialBackoff
    from redis.exceptions import BusyLoadingError
    from redis.exceptions import ConnectionError as RedisConnectionError
    from redis.retry import Retry
    retry = Retry(
        ExponentialBackoff(cap=2.0, base=0.1),
        retries=5,
        supported_errors=(RedisConnectionError, BusyLoadingError),
    )
    return redis.Redis.from_url(
        REDIS_URL,
        decode_responses=False,
        retry=retry,
        retry_on_error=[RedisConnectionError, BusyLoadingError],
        health_check_interval=30,
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# LOCAL MOD (Redis yok, tek makine)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class LocalWorkerPool:
    """Process-based worker pool (tek makine, n8n'e gerek yok)."""

    def __init__(self):
        self._executor = ThreadPoolExecutor(
            max_workers=OCR_MAX_WORKERS,
        )
        self._semaphore = asyncio.Semaphore(OCR_MAX_WORKERS)
        self._queue_semaphore = asyncio.Semaphore(OCR_QUEUE_MAX_SIZE)
        self._active = 0
        self._waiting = 0
        self._processed = 0
        self._failed = 0
        self._rejected = 0
        self._timed_out = 0
        logger.info("Local mod: %d worker, %d kuyruk", OCR_MAX_WORKERS, OCR_QUEUE_MAX_SIZE)

    async def submit(self, fn: Callable, *args, **kwargs) -> Any:
        if not self._queue_semaphore._value:
            self._rejected += 1
            raise QueueFullError(f"Kuyruk dolu ({OCR_QUEUE_MAX_SIZE}). Aktif: {self._active}")

        await self._queue_semaphore.acquire()
        self._waiting += 1

        try:
            try:
                async with asyncio.timeout(OCR_QUEUE_TIMEOUT):
                    await self._semaphore.acquire()
            except TimeoutError:
                self._timed_out += 1
                raise QueueTimeoutError(f"Timeout ({OCR_QUEUE_TIMEOUT}s). Aktif: {self._active}")

            self._waiting -= 1
            self._active += 1

            try:
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    self._executor, lambda: fn(*args, **kwargs),
                )
                self._processed += 1
                return result
            except Exception:
                self._failed += 1
                raise
            finally:
                self._active -= 1
                self._semaphore.release()
        finally:
            self._queue_semaphore.release()

    def status(self) -> dict:
        return {
            "mode": "local",
            "workers_total": OCR_MAX_WORKERS,
            "workers_active": self._active,
            "queue_waiting": self._waiting,
            "queue_max": OCR_QUEUE_MAX_SIZE,
            "processed": self._processed,
            "failed": self._failed,
            "rejected": self._rejected,
            "timed_out": self._timed_out,
            "timeout_sec": OCR_QUEUE_TIMEOUT,
        }

    def shutdown(self):
        self._executor.shutdown(wait=True, cancel_futures=True)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# REDIS MOD (main/worker ayrı container)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class RedisWorkerPool:
    """
    Redis-backed pool — main (API) tarafı.
    İşi Redis'e atar, sonucu bekler. OCR yapmaz.
    """

    def __init__(self):
        self._redis = _redis_client()
        self._redis.ping()
        self._processed = 0
        self._failed = 0
        self._rejected = 0
        self._timed_out = 0
        logger.info("Redis mod (main): %s", REDIS_URL)

    async def submit(self, fn: Callable, *args, **kwargs) -> Any:
        queue_len = self._redis.llen(REDIS_QUEUE_NAME)
        if queue_len >= OCR_QUEUE_MAX_SIZE:
            self._rejected += 1
            raise QueueFullError(f"Kuyruk dolu ({queue_len}/{OCR_QUEUE_MAX_SIZE}).")

        job_id = str(uuid.uuid4())
        result_key = f"wendococr:result:{job_id}"
        # GUVENLIK (K1): fonksiyon allowlist anahtariyla referans verilir, JSON tasinir.
        # args icindeki Path -> str (JSON-uyumlu); process_document Path|str kabul eder.
        # ÇOK-MAKİNE (JOB_FILE_INLINE): ilk dosya argümanını base64 ile payload'a göm.
        # Worker kendi tmpfs'ine yazıp işler; API ile aynı volume'u paylaşmak zorunda kalmaz.
        # Kapalıysa eski davranış: yol (str) gönderilir, worker aynı makinede olmalı.
        job_args: list = []
        file_b64 = None
        file_name = None
        for a in args:
            if JOB_FILE_INLINE and file_b64 is None and isinstance(a, os.PathLike) and Path(a).is_file():
                file_b64 = base64.b64encode(Path(a).read_bytes()).decode("ascii")
                file_name = Path(a).name
                job_args.append(_FILE_PLACEHOLDER)
            else:
                job_args.append(str(a) if isinstance(a, os.PathLike) else a)
        job: dict = {
            "job_id": job_id,
            "fn_key": _fn_key_for(fn),
            "args": job_args,
            "kwargs": kwargs,
            "submitted_at": time.time(),
        }
        if file_b64 is not None:
            job["file_b64"] = file_b64
            job["file_name"] = file_name
        job_data = json.dumps(job).encode("utf-8")

        self._redis.lpush(REDIS_QUEUE_NAME, job_data)

        loop = asyncio.get_event_loop()
        try:
            result = await asyncio.wait_for(
                loop.run_in_executor(None, self._wait_result, result_key),
                timeout=OCR_QUEUE_TIMEOUT,
            )
        except asyncio.TimeoutError:
            self._timed_out += 1
            # SONUCU SİLME: worker işi yine de bitirip result_key'e TTL ile yazar. Eskiden
            # delete() işi çöpe atıyordu. İstemci şimdilik 504 alır; job_id loglanır ki
            # async iş API'si eklendiğinde sonuç geri alınabilsin.
            logger.warning("Timeout (%ss) job=%s — sonuç Redis'te TTL ile bekliyor", OCR_QUEUE_TIMEOUT, job_id)
            raise QueueTimeoutError(f"Timeout ({OCR_QUEUE_TIMEOUT}s): {job_id}")

        if result.get("error"):
            self._failed += 1
            raise RuntimeError(result["error"])

        self._processed += 1
        return result["data"]

    def _wait_result(self, result_key: str) -> dict:
        import redis
        r = _redis_client()
        try:
            while True:
                # redis-py 8+: sonuc henuz yokken blpop None yerine TimeoutError firlatir.
                # Bu "hazir degil" demek — beklemeye devam et (ust katmanda
                # OCR_QUEUE_TIMEOUT zaten genel sureyi sinirliyor).
                try:
                    raw = r.blpop(result_key, timeout=2)
                except redis.exceptions.TimeoutError:
                    continue
                if raw:
                    return json.loads(raw[1])
        finally:
            r.close()

    def status(self) -> dict:
        try:
            queue_len = self._redis.llen(REDIS_QUEUE_NAME)
            processing = self._redis.llen(f"{REDIS_QUEUE_NAME}:processing")
            # Aktif worker sayısı (heartbeat)
            worker_keys = self._redis.hgetall(WORKER_HEARTBEAT_KEY)
            now = time.time()
            alive_workers = sum(
                1 for ts in worker_keys.values()
                if now - float(ts) < WORKER_HEARTBEAT_TTL
            )
            connected = True
        except Exception:
            queue_len = -1
            processing = -1
            alive_workers = 0
            connected = False

        return {
            "mode": "redis",
            "redis": REDIS_URL.split("@")[-1] if "@" in REDIS_URL else REDIS_URL,
            "connected": connected,
            "workers_alive": alive_workers,
            "queue_pending": queue_len,
            "queue_processing": processing,
            "queue_max": OCR_QUEUE_MAX_SIZE,
            "processed": self._processed,
            "failed": self._failed,
            "rejected": self._rejected,
            "timed_out": self._timed_out,
            "timeout_sec": OCR_QUEUE_TIMEOUT,
        }

    def shutdown(self):
        self._redis.close()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# WORKER PROCESS (ayrı container'da çalışır)
# python -m app.core.worker_pool
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _reap_stale_jobs(r, processing_key: str) -> int:
    """
    ÇÖKME KURTARMA: ölü worker'ın (heartbeat kesik) veya patolojik uzun (JOB_HARD_MAX_SEC)
    işini processing listesinden GERİ KUYRUĞA alır. Her worker periyodik çağırır.
    Yarış güvenli: lrem tam 1 dönerse bu worker requeue eder; başkası aldıysa 0 döner, atlar.
    Döner: geri alınan iş sayısı.
    """
    try:
        meta = r.hgetall(PROCESSING_META_KEY)
        if not meta:
            return 0
        beats = r.hgetall(WORKER_HEARTBEAT_KEY)
        now = time.time()
        alive = {k.decode() if isinstance(k, bytes) else k
                 for k, ts in beats.items() if now - float(ts) < WORKER_HEARTBEAT_TTL}
        stale: dict[str, str] = {}
        for jid_b, m_b in meta.items():
            jid = jid_b.decode() if isinstance(jid_b, bytes) else jid_b
            try:
                m = json.loads(m_b)
            except Exception:
                stale[jid] = "bozuk-meta"; continue
            if m.get("worker_id") not in alive:
                stale[jid] = "worker-olu"
            elif now - float(m.get("started_at", now)) > JOB_HARD_MAX_SEC:
                stale[jid] = "hard-max"
        if not stale:
            return 0
        requeued = 0
        for raw in r.lrange(processing_key, 0, -1):
            try:
                jid = json.loads(raw).get("job_id")
            except Exception:
                continue
            if jid in stale:
                if r.lrem(processing_key, 1, raw) == 1:
                    r.lpush(REDIS_QUEUE_NAME, raw)
                    requeued += 1
                    logger.warning("REAPER: is geri kuyruga alindi %s (%s)", jid[:8], stale[jid])
                r.hdel(PROCESSING_META_KEY, jid)
        # processing listesinde olmayan ama meta'da kalan yetimleri temizle
        for jid in stale:
            r.hdel(PROCESSING_META_KEY, jid)
        return requeued
    except Exception as e:
        logger.error("Reaper hatasi: %s", e)
        return 0


def run_worker():
    """
    Worker container'da çalışır:
        command: python -m app.core.worker_pool

    - Redis'ten BRPOPLPUSH ile iş alır (reliable queue: iş processing listesine taşınır)
    - Dosya payload'a gömülüyse (JOB_FILE_INLINE) kendi tmpfs'ine yazar -> ÇOK-MAKİNE
    - OCR işler, sonucu Redis'e yazar, yerel dosyayı siler (KVKK)
    - Heartbeat AYRI THREAD'de: OCR sırasında da atılır -> uzun iş ölü sanılmaz
    - Reaper: ölü worker'ın takılı işini geri kuyruğa alır -> çökmede kayıp yok
    """
    import redis as redis_lib

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [WORKER-%(process)d] %(message)s",
    )

    r = _redis_client()
    r.ping()

    # BENZERSİZ worker_id: container'da pid hep 1, --network host'ta hostname aynı ->
    # "1@host" çakışır; reaper ölü worker'ı canlı sanır, işini geri almazdı. UUID eki şart.
    worker_id = f"{os.getpid()}@{os.uname().nodename}:{uuid.uuid4().hex[:8]}"
    processing_key = f"{REDIS_QUEUE_NAME}:processing"
    running = True
    processed = 0

    # HEARTBEAT THREAD: döngü içinde değil, arka planda. Böylece worker 60sn'lik bir PDF
    # işlerken de heartbeat atar; reaper onu yanlışlıkla ölü sayıp işini çalmaz.
    def _heartbeat_loop():
        hb = _redis_client()
        while running:
            try:
                hb.hset(WORKER_HEARTBEAT_KEY, worker_id, str(time.time()))
            except Exception:
                pass
            time.sleep(10)
    threading.Thread(target=_heartbeat_loop, daemon=True, name="heartbeat").start()

    def handle_signal(sig, frame):
        nonlocal running
        logger.info("Durduruluyor (signal %s)...", sig)
        running = False

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    logger.info("Worker baslatildi: %s | Queue: %s | inline-file=%s", worker_id, REDIS_QUEUE_NAME, JOB_FILE_INLINE)
    last_reap = 0.0

    while running:
        try:
            # REAPER: periyodik, ucuz (meta hash + processing listesi taraması)
            if time.time() - last_reap > REAPER_INTERVAL_SEC:
                _reap_stale_jobs(r, processing_key)
                last_reap = time.time()

            # redis-py 8+: bos kuyrukta blocking pop None dondurmez, TimeoutError firlatir.
            try:
                raw = r.brpoplpush(REDIS_QUEUE_NAME, processing_key, timeout=5)
            except redis_lib.exceptions.TimeoutError:
                continue
            if raw is None:
                continue

            # GUVENLIK (K1): JSON parse + allowlist.
            job = json.loads(raw)
            job_id = job["job_id"]
            result_key = f"wendococr:result:{job_id}"
            # Sahiplik kaydı: reaper hangi worker'ın işi olduğunu buradan bilir.
            r.hset(PROCESSING_META_KEY, job_id, json.dumps({"worker_id": worker_id, "started_at": time.time()}))

            logger.info("Is alindi: %s | %s", job_id[:8], job.get("fn_key", "?"))
            start = time.time()
            local_file: Path | None = None

            try:
                args = list(job.get("args", []))
                # ÇOK-MAKİNE: payload'daki dosyayı KENDİ tmpfs'ine yaz, yer tutucuyu değiştir.
                if job.get("file_b64"):
                    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
                    safe = "".join(c for c in str(job.get("file_name") or "file")[:80] if c.isalnum() or c in "._-") or "file"
                    local_file = UPLOAD_DIR / f"{job_id}_{safe}"
                    local_file.write_bytes(base64.b64decode(job["file_b64"]))
                    args = [str(local_file) if a == _FILE_PLACEHOLDER else a for a in args]

                fn = _resolve_allowed(job["fn_key"])  # allowlist disi -> ValueError
                result_data = fn(*args, **job.get("kwargs", {}))

                r.lpush(result_key, json.dumps({"data": result_data, "error": None}).encode("utf-8"))
                r.expire(result_key, REDIS_RESULT_TTL)

                elapsed = round(time.time() - start, 2)
                processed += 1
                logger.info("Tamamlandi: %s | %.1fs | toplam: %d", job_id[:8], elapsed, processed)

            except Exception as e:
                logger.exception("Basarisiz: %s | %s", job_id[:8], e)
                r.lpush(result_key, json.dumps({"data": None, "error": str(e)}).encode("utf-8"))
                r.expire(result_key, REDIS_RESULT_TTL)

            finally:
                # KVKK: yerel kopyayı hemen sil
                if local_file is not None:
                    try:
                        local_file.unlink(missing_ok=True)
                    except Exception:
                        pass
                r.lrem(processing_key, 1, raw)
                r.hdel(PROCESSING_META_KEY, job_id)

        except Exception as e:
            if running:
                logger.error("Dongu hatasi: %s", e)
                time.sleep(2)

    # Çıkışta heartbeat sil
    r.hdel(WORKER_HEARTBEAT_KEY, worker_id)
    r.close()
    logger.info("Worker kapatildi. Toplam: %d", processed)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ORTAK
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class QueueFullError(Exception):
    pass

class QueueTimeoutError(Exception):
    pass

def _worker_wrapper(fn, args, kwargs):
    return fn(*args, **kwargs)

_pool = None

def get_pool() -> LocalWorkerPool | RedisWorkerPool:
    global _pool
    if _pool is None:
        if REDIS_URL:
            _pool = RedisWorkerPool()
        else:
            _pool = LocalWorkerPool()
    return _pool


if __name__ == "__main__":
    if not REDIS_URL:
        print("HATA: REDIS_URL gerekli.")
        print("  export REDIS_URL=redis://localhost:6379/0")
        exit(1)
    run_worker()
