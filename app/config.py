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

# İzin verilen MIME / uzantılar
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/jpg"}
ALLOWED_PDF_TYPE = "application/pdf"
ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}

# Desteklenen mode değerleri
EXTRACT_MODES = {"auto", "pdftext", "pdftexttable", "pdfimagev5", "pdfimagets", "pdftxtimage"}
