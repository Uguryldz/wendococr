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
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from app.config import (
    OCR_MAX_WORKERS,
    OCR_QUEUE_MAX_SIZE,
    OCR_QUEUE_TIMEOUT,
    REDIS_URL,
    REDIS_QUEUE_NAME,
    REDIS_RESULT_TTL,
)

logger = logging.getLogger("wendococr.pool")

WORKER_HEARTBEAT_KEY = "wendococr:workers"
WORKER_HEARTBEAT_TTL = 30  # saniye — 30s heartbeat gelmezse ölü sayılır

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
        import redis
        self._redis = redis.Redis.from_url(REDIS_URL, decode_responses=False)
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
        job_data = json.dumps({
            "job_id": job_id,
            "fn_key": _fn_key_for(fn),
            "args": [str(a) if isinstance(a, os.PathLike) else a for a in args],
            "kwargs": kwargs,
            "submitted_at": time.time(),
        }).encode("utf-8")

        self._redis.lpush(REDIS_QUEUE_NAME, job_data)

        loop = asyncio.get_event_loop()
        try:
            result = await asyncio.wait_for(
                loop.run_in_executor(None, self._wait_result, result_key),
                timeout=OCR_QUEUE_TIMEOUT,
            )
        except asyncio.TimeoutError:
            self._timed_out += 1
            self._redis.delete(result_key)
            raise QueueTimeoutError(f"Timeout ({OCR_QUEUE_TIMEOUT}s): {job_id}")

        if result.get("error"):
            self._failed += 1
            raise RuntimeError(result["error"])

        self._processed += 1
        return result["data"]

    def _wait_result(self, result_key: str) -> dict:
        import redis
        r = redis.Redis.from_url(REDIS_URL, decode_responses=False)
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

def run_worker():
    """
    Worker container'da çalışır:
        command: python -m app.core.worker_pool

    - Redis'ten BRPOPLPUSH ile iş alır (reliable queue)
    - OCR işler, sonucu Redis'e yazar
    - Çökerse processing listesinden geri alınır → kayıp yok
    - Heartbeat gönderir → main kaç worker aktif bilir
    """
    import redis as redis_lib

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [WORKER-%(process)d] %(message)s",
    )

    r = redis_lib.Redis.from_url(REDIS_URL, decode_responses=False)
    r.ping()

    worker_id = f"{os.getpid()}@{os.uname().nodename}"
    processing_key = f"{REDIS_QUEUE_NAME}:processing"
    running = True
    processed = 0
    last_heartbeat = 0

    def _heartbeat():
        nonlocal last_heartbeat
        now = time.time()
        if now - last_heartbeat > 10:
            r.hset(WORKER_HEARTBEAT_KEY, worker_id, str(now))
            last_heartbeat = now

    def handle_signal(sig, frame):
        nonlocal running
        logger.info("Durduruluyor (signal %s)...", sig)
        running = False

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    logger.info("Worker baslatildi: %s | Queue: %s", worker_id, REDIS_QUEUE_NAME)

    while running:
        try:
            _heartbeat()

            # redis-py 8+: bos kuyrukta blocking pop None dondurmez, TimeoutError firlatir.
            # Bu normal bir "is yok" durumu — hata degil, sessizce dongu basa doner.
            try:
                raw = r.brpoplpush(REDIS_QUEUE_NAME, processing_key, timeout=5)
            except redis_lib.exceptions.TimeoutError:
                continue
            if raw is None:
                continue

            # GUVENLIK (K1): JSON parse + allowlist. Kuyruktaki veri keyfi kod/fonksiyon
            # tasiyamaz; bilinmeyen fn_key veya bozuk JSON reddedilir.
            job = json.loads(raw)
            job_id = job["job_id"]
            result_key = f"wendococr:result:{job_id}"

            logger.info("Is alindi: %s | %s", job_id[:8], job.get("fn_key", "?"))
            start = time.time()

            try:
                fn = _resolve_allowed(job["fn_key"])  # allowlist disi -> ValueError
                result_data = fn(*job.get("args", []), **job.get("kwargs", {}))

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
                r.lrem(processing_key, 1, raw)

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
