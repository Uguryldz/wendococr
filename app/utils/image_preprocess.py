"""Görüntü ön işleme: grayscale, thresholding, deskew (OpenCV)."""
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


def preprocess_image(image: NDArray, *, grayscale: bool = True, threshold: bool = True, deskew: bool = True) -> NDArray:
    """
    OCR öncesi görüntü işleme.
    - grayscale: BGR/RGB -> gri
    - threshold: Otsu ile binary
    - deskew: Eğiklik düzeltme
    """
    if image is None or image.size == 0:
        return image
    out = image.copy()
    if len(out.shape) == 3 and grayscale:
        out = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)
    if threshold and len(out.shape) == 2:
        out = cv2.threshold(out, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
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
