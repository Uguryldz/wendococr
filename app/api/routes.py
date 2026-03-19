"""FastAPI endpoint'leri: her motor için ayrı uç, /health."""
import asyncio
import time
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import PlainTextResponse

from app.config import (
    ALLOWED_EXTENSIONS,
    ALLOWED_IMAGE_TYPES,
    ALLOWED_PDF_TYPE,
    EXT_TO_MIME,
    MAX_FILE_SIZE_BYTES,
    MAX_PAGES,
    UPLOAD_DIR,
)
from app.core.router import process_document
from app.schemas import ExtractResponse, PageResult, page_result_from_engine
from app.utils.page_range import parse_page_range

# Swagger'da dosya alanı açıklaması
FILE_UPLOAD_DESC = (
    "Belge dosyası. Desteklenen: PDF; resim: JPEG, PNG, BMP, WEBP, TIFF, TIF, GIF, PBM, PGM, PPM. "
    "Endpoint'e göre sadece PDF veya sadece resim kabul edenler var (açıklamaya bakın)."
)
router = APIRouter()


def _validate_file(file: UploadFile, mode: str) -> None:
    """Dosya tipi ve uzantı doğrulaması. Geçersizse HTTPException."""
    suffix = Path(file.filename or "file").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"Desteklenmeyen dosya uzantısı: {suffix}. İzin verilen: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )
    ct = (file.content_type or "").strip().lower()
    expected_mime = EXT_TO_MIME.get(suffix)
    if ct and expected_mime:
        # content_type ile uzantı uyumlu olmalı
        if ct != expected_mime and ct not in (ALLOWED_IMAGE_TYPES | {ALLOWED_PDF_TYPE}):
            raise HTTPException(
                status_code=415,
                detail=f"Dosya tipi uyumsuz: uzantı {suffix}, Content-Type {ct}",
            )
    # PDF-only modlar
    if mode in ("pdftext", "pdftexttable", "pdftxtimage", "pdfimagetable"):
        if suffix != ".pdf":
            raise HTTPException(status_code=415, detail="Bu endpoint sadece PDF kabul eder.")


async def _process_upload(
    file: UploadFile,
    mode: str,
    *,
    page_range: str | None = None,
    format: str = "json",
) -> ExtractResponse | PlainTextResponse:
    """Ortak: dosyayı kaydet, ilgili motorla işle, yanıt döndür."""
    content = await file.read()
    if len(content) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Dosya çok büyük. Maksimum: {MAX_FILE_SIZE_BYTES // (1024*1024)} MB",
        )
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Boş dosya.")

    suffix = Path(file.filename or "file").suffix.lower() or ".bin"
    _validate_file(file, mode)

    safe_name = "".join(c for c in (file.filename or "upload")[:80] if c.isalnum() or c in "._- ") or "upload"
    tmp_path = UPLOAD_DIR / f"{safe_name}_{time.time_ns()}{suffix}"
    try:
        tmp_path.write_bytes(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Dosya yazılamadı: {e}")

    # Sayfa aralığı parse (max 500)
    page_numbers = parse_page_range(page_range, max_pages=MAX_PAGES)

    start_time = time.perf_counter()
    try:
        loop = asyncio.get_event_loop()
        pages_raw, method_used = await loop.run_in_executor(
            None,
            lambda: process_document(
                tmp_path,
                mode=mode,
                content_type=file.content_type or EXT_TO_MIME.get(suffix),
                page_numbers=page_numbers,
            ),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"İşleme hatası: {str(e)}")
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
    processing_time_sec = round(time.perf_counter() - start_time, 3)

    if len(pages_raw) > MAX_PAGES:
        raise HTTPException(status_code=422, detail=f"Sayfa sayısı limiti aşıldı (max {MAX_PAGES}).")

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

    if format == "text":
        full_text = "\n\n".join(f"--- Sayfa {p.page_number} ---\n{p.content}" for p in pages)
        return PlainTextResponse(content=full_text, media_type="text/plain; charset=utf-8")

    return ExtractResponse(
        filename=file.filename or "unknown",
        method_used=method_used or mode,
        processing_time_sec=processing_time_sec,
        pages=pages,
    )


def _check_tesseract() -> bool:
    """Tesseract ve tur dili kurulu mu?"""
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
        # tur traineddata var mı?
        langs = set(pytesseract.get_languages(config=""))
        if "tur" not in langs:
            return False
        return True
    except Exception:
        return False


def _check_rapidocr() -> bool:
    """RapidOCR modülü yüklenebilir mi?"""
    try:
        from rapidocr_onnxruntime import RapidOCR  # noqa: F401
        return True
    except Exception:
        return False


def _check_upload_dir() -> bool:
    """UPLOAD_DIR yazılabilir mi?"""
    try:
        test_file = UPLOAD_DIR / ".health_check"
        test_file.write_text("ok")
        test_file.unlink(missing_ok=True)
        return True
    except Exception:
        return False


@router.get("/health", tags=["Sistem"], summary="Sağlık kontrolü")
def health():
    """Servisin ayakta olduğunu ve bağımlılıkları doğrular."""
    return {
        "status": "ok",
        "checks": {
            "tesseract": _check_tesseract(),
            "rapidocr": _check_rapidocr(),
            "upload_dir_writable": _check_upload_dir(),
        },
    }


@router.post(
    "/v1/auto",
    tags=["Belge çıkarımı"],
    summary="Otomatik motor seçimi",
)
async def v1_auto(
    file: UploadFile = File(..., description=FILE_UPLOAD_DESC),
    page_range: str | None = Query(None, description="Sayfa aralığı: 1-5, 1,3,7"),
    format: str = Query("json", description="Çıktı: json veya text"),
):
    """
    Belgeyi otomatik analiz eder; içeriğe göre sayfa bazlı en uygun motoru seçer.

    **Kabul edilen formatlar:** PDF, JPEG, PNG, BMP, WEBP, TIFF, TIF, GIF, PBM, PGM, PPM.
    Resim → OCR. PDF: metin katmanı ve tablo yoğunluğuna göre otomatik motor seçimi.
    **Kütüphaneler:** pymupdf>=1.23.0, pdfplumber>=0.10.0, rapidocr_onnxruntime>=1.3.0, opencv-python-headless>=4.8.0 (motor seçimine göre).
    """
    return await _process_upload(file, "auto", page_range=page_range, format=format)


@router.post(
    "/v1/pdftext",
    tags=["Belge çıkarımı"],
    summary="PDF metin",
)
async def v1_pdftext(
    file: UploadFile = File(..., description=FILE_UPLOAD_DESC),
    page_range: str | None = Query(None, description="Sayfa aralığı: 1-5, 1,3,7"),
    format: str = Query("json", description="Çıktı: json veya text"),
):
    """
    Dijital (searchable) PDF'ten yalnızca metin çıkarımı. **Sadece PDF** kabul edilir.
    **Kütüphaneler:** pymupdf>=1.23.0. Motor: app.engines.pdf_text.
    """
    return await _process_upload(file, "pdftext", page_range=page_range, format=format)


@router.post(
    "/v1/pdftexttable",
    tags=["Belge çıkarımı"],
    summary="Metin + tablo",
)
async def v1_pdftexttable(
    file: UploadFile = File(..., description=FILE_UPLOAD_DESC),
    page_range: str | None = Query(None, description="Sayfa aralığı: 1-5, 1,3,7"),
    format: str = Query("json", description="Çıktı: json veya text"),
):
    """
    Dijital PDF'ten metin ve tablo çıkarımı. Tablo ağırlıklı belgeler için. **Sadece PDF** kabul edilir.
    **Kütüphaneler:** pdfplumber>=0.10.0. Motor: app.engines.pdf_table.
    """
    return await _process_upload(file, "pdftexttable", page_range=page_range, format=format)


@router.post(
    "/v1/pdfimagev5",
    tags=["Belge çıkarımı"],
    summary="Taranmış PDF / resim OCR",
)
async def v1_pdfimagev5(
    file: UploadFile = File(..., description=FILE_UPLOAD_DESC),
    page_range: str | None = Query(None, description="Sayfa aralığı: 1-5, 1,3,7"),
    format: str = Query("json", description="Çıktı: json veya text"),
):
    """
    Taranmış PDF veya resim üzerinde OCR. **PDF veya resim** kabul edilir.
    Resim: JPEG, PNG, BMP, WEBP, TIFF, TIF, GIF, PBM, PGM, PPM (okunabilen tüm formatlar).
    **Kütüphaneler:** rapidocr_onnxruntime>=1.3.0, pymupdf>=1.23.0 (PDF→görüntü), opencv-python-headless>=4.8.0. Motor: app.engines.ocr_rapid.
    """
    return await _process_upload(file, "pdfimagev5", page_range=page_range, format=format)


@router.post(
    "/v1/pdfimagets",
    tags=["Belge çıkarımı"],
    summary="OCR (Türkçe)",
)
async def v1_pdfimagets(
    file: UploadFile = File(..., description=FILE_UPLOAD_DESC),
    page_range: str | None = Query(None, description="Sayfa aralığı: 1-5, 1,3,7"),
    format: str = Query("json", description="Çıktı: json veya text"),
):
    """
    Türkçe OCR (Tesseract). **PDF veya resim** kabul edilir.
    Resim: JPEG, PNG, BMP, WEBP, TIFF, TIF, GIF, PBM, PGM, PPM.
    **Kilitli endpoint** — Tesseract Türkçe için ayarlı, değiştirmeyin.
    **Kütüphaneler:** pytesseract>=0.3.10, pymupdf>=1.23.0 (PDF→görüntü), opencv-python-headless>=4.8.0, tesseract-ocr-tur (sistem). Motor: app.engines.ocr_tesseract.
    """
    return await _process_upload(file, "pdfimagets", page_range=page_range, format=format)


@router.post(
    "/v1/pdftxtimage",
    tags=["Belge çıkarımı"],
    summary="Hibrit: metin + gömülü resim OCR (Findeks Raporu tarzı)",
)
async def v1_pdftxtimage(
    file: UploadFile = File(..., description=FILE_UPLOAD_DESC),
    page_range: str | None = Query(None, description="Sayfa aralığı: 1-5, 1,3,7"),
    format: str = Query("json", description="Çıktı: json veya text"),
):
    """
    Findeks Raporu vb. hibrit belgeler: PDF'te hem metin katmanı hem gömülü resimler.
    Gömülü resimler Tesseract Türkçe (lang=tur, --oem 3 --psm 6) ile OCR. Motor: app.engines.ocr_txtimage.
    **Kilitli endpoint** — düzgün çalışıyor, değiştirmeyin. **Sadece PDF** kabul edilir.
    **Kütüphaneler:** pymupdf>=1.23.0, pytesseract>=0.3.10, opencv-python-headless>=4.8.0, tesseract-ocr-tur (sistem).
    """
    return await _process_upload(file, "pdftxtimage", page_range=page_range, format=format)


@router.post(
    "/v1/pdfimagetable",
    tags=["Belge çıkarımı"],
    summary="Tablo yapısı korumalı OCR (Findeks Raporu tarzı)",
)
async def v1_pdfimagetable(
    file: UploadFile = File(..., description=FILE_UPLOAD_DESC),
    page_range: str | None = Query(None, description="Sayfa aralığı: 1-5, 1,3,7"),
    format: str = Query("json", description="Çıktı: json veya text"),
):
    """
    Findeks Raporu, kredi raporu vb. tablo + gömülü resim içeren belgeler için.
    Tablo yapısını koruyarak metin + gömülü resim OCR (Tesseract Türkçe). PDF sayfa düzeni bozulmaz.
    **Kilitli endpoint** — düzgün çalışıyor, değiştirmeyin. **Sadece PDF** kabul edilir.
    **Kütüphaneler:** pdfplumber>=0.10.0, pymupdf>=1.23.0, pytesseract>=0.3.10, opencv-python-headless>=4.8.0, tesseract-ocr-tur (sistem). Motor: app.engines.ocr_imagetable.
    """
    return await _process_upload(file, "pdfimagetable", page_range=page_range, format=format)
