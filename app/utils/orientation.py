"""
Otomatik sayfa yönü düzeltme (auto-rotate).

deskew'den FARKLI: deskew küçük eğikliği (±birkaç derece) düzeltir; bu modül
90°/180°/270° YATAY veya TERS gelmiş taranmış belgeleri tespit edip düzeltir.

Yöntem: Tesseract OSD (Orientation & Script Detection, --psm 0). OSD, sayfayı dik
konuma getirmek için gereken saat-yönü dönme açısını (0/90/180/270) ve bir güven
skoru verir. Güven eşiğin altındaysa DOKUNULMAZ (yanlış döndürüp bozmamak için).

Hız: OSD küçük görüntüde hızlıdır; büyük sayfalar tespit için küçültülür. Asıl OCR
her zaman TAM çözünürlüklü görüntü üzerinde yapılır — sadece açı buradan alınır.
"""
from __future__ import annotations

from contextvars import ContextVar

import cv2
import numpy as np
import pytesseract

from app.config import (
    AUTO_ROTATE,
    AUTO_ROTATE_MAX_SIDE,
    AUTO_ROTATE_MIN_CONF,
    AUTO_ROTATE_MIN_SIDE,
    AUTO_ROTATE_VERIFY_MIN_SIDE,
)

# İstek-başına override: route'tan ?auto_rotate=true/false gelir. None = config varsayılanı.
# ContextVar: local ThreadPool modunda iş başına izole; Redis worker'da process_document
# başında set edilir (her iş kendi değerini görür).
_rotate_override: ContextVar[bool | None] = ContextVar("auto_rotate_override", default=None)


def set_auto_rotate(flag: bool | None) -> None:
    """İstek-başına auto-rotate override'ını ayarlar (None = config varsayılanına dön)."""
    _rotate_override.set(flag)


def _rotate_enabled() -> bool:
    ov = _rotate_override.get()
    return AUTO_ROTATE if ov is None else ov

# OSD 'rotate' = görüntüyü dik yapmak için saat yönünde döndürülecek derece.
_ROTATE_CODE = {
    90: cv2.ROTATE_90_CLOCKWISE,
    180: cv2.ROTATE_180,
    270: cv2.ROTATE_90_COUNTERCLOCKWISE,
}


def _to_gray(img: np.ndarray) -> np.ndarray:
    if img.ndim == 2:
        return img
    if img.shape[2] == 4:
        return cv2.cvtColor(img, cv2.COLOR_BGRA2GRAY)
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def detect_rotation(img: np.ndarray) -> int:
    """
    Sayfayı dik yapmak için gereken saat-yönü dönme açısı: 0, 90, 180 veya 270.
    OSD güveni eşiğin altındaysa 0 döner (güvenli varsayılan — döndürme).
    """
    if not _rotate_enabled() or img is None or img.size == 0:
        return 0
    h, w = img.shape[:2]
    # Sadece tam-sayfa ölçekli görüntü: küçük bölge/antet OCR'ında yön tespiti yapma.
    if min(h, w) < AUTO_ROTATE_MIN_SIDE:
        return 0
    gray = _to_gray(img)
    longest = max(h, w)
    if longest > AUTO_ROTATE_MAX_SIDE:
        s = AUTO_ROTATE_MAX_SIDE / longest
        gray = cv2.resize(gray, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    try:
        osd = pytesseract.image_to_osd(gray, output_type=pytesseract.Output.DICT)
    except Exception:
        return 0  # OSD başarısız (az metin/gürültü) -> döndürme
    try:
        rotate = int(osd.get("rotate", 0)) % 360
        conf = float(osd.get("orientation_conf", 0) or 0)
    except (TypeError, ValueError):
        return 0
    if rotate == 0 or conf < AUTO_ROTATE_MIN_CONF:
        return 0
    return rotate if rotate in _ROTATE_CODE else 0


OSD_UNKNOWN = -1   # OSD çöktü/karar veremedi -> çağıran 4-yön OCR oylaması yapsın
OSD_DISABLED = -2  # auto-rotate KAPALI veya görüntü çok küçük -> hiç dokunma (oylama da yok)


def detect_rotation_candidate(img: np.ndarray) -> tuple[int, float]:
    """
    OSD ham adayı: (açı, güven). Güven eşiği UYGULANMAZ — çağıran karar verir.
    - (OSD_DISABLED, 0.0): auto-rotate kapalı VEYA görüntü boyut-altı -> HİÇ dokunma,
      oylama bile yapma (parametre ?auto_rotate=false burada devreye girer).
    - (0, 0.0): OSD "dik" dedi (düşük güvenle) -> çağıran isterse oylayabilir.
    - (OSD_UNKNOWN, 0.0): OSD ÇÖKTÜ -> çağıran 4-yön OCR oylaması yapmalı.
    - (90/180/270, conf): OSD bir açı önerdi.
    """
    if not _rotate_enabled() or img is None or img.size == 0:
        return OSD_DISABLED, 0.0
    h, w = img.shape[:2]
    # Doğrulama OCR ile korunduğu için düşük eşik (küçük fiş fotoğrafları da geçer).
    if min(h, w) < AUTO_ROTATE_VERIFY_MIN_SIDE:
        return OSD_DISABLED, 0.0
    gray = _to_gray(img)
    longest = max(h, w)
    if longest > AUTO_ROTATE_MAX_SIDE:
        s = AUTO_ROTATE_MAX_SIDE / longest
        gray = cv2.resize(gray, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    try:
        osd = pytesseract.image_to_osd(gray, output_type=pytesseract.Output.DICT)
        rotate = int(osd.get("rotate", 0)) % 360
        conf = float(osd.get("orientation_conf", 0) or 0)
    except Exception:
        # OSD hata verdi (çözünürlük/az metin) -> "bilinmiyor": 4-yön oylamaya bırak
        return OSD_UNKNOWN, 0.0
    return (rotate if rotate in _ROTATE_CODE else 0), conf


def apply_rotation(img: np.ndarray, angle: int) -> np.ndarray:
    """Görüntüyü verilen açıyla (90/180/270) saat yönünde döndürür."""
    code = _ROTATE_CODE.get(angle)
    return cv2.rotate(img, code) if code is not None else img


def auto_orient(img: np.ndarray) -> tuple[np.ndarray, int]:
    """
    Görüntüyü tespit edilen yöne göre dik konuma getirir.
    Döner: (düzeltilmiş_görüntü, uygulanan_açı). Açı 0 ise görüntü değişmez.
    """
    angle = detect_rotation(img)
    if angle == 0:
        return img, 0
    return apply_rotation(img, angle), angle
