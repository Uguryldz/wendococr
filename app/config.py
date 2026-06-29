"""Uygulama ayarları (sabit değerler, .env kullanılmaz)."""
import os
from pathlib import Path

# Worker / Kuyruk
OCR_MAX_WORKERS = int(os.environ.get("OCR_MAX_WORKERS", "3"))
OCR_QUEUE_MAX_SIZE = int(os.environ.get("OCR_QUEUE_MAX_SIZE", "20"))
OCR_QUEUE_TIMEOUT = int(os.environ.get("OCR_QUEUE_TIMEOUT", "120"))  # saniye

# Redis (dağıtık mod)
REDIS_URL = os.environ.get("REDIS_URL", "")  # boş = local mod (Redis yok)
REDIS_QUEUE_NAME = os.environ.get("REDIS_QUEUE_NAME", "wendococr:jobs")
REDIS_RESULT_TTL = int(os.environ.get("REDIS_RESULT_TTL", "300"))  # sonuç saklama süresi (sn)

# Geçici dosyalar
UPLOAD_DIR = Path("/tmp/wendococr")
try:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    pass

# Yetim dosya temizligi (KVKK + RAM/tmpfs birikme onleme).
# Normalde her istek dosyayi finally'de siler; ama OOM-kill/cokme gibi kenar
# durumlarda dosya kalabilir. Periyodik temizleyici bunlari siler.
UPLOAD_CLEANUP_INTERVAL_SEC = int(os.environ.get("UPLOAD_CLEANUP_INTERVAL_SEC", "300"))  # 5 dk
UPLOAD_FILE_MAX_AGE_SEC = int(os.environ.get("UPLOAD_FILE_MAX_AGE_SEC", "600"))          # 10 dk'dan eski = yetim

# Limitler
MAX_FILE_SIZE_MB = 50
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
MAX_PAGES = 500

# OCR ayarları
# PDF -> görüntü DPI: yükseldikçe kalite artar, hız düşer.
# Türkçe diacritik koruma için minimum 200 DPI önerilir (ö/ü/ç/ş/ğ/İ noktaları).
OCR_DPI_RAPID = 200
OCR_DPI_TESSERACT = 250
AUTO_FORCE_RAPID_OCR = True
# Auto modu fatura gibi "akıllı" davransın mı: True ise dijital PDF'lerde
# OCR'a zorlamadan metin katmanını okur (AUTO_FORCE_RAPID_OCR bypass edilir).
# Fatura'dan bağımsız ayar — auto'nun davranışı buradan değiştirilir.
AUTO_SMART = True

# RapidOCR ayarları (daha katı çıkarım için)
RAPIDOCR_DET_LIMIT_SIDE_LEN = 1280  # 960->1280: kucuk punto (seri no, MRZ, ince satir) daha net
RAPIDOCR_TEXT_SCORE = 0.40
RAPIDOCR_MIN_TOKEN_LEN = 1
RAPIDOCR_MIN_CONFIDENCE = 0.35
RAPIDOCR_MIN_BOX_AREA = 8.0

# RapidOCR detection ince ayar (doruluk; CPU-uyumlu, model degismez)
# unclip_ratio: tespit kutusunu disa genisletir -> kesik harf/kenar kurtarir (1.6 default)
RAPIDOCR_DET_UNCLIP_RATIO = 1.8
# box_thresh: kutu guven esigi -> dusurmek soluk/ince metni yakalar (0.5 default)
RAPIDOCR_DET_BOX_THRESH = 0.4

# RapidOCR ön işleme seçenekleri
RAPIDOCR_THRESHOLD = False
RAPIDOCR_ENHANCE = True

# Resim OCR'da tablo yapisi tespiti (OpenCV cizgi tabanli).
# Default kapali — aciksa resimde yatay/dikey cizgiler bulunup tables alani doldurulur.
RAPIDOCR_DETECT_TABLES = False

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

# ICR (El Yazısı Tanıma) ayarları
ICR_DPI = 300  # El yazısı için yüksek DPI gerekli
ICR_PSM_CANDIDATES = ["4", "6", "13", "3"]  # PSM 4: tek sütun, 6: blok, 13: raw line, 3: auto
ICR_USER_DEFINED_DPI = "300"

# Desteklenen mode değerleri
EXTRACT_MODES = {
    "auto", "fatura", "pdftext", "pdftexttable", "pdfimagev5", "pdfimagets",
    "pdftxtimage", "pdfimagetable", "pdfimagepaddleocrlow",
    "icr", "icrpaddle",
}

# PaddleOCR (low bellek) ayarları
# Not: PaddleOCR bağımlılıkları Docker imajına eklenecek (requirements.txt).
# Bu motor, büyük görsellerde RAM patlamasını önlemek için ağır doc pipeline kapalı ve input boyutu sınırlandırılır.
AUTO_FORCE_PADDLEOCR_LOW = False

OCR_DPI_PADDLEOCR_LOW = 200
PADDLEOCR_LOW_MAX_SIDE = 1200
PADDLEOCR_LOW_TEXT_DET_LIMIT = 1200
PADDLEOCR_LOW_TEXT_DET_LIMIT_TYPE = "min"
PADDLEOCR_LOW_TEXT_DET_THRESH = 0.3
PADDLEOCR_LOW_TEXT_DET_BOX_THRESH = 0.6
PADDLEOCR_LOW_TEXT_DET_UNCLIP_RATIO = 1.5
PADDLEOCR_LOW_TEXT_REC_SCORE_THRESH = 0.1
