"""
pdfimagepaddleocrlow motoru: PaddleOCR ile OCR (low bellek profili).

Amaç:
- Docker ortamında RAM patlamasını önlemek.
- Büyük görsellerde doc preprocessor / unwarping / yönelim adımlarını kapatmak.
- Hem input görselini küçültmek hem de PaddleOCR text-detection limitlerini uygulamak.
- Türkçe diacritik post-processing uygulamak.
"""

from __future__ import annotations

import os
import time
import uuid
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from app.config import (
    OCR_DPI_PADDLEOCR_LOW,
    PADDLEOCR_LOW_MAX_SIDE,
    PADDLEOCR_LOW_TEXT_DET_LIMIT,
    PADDLEOCR_LOW_TEXT_DET_LIMIT_TYPE,
    PADDLEOCR_LOW_TEXT_DET_THRESH,
    PADDLEOCR_LOW_TEXT_DET_BOX_THRESH,
    PADDLEOCR_LOW_TEXT_DET_UNCLIP_RATIO,
    PADDLEOCR_LOW_TEXT_REC_SCORE_THRESH,
)
from app.config import UPLOAD_DIR
from app.utils.turkish_postprocess import postprocess_turkish

_OCR_CACHE: dict[int, Any] = {}


def _enhance_for_turkish_paddle(image: np.ndarray) -> np.ndarray:
    """
    Türkçe diacritik-safe ön işleme (PaddleOCR için).
    - CLAHE ile lokal kontrast artırma
    - Unsharp mask ile diacritik keskinleştirme
    """
    if image is None or image.size == 0:
        return image
    # Grayscale'e çevir
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image
    # CLAHE
    try:
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        gray = clahe.apply(gray)
    except Exception:
        pass
    # Unsharp mask
    blurred = cv2.GaussianBlur(gray, (0, 0), sigmaX=2.0)
    sharp = cv2.addWeighted(gray, 1.4, blurred, -0.4, 0)
    sharp = np.clip(sharp, 0, 255).astype(np.uint8)
    # BGR'ye geri dönüştür (PaddleOCR 3 kanal bekler)
    return cv2.cvtColor(sharp, cv2.COLOR_GRAY2BGR)


def _as_resized_image_path(image: np.ndarray, *, max_side: int, out_dir: Path) -> tuple[Path, float, float]:
    h, w = image.shape[:2]
    max_dim = max(h, w)
    if max_dim > max_side:
        scale = float(max_side) / float(max_dim)
        new_w = max(1, int(round(w * scale)))
        new_h = max(1, int(round(h * scale)))
        resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)
    else:
        resized = image
        new_w, new_h = w, h

    # Türkçe diacritik iyileştirme uygula
    resized = _enhance_for_turkish_paddle(resized)

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"paddleocr_low_{uuid.uuid4().hex}_max{max_side}.png"
    cv2.imwrite(str(out_path), resized)
    return out_path, float(new_h), float(new_w)  # page_height, page_width


def _get_ocr(det_limit_side_len: int):
    """
    Det_limit_side_len'e göre PaddleOCR örneğini cache'ler.
    """
    if det_limit_side_len in _OCR_CACHE:
        return _OCR_CACHE[det_limit_side_len]

    # PaddleOCR ilk kullanımda internet/hoster kontrolü yapabiliyor; docker'da bunu pas geçiyoruz.
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    os.environ.setdefault("FLAGS_use_mkldnn", "0")

    from paddleocr import PaddleOCR  # lazy import

    ocr = PaddleOCR(
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        enable_mkldnn=False,
        device="cpu",
        text_det_limit_side_len=int(det_limit_side_len),
        text_det_limit_type=str(PADDLEOCR_LOW_TEXT_DET_LIMIT_TYPE),
        text_det_thresh=float(PADDLEOCR_LOW_TEXT_DET_THRESH),
        text_det_box_thresh=float(PADDLEOCR_LOW_TEXT_DET_BOX_THRESH),
        text_det_unclip_ratio=float(PADDLEOCR_LOW_TEXT_DET_UNCLIP_RATIO),
        text_rec_score_thresh=float(PADDLEOCR_LOW_TEXT_REC_SCORE_THRESH),
        return_word_box=False,
    )
    _OCR_CACHE[det_limit_side_len] = ocr
    return ocr


def _predict_to_text_blocks(raw_result: dict[str, Any]) -> list[dict[str, Any]]:
    res = (raw_result or {}).get("res", {}) or {}
    texts = res.get("rec_texts", []) or []
    boxes = res.get("rec_boxes", []) or []

    out: list[dict[str, Any]] = []
    for i, text in enumerate(texts):
        t = (text or "").strip()
        if not t:
            continue
        # Türkçe post-processing: diacritik restorasyon + artefakt temizleme
        t = postprocess_turkish(t)
        box = boxes[i] if i < len(boxes) else None
        if box is None:
            continue
        box_arr = np.array(box, dtype=np.float32)

        # Farklı Paddle/PaddleOCR sürümlerinde rec_boxes formatı değişebilir:
        # - [x0, y0, x1, y1]
        # - [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
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
    Tek sayfa OCR.

    Dönüş:
    - "page_number", "content", "tables", "text_blocks", "page_width", "page_height"
    """
    page_no = (page_numbers[0] + 1) if page_numbers else 1

    # Pipelinede RAM patlamasını engellemek için 2-3 adımlı küçültme/yeniden deneme.
    base_max_side = int(os.environ.get("PADDLEOCR_LOW_MAX_SIDE", str(PADDLEOCR_LOW_MAX_SIDE)))
    base_det_limit = int(os.environ.get("PADDLEOCR_LOW_TEXT_DET_LIMIT", str(PADDLEOCR_LOW_TEXT_DET_LIMIT)))

    retry_max_sides = [
        base_max_side,
        max(600, int(base_max_side * 0.8)),
        max(400, int(base_max_side * 0.6)),
    ]

    # input'ı decode et
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

    out_dir = UPLOAD_DIR  # /tmp/wendococr gibi

    last_error: Exception | None = None
    for attempt_idx, max_side in enumerate(retry_max_sides):
        try:
            det_limit = min(base_det_limit, max_side)
            ocr = _get_ocr(det_limit_side_len=det_limit)

            resized_path, page_h, page_w = _as_resized_image_path(
                img,
                max_side=max_side,
                out_dir=out_dir,
            )

            try:
                start = time.perf_counter()
                result_list = ocr.predict(input=str(resized_path))
                elapsed = time.perf_counter() - start  # şu an kullanılmıyor, debug için tutulabilir
            finally:
                try:
                    resized_path.unlink(missing_ok=True)
                except Exception:
                    pass

            first_result = next(iter(result_list), None)
            if not first_result:
                return [{
                    "page_number": page_no,
                    "content": "",
                    "tables": [],
                    "text_blocks": [],
                    "page_width": float(page_w),
                    "page_height": float(page_h),
                }]

            text_blocks = _predict_to_text_blocks(first_result.json)
            from app.utils.text_layout import content_from_text_blocks_with_bbox
            content = content_from_text_blocks_with_bbox(text_blocks)

            return [{
                "page_number": page_no,
                "content": content,
                "tables": [],
                "text_blocks": text_blocks,
                "page_width": float(page_w),
                "page_height": float(page_h),
            }]
        except Exception as e:  # pragma: no cover (runtime hataları ortam bağımlı)
            last_error = e
            # MemoryError / ResourceExhaustedError gibi durumlarda retry'ye geç.
            if attempt_idx >= len(retry_max_sides) - 1:
                raise

    # unreachable
    if last_error:
        raise last_error
    return []

