"""Uygulama ayarları (sabit değerler, .env kullanılmaz)."""
from pathlib import Path

# Geçici dosyalar
UPLOAD_DIR = Path("/tmp/wendococr")
try:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    pass

# Limitler
MAX_FILE_SIZE_MB = 50
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
MAX_PAGES = 500

# OCR ayarları
# PDF -> görüntü DPI: yükseldikçe kalite artar, hız düşer.
OCR_DPI_RAPID = 150
OCR_DPI_TESSERACT = 200

# RapidOCR ayarları (daha katı çıkarım için)
RAPIDOCR_DET_LIMIT_SIDE_LEN = 960
RAPIDOCR_TEXT_SCORE = 0.40
RAPIDOCR_MIN_TOKEN_LEN = 1
RAPIDOCR_MIN_CONFIDENCE = 0.35
RAPIDOCR_MIN_BOX_AREA = 8.0

# RapidOCR ön işleme seçenekleri
RAPIDOCR_THRESHOLD = False
RAPIDOCR_ENHANCE = True

# Tesseract (Türkçe) ayarları
TESSERACT_PSM = "3"  # 3: auto, 6: block text
TESSERACT_DESKEW = False
TESSERACT_THRESHOLD = False
TESSERACT_ENHANCE = True
TESSERACT_USER_DEFINED_DPI = "300"

# Logging
LOG_LEVEL = "INFO"
DEBUG = False

# CORS
CORS_ORIGINS = ["*"]

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
