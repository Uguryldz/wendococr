#!/usr/bin/env python3
"""RapidOCR (pdfimagev5) ile koordinatlı JSON çıktısı. Kullanım: python ocr_rapid_test.py sgk.pdf veya sil.png"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.router import process_document
from app.schemas import ExtractResponse, page_result_from_engine


def main():
    if len(sys.argv) < 2:
        print("Kullanım: python ocr_rapid_test.py <dosya.pdf|dosya.png|dosya.jpg>", file=sys.stderr)
        sys.exit(1)
    path = Path(sys.argv[1])
    if not path.exists():
        print(f"Dosya bulunamadı: {path}", file=sys.stderr)
        sys.exit(1)

    suffix = path.suffix.lower()
    content_type = "application/pdf" if suffix == ".pdf" else f"image/{'jpeg' if suffix in ('.jpg', '.jpeg') else 'png'}"

    pages_raw, method_used = process_document(path, mode="pdfimagev5", content_type=content_type)
    pages = [
        page_result_from_engine(
            p["page_number"],
            p.get("content", ""),
            p.get("tables"),
            text_blocks=p.get("text_blocks"),
            page_width=p.get("page_width"),
            page_height=p.get("page_height"),
        )
        for p in pages_raw
    ]
    pages.sort(key=lambda x: x.page_number)

    resp = ExtractResponse(
        filename=path.name,
        method_used=method_used,
        processing_time_sec=0,
        pages=pages,
    )
    print(json.dumps(resp.model_dump(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
