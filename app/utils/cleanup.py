"""
Yetim geçici dosya temizleyici.

Her istek UPLOAD_DIR'e bir dosya yazıp işi bitince finally'de siler. Ama
OOM-kill / process çökmesi / SIGKILL gibi kenar durumlarda finally çalışmadan
dosya RAM'de (tmpfs) kalabilir. Uzun ömürlü container'da bunlar birikip tmpfs'i
doldurabilir. Bu modül periyodik olarak "yeterince eski" (= artık işlenmediği
kesin) dosyaları siler. KVKK açısından da hassas belge artığı bırakmaz.
"""
import asyncio
import logging
import time
from pathlib import Path

from app.config import (
    UPLOAD_DIR,
    UPLOAD_CLEANUP_INTERVAL_SEC,
    UPLOAD_FILE_MAX_AGE_SEC,
)

logger = logging.getLogger("wendococr.cleanup")


def sweep_orphans(max_age_sec: int = UPLOAD_FILE_MAX_AGE_SEC) -> int:
    """
    UPLOAD_DIR'deki max_age_sec'ten eski dosyaları siler.
    Aktif işlenen bir dosyayı silmemek için yaş eşiği, en uzun OCR süresinden
    (findeks ~45s) belirgin yüksek tutulur. Silinen dosya sayısını döner.
    """
    if not UPLOAD_DIR.exists():
        return 0
    now = time.time()
    removed = 0
    try:
        for p in UPLOAD_DIR.iterdir():
            if not p.is_file():
                continue
            # .health_check gibi servis dosyalarına dokunma
            if p.name.startswith("."):
                continue
            try:
                age = now - p.stat().st_mtime
                if age >= max_age_sec:
                    p.unlink(missing_ok=True)
                    removed += 1
            except OSError:
                continue
    except OSError:
        return removed
    if removed:
        logger.info("Yetim dosya temizligi: %d dosya silindi (>%ds)", removed, max_age_sec)
    return removed


async def cleanup_loop() -> None:
    """Periyodik temizlik döngüsü — startup'ta background task olarak başlatılır."""
    # Startup'ta bir kez süpür (önceki çökmeden kalan artıklar için)
    sweep_orphans()
    while True:
        try:
            await asyncio.sleep(UPLOAD_CLEANUP_INTERVAL_SEC)
            sweep_orphans()
        except asyncio.CancelledError:
            # Iptal semantigini koru: yut ma, yeniden firlat (S7497).
            raise
        except Exception as e:  # döngü asla ölmemeli
            logger.warning("Temizlik dongusu hatasi: %s", e)
