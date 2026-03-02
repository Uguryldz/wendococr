"""Tesseract ile resim/taranmış sayfa OCR (Türkçe, koordinatlı)."""
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pytesseract

from app.utils.image_preprocess import preprocess_image, load_image


def _run_tesseract(
    image_bytes: bytes | None = None,
    image_array: np.ndarray | None = None,
) -> tuple[list[tuple[list[float], str]], int, int]:
    """
    Tesseract ile metin + koordinatlar (image_to_data). Döner: ([(bbox, text), ...], width, height).
    bbox: [x0, y0, x1, y1] piksel.
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
    img = preprocess_image(img, grayscale=True, threshold=True, deskew=True)
    out = []
    try:
        data = pytesseract.image_to_data(img, lang="tur", output_type=pytesseract.Output.DICT)
        n = len(data.get("text") or [])
        for i in range(n):
            text = (data.get("text") or [])[i] or ""
            if not text.strip():
                continue
            left = int((data.get("left") or [0])[i])
            top = int((data.get("top") or [0])[i])
            width = int((data.get("width") or [0])[i])
            height = int((data.get("height") or [0])[i])
            bbox = [float(left), float(top), float(left + width), float(top + height)]
            out.append((bbox, text))
    except Exception:
        pass
    return out, w, h


def extract(
    file_path: Path | str,
    page_numbers: list[int] | None = None,
    *,
    image_bytes: bytes | None = None,
) -> list[dict[str, Any]]:
    """
    Tek sayfa resim veya PDF'ten gelen görüntü. text_blocks ile koordinatlı çıktı.
    """
    file_path = Path(file_path) if file_path else None
    page_no = (page_numbers[0] + 1) if page_numbers else 1

    if image_bytes:
        lines_bbox, page_width, page_height = _run_tesseract(image_bytes=image_bytes)
    elif file_path and file_path.exists():
        img = load_image(file_path)
        if img is None:
            return []
        lines_bbox, page_width, page_height = _run_tesseract(image_array=img)
    else:
        return []

    text_blocks = [{"text": t, "bbox": b} for b, t in lines_bbox]
    content = " ".join(t for _, t in lines_bbox)  # tesseract word-by-word
    return [{
        "page_number": page_no,
        "content": content,
        "tables": [],
        "text_blocks": text_blocks,
        "page_width": float(page_width),
        "page_height": float(page_height),
    }]
