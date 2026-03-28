"""FastAPI uygulama giriş noktası."""
import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from app.api import router as api_router
from app.config import CORS_ORIGINS, DEBUG, LOG_LEVEL

# Logging
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("wendococr")

STATIC_DIR = Path(__file__).resolve().parent / "static"

# ─── Swagger Kategori Sıralaması ───
OPENAPI_TAGS = [
    {
        "name": "Otomatik",
        "description": "Belgeyi analiz edip sayfa bazlı en uygun motoru otomatik seçer. Ne kullanacağınızdan emin değilseniz buradan başlayın.",
    },
    {
        "name": "Dijital PDF",
        "description": "Metin katmanı olan (searchable) PDF belgeler. OCR kullanmaz, doğrudan metin/tablo çeker. En hızlı yöntem.",
    },
    {
        "name": "Taranmış Belge OCR",
        "description": "Taranmış PDF veya resim dosyaları. 3 farklı OCR motoru: RapidOCR (hızlı), Tesseract (Türkçe optimize), PaddleOCR (düşük bellek). Tüm motorlarda Türkçe diacritik post-processing aktif.",
    },
    {
        "name": "Hibrit OCR",
        "description": "Hem metin katmanı hem gömülü resim içeren belgeler (Findeks raporu, kredi raporu vb.). Native metin + gömülü resim OCR birleştirilir. Kilitli endpoint'ler.",
    },
    {
        "name": "El Yazısı Tanıma (ICR)",
        "description": "El yazısı belgeler: dilekçe, başvuru formu, el notu, imza üstü yazılar. El yazısına özel preprocessing (bilateral filter, morfolojik dilation, agresif deskew) + Türkçe post-processing.",
    },
    {
        "name": "Findeks Export",
        "description": "Findeks Kredi Notu ve Risk Raporu PDF'inden 14 bölümü yapısal olarak çıkarır. JSON ve XLSX formatında export. Kilitli endpoint.",
    },
    {
        "name": "Sistem",
        "description": "Sağlık kontrolü, motor durumları ve servis bilgisi.",
    },
]

app = FastAPI(
    title="wendococr",
    description=(
        "## Hybrid OCR, ICR & Document Parser\n"
        "CPU Optimized | Türkçe Diacritik Desteği\n\n"
        "### Yetenekler\n"
        "| Kategori | Açıklama | Endpoint Sayısı |\n"
        "|----------|----------|-----------------|\n"
        "| **Otomatik** | Akıllı motor seçimi | 1 |\n"
        "| **Dijital PDF** | Native metin/tablo çıkarımı | 2 |\n"
        "| **Taranmış Belge OCR** | RapidOCR, Tesseract, PaddleOCR | 3 |\n"
        "| **Hibrit OCR** | Metin + gömülü resim | 2 |\n"
        "| **El Yazısı (ICR)** | Tesseract ICR, PaddleOCR ICR | 2 |\n"
        "| **Findeks Export** | Yapısal veri çıkarımı (JSON/XLSX) | 1 |\n\n"
        "### Desteklenen Formatlar\n"
        "**PDF** | **Resim:** JPEG, PNG, BMP, WEBP, TIFF, GIF, PBM, PGM, PPM\n\n"
        "### Ortak Parametreler\n"
        "- `page_range`: Sayfa aralığı (ör: `1-5`, `1,3,7`, `1-3,7,9-10`)\n"
        "- `format`: Çıktı formatı — `json` (varsayılan) veya `text`\n"
    ),
    version="0.2.0",
    openapi_tags=OPENAPI_TAGS,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unexpected error: %s", exc)
    detail = str(exc) if DEBUG else "Sunucu hatası. Lütfen tekrar deneyin."
    return JSONResponse(status_code=500, content={"detail": detail})


@app.get("/", tags=["Sistem"], summary="Servis bilgisi ve endpoint haritası")
def root():
    """Tüm endpoint'lerin kategorize listesi."""
    return {
        "service": "wendococr",
        "version": "0.2.0",
        "docs": "/docs",
        "health": "/health",
        "endpoints": {
            "otomatik": {
                "/v1/auto": "Akıllı motor seçimi",
            },
            "dijital_pdf": {
                "/v1/pdftext": "PDF metin çıkarımı",
                "/v1/pdftexttable": "PDF metin + tablo çıkarımı",
            },
            "taranmis_belge_ocr": {
                "/v1/pdfimagev5": "RapidOCR (hızlı)",
                "/v1/pdfimagets": "Tesseract Türkçe",
                "/v1/pdfimagepaddleocrlow": "PaddleOCR (düşük bellek)",
            },
            "hibrit_ocr": {
                "/v1/pdftxtimage": "Metin + gömülü resim OCR",
                "/v1/pdfimagetable": "Tablo + gömülü resim OCR",
            },
            "el_yazisi_icr": {
                "/v1/icr": "Tesseract ICR",
                "/v1/icrpaddle": "PaddleOCR ICR",
            },
            "findeks_export": {
                "/v1/findeksexport": "Findeks rapor çıkarımı (JSON/XLSX)",
            },
        },
        "ui": {
            "/jsontotext": "JSON → metin grid mapping",
            "/rawjsontotext": "Ham JSON + konumsal metin",
        },
    }


@app.get("/jsontotext", include_in_schema=False)
def jsontotext_page():
    path = STATIC_DIR / "jsontotext.html"
    if not path.exists():
        return {"detail": "jsontotext.html not found"}
    return FileResponse(path, media_type="text/html")


@app.get("/rawjsontotext", include_in_schema=False)
def rawjsontotext_page():
    path = STATIC_DIR / "rawjsontotext.html"
    if not path.exists():
        return {"detail": "rawjsontotext.html not found"}
    return FileResponse(path, media_type="text/html")
