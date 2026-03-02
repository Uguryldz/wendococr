"""PDF sayfasını görüntüye dönüştürme (PyMuPDF). Lazy import ile startup hızlanır."""
from pathlib import Path
from typing import Iterator


def pdf_page_to_image(
    pdf_path: Path | str,
    page_index: int,
    dpi: int = 150,
) -> bytes | None:
    """
    PDF'in tek bir sayfasını PNG bytes olarak döner.
    OCR için uygun çözünürlük: dpi 150–200.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        return None
    try:
        import fitz
        doc = fitz.open(pdf_path)
        if page_index < 0 or page_index >= len(doc):
            doc.close()
            return None
        page = doc[page_index]
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        png_bytes = pix.tobytes("png")
        doc.close()
        return png_bytes
    except Exception:
        return None


def pdf_page_count(pdf_path: Path | str) -> int:
    """PDF sayfa sayısı."""
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        return 0
    try:
        import fitz
        doc = fitz.open(pdf_path)
        n = len(doc)
        doc.close()
        return n
    except Exception:
        return 0


def iter_pdf_pages_as_images(pdf_path: Path | str, dpi: int = 150) -> Iterator[tuple[int, bytes]]:
    """Sayfa indeksi ve PNG bytes üretir."""
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        return
    try:
        import fitz
        doc = fitz.open(pdf_path)
        for i in range(len(doc)):
            page = doc[i]
            mat = fitz.Matrix(dpi / 72, dpi / 72)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            yield i, pix.tobytes("png")
        doc.close()
    except Exception:
        pass
