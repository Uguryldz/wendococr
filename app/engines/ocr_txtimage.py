import fitz  # PyMuPDF
import json
import os
import time
import numpy as np
import cv2
from pathlib import Path
from typing import Any

from rapidocr_onnxruntime import RapidOCR
import traceback

_rapid_engine = None


def _get_rapid_engine():
    """RapidOCR örneğini tekilleştirir (lazy)."""
    global _rapid_engine
    if _rapid_engine is None:
        try:
            _rapid_engine = RapidOCR(det_limit_side_len=960)
        except Exception:
            pass
    return _rapid_engine


def _box_to_bbox(box: list) -> list[float]:
    """Dört nokta [[x,y],...] -> [x0, y0, x1, y1]."""
    if not box or len(box) < 4:
        return [0.0, 0.0, 0.0, 0.0]
    xs = [p[0] for p in box]
    ys = [p[1] for p in box]
    return [float(min(xs)), float(min(ys)), float(max(xs)), float(max(ys))]


def _process_page(page, ocr_engine) -> tuple[list[dict], float, float]:
    """
    Tek sayfa: native metin + resim OCR, spatial sıralı satır listesi.
    Döner: (page_lines, page_width, page_height).
    """
    rect = page.rect
    page_width, page_height = float(rect.width), float(rect.height)
    page_lines = []

    # 1. Native metin blokları
    text_dict = page.get_text("dict")
    for block in text_dict["blocks"]:
        if block["type"] == 0:
            for line in block["lines"]:
                line_text = "".join(span["text"] for span in line["spans"])
                b = line["bbox"]
                page_lines.append({
                    "text": line_text.strip(),
                    "confidence": 1.0,
                    "box": [[b[0], b[1]], [b[2], b[1]], [b[2], b[3]], [b[0], b[3]]],
                    "source": "native",
                })

    # 2. Resim blokları → OCR
    image_list = page.get_image_info(hashes=False)
    for img_info in image_list:
        bbox = img_info["bbox"]
        if (bbox[2] - bbox[0]) < 5 or (bbox[3] - bbox[1]) < 5:
            continue
        zoom = 5
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, clip=fitz.Rect(bbox))
        img_np = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
        if pix.n == 4:
            img_np = cv2.cvtColor(img_np, cv2.COLOR_RGBA2RGB)
        gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
        processed = cv2.convertScaleAbs(gray, alpha=1.5, beta=0)
        ocr_result, _ = ocr_engine(processed)
        if ocr_result:
            for item in ocr_result:
                res_box, res_text, res_conf = item
                page_lines.append({
                    "text": res_text.strip(),
                    "confidence": float(res_conf),
                    "box": [[p[0] / zoom + bbox[0], p[1] / zoom + bbox[1]] for p in res_box],
                    "source": "ocr_image",
                })

    page_lines.sort(key=lambda x: (x["box"][0][1], x["box"][0][0]))
    return page_lines, page_width, page_height


def extract(
    file_path: Path | str | None,
    page_numbers: list[int] | None = None,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    """
    Proje engine arayüzü: PDF'ten native metin + gömülü resim OCR.
    Döner: list[dict] with page_number, content, tables, text_blocks, page_width, page_height.
    """
    path = Path(file_path) if file_path else None
    if not path or not path.exists():
        return []

    engine = _get_rapid_engine()
    if engine is None:
        return []

    out = []
    try:
        doc = fitz.open(path)
        total = len(doc)
        pages_to_process = list(range(total))
        if page_numbers is not None:
            pages_to_process = [i for i in page_numbers if 0 <= i < total]
        for page_idx in pages_to_process:
            page = doc.load_page(page_idx)
            page_lines, page_width, page_height = _process_page(page, engine)
            content = "\n".join(l["text"] for l in page_lines).strip()
            text_blocks = [
                {"text": l["text"], "bbox": _box_to_bbox(l["box"])}
                for l in page_lines
            ]
            out.append({
                "page_number": page_idx + 1,
                "content": content,
                "tables": [],
                "text_blocks": text_blocks,
                "page_width": page_width,
                "page_height": page_height,
            })
        doc.close()
    except Exception:
        traceback.print_exc()
        return []
    return out


def process_findeks_special(pdf_path, output_json, ocr_engine=None, page_limit=999):
    """
    Findeks PDF'leri için özel hibrit motor:
    1. Metin bloklarını doğrudan çeker.
    2. Resim bloklarını tespit eder, OCR yapar.
    3. Spatial (konumsal) birleştirme ile tablo yapısını korur.
    """
    if not os.path.exists(pdf_path):
        print(f"Hata: {pdf_path} bulunamadı.")
        return

    engine = ocr_engine or _get_rapid_engine()
    if engine is None:
        print("Hata: OCR engine kullanılamıyor.")
        return

    results = []
    start_time = time.time()
    try:
        doc = fitz.open(pdf_path)
        num_pages = min(len(doc), page_limit)
        for page_idx in range(num_pages):
            page = doc.load_page(page_idx)
            page_lines, _, _ = _process_page(page, engine)
            results.append({"page": page_idx + 1, "lines": page_lines})
        doc.close()
        with open(output_json, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=4)
        print(f"İşlem Tamamlandı: {output_json} (Süre: {time.time() - start_time:.2f}s)")
    except Exception as e:
        print(f"Hata: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    process_findeks_special(
        "/home/uyildiz/test/test/findeks.pdf",
        "/home/uyildiz/test/test/findeks_special.json",
    )
