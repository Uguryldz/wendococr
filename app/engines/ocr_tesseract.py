"""
pdfimagets motoru: Tesseract ile resim/taranmış sayfa OCR (Türkçe, koordinatlı).

KİLİTLİ: Bu modül Türkçe için ayarlandı; sonraki işlemlerde bu dosyaya müdahale etmeyin.

Türkçe için yaklaşım:
  - lang=tur
  - --oem 3 (LSTM)
  - PSM varsayılan 3 (auto); gerekirse env ile değiştirilebilir
  - preserve_interword_spaces=1 (rapor/tablolu metinde boşluklar daha stabil)
  - Ön işleme: Türkçe diakritikler için threshold varsayılan kapalı; deskew opsiyonel

Kullanılan kütüphaneler / versiyon (requirements.txt ile uyumlu):
  - pytesseract>=0.3.10 + sistem tesseract-ocr, tesseract-ocr-tur
  - opencv-python-headless>=4.8.0
  - app.utils.image_preprocess (preprocess_image)
"""
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pytesseract

from app.config import (
    TESSERACT_DESKEW,
    TESSERACT_ENHANCE,
    TESSERACT_PSM,
    TESSERACT_THRESHOLD,
    TESSERACT_USER_DEFINED_DPI,
)
from app.utils.image_preprocess import preprocess_image, load_image


def _enhance_for_turkish_tesseract(gray: np.ndarray) -> np.ndarray:
    """
    Türkçe karakterleri koruyarak Tesseract'a daha okunur görüntü vermek için hafif iyileştirme.
    - Küçük görüntülerde 2x büyütme (INTER_CUBIC)
    - CLAHE ile lokal kontrast
    """
    if gray is None or gray.size == 0:
        return gray
    h, w = gray.shape[:2]
    out = gray
    if max(h, w) < 1200:
        out = cv2.resize(out, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    try:
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        out = clahe.apply(out)
    except Exception:
        pass
    return out


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
    # 1) Griye çevir + (opsiyonel) iyileştirme + (opsiyonel) threshold/deskew
    if len(img.shape) == 3:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    if TESSERACT_ENHANCE:
        img = _enhance_for_turkish_tesseract(img)
    img = preprocess_image(
        cv2.cvtColor(img, cv2.COLOR_GRAY2BGR),
        grayscale=True,
        threshold=TESSERACT_THRESHOLD,
        deskew=TESSERACT_DESKEW,
    )
    out = []
    # Türkçe: lang=tur, LSTM motor (oem 3), otomatik segmentasyon (psm 3) + boşluk koruma
    # preserve_interword_spaces: tablo/rapor metinlerinde boşluk kaybını azaltır
    base_psm = str(TESSERACT_PSM).strip() or "3"
    psm_candidates = [base_psm, "6", "11"]
    # sırayı koruyarak tekilleştir
    seen: set[str] = set()
    psm_candidates = [p for p in psm_candidates if not (p in seen or seen.add(p))]

    base_cfg = "--oem 3 -c preserve_interword_spaces=1"
    if str(TESSERACT_USER_DEFINED_DPI).strip():
        base_cfg += f" -c user_defined_dpi={str(TESSERACT_USER_DEFINED_DPI).strip()}"

    def run_with_psm(psm_val: str) -> tuple[list[tuple[list[float], str]], float]:
        cfg = f"{base_cfg} --psm {psm_val}"
        # tur+eng: Türkçe + Latin (banka isimleri, kısaltmalar, sayılar)
        data = pytesseract.image_to_data(
            img, lang="tur+eng", config=cfg, output_type=pytesseract.Output.DICT
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
        n = len(texts)
        for i in range(n):
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
                width = int(widths[i])
                height = int(heights[i])
            except Exception:
                continue
            bbox = [float(left), float(top), float(left + width), float(top + height)]
            local_out.append((bbox, text))
        avg_conf = (conf_sum / conf_n) if conf_n else -1.0
        return local_out, avg_conf

    best_out: list[tuple[list[float], str]] = []
    best_conf = -1.0
    try:
        for psm_val in psm_candidates:
            local_out, avg_conf = run_with_psm(psm_val)
            # bazı sürümlerde conf=-1 gelebilir; bu durumda token sayısını da gözet
            better = avg_conf > best_conf
            if avg_conf < 0 and best_conf < 0:
                better = len(local_out) > len(best_out)
            if better:
                best_out, best_conf = local_out, avg_conf
        out = best_out
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
