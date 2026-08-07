"""Görüntü ön işleme: grayscale, thresholding, deskew, Türkçe diacritik koruma (OpenCV)."""
from pathlib import Path
import cv2
import numpy as np
from numpy.typing import NDArray


def _deskew(image: NDArray) -> NDArray:
    """Eğikliği düzeltir (deskew). Milyonlarca nokta minAreaRect'i yavaşlatır; max 10k nokta örneklenir."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
    coords = np.column_stack(np.where(gray < 255))
    if len(coords) < 100:
        return image
    if len(coords) > 10_000:
        rng = np.random.default_rng(42)
        coords = coords[rng.choice(len(coords), 10_000, replace=False)]
    angle = cv2.minAreaRect(coords)[-1]
    if angle < -45:
        angle = 90 + angle
    elif angle > 45:
        angle = angle - 90
    if abs(angle) < 0.5:
        return image
    h, w = image.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(image, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def _adaptive_threshold(gray: NDArray) -> NDArray:
    """
    Türkçe diacritik-safe adaptive threshold.

    Otsu (global) yerine Gaussian adaptive threshold kullanır.
    Sebep: Otsu global eşik değeri, ince vuruşları (ö/ü noktaları, ç/ş kuyrukları,
    ğ breve'si, İ noktası) yok edebilir. Adaptive threshold lokal pencere
    kullanarak bu detayları korur.

    Ek olarak morfolojik closing ile kopmuş diacritik parçalarını yeniden birleştirir.
    """
    if gray is None or gray.size == 0:
        return gray

    h, w = gray.shape[:2]

    # Block size: görüntü boyutuna göre ayarla (küçük görüntüde küçük pencere)
    block_size = max(11, min(31, int(min(h, w) / 30) | 1))  # tek sayı olmalı
    if block_size % 2 == 0:
        block_size += 1

    binary = cv2.adaptiveThreshold(
        gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        blockSize=block_size,
        C=8,  # offset: gürültüye karşı tolerans
    )

    # Morfolojik closing: kopmuş diacritik noktalarını/kuyruklarını geri birleştir
    # Küçük kernel (2x2) - sadece 1px boşlukları kapatır, metni bulandırmaz
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2, 2))
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=1)

    return binary


def _sharpen_diacritics(gray: NDArray) -> NDArray:
    """
    Türkçe diacritik vurgulama: unsharp mask ile ince detayları keskinleştirir.
    ö, ü, ç, ş, ğ, İ gibi karakterlerin nokta/kuyruk/breve kısımlarını OCR'a
    daha görünür hale getirir.
    """
    if gray is None or gray.size == 0:
        return gray
    # Unsharp mask: orijinal - blur = detay; orijinal + detay = keskin
    blurred = cv2.GaussianBlur(gray, (0, 0), sigmaX=2.0)
    sharpened = cv2.addWeighted(gray, 1.5, blurred, -0.5, 0)
    return np.clip(sharpened, 0, 255).astype(np.uint8)


def preprocess_image(
    image: NDArray,
    *,
    grayscale: bool = True,
    threshold: bool = True,
    deskew: bool = True,
    sharpen: bool = False,
) -> NDArray:
    """
    OCR öncesi görüntü işleme (Türkçe diacritik-safe).

    - grayscale: BGR/RGB -> gri
    - threshold: Adaptive Gaussian threshold (Türkçe diacritikleri korur)
    - deskew: Eğiklik düzeltme
    - sharpen: Diacritik keskinleştirme (opsiyonel, OCR öncesi detay vurgulama)
    """
    if image is None or image.size == 0:
        return image
    out = image.copy()
    # Otomatik yön düzeltme (90°/180°/270°) — grayscale/threshold'dan ÖNCE, renkli görüntüde.
    # Boyut eşiği küçük gömülü-resim kırpıklarını (Findeks) otomatik atlar.
    try:
        from app.utils.orientation import auto_orient
        out, _rot = auto_orient(out)
    except Exception:
        pass
    if len(out.shape) == 3 and grayscale:
        out = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)
    if sharpen and len(out.shape) == 2:
        out = _sharpen_diacritics(out)
    if threshold and len(out.shape) == 2:
        out = _adaptive_threshold(out)
    if deskew and out is not None:
        if len(out.shape) == 2:
            out = cv2.cvtColor(out, cv2.COLOR_GRAY2BGR)
        out = _deskew(out)
        out = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY) if grayscale else out
    return out


def load_image(path: Path | str) -> NDArray | None:
    """Dosyadan görüntü yükler."""
    path = Path(path)
    if not path.exists():
        return None
    img = cv2.imread(str(path))
    return img
