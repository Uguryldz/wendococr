"""
Akıllı Karar Mekanizması (Brain).
Gelen belgeye göre sayfa bazlı engine seçer. Ağır kütüphaneler ilk kullanımda yüklenir (hızlı startup).
"""
from pathlib import Path
from typing import Any

from app.config import ALLOWED_IMAGE_TYPES, ALLOWED_PDF_TYPE, EXTRACT_MODES

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
    return "pdfimagev5"


def process_document(
    file_path: Path,
    mode: str = "auto",
    content_type: str | None = None,
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
        raw = pdf_text_extract(path, page_numbers=None)
        return raw, "pdftext"
    if mode == "pdftexttable":
        from app.engines.pdf_table import extract as pdf_table_extract
        raw = pdf_table_extract(path, page_numbers=None)
        return raw, "pdftexttable"
    if mode == "pdfimagev5":
        return _run_ocr_pdf_or_image(path, content_type, engine="pdfimagev5")
    if mode == "pdfimagets":
        return _run_ocr_pdf_or_image(path, content_type, engine="pdfimagets")
    if mode == "pdftxtimage":
        from app.engines.ocr_txtimage import extract as ocr_txtimage_extract
        raw = ocr_txtimage_extract(path, page_numbers=None)
        return raw, "pdftxtimage"
    if mode == "pdfimagetable":
        from app.engines.ocr_imagetable import extract as ocr_imagetable_extract
        raw = ocr_imagetable_extract(path, page_numbers=None)
        return raw, "pdfimagetable"

    # --- AUTO ---
    if content_type and content_type.lower() in ALLOWED_IMAGE_TYPES:
        from app.engines.ocr_rapid import extract as ocr_rapid_extract
        raw = ocr_rapid_extract(path, page_numbers=[0])
        return raw, "pdfimagev5"

    if content_type and content_type.lower() == ALLOWED_PDF_TYPE:
        pass
    else:
        if path.suffix.lower() == ".pdf":
            content_type = ALLOWED_PDF_TYPE
        else:
            from app.engines.ocr_rapid import extract as ocr_rapid_extract
            raw = ocr_rapid_extract(path, page_numbers=[0])
            return raw, "pdfimagev5"

    # PDF auto: sayfa bazlı karar (pdf_convert ve engines ilk kullanımda yüklenir)
    from app.utils.pdf_convert import pdf_page_count, pdf_page_to_image
    from app.engines.pdf_text import extract as pdf_text_extract
    from app.engines.pdf_table import extract as pdf_table_extract
    from app.engines.ocr_rapid import extract as ocr_rapid_extract

    n_pages = pdf_page_count(path)
    if n_pages == 0:
        return [], ""
    all_pages: list[dict[str, Any]] = []
    methods_used: list[str] = []
    empty_page = {"page_number": 0, "content": "", "tables": [], "text_blocks": [], "page_width": None, "page_height": None}

    for i in range(n_pages):
        engine = _decide_engine_for_pdf_page(path, i)
        methods_used.append(engine)
        empty_page = {"page_number": i + 1, "content": "", "tables": [], "text_blocks": [], "page_width": None, "page_height": None}

        if engine == "pdftext":
            part = pdf_text_extract(path, page_numbers=[i])
        elif engine == "pdftexttable":
            part = pdf_table_extract(path, page_numbers=[i])
        else:
            png_bytes = pdf_page_to_image(path, i, dpi=150)
            if png_bytes:
                part = ocr_rapid_extract(path, page_numbers=[i], image_bytes=png_bytes)
            else:
                part = [dict(empty_page)]
        all_pages.extend(part)

    if not methods_used:
        return [], ""
    method_used = max(set(methods_used), key=methods_used.count)
    return all_pages, method_used


def _run_ocr_pdf_or_image(
    path: Path,
    content_type: str | None,
    engine: str,
) -> tuple[list[dict[str, Any]], str]:
    """PDF veya resim; OCR motoru lazy yüklenir."""
    path = Path(path)
    is_pdf = content_type and content_type.lower() == ALLOWED_PDF_TYPE
    is_pdf = is_pdf or path.suffix.lower() == ".pdf"
    empty_page = {"page_number": 0, "content": "", "tables": [], "text_blocks": [], "page_width": None, "page_height": None}

    if is_pdf:
        from app.utils.pdf_convert import pdf_page_count, pdf_page_to_image
        n_pages = pdf_page_count(path)
        all_pages = []
        for i in range(n_pages):
            png_bytes = pdf_page_to_image(path, i, dpi=150)
            if png_bytes:
                if engine == "pdfimagev5":
                    from app.engines.ocr_rapid import extract as ocr_rapid_extract
                    part = ocr_rapid_extract(path, page_numbers=[i], image_bytes=png_bytes)
                else:
                    from app.engines.ocr_tesseract import extract as ocr_tesseract_extract
                    part = ocr_tesseract_extract(path, page_numbers=[i], image_bytes=png_bytes)
            else:
                part = [dict(empty_page)]
                part[0]["page_number"] = i + 1
            all_pages.extend(part)
        return all_pages, engine

    if engine == "pdfimagev5":
        from app.engines.ocr_rapid import extract as ocr_rapid_extract
        raw = ocr_rapid_extract(path, page_numbers=[0])
    else:
        from app.engines.ocr_tesseract import extract as ocr_tesseract_extract
        raw = ocr_tesseract_extract(path, page_numbers=[0])
    return raw, engine
