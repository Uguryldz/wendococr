"""Uygulama ayarları."""
import os
from pathlib import Path

# Geçici dosyalar (mkdir ilk upload'ta da denenebilir; startup bloklamaz)
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "/tmp/wendococr"))
try:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    pass

# Limitler (DEV_NOTES ile uyumlu)
MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "50"))
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
MAX_PAGES = int(os.getenv("MAX_PAGES", "500"))

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
DEBUG = os.getenv("DEBUG", "false").lower() in ("true", "1", "yes")

# CORS: virgülle ayrılmış origin listesi; "*" = tümü
_cors_raw = os.getenv("CORS_ORIGINS", "*")
CORS_ORIGINS = [o.strip() for o in _cors_raw.split(",") if o.strip()] if _cors_raw != "*" else ["*"]

# İzin verilen MIME / uzantılar
ALLOWED_IMAGE_TYPES = {
    "image/jpeg", "image/jpg", "image/png", "image/bmp", "image/webp",
    "image/tiff", "image/gif",
    "image/x-portable-pixmap", "image/x-portable-graymap", "image/x-portable-bitmap",
}
ALLOWED_PDF_TYPE = "application/pdf"
ALLOWED_EXTENSIONS = {
    ".pdf", ".jpg", ".jpeg", ".png", ".bmp", ".webp",
    ".tiff", ".tif", ".gif", ".pbm", ".pgm", ".ppm",
}

# Uzantı -> MIME eşlemesi (content_type yoksa fallback)
EXT_TO_MIME = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".png": "image/png", ".bmp": "image/bmp", ".webp": "image/webp",
    ".tiff": "image/tiff", ".tif": "image/tiff", ".gif": "image/gif",
    ".pbm": "image/x-portable-bitmap", ".pgm": "image/x-portable-graymap",
    ".ppm": "image/x-portable-pixmap",
}

# Desteklenen mode değerleri
EXTRACT_MODES = {"auto", "pdftext", "pdftexttable", "pdfimagev5", "pdfimagets", "pdftxtimage", "pdfimagetable"}
