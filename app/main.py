"""FastAPI uygulama giriş noktası."""
import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from fastapi.openapi.docs import get_swagger_ui_html

from app.api import router as api_router
from app.config import CORS_ORIGINS, DEBUG, LOG_LEVEL, OCR_MAX_WORKERS

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
        "description": "Taranmış PDF veya resim dosyaları. RapidOCR (ONNX, CPU optimize, hızlı) + otomatik yön düzeltme (auto-rotate). Türkçe diacritik post-processing aktif.",
    },
    {
        "name": "Hibrit OCR",
        "description": "Hem metin katmanı hem gömülü resim içeren belgeler. imagetexthybrid: dijital metin + görsel-içi metin, layout korumalı (önerilen). pdfimagetable: taranmış tablodan hücre yapısı çıkarımı.",
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
        "| **Otomatik** | Akıllı motor seçimi (auto-rotate dahil) | 1 |\n"
        "| **Dijital PDF** | Native metin / tablo çıkarımı | 2 |\n"
        "| **Taranmış Belge OCR** | RapidOCR (hızlı) | 1 |\n"
        "| **Hibrit OCR** | Dijital metin + görsel-içi metin, tablo hücre | 2 |\n"
        "| **El Yazısı (ICR)** | Tesseract ICR | 1 |\n"
        "| **Findeks Export** | Yapısal veri çıkarımı (JSON/XLSX) | 1 |\n\n"
        "### Desteklenen Formatlar\n"
        "**PDF** | **Resim:** JPEG, PNG, BMP, WEBP, TIFF, GIF, PBM, PGM, PPM\n\n"
        "### Ortak Parametreler\n"
        "- `page_range`: Sayfa aralığı (ör: `1-5`, `1,3,7`, `1-3,7,9-10`)\n"
        "- `format`: Çıktı formatı — `json` (varsayılan) veya `text`\n"
    ),
    version="0.2.0",
    openapi_tags=OPENAPI_TAGS,
    docs_url=None,  # ozel Swagger (sag-alt sabit imza icin) — asagida tanimli
)
# CORS (K3): "*" origin ile credentials BIRLIKTE kullanilamaz (CORS spec + tarayici
# reddeder). Origin whitelist verilmisse credentials acilir; "*" ise kapatilir.
_cors_wildcard = "*" in CORS_ORIGINS
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=not _cors_wildcard,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router)


# Ozel Swagger UI: standart docs + sag-alt kosede sabit (fixed) imza.
_SIGNATURE_HTML = """
<style>
#wendococr-sign{position:fixed;right:14px;bottom:10px;z-index:9999;
font:italic 12px/1.4 -apple-system,Segoe UI,Roboto,sans-serif;
color:#8a8a8a;opacity:.75;transition:opacity .2s;}
#wendococr-sign:hover{opacity:1;}
#wendococr-sign a{color:#5b6b7b;text-decoration:none;}
#wendococr-sign a:hover{text-decoration:underline;}
</style>
<div id="wendococr-sign">&copy; <a href="https://www.linkedin.com/in/uguryldz/" target="_blank" rel="noopener">uğur yıldız</a></div>
"""


@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui():
    html = get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=app.title + " — API",
    )
    body = html.body.decode("utf-8").replace("</body>", _SIGNATURE_HTML + "</body>")
    return HTMLResponse(body)

_cleanup_task = None


@app.on_event("startup")
async def start_cleanup():
    # Yetim geçici dosya temizleyiciyi başlat (KVKK + tmpfs birikme önleme).
    import asyncio
    from app.utils.cleanup import cleanup_loop
    global _cleanup_task
    _cleanup_task = asyncio.create_task(cleanup_loop())


@app.on_event("shutdown")
async def shutdown_pool():
    from app.core.worker_pool import get_pool
    get_pool().shutdown()
    if _cleanup_task is not None:
        _cleanup_task.cancel()


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unexpected error: %s", exc)
    detail = str(exc) if DEBUG else "Sunucu hatası. Lütfen tekrar deneyin."
    return JSONResponse(status_code=500, content={"detail": detail})


@app.get("/", tags=["Sistem"], summary="Servis bilgisi ve endpoint haritası")
def root():
    """Tüm endpoint'lerin kategorize listesi + canlı worker durumu."""
    from app.core.worker_pool import get_pool
    pool = get_pool()
    return {
        "service": "wendococr",
        "version": "0.3.0",
        "docs": "/docs",
        "health": "/health",
        "workers": pool.status(),
        "endpoints": {
            "otomatik": {
                "/v1/auto": "Akıllı motor seçimi (auto-rotate dahil)",
            },
            "dijital_pdf": {
                "/v1/pdftext": "PDF metin çıkarımı",
                "/v1/pdftexttable": "PDF metin + tablo çıkarımı",
            },
            "taranmis_belge_ocr": {
                "/v1/pdfimagev5": "RapidOCR (hızlı)",
            },
            "hibrit_ocr": {
                "/v1/imagetexthybrid": "Dijital metin + görsel-içi metin (layout korumalı)",
                "/v1/pdfimagetable": "Tablo hücre yapısı + gömülü resim OCR",
            },
            "el_yazisi_icr": {
                "/v1/icr": "Tesseract ICR",
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
