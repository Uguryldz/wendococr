#!/usr/bin/env python3
"""
EasyOCR ile basit OCR testi.

Kullanım:
  python test/easyocr_test.py test/sil.png
  python test/easyocr_test.py test/ocr/sgk.pdf --lang tr en --dpi 200

Notlar:
  - PDF sayfaları görüntüye çevirmek için projedeki `app.utils.pdf_convert` kullanılır.
  - Çıktı stdout'a JSON olarak yazılır.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import easyocr
except ImportError:
    print("easyocr bulunamadı. Kurulum: pip install easyocr", file=sys.stderr)
    sys.exit(1)

from app.utils.pdf_convert import iter_pdf_pages_as_images, pdf_page_count
from app.schemas import ExtractResponse, page_result_from_engine


def _to_jsonable(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    # numpy scalar / other numeric-like objects
    try:
        if hasattr(value, "item"):
            return _to_jsonable(value.item())
    except Exception:
        pass
    return str(value)


def _bbox_to_xyxy(bbox) -> list[float]:
    # EasyOCR bbox formati: [[x,y], [x,y], [x,y], [x,y]]
    points = _to_jsonable(bbox)
    if not isinstance(points, list) or len(points) < 4:
        return [0.0, 0.0, 0.0, 0.0]
    xs: list[float] = []
    ys: list[float] = []
    for p in points:
        if isinstance(p, list) and len(p) >= 2:
            xs.append(float(p[0]))
            ys.append(float(p[1]))
    if not xs or not ys:
        return [0.0, 0.0, 0.0, 0.0]
    return [min(xs), min(ys), max(xs), max(ys)]


def ocr_image_bytes(reader: "easyocr.Reader", image_bytes: bytes) -> dict:
    # EasyOCR, bytes için dosya yolu bekler; burada bytes'ı numpy'ye çevirmek için cv2 kullanıyoruz.
    try:
        import numpy as np
        import cv2
    except ImportError:
        print(
            "PDF sayfalarını (bytes) işlemek için ek paketler gerekiyor. Kurulum: pip install opencv-python numpy",
            file=sys.stderr,
        )
        sys.exit(1)

    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError("Görüntü decode edilemedi (cv2.imdecode None döndü).")

    results = reader.readtext(img)
    text_blocks = []
    content_parts = []
    for bbox, text, conf in results:
        xyxy = _bbox_to_xyxy(bbox)
        clean_text = (text or "").strip()
        if clean_text:
            content_parts.append(clean_text)
        text_blocks.append(
            {
                "bbox": xyxy,
                "text": clean_text,
                "confidence": float(conf) if conf is not None else None,
            }
        )
    return {"content": "\n".join(content_parts), "text_blocks": text_blocks}


def ocr_image_path(reader: "easyocr.Reader", path: Path) -> dict:
    results = reader.readtext(str(path))
    text_blocks = []
    content_parts = []
    for bbox, text, conf in results:
        xyxy = _bbox_to_xyxy(bbox)
        clean_text = (text or "").strip()
        if clean_text:
            content_parts.append(clean_text)
        text_blocks.append(
            {
                "bbox": xyxy,
                "text": clean_text,
                "confidence": float(conf) if conf is not None else None,
            }
        )
    return {"content": "\n".join(content_parts), "text_blocks": text_blocks}


def main() -> None:
    p = argparse.ArgumentParser(description="EasyOCR test script (PDF veya görüntü)")
    p.add_argument("path", type=Path, help="PDF veya görüntü dosyası")
    p.add_argument("--lang", nargs="+", default=["tr"], help="Dil listesi (örn: tr en)")
    p.add_argument("--gpu", action="store_true", help="GPU kullan (CUDA varsa)")
    p.add_argument("--dpi", type=int, default=200, help="PDF sayfalarını görüntüye çevirme DPI")
    p.add_argument("-o", "--output", type=Path, help="JSON cikti dosyasi (orn: test/sil.json)")
    args = p.parse_args()

    path = Path(args.path)
    if not path.exists():
        print(f"Dosya bulunamadı: {path}", file=sys.stderr)
        sys.exit(1)

    reader = easyocr.Reader(args.lang, gpu=bool(args.gpu))

    suffix = path.suffix.lower()
    pages = []
    t0 = time.perf_counter()

    if suffix == ".pdf":
        total_pages = pdf_page_count(path)
        for i, png_bytes in iter_pdf_pages_as_images(path, dpi=args.dpi):
            page = ocr_image_bytes(reader, png_bytes)
            pages.append(
                {
                    "page_number": i + 1,
                    "content": page["content"],
                    "text_blocks": page["text_blocks"],
                    "tables": [],
                    "page_width": None,
                    "page_height": None,
                }
            )
    else:
        page = ocr_image_path(reader, path)
        pages.append(
            {
                "page_number": 1,
                "content": page["content"],
                "text_blocks": page["text_blocks"],
                "tables": [],
                "page_width": None,
                "page_height": None,
            }
        )

    api_pages = [
        page_result_from_engine(
            p["page_number"],
            p.get("content", ""),
            p.get("tables"),
            text_blocks=p.get("text_blocks"),
            page_width=p.get("page_width"),
            page_height=p.get("page_height"),
        )
        for p in pages
    ]
    api_pages.sort(key=lambda x: x.page_number)
    result = ExtractResponse(
        filename=path.name,
        method_used="easyocr",
        processing_time_sec=round(time.perf_counter() - t0, 3),
        pages=api_pages,
    ).model_dump()

    payload = json.dumps(result, ensure_ascii=False, indent=2)
    print(payload)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")


if __name__ == "__main__":
    main()

