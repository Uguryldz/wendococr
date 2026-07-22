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

# Geçici dosyalar. Bandit B108: bilincli — bu dizin compose'da tmpfs (RAM) +
# mode=0700/uid=10001 ile mount edilir, dosyalar finally + cleanup ile silinir.
UPLOAD_DIR = Path("/tmp/wendococr")  # nosec B108
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

# CORS (K3): origin whitelist .env'den (virgulle ayrik). Varsayilan "*" ama
# "*" ile credentials BIRLIKTE kullanilamaz (spec-disi) — main.py bunu otomatik
# ele alir. Production'da CORS_ORIGINS'i gercek domain(ler)e kisitlayin.
CORS_ORIGINS = [o.strip() for o in os.environ.get("CORS_ORIGINS", "*").split(",") if o.strip()]

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
    "imagetexthybrid",
    "icr", "icrpaddle",
}

# ONNX Runtime thread sayısı. 0 = konteyner CPU kotasından otomatik (önerilen).
# Host çekirdek sayısı kadar thread açmak cgroup limitli konteynerde ciddi yavaşlatır.
RAPIDOCR_NUM_THREADS = int(os.environ.get("RAPIDOCR_NUM_THREADS", "0"))

# ── imagetexthybrid: dijital metin + görsel-içi metin birleşik çıkarım ──
# Resmi yazışmalarda antet/logo/kaşe yalnızca görsel olarak gömülü olur; metnin
# kaplamadığı bantlar tespit edilip SADECE oralar OCR'lanır.
# Render DPI: pdfimagev5 (auto) ile AYNI — o hat Türkçe diacritik için doğrulanmış.
HYBRID_DPI = int(os.environ.get("HYBRID_DPI", str(OCR_DPI_RAPID)))
HYBRID_GAP_MIN_HEIGHT = float(os.environ.get("HYBRID_GAP_MIN_HEIGHT", "10"))   # pt; altı gürültü
HYBRID_MIN_REGION_WIDTH = float(os.environ.get("HYBRID_MIN_REGION_WIDTH", "20"))  # pt; ikon eler
HYBRID_MIN_REGION_AREA = float(os.environ.get("HYBRID_MIN_REGION_AREA", "2000"))  # pt²; dilim eler
HYBRID_TEXT_PAD = float(os.environ.get("HYBRID_TEXT_PAD", "2"))  # metin bbox şişirme (kırpık harf)
HYBRID_MIN_INK_RATIO = float(os.environ.get("HYBRID_MIN_INK_RATIO", "0.002"))  # boş bant elemesi
HYBRID_MIN_NATIVE_CHARS = int(os.environ.get("HYBRID_MIN_NATIVE_CHARS", "20"))  # altı = saf tarama
HYBRID_DEDUP = os.environ.get("HYBRID_DEDUP", "1") == "1"      # dijital metinde geçeni tekrar yazma
# Bu uzunluğun altındaki OCR satırı yalnız birebir eşleşirse elenir (kısa antet koruması)
HYBRID_DEDUP_MIN_LEN = int(os.environ.get("HYBRID_DEDUP_MIN_LEN", "12"))

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
