"""
ICR (Intelligent Character Recognition) motoru: PaddleOCR ile Türkçe el yazısı tanıma.

PaddleOCR'ın PP-OCRv4 modeli basılı+el yazısı hibrit tanıma yapabilir.
El yazısı için özelleştirilmiş preprocessing uygulanır.

Kullanılan kütüphaneler:
  - paddleocr (lazy import — Docker'da preload)
  - paddlepaddle
  - opencv-python-headless>=4.8.0
  - app.utils.turkish_postprocess
"""
from __future__ import annotations

import os
import uuid
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from app.config import (
    ICR_DPI,
    PADDLEOCR_LOW_MAX_SIDE,
    UPLOAD_DIR,
)
from app.utils.turkish_postprocess import postprocess_turkish
from app.utils.text_layout import content_from_text_blocks_with_bbox

_ICR_PADDLE_CACHE: dict[str, Any] = {}


def _preprocess_handwriting_paddle(image: np.ndarray) -> np.ndarray:
    """
    El yazısı preprocessing (PaddleOCR için).
    PaddleOCR kendi detection/recognition pipeline'ı olduğu için
    daha hafif preprocessing yeterli — ağır binarizasyon yapmıyoruz.
    """
    if image is None or image.size == 0:
        return image

    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image.copy()

    h, w = gray.shape[:2]

    # Küçük görüntüleri büyüt
    if max(h, w) < 1200:
        scale = 1.8
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

    # Bilateral filter: gürültü azalt, kenar koru
    gray = cv2.bilateralFilter(gray, d=5, sigmaColor=40, sigmaSpace=40)

    # CLAHE: soluk mürekkep/kalem kontrastını artır
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)

    # Unsharp mask
    blurred = cv2.GaussianBlur(gray, (0, 0), sigmaX=1.5)
    sharp = cv2.addWeighted(gray, 1.5, blurred, -0.5, 0)
    sharp = np.clip(sharp, 0, 255).astype(np.uint8)

    # BGR'ye geri dönüştür (PaddleOCR 3 kanal bekler)
    return cv2.cvtColor(sharp, cv2.COLOR_GRAY2BGR)


def _get_icr_paddle():
    """PaddleOCR ICR instance'ı (lazy + cached)."""
    cache_key = "icr"
    if cache_key in _ICR_PADDLE_CACHE:
        return _ICR_PADDLE_CACHE[cache_key]

    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    os.environ.setdefault("FLAGS_use_mkldnn", "0")

    from paddleocr import PaddleOCR

    ocr = PaddleOCR(
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        enable_mkldnn=False,
        device="cpu",
        text_det_limit_side_len=960,
        text_det_limit_type="min",
        text_det_thresh=0.25,
        text_det_box_thresh=0.5,
        text_det_unclip_ratio=1.8,
        text_rec_score_thresh=0.08,
        return_word_box=False,
    )
    _ICR_PADDLE_CACHE[cache_key] = ocr
    return ocr


def _predict_to_text_blocks(raw_result: dict[str, Any]) -> list[dict[str, Any]]:
    """PaddleOCR predict sonucunu text_blocks formatına çevir."""
    res = (raw_result or {}).get("res", {}) or {}
    texts = res.get("rec_texts", []) or []
    boxes = res.get("rec_boxes", []) or []

    out: list[dict[str, Any]] = []
    for i, text in enumerate(texts):
        t = (text or "").strip()
        if not t:
            continue
        t = postprocess_turkish(t)
        box = boxes[i] if i < len(boxes) else None
        if box is None:
            continue
        box_arr = np.array(box, dtype=np.float32)

        if box_arr.ndim == 1 and box_arr.size >= 4:
            x_min = float(min(box_arr[0], box_arr[2]))
            y_min = float(min(box_arr[1], box_arr[3]))
            x_max = float(max(box_arr[0], box_arr[2]))
            y_max = float(max(box_arr[1], box_arr[3]))
        elif box_arr.ndim >= 2 and box_arr.shape[-1] >= 2:
            x_min = float(np.min(box_arr[..., 0]))
            y_min = float(np.min(box_arr[..., 1]))
            x_max = float(np.max(box_arr[..., 0]))
            y_max = float(np.max(box_arr[..., 1]))
        else:
            continue

        out.append({"text": t, "bbox": [x_min, y_min, x_max, y_max]})
    return out


def extract(
    file_path: Path | str | None,
    page_numbers: list[int] | None = None,
    *,
    image_bytes: bytes | None = None,
) -> list[dict[str, Any]]:
    """
    ICR engine arayüzü: el yazısı tanıma (PaddleOCR Türkçe post-processing).
    PDF veya resim kabul eder.
    """
    page_no = (page_numbers[0] + 1) if page_numbers else 1

    # Input decode
    img: np.ndarray | None = None
    if image_bytes:
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    elif file_path:
        file_path = Path(file_path)
        if file_path.exists():
            img = cv2.imread(str(file_path), cv2.IMREAD_COLOR)

    if img is None:
        return []

    # Otomatik yön düzeltme (güven düşükse döndürmez — el yazısında güvenli).
    try:
        from app.utils.orientation import auto_orient
        img, _rot = auto_orient(img)
    except Exception:
        pass

    h, w = img.shape[:2]

    # El yazısı preprocessing
    processed = _preprocess_handwriting_paddle(img)

    # Max side limit
    max_side = int(os.environ.get("PADDLEOCR_LOW_MAX_SIDE", str(PADDLEOCR_LOW_MAX_SIDE)))
    proc_h, proc_w = processed.shape[:2]
    max_dim = max(proc_h, proc_w)
    if max_dim > max_side:
        scale = float(max_side) / float(max_dim)
        new_w = max(1, int(round(proc_w * scale)))
        new_h = max(1, int(round(proc_h * scale)))
        processed = cv2.resize(processed, (new_w, new_h), interpolation=cv2.INTER_AREA)

    # Temp file (PaddleOCR predict file path gerektirir)
    out_dir = UPLOAD_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = out_dir / f"icr_paddle_{uuid.uuid4().hex}.png"

    try:
        cv2.imwrite(str(tmp_path), processed)
        ocr = _get_icr_paddle()
        result_list = ocr.predict(input=str(tmp_path))
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass

    first_result = next(iter(result_list), None)
    if not first_result:
        return [{
            "page_number": page_no,
            "content": "",
            "tables": [],
            "text_blocks": [],
            "page_width": float(w),
            "page_height": float(h),
        }]

    text_blocks = _predict_to_text_blocks(first_result.json)
    content = content_from_text_blocks_with_bbox(text_blocks)

    return [{
        "page_number": page_no,
        "content": content,
        "tables": [],
        "text_blocks": text_blocks,
        "page_width": float(w),
        "page_height": float(h),
    }]
