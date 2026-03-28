"""
Akıllı Karar Mekanizması (Brain).
Gelen belgeye göre sayfa bazlı engine seçer. Ağır kütüphaneler ilk kullanımda yüklenir (hızlı startup).
"""
from pathlib import Path
import os
from typing import Any

from app.config import (
    ALLOWED_IMAGE_TYPES,
    ALLOWED_PDF_TYPE,
    AUTO_FORCE_RAPID_OCR,
    AUTO_FORCE_PADDLEOCR_LOW,
    EXTRACT_MODES,
    ICR_DPI,
    OCR_DPI_RAPID,
    OCR_DPI_TESSERACT,
    OCR_DPI_PADDLEOCR_LOW,
)

# Minimum metin uzunluğu: sayfa "searchable" kabul edilir
MIN_TEXT_LENGTH_SEARCHABLE = 20
MIN_TABLE_ROWS_FOR_TABLE_ENGINE = 2


def _page_has_text_layer(pdf_path: Path, page_index: int) -> bool:
    """PyMuPDF ile sayfada metin katmanı var mı (lazy import)."""
    try:
        import fitz
        doc = fitz.open(pdf_path)
        page = doc[page_index]
        text = page.get_text().strip()
        doc.close()
        return len(text) >= MIN_TEXT_LENGTH_SEARCHABLE
    except Exception:
        return False


def _page_is_table_heavy(pdf_path: Path, page_index: int) -> bool:
    """pdfplumber ile sayfada anlamlı tablo var mı (lazy import)."""
    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            if page_index >= len(pdf.pages):
                return False
            page = pdf.pages[page_index]
            tables = page.extract_tables() or []
            for t in tables:
                if t and len(t) >= MIN_TABLE_ROWS_FOR_TABLE_ENGINE:
                    return True
            return False
    except Exception:
        return False


def _decide_engine_for_pdf_page(pdf_path: Path, page_index: int) -> str:
    """Tek bir PDF sayfası için engine seçer."""
    if _page_has_text_layer(pdf_path, page_index):
        if _page_is_table_heavy(pdf_path, page_index):
            return "pdftexttable"
        return "pdftext"
    if AUTO_FORCE_PADDLEOCR_LOW:
        return "pdfimagepaddleocrlow"
    return "pdfimagev5"


def process_document(
    file_path: Path,
    mode: str = "auto",
    content_type: str | None = None,
    page_numbers: list[int] | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """
    Belgeyi işler; sayfa bazlı karar (auto modda) uygular.
    Motorlar ilk kullanımda yüklenir.
    """
    if mode not in EXTRACT_MODES:
        mode = "auto"
    path = Path(file_path)
    if not path.exists():
        return [], ""

    # Lazy import: sadece kullanılan motor yüklenir
    if mode == "pdftext":
        from app.engines.pdf_text import extract as pdf_text_extract
        raw = pdf_text_extract(path, page_numbers=page_numbers)
        return raw, "pdftext"
    if mode == "pdftexttable":
        from app.engines.pdf_table import extract as pdf_table_extract
        raw = pdf_table_extract(path, page_numbers=page_numbers)
        return raw, "pdftexttable"
    if mode == "pdfimagev5":
        return _run_ocr_pdf_or_image(path, content_type, engine="pdfimagev5", page_numbers=page_numbers)
    if mode == "pdfimagets":
        return _run_ocr_pdf_or_image(path, content_type, engine="pdfimagets", page_numbers=page_numbers)
    if mode == "pdfimagepaddleocrlow":
        return _run_ocr_pdf_or_image(path, content_type, engine="pdfimagepaddleocrlow", page_numbers=page_numbers)
    if mode == "pdftxtimage":
        from app.engines.ocr_txtimage import extract as ocr_txtimage_extract
        raw = ocr_txtimage_extract(path, page_numbers=page_numbers)
        return raw, "pdftxtimage"
    if mode == "pdfimagetable":
        from app.engines.ocr_imagetable import extract as ocr_imagetable_extract
        raw = ocr_imagetable_extract(path, page_numbers=page_numbers)
        return raw, "pdfimagetable"
    if mode == "icr":
        return _run_ocr_pdf_or_image(path, content_type, engine="icr", page_numbers=page_numbers)
    if mode == "icrpaddle":
        return _run_ocr_pdf_or_image(path, content_type, engine="icrpaddle", page_numbers=page_numbers)
    # --- AUTO ---
    if content_type and content_type.lower() in ALLOWED_IMAGE_TYPES:
        return _run_ocr_pdf_or_image(path, content_type, engine="pdfimagev5", page_numbers=page_numbers or [0])

    if content_type and content_type.lower() == ALLOWED_PDF_TYPE:
        pass
    else:
        if path.suffix.lower() == ".pdf":
            content_type = ALLOWED_PDF_TYPE
        else:
            return _run_ocr_pdf_or_image(path, content_type, engine="pdfimagev5", page_numbers=page_numbers or [0])

    # AUTO_FORCE_RAPID_OCR aktifse PDF tarafında da direkt RapidOCR kullan.
    if AUTO_FORCE_RAPID_OCR:
        return _run_ocr_pdf_or_image(path, content_type, engine="pdfimagev5", page_numbers=page_numbers)

    # PDF auto: sayfa bazlı karar (pdf_convert ve engines ilk kullanımda yüklenir)
    from app.utils.pdf_convert import pdf_page_count, pdf_page_to_image
    from app.engines.pdf_text import extract as pdf_text_extract
    from app.engines.pdf_table import extract as pdf_table_extract
    from app.engines.ocr_rapid import extract as ocr_rapid_extract

    n_pages = pdf_page_count(path)
    if n_pages == 0:
        return [], ""
    indices = page_numbers if page_numbers is not None else list(range(n_pages))
    indices = [i for i in indices if 0 <= i < n_pages]
    all_pages: list[dict[str, Any]] = []
    methods_used: list[str] = []
    empty_page = {"page_number": 0, "content": "", "tables": [], "text_blocks": [], "page_width": None, "page_height": None}

    for i in indices:
        engine = _decide_engine_for_pdf_page(path, i)
        methods_used.append(engine)
        ep = dict(empty_page)
        ep["page_number"] = i + 1

        if engine == "pdftext":
            part = pdf_text_extract(path, page_numbers=[i])
        elif engine == "pdftexttable":
            part = pdf_table_extract(path, page_numbers=[i])
        else:
            png_bytes = pdf_page_to_image(path, i, dpi=OCR_DPI_RAPID)
            if png_bytes:
                part = ocr_rapid_extract(path, page_numbers=[i], image_bytes=png_bytes)
            else:
                part = [ep]
        all_pages.extend(part)

    if not methods_used:
        return [], ""
    method_used = max(set(methods_used), key=methods_used.count)
    return all_pages, method_used


def _run_ocr_pdf_or_image(
    path: Path,
    content_type: str | None,
    engine: str,
    page_numbers: list[int] | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """PDF veya resim; OCR motoru lazy yüklenir."""
    path = Path(path)
    is_pdf = content_type and content_type.lower() == ALLOWED_PDF_TYPE
    is_pdf = is_pdf or path.suffix.lower() == ".pdf"
    empty_page = {"page_number": 0, "content": "", "tables": [], "text_blocks": [], "page_width": None, "page_height": None}

    if is_pdf:
        from app.utils.pdf_convert import pdf_page_count, pdf_page_to_image
        n_pages = pdf_page_count(path)
        indices = page_numbers if page_numbers is not None else list(range(n_pages))
        indices = [i for i in indices if 0 <= i < n_pages]
        all_pages = []
        for i in indices:
            if engine == "pdfimagev5":
                dpi = OCR_DPI_RAPID
            elif engine == "pdfimagepaddleocrlow":
                dpi = int(os.environ.get("OCR_DPI_PADDLEOCR_LOW", str(OCR_DPI_PADDLEOCR_LOW)))
            elif engine in ("icr", "icrpaddle"):
                dpi = ICR_DPI
            else:
                dpi = OCR_DPI_TESSERACT
            png_bytes = pdf_page_to_image(path, i, dpi=dpi)
            if png_bytes:
                if engine == "pdfimagev5":
                    from app.engines.ocr_rapid import extract as ocr_rapid_extract
                    part = ocr_rapid_extract(path, page_numbers=[i], image_bytes=png_bytes)
                elif engine == "pdfimagepaddleocrlow":
                    from app.engines.ocr_paddleocr_low import extract as ocr_paddleocr_low_extract
                    part = ocr_paddleocr_low_extract(path, page_numbers=[i], image_bytes=png_bytes)
                elif engine == "icr":
                    from app.engines.icr_tesseract import extract as icr_tesseract_extract
                    part = icr_tesseract_extract(path, page_numbers=[i], image_bytes=png_bytes)
                elif engine == "icrpaddle":
                    from app.engines.icr_paddleocr import extract as icr_paddleocr_extract
                    part = icr_paddleocr_extract(path, page_numbers=[i], image_bytes=png_bytes)
                else:
                    from app.engines.ocr_tesseract import extract as ocr_tesseract_extract
                    part = ocr_tesseract_extract(path, page_numbers=[i], image_bytes=png_bytes)
            else:
                part = [dict(empty_page)]
                part[0]["page_number"] = i + 1
            all_pages.extend(part)
        return all_pages, engine

    # Tek sayfa resim
    if engine == "pdfimagev5":
        from app.engines.ocr_rapid import extract as ocr_rapid_extract
        raw = ocr_rapid_extract(path, page_numbers=[0])
    elif engine == "pdfimagepaddleocrlow":
        from app.engines.ocr_paddleocr_low import extract as ocr_paddleocr_low_extract
        raw = ocr_paddleocr_low_extract(path, page_numbers=[0])
    elif engine == "icr":
        from app.engines.icr_tesseract import extract as icr_tesseract_extract
        raw = icr_tesseract_extract(path, page_numbers=[0])
    elif engine == "icrpaddle":
        from app.engines.icr_paddleocr import extract as icr_paddleocr_extract
        raw = icr_paddleocr_extract(path, page_numbers=[0])
    else:
        from app.engines.ocr_tesseract import extract as ocr_tesseract_extract
        raw = ocr_tesseract_extract(path, page_numbers=[0])
    return raw, engine
