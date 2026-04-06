"""
pdfimagev5 motoru: RapidOCR ile hızlı OCR (Türkçe iyileştirme + gürültü filtreleme).

KİLİTLİ: Bu modül mevcut ayarlarla stabil; sonraki işlemlerde müdahale etmeyin.
"""
import cv2
import numpy as np
from pathlib import Path
from typing import Any
from rapidocr import RapidOCR
import re

from app.config import (
    RAPIDOCR_DET_LIMIT_SIDE_LEN,
    RAPIDOCR_ENHANCE,
    RAPIDOCR_MIN_BOX_AREA,
    RAPIDOCR_MIN_CONFIDENCE,
    RAPIDOCR_MIN_TOKEN_LEN,
    RAPIDOCR_THRESHOLD,
    RAPIDOCR_TEXT_SCORE,
)

try:
    from app.utils.image_preprocess import preprocess_image, load_image
except ImportError:
    def load_image(p): return cv2.imread(str(p))
    def preprocess_image(img, **kwargs): return img

from app.utils.turkish_postprocess import postprocess_turkish

_rapid_engine = None

def _get_rapid_engine():
    """RapidOCR örneğini Türkçe/Latin dahil çok dilli kullanım için başlatır."""
    global _rapid_engine
    if _rapid_engine is None:
        try:
            # det_limit_side_len: taranmış sayfa boyutu (960 hız/kalite dengesi)
            # text_score: 0.4 — Türkçe/Latin karakterlerde daha toleranslı tanıma
            _rapid_engine = RapidOCR(params={
                "Det": {"limit_side_len": RAPIDOCR_DET_LIMIT_SIDE_LEN},
            })
            _rapid_engine.text_score = RAPIDOCR_TEXT_SCORE
        except Exception:
            pass
    return _rapid_engine


_WHITESPACE_RE = re.compile(r"\s+")


def _enhance_for_turkish_rapid(gray: np.ndarray) -> np.ndarray:
    """
    Türkçe diakritiklerini koruyacak iyileştirme.
    - Küçük metinlerde upscale (diacritikler daha görünür)
    - CLAHE ile lokal kontrast artırma
    - Unsharp mask ile diacritik keskinleştirme (ö/ü/ç/ş/ğ/İ noktaları)
    """
    if gray is None or gray.size == 0:
        return gray
    h, w = gray.shape[:2]
    out = gray
    # Küçük görüntüleri büyüt — diacritik noktaları daha net olur
    if max(h, w) < 1400:
        out = cv2.resize(out, None, fx=1.5, fy=1.5, interpolation=cv2.INTER_CUBIC)
    try:
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        out = clahe.apply(out)
    except Exception:
        pass
    # Unsharp mask: diacritik detaylarını vurgula
    blurred = cv2.GaussianBlur(out, (0, 0), sigmaX=2.0)
    out = cv2.addWeighted(out, 1.4, blurred, -0.4, 0)
    out = np.clip(out, 0, 255).astype(np.uint8)
    return out


def _clean_text(text: str) -> str:
    """OCR metnini katı filtre için normalize eder."""
    text = _WHITESPACE_RE.sub(" ", (text or "").strip())
    return text

def _run_rapidocr(
    image_bytes: bytes | None = None,
    image_array: np.ndarray | None = None,
) -> tuple[list[tuple[list[float], str]], int, int]:
    """
    Hız odaklı RapidOCR motoru.
    """
    engine = _get_rapid_engine()
    if engine is None:
        return [], 0, 0

    # 1. Görseli Yükle
    if image_array is not None:
        img = image_array.copy()
    elif image_bytes:
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    else:
        return [], 0, 0

    if img is None:
        return [], 0, 0

    h, w = img.shape[:2]

    # 2. Ön İşleme (DARBOĞAZ BURASI OLABİLİR)
    # Eğer hala yavaşsa: grayscale=False, threshold=False yaparak dene.
    # Yüksek çözünürlükte threshold işlemi CPU'yu çok yorar.
    if max(h, w) > 2000:
        # Çok büyük resimlerde threshold açmak detay kaybı yapabilir.
        if len(img.shape) == 3:
            img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        if RAPIDOCR_ENHANCE:
            img = _enhance_for_turkish_rapid(img)
    else:
        if len(img.shape) == 3:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        else:
            gray = img
        if RAPIDOCR_ENHANCE:
            gray = _enhance_for_turkish_rapid(gray)
        img = preprocess_image(
            cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR),
            grayscale=True,
            threshold=RAPIDOCR_THRESHOLD,
            deskew=False,
        )

    # RapidOCR 3 kanal (BGR) beklediği için gerekirse dönüştür
    if len(img.shape) == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)

    # 3. OCR İşlemi
    # det_limit_side_len zaten engine içinde set edildiği için burada hızlı çalışacaktır.
    result = engine(img, text_score=RAPIDOCR_TEXT_SCORE)

    if not result or not result.boxes:
        return [], w, h

    # 4. Koordinatları topla + katı filtre uygula
    out = []
    for box, text, score in zip(result.boxes, result.txts, result.scores):
        score = float(score) if score is not None else None

        text = _clean_text(text)
        if not text:
            continue
        # Türkçe post-processing: diacritik restorasyon + artefakt temizleme
        text = postprocess_turkish(text)
        if not text:
            continue
        if len(text) < RAPIDOCR_MIN_TOKEN_LEN and not any(ch.isdigit() for ch in text):
            continue
        if score is not None and score < RAPIDOCR_MIN_CONFIDENCE:
            continue

        # Bbox: [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
        box_arr = np.array(box)
        x_min, y_min = np.min(box_arr, axis=0)
        x_max, y_max = np.max(box_arr, axis=0)
        area = max(0.0, float(x_max - x_min)) * max(0.0, float(y_max - y_min))
        if area < RAPIDOCR_MIN_BOX_AREA:
            continue

        bbox = [float(x_min), float(y_min), float(x_max), float(y_max)]
        out.append((bbox, text))

    return out, w, h

def extract(
    file_path: Path | str | None,
    page_numbers: list[int] | None = None,
    *,
    image_bytes: bytes | None = None,
) -> list[dict[str, Any]]:
    """
    Ana OCR fonksiyonu.
    """
    page_no = (page_numbers[0] + 1) if page_numbers else 1

    if image_bytes:
        lines_bbox, page_width, page_height = _run_rapidocr(image_bytes=image_bytes)
    elif file_path:
        file_path = Path(file_path)
        if not file_path.exists(): return []
        img = load_image(str(file_path))
        lines_bbox, page_width, page_height = _run_rapidocr(image_array=img)
    else:
        return []

    text_blocks = [{"text": t, "bbox": b} for b, t in lines_bbox]
    from app.utils.text_layout import content_from_text_blocks_with_bbox
    content = content_from_text_blocks_with_bbox(text_blocks)

    return [{
        "page_number": page_no,
        "content": content,
        "tables": [],
        "text_blocks": text_blocks,
        "page_width": float(page_width),
        "page_height": float(page_height),
    }]