"""FastAPI uygulama giriş noktası."""
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.api import router as api_router

# jsontotext sayfası için statik dosya yolu
STATIC_DIR = Path(__file__).resolve().parent / "static"

# Swagger'da desteklenen formatlar açıklaması (tag açıklamasında kullanılır)
SUPPORTED_FORMATS_DESC = (
    "Desteklenen belge formatları: PDF; resim: JPEG, JPG, PNG, BMP, WEBP, TIFF, TIF, GIF, PBM, PGM, PPM "
    "(OpenCV ile okunabilen tüm resim türleri). Endpoint'e göre sadece PDF veya sadece resim kabul edenler vardır."
)

OPENAPI_TAGS = [
    {
        "name": "Belge çıkarımı",
        "description": "PDF veya resim yükleyip metin/tablo çıkarımı. Her endpoint farklı motor kullanır. " + SUPPORTED_FORMATS_DESC,
    },
    {"name": "Sistem", "description": "Sağlık kontrolü ve servis bilgisi."},
]
app = FastAPI(
    title="wendococr",
    description=(
        "Hybrid OCR & Document Parser (CPU Optimized).\n\n"
        "**Desteklenen formatlar:** PDF; resim: JPEG, PNG, BMP, WEBP, TIFF, TIF, GIF, PBM, PGM, PPM "
        "(okuyabildiğimiz tüm resim türleri). Endpoint bazında sadece PDF veya sadece resim kabul edenler olabilir."
    ),
    version="0.1.0",
    openapi_tags=OPENAPI_TAGS,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router)


@app.get("/")
def root():
    return {"service": "wendococr", "docs": "/docs", "health": "/health", "jsontotext": "/jsontotext"}


@app.get("/jsontotext", include_in_schema=False)
def jsontotext_page():
    """Koordinatlı JSON çıktısını grid mapping ile metne çeviren sayfa (solda JSON, sağda hizalı TXT)."""
    path = STATIC_DIR / "jsontotext.html"
    if not path.exists():
        return {"detail": "jsontotext.html not found"}
    return FileResponse(path, media_type="text/html")
