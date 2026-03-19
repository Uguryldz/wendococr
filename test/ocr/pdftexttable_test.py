#!/usr/bin/env python3
"""pdfplumber (pdftexttable) ile koordinatlı JSON çıktısı. Kullanım: python pdftexttable_test.py sgk.pdf"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.router import process_document
from app.schemas import ExtractResponse, page_result_from_engine


def main():
    if len(sys.argv) < 2:
        print("Kullanım: python pdftexttable_test.py <dosya.pdf>", file=sys.stderr)
        sys.exit(1)
    path = Path(sys.argv[1])
    if not path.exists():
        print(f"Dosya bulunamadı: {path}", file=sys.stderr)
        sys.exit(1)

    pages_raw, method_used = process_document(path, mode="pdftexttable", content_type="application/pdf")
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
