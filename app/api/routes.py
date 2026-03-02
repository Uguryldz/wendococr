"""FastAPI endpoint'leri: her motor için ayrı uç, /health."""
import asyncio
import time
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.config import MAX_FILE_SIZE_BYTES, MAX_PAGES, UPLOAD_DIR

# Swagger'da dosya alanı açıklaması
FILE_UPLOAD_DESC = (
    "Belge dosyası. Desteklenen: PDF; resim: JPEG, PNG, BMP, WEBP, TIFF, TIF, GIF, PBM, PGM, PPM. "
    "Endpoint'e göre sadece PDF veya sadece resim kabul edenler var (açıklamaya bakın)."
)
from app.core.router import process_document
from app.schemas import ExtractResponse, PageResult, page_result_from_engine

router = APIRouter()


async def _process_upload(file: UploadFile, mode: str) -> ExtractResponse:
    """Ortak: dosyayı kaydet, ilgili motorla işle, yanıt döndür."""
    content = await file.read()
    if len(content) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Dosya çok büyük. Maksimum: {MAX_FILE_SIZE_BYTES // (1024*1024)} MB",
        )
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Boş dosya.")

    suffix = Path(file.filename or "file").suffix or ".bin"
    safe_name = "".join(c for c in (file.filename or "upload")[:80] if c.isalnum() or c in "._- ") or "upload"
    tmp_path = UPLOAD_DIR / f"{safe_name}_{time.time_ns()}{suffix}"
    try:
        tmp_path.write_bytes(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Dosya yazılamadı: {e}")

    start_time = time.perf_counter()
    try:
        loop = asyncio.get_event_loop()
        pages_raw, method_used = await loop.run_in_executor(
            None,
            lambda: process_document(tmp_path, mode=mode, content_type=file.content_type),
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

    return ExtractResponse(
        filename=file.filename or "unknown",
        method_used=method_used or mode,
        processing_time_sec=processing_time_sec,
        pages=pages,
    )


@router.get("/health", tags=["Sistem"], summary="Sağlık kontrolü")
def health():
    """Servisin ayakta olduğunu doğrular."""
    return {"status": "ok"}


@router.post(
    "/v1/auto",
    response_model=ExtractResponse,
    tags=["Belge çıkarımı"],
    summary="Otomatik motor seçimi",
)
async def v1_auto(file: UploadFile = File(..., description=FILE_UPLOAD_DESC)):
    """
    Belgeyi otomatik analiz eder; içeriğe göre sayfa bazlı en uygun motoru seçer.

    **Kabul edilen formatlar:** PDF, JPEG, PNG, BMP, WEBP, TIFF, TIF, GIF, PBM, PGM, PPM.
    Resim → OCR. PDF: metin katmanı ve tablo yoğunluğuna göre otomatik motor seçimi.
    """
    return await _process_upload(file, "auto")


@router.post(
    "/v1/pdftext",
    response_model=ExtractResponse,
    tags=["Belge çıkarımı"],
    summary="PDF metin",
)
async def v1_pdftext(file: UploadFile = File(..., description=FILE_UPLOAD_DESC)):
    """Dijital (searchable) PDF'ten yalnızca metin çıkarımı. **Sadece PDF** kabul edilir."""
    return await _process_upload(file, "pdftext")


@router.post(
    "/v1/pdftexttable",
    response_model=ExtractResponse,
    tags=["Belge çıkarımı"],
    summary="Metin + tablo",
)
async def v1_pdftexttable(file: UploadFile = File(..., description=FILE_UPLOAD_DESC)):
    """Dijital PDF'ten metin ve tablo çıkarımı. Tablo ağırlıklı belgeler için. **Sadece PDF** kabul edilir."""
    return await _process_upload(file, "pdftexttable")


@router.post(
    "/v1/pdfimagev5",
    response_model=ExtractResponse,
    tags=["Belge çıkarımı"],
    summary="Taranmış PDF / resim OCR",
)
async def v1_pdfimagev5(file: UploadFile = File(..., description=FILE_UPLOAD_DESC)):
    """
    Taranmış PDF veya resim üzerinde OCR. **PDF veya resim** kabul edilir.
    Resim: JPEG, PNG, BMP, WEBP, TIFF, TIF, GIF, PBM, PGM, PPM (okunabilen tüm formatlar).
    """
    return await _process_upload(file, "pdfimagev5")


@router.post(
    "/v1/pdfimagets",
    response_model=ExtractResponse,
    tags=["Belge çıkarımı"],
    summary="OCR (Türkçe)",
)
async def v1_pdfimagets(file: UploadFile = File(..., description=FILE_UPLOAD_DESC)):
    """
    Türkçe OCR. **PDF veya resim** kabul edilir.
    Resim: JPEG, PNG, BMP, WEBP, TIFF, TIF, GIF, PBM, PGM, PPM. Yedek motor.
    """
    return await _process_upload(file, "pdfimagets")


@router.post(
    "/v1/pdftxtimage",
    response_model=ExtractResponse,
    tags=["Belge çıkarımı"],
    summary="Hibrit: metin + gömülü resim OCR",
)
async def v1_pdftxtimage(file: UploadFile = File(..., description=FILE_UPLOAD_DESC)):
    """
    PDF'te hem metin katmanını hem gömülü resimleri işler. Findeks vb. hibrit belgeler için uygundur.
    **Sadece PDF** kabul edilir.
    """
    return await _process_upload(file, "pdftxtimage")
