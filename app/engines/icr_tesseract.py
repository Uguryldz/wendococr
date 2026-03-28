"""
ICR (Intelligent Character Recognition) motoru: Tesseract ile Türkçe el yazısı tanıma.

El yazısı belgeler (dilekçe, başvuru formu, el notu, imza üstü yazılar) için
özelleştirilmiş preprocessing + Tesseract LSTM OCR.

El yazısı ≠ basılı metin:
  - Vuruş kalınlığı değişken → Sauvola/adaptive threshold
  - Eğiklik fazla → agresif deskew
  - Gürültü farklı → bilateral filter
  - Diacritikler daha zor → morfolojik dilation ile kalınlaştırma
  - PSM 4/6 (metin bloğu) — el yazısı auto-segmentasyon zor

Kullanılan kütüphaneler:
  - pytesseract>=0.3.10 + sistem tesseract-ocr, tesseract-ocr-tur
  - opencv-python-headless>=4.8.0
  - app.utils.turkish_postprocess
"""
import cv2
import numpy as np
from pathlib import Path
from typing import Any

import pytesseract

from app.config import ICR_DPI, ICR_PSM_CANDIDATES, ICR_USER_DEFINED_DPI
from app.utils.turkish_postprocess import postprocess_turkish


def _preprocess_handwriting_soft(img: np.ndarray) -> np.ndarray:
    """
    El yazısı preprocessing — hafif versiyon (threshold yok).
    Karma belgeler (basılı + el yazısı) için daha güvenli.
    """
    if img is None or img.size == 0:
        return img
    if len(img.shape) == 3:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    else:
        gray = img.copy()

    h, w = gray.shape[:2]
    if max(h, w) < 1500:
        gray = cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)

    gray = cv2.bilateralFilter(gray, d=5, sigmaColor=50, sigmaSpace=50)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)
    blurred = cv2.GaussianBlur(gray, (0, 0), sigmaX=1.5)
    sharp = cv2.addWeighted(gray, 1.5, blurred, -0.5, 0)
    sharp = np.clip(sharp, 0, 255).astype(np.uint8)
    sharp = _deskew_handwriting(sharp)
    return sharp


def _preprocess_handwriting_hard(img: np.ndarray) -> np.ndarray:
    """
    El yazısı preprocessing — agresif versiyon (threshold + morfoloji).
    Saf el yazısı belgeler (kalem/mürekkep kağıt üzerinde) için.
    """
    if img is None or img.size == 0:
        return img
    if len(img.shape) == 3:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    else:
        gray = img.copy()

    h, w = gray.shape[:2]
    if max(h, w) < 1500:
        gray = cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
        h, w = gray.shape[:2]

    gray = cv2.bilateralFilter(gray, d=5, sigmaColor=50, sigmaSpace=50)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)
    blurred = cv2.GaussianBlur(gray, (0, 0), sigmaX=1.5)
    sharp = cv2.addWeighted(gray, 1.6, blurred, -0.6, 0)
    sharp = np.clip(sharp, 0, 255).astype(np.uint8)

    block_size = max(15, min(51, int(min(h, w) / 20) | 1))
    if block_size % 2 == 0:
        block_size += 1
    binary = cv2.adaptiveThreshold(
        sharp, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY,
        blockSize=block_size, C=10,
    )
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2, 2))
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=1)
    binary = _deskew_handwriting(binary)
    return binary


def _deskew_handwriting(binary: np.ndarray) -> np.ndarray:
    """El yazısı için deskew — daha toleranslı açı tespiti."""
    coords = np.column_stack(np.where(binary < 200))
    if len(coords) < 50:
        return binary
    if len(coords) > 15_000:
        rng = np.random.default_rng(42)
        coords = coords[rng.choice(len(coords), 15_000, replace=False)]
    angle = cv2.minAreaRect(coords)[-1]
    if angle < -45:
        angle = 90 + angle
    elif angle > 45:
        angle = angle - 90
    if abs(angle) < 0.3:
        return binary
    h, w = binary.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(binary, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def _run_icr_tesseract(
    image_bytes: bytes | None = None,
    image_array: np.ndarray | None = None,
) -> tuple[list[tuple[list[float], str]], int, int]:
    """
    Tesseract ICR: el yazısı tanıma.
    Birden fazla PSM dener, en iyi sonucu seçer.
    """
    if image_array is not None:
        img = image_array
    elif image_bytes:
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            return [], 0, 0
    else:
        return [], 0, 0

    h, w = img.shape[:2]

    # İki preprocessing dener: soft (karma belge) + hard (saf el yazısı)
    # En çok metin üreten varyantı seçer
    variants = [
        _preprocess_handwriting_soft(img),
        _preprocess_handwriting_hard(img),
    ]

    base_cfg = "--oem 3 -c preserve_interword_spaces=1"
    if str(ICR_USER_DEFINED_DPI).strip():
        base_cfg += f" -c user_defined_dpi={str(ICR_USER_DEFINED_DPI).strip()}"

    psm_candidates = list(ICR_PSM_CANDIDATES)

    def run_with_psm(psm_val: str) -> tuple[list[tuple[list[float], str]], float]:
        cfg = f"{base_cfg} --psm {psm_val}"
        data = pytesseract.image_to_data(
            processed, lang="tur+eng", config=cfg, output_type=pytesseract.Output.DICT
        )
        texts = data.get("text") or []
        confs = data.get("conf") or []
        lefts = data.get("left") or []
        tops = data.get("top") or []
        widths = data.get("width") or []
        heights = data.get("height") or []

        local_out: list[tuple[list[float], str]] = []
        conf_sum = 0.0
        conf_n = 0
        for i in range(len(texts)):
            text = (texts[i] or "").strip()
            if not text:
                continue
            try:
                conf = float(confs[i])
            except Exception:
                conf = -1.0
            if conf >= 0:
                conf_sum += conf
                conf_n += 1
            try:
                left = int(lefts[i])
                top = int(tops[i])
                width_val = int(widths[i])
                height_val = int(heights[i])
            except Exception:
                continue
            bbox = [float(left), float(top), float(left + width_val), float(top + height_val)]
            text = postprocess_turkish(text)
            local_out.append((bbox, text))
        avg_conf = (conf_sum / conf_n) if conf_n else -1.0
        return local_out, avg_conf

    overall_best: list[tuple[list[float], str]] = []
    overall_best_score = -1.0

    for variant in variants:
        processed = variant
        best_out: list[tuple[list[float], str]] = []
        best_conf = -1.0
        try:
            for psm_val in psm_candidates:
                local_out, avg_conf = run_with_psm(psm_val)
                better = avg_conf > best_conf
                if avg_conf < 0 and best_conf < 0:
                    better = len(local_out) > len(best_out)
                if better:
                    best_out, best_conf = local_out, avg_conf
        except Exception:
            pass
        # Skor: confidence * token sayısı (hem doğruluk hem kapsam)
        score = best_conf * len(best_out) if best_conf > 0 else len(best_out)
        if score > overall_best_score:
            overall_best_score = score
            overall_best = best_out

    return overall_best, w, h


def extract(
    file_path: Path | str | None,
    page_numbers: list[int] | None = None,
    *,
    image_bytes: bytes | None = None,
) -> list[dict[str, Any]]:
    """
    ICR engine arayüzü: el yazısı tanıma (Tesseract Türkçe).
    PDF veya resim kabul eder. Koordinatlı text_blocks çıktısı.
    """
    file_path = Path(file_path) if file_path else None
    page_no = (page_numbers[0] + 1) if page_numbers else 1

    if image_bytes:
        lines_bbox, page_width, page_height = _run_icr_tesseract(image_bytes=image_bytes)
    elif file_path and file_path.exists():
        from app.utils.image_preprocess import load_image
        img = load_image(file_path)
        if img is None:
            return []
        lines_bbox, page_width, page_height = _run_icr_tesseract(image_array=img)
    else:
        return []

    text_blocks = [{"text": t, "bbox": b} for b, t in lines_bbox]
    content = " ".join(t for _, t in lines_bbox)
    return [{
        "page_number": page_no,
        "content": content,
        "tables": [],
        "text_blocks": text_blocks,
        "page_width": float(page_width),
        "page_height": float(page_height),
    }]
