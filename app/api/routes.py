"""FastAPI endpoint'leri: OCR, ICR, Findeks Export, Sistem."""
import asyncio
import time
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import PlainTextResponse, Response

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

# ─── Swagger Dosya Açıklamaları ───
_PDF_OR_IMAGE = "PDF veya resim (JPEG, PNG, BMP, WEBP, TIFF, GIF, PBM, PGM, PPM)."
_PDF_ONLY = "Sadece PDF dosyası."
_HANDWRITING = "El yazısı belge: " + _PDF_OR_IMAGE

router = APIRouter()


# ═══════════════════════════════════════════════════════════
# ORTAK
# ═══════════════════════════════════════════════════════════

def _validate_file(file: UploadFile, mode: str) -> None:
    suffix = Path(file.filename or "file").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"Desteklenmeyen dosya uzantısı: {suffix}. İzin verilen: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )
    ct = (file.content_type or "").strip().lower()
    expected_mime = EXT_TO_MIME.get(suffix)
    if ct and expected_mime:
        if ct != expected_mime and ct not in (ALLOWED_IMAGE_TYPES | {ALLOWED_PDF_TYPE}):
            raise HTTPException(415, detail=f"Dosya tipi uyumsuz: uzantı {suffix}, Content-Type {ct}")
    if mode in ("pdftext", "pdftexttable", "pdftxtimage", "pdfimagetable") and suffix != ".pdf":
        raise HTTPException(415, detail="Bu endpoint sadece PDF kabul eder.")


async def _process_upload(
    file: UploadFile,
    mode: str,
    *,
    page_range: str | None = None,
    format: str = "json",
) -> ExtractResponse | PlainTextResponse:
    content = await file.read()
    if len(content) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(413, detail=f"Dosya çok büyük. Maksimum: {MAX_FILE_SIZE_BYTES // (1024*1024)} MB")
    if len(content) == 0:
        raise HTTPException(400, detail="Boş dosya.")

    suffix = Path(file.filename or "file").suffix.lower() or ".bin"
    _validate_file(file, mode)

    safe_name = "".join(c for c in (file.filename or "upload")[:80] if c.isalnum() or c in "._- ") or "upload"
    tmp_path = UPLOAD_DIR / f"{safe_name}_{time.time_ns()}{suffix}"
    try:
        tmp_path.write_bytes(content)
    except Exception as e:
        raise HTTPException(500, detail=f"Dosya yazılamadı: {e}")

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
        raise HTTPException(500, detail=f"İşleme hatası: {str(e)}")
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
    processing_time_sec = round(time.perf_counter() - start_time, 3)

    if len(pages_raw) > MAX_PAGES:
        raise HTTPException(422, detail=f"Sayfa sayısı limiti aşıldı (max {MAX_PAGES}).")

    pages = [
        page_result_from_engine(
            p["page_number"], p.get("content", ""), p.get("tables"),
            text_blocks=p.get("text_blocks"),
            page_width=p.get("page_width"), page_height=p.get("page_height"),
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


# ═══════════════════════════════════════════════════════════
# SİSTEM
# ═══════════════════════════════════════════════════════════

def _check_tesseract() -> bool:
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
        return "tur" in set(pytesseract.get_languages(config=""))
    except Exception:
        return False

def _check_rapidocr() -> bool:
    try:
        from rapidocr_onnxruntime import RapidOCR  # noqa: F401
        return True
    except Exception:
        return False

def _check_paddleocr() -> bool:
    try:
        from paddleocr import PaddleOCR  # noqa: F401
        return True
    except Exception:
        return False

def _check_upload_dir() -> bool:
    try:
        test_file = UPLOAD_DIR / ".health_check"
        test_file.write_text("ok")
        test_file.unlink(missing_ok=True)
        return True
    except Exception:
        return False


@router.get("/health", tags=["Sistem"], summary="Sağlık kontrolü")
def health():
    """Servisin ayakta olduğunu ve tüm motor bağımlılıklarını doğrular."""
    return {
        "status": "ok",
        "motorlar": {
            "tesseract_tur": _check_tesseract(),
            "rapidocr": _check_rapidocr(),
            "paddleocr": _check_paddleocr(),
        },
        "sistem": {
            "upload_dir": _check_upload_dir(),
        },
    }


# ═══════════════════════════════════════════════════════════
# 1. OTOMATİK
# ═══════════════════════════════════════════════════════════

@router.post("/v1/auto", tags=["Otomatik"], summary="Akıllı motor seçimi")
async def v1_auto(
    file: UploadFile = File(..., description=_PDF_OR_IMAGE),
    page_range: str | None = Query(None, description="Sayfa aralığı: 1-5, 1,3,7"),
    format: str = Query("json", description="Çıktı: json veya text"),
):
    """
    Belgeyi analiz eder, **sayfa bazlı** en uygun motoru otomatik seçer.

    | Durum | Seçilen Motor |
    |-------|---------------|
    | Resim dosyası | RapidOCR |
    | PDF — metin katmanı var, tablo yok | PyMuPDF (pdftext) |
    | PDF — metin katmanı var, tablo var | pdfplumber (pdftexttable) |
    | PDF — metin katmanı yok | RapidOCR (pdfimagev5) |
    """
    return await _process_upload(file, "auto", page_range=page_range, format=format)


# ═══════════════════════════════════════════════════════════
# 2. DİJİTAL PDF
# ═══════════════════════════════════════════════════════════

@router.post("/v1/pdftext", tags=["Dijital PDF"], summary="Metin çıkarımı")
async def v1_pdftext(
    file: UploadFile = File(..., description=_PDF_ONLY),
    page_range: str | None = Query(None, description="Sayfa aralığı: 1-5, 1,3,7"),
    format: str = Query("json", description="Çıktı: json veya text"),
):
    """
    Dijital (searchable) PDF'ten metin çıkarımı. OCR kullanmaz.

    **Motor:** PyMuPDF — en hızlı yöntem.
    **Çıktı:** Koordinatlı metin blokları (satır bazlı bbox).
    """
    return await _process_upload(file, "pdftext", page_range=page_range, format=format)


@router.post("/v1/pdftexttable", tags=["Dijital PDF"], summary="Metin + tablo çıkarımı")
async def v1_pdftexttable(
    file: UploadFile = File(..., description=_PDF_ONLY),
    page_range: str | None = Query(None, description="Sayfa aralığı: 1-5, 1,3,7"),
    format: str = Query("json", description="Çıktı: json veya text"),
):
    """
    Dijital PDF'ten metin ve tablo çıkarımı. Tablo ağırlıklı belgeler için.

    **Motor:** pdfplumber.
    **Çıktı:** Koordinatlı metin blokları + yapısal tablolar (satır/sütun + hücre bbox).
    """
    return await _process_upload(file, "pdftexttable", page_range=page_range, format=format)


# ═══════════════════════════════════════════════════════════
# 3. TARANMIŞ BELGE OCR
# ═══════════════════════════════════════════════════════════

@router.post("/v1/pdfimagev5", tags=["Taranmış Belge OCR"], summary="RapidOCR (hızlı)")
async def v1_pdfimagev5(
    file: UploadFile = File(..., description=_PDF_OR_IMAGE),
    page_range: str | None = Query(None, description="Sayfa aralığı: 1-5, 1,3,7"),
    format: str = Query("json", description="Çıktı: json veya text"),
):
    """
    Taranmış PDF veya resim üzerinde OCR.

    **Motor:** RapidOCR (ONNX tabanlı, CPU optimized).
    **Hız:** En hızlı OCR motoru.
    **Türkçe:** Diacritik post-processing + CLAHE + unsharp mask.
    """
    return await _process_upload(file, "pdfimagev5", page_range=page_range, format=format)


@router.post("/v1/pdfimagets", tags=["Taranmış Belge OCR"], summary="Tesseract Türkçe")
async def v1_pdfimagets(
    file: UploadFile = File(..., description=_PDF_OR_IMAGE),
    page_range: str | None = Query(None, description="Sayfa aralığı: 1-5, 1,3,7"),
    format: str = Query("json", description="Çıktı: json veya text"),
):
    """
    Tesseract LSTM ile Türkçe OCR.

    **Motor:** Tesseract (lang=tur+eng, --oem 3).
    **Doğruluk:** Türkçe'de en yüksek doğruluk. Birden fazla PSM dener, en iyisini seçer.
    **Türkçe:** Diacritik post-processing + sharpen + CLAHE.
    """
    return await _process_upload(file, "pdfimagets", page_range=page_range, format=format)


@router.post("/v1/pdfimagepaddleocrlow", tags=["Taranmış Belge OCR"], summary="PaddleOCR (düşük bellek)")
async def v1_pdfimagepaddleocrlow(
    file: UploadFile = File(..., description=_PDF_OR_IMAGE),
    page_range: str | None = Query(None, description="Sayfa aralığı: 1-5, 1,3,7"),
    format: str = Query("json", description="Çıktı: json veya text"),
):
    """
    PaddleOCR PP-OCRv4 ile taranmış belge OCR (düşük bellek profili).

    **Motor:** PaddleOCR — doc preprocessor kapalı, input boyutu sınırlı.
    **Kullanım:** Docker/kısıtlı RAM ortamları.
    **Türkçe:** Diacritik post-processing + CLAHE + sharpen.
    """
    return await _process_upload(file, "pdfimagepaddleocrlow", page_range=page_range, format=format)


# ═══════════════════════════════════════════════════════════
# 4. HİBRİT OCR
# ═══════════════════════════════════════════════════════════

@router.post("/v1/pdftxtimage", tags=["Hibrit OCR"], summary="Metin + gömülü resim OCR")
async def v1_pdftxtimage(
    file: UploadFile = File(..., description=_PDF_ONLY),
    page_range: str | None = Query(None, description="Sayfa aralığı: 1-5, 1,3,7"),
    format: str = Query("json", description="Çıktı: json veya text"),
):
    """
    Hem metin katmanı hem gömülü resim içeren PDF'ler (Findeks raporu tarzı).

    **Yöntem:** PyMuPDF (native metin) + Tesseract Türkçe (gömülü resim OCR).
    **Kullanım:** Findeks, kredi raporu gibi hibrit belgeler.
    **Kilitli endpoint.**
    """
    return await _process_upload(file, "pdftxtimage", page_range=page_range, format=format)


@router.post("/v1/pdfimagetable", tags=["Hibrit OCR"], summary="Tablo yapısı korumalı OCR")
async def v1_pdfimagetable(
    file: UploadFile = File(..., description=_PDF_ONLY),
    page_range: str | None = Query(None, description="Sayfa aralığı: 1-5, 1,3,7"),
    format: str = Query("json", description="Çıktı: json veya text"),
):
    """
    Tablo + gömülü resim içeren PDF'ler. Tablo yapısı bozulmadan OCR.

    **Yöntem:** pdfplumber (tablo tespiti + hücre bbox) + PyMuPDF (resim çıkarma) + Tesseract Türkçe (OCR).
    **Kullanım:** Findeks, kredi raporu — tablo hücrelerine OCR sonucu yazılır.
    **Kilitli endpoint.**
    """
    return await _process_upload(file, "pdfimagetable", page_range=page_range, format=format)


# ═══════════════════════════════════════════════════════════
# 5. EL YAZISI TANIMA (ICR)
# ═══════════════════════════════════════════════════════════

@router.post("/v1/icr", tags=["El Yazısı Tanıma (ICR)"], summary="Tesseract ICR")
async def v1_icr(
    file: UploadFile = File(..., description=_HANDWRITING),
    page_range: str | None = Query(None, description="Sayfa aralığı: 1-5, 1,3,7"),
    format: str = Query("json", description="Çıktı: json veya text"),
):
    """
    El yazısı belgeler için ICR (Intelligent Character Recognition).

    **Kullanım:** Dilekçe, başvuru formu, el notu, imza üstü yazılar.

    **El yazısına özel preprocessing:**

    | Adım | Ne Yapar |
    |------|----------|
    | Bilateral filter | Gürültü azaltır, vuruş kenarlarını korur |
    | CLAHE | Soluk kalem/mürekkep kontrastını artırır |
    | Unsharp mask | Vuruş detaylarını keskinleştirir |
    | Morfolojik closing + erosion | Kopuk vuruşları bağlar, ince çizgileri kalınlaştırır |
    | Adaptive threshold | Değişken vuruş kalınlığına uyum sağlar |
    | Agresif deskew | El yazısı eğikliğini düzeltir |

    **Motor:** Tesseract LSTM (lang=tur+eng, 300 DPI). 4 farklı PSM dener, en iyisini seçer.
    """
    return await _process_upload(file, "icr", page_range=page_range, format=format)


@router.post("/v1/icrpaddle", tags=["El Yazısı Tanıma (ICR)"], summary="PaddleOCR ICR")
async def v1_icrpaddle(
    file: UploadFile = File(..., description=_HANDWRITING),
    page_range: str | None = Query(None, description="Sayfa aralığı: 1-5, 1,3,7"),
    format: str = Query("json", description="Çıktı: json veya text"),
):
    """
    El yazısı belgeler için ICR — PaddleOCR PP-OCRv4 motoru.

    **Yöntem:** PaddleOCR'ın detection + recognition pipeline'ı hem basılı hem el yazısını tanır.
    **Preprocessing:** Bilateral filter + CLAHE + unsharp mask (hafif — PaddleOCR kendi pipeline'ı var).
    **Kullanım:** Docker/düşük bellek ortamlarında el yazısı tanıma.
    """
    return await _process_upload(file, "icrpaddle", page_range=page_range, format=format)


# ═══════════════════════════════════════════════════════════
# 6. FİNDEKS EXPORT
# ═══════════════════════════════════════════════════════════

@router.post("/v1/findeksexport", tags=["Findeks Export"], summary="Findeks rapor çıkarımı (JSON / XLSX)")
async def v1_findeksexport(
    file: UploadFile = File(..., description="Findeks Risk Raporu PDF dosyası."),
    format: str = Query("json", description="Çıktı: json veya xlsx"),
):
    """
    Findeks Kredi Notu ve Risk Raporu PDF'inden yapısal veri çıkarımı.

    **Çıktı formatı:** `json` (varsayılan) veya `xlsx` (Excel dosyası indirilir).

    **Çıkarılan 14 bölüm:**

    | # | Bölüm |
    |---|-------|
    | 1 | Rapor Özeti (vergi no, firma, tarih) |
    | 2 | Ticari Krediler Özet |
    | 3 | Kredi Türü Bazında Hesap Bilgileri |
    | 4 | Vade Bazlı Limit ve Borç |
    | 5 | Bankalar Özet |
    | 6 | Banka Bazlı Limit/Risk (OCR ile banka adı tanıma) |
    | 7 | Finansman Şirketleri Özet |
    | 8 | Finansman Şirketi Bazlı Limit/Risk |
    | 9 | Limit/Risk Toplam |
    | 10 | Leasing |
    | 11 | Faktoring |
    | 12 | Takibe Alınmış Ticari Krediler |
    | 13 | Takibe Alınmış Leasing |
    | 14 | Takibe Alınmış Faktoring |

    **Kilitli endpoint.**
    """
    suffix = Path(file.filename or "file").suffix.lower()
    if suffix != ".pdf":
        raise HTTPException(415, detail="Bu endpoint sadece PDF kabul eder.")

    content = await file.read()
    if len(content) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(413, detail=f"Dosya çok büyük. Maksimum: {MAX_FILE_SIZE_BYTES // (1024*1024)} MB")
    if len(content) == 0:
        raise HTTPException(400, detail="Boş dosya.")

    safe_name = "".join(c for c in (file.filename or "upload")[:80] if c.isalnum() or c in "._- ") or "upload"
    tmp_path = UPLOAD_DIR / f"{safe_name}_{time.time_ns()}{suffix}"
    try:
        tmp_path.write_bytes(content)
    except Exception as e:
        raise HTTPException(500, detail=f"Dosya yazılamadı: {e}")

    start_time = time.perf_counter()
    try:
        from app.engines.findeks_extract import generate_xlsx, process_findeks
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(None, process_findeks, tmp_path)
    except Exception as e:
        raise HTTPException(500, detail=f"Findeks işleme hatası: {str(e)}")
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass

    processing_time_sec = round(time.perf_counter() - start_time, 3)

    if format == "xlsx":
        try:
            xlsx_bytes = await loop.run_in_executor(None, generate_xlsx, data)
        except Exception as e:
            raise HTTPException(500, detail=f"Excel oluşturma hatası: {str(e)}")
        filename = Path(file.filename or "findeks").stem + "_extract.xlsx"
        return Response(
            content=xlsx_bytes,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    return {
        "filename": file.filename or "unknown",
        "method_used": "findeksexport",
        "processing_time_sec": processing_time_sec,
        "data": data,
    }
