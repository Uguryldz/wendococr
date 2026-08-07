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
# unclip_ratio: tespit kutusunu disa genisletir. 1.8 idi ama SIK SATIRLI belgelerde
# ust/alt satir kutulari birlesip RapidOCR iki satiri ust uste binmis gorup COP uretiyordu
# (resmi yazi maddeleri "a i k in sn a" gibi yutuluyordu). Olcum: 1.5 her belgede esit ya da
# DAHA IYI (ec403d31'de +260 karakter kurtardi, digerlerinde fark ±2-4 gurultu). RapidOCR
# default'u da 1.5 — geri donuldu.
RAPIDOCR_DET_UNCLIP_RATIO = 1.5
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
    "auto", "pdftext", "pdftexttable", "pdfimagev5",
    "pdfimagetable", "imagetexthybrid", "icr",
}

# ── AUTO-ROTATE: yatay/ters gelmiş taranmış belgeleri OCR öncesi dik konuma getir ──
# Tesseract OSD ile sayfa yönü (0/90/180/270) tespit edilir. Güven eşiğin altındaysa
# DOKUNULMAZ (yanlış döndürüp bozmamak için). deskew'den farklı: o küçük eğikliği,
# bu 90°/180° tam sayfa dönüşünü düzeltir. Tüm raster OCR motorlarında geçerli.
AUTO_ROTATE = os.environ.get("AUTO_ROTATE", "1") == "1"
AUTO_ROTATE_MIN_CONF = float(os.environ.get("AUTO_ROTATE_MIN_CONF", "2.0"))  # OSD güven alt sınırı
# OSD için küçültme sınırı. ÇOK küçültmek (1600) büyük fişlerde metni bozup OSD güvenini
# çökertiyordu (4032px fiş: 1600'e küçültünce conf 0.12 ve yanlış yön; 2600'de conf ~7 doğru).
# Süre farkı küçük (0.7s -> 1.1s), doğruluk kazancı büyük.
AUTO_ROTATE_MAX_SIDE = int(os.environ.get("AUTO_ROTATE_MAX_SIDE", "2600"))
# Sadece tam-sayfa ölçekli görüntüde çalış: hybrid'in ince antet/bölge OCR'ında (küçük
# görüntü) yön tespiti hem gereksiz hem riskli — kısa kenar bunun altındaysa dokunma.
AUTO_ROTATE_MIN_SIDE = int(os.environ.get("AUTO_ROTATE_MIN_SIDE", "1000"))
# DÜŞÜK GÜVEN DOĞRULAMA (fiş/fatura fotoğrafları): OSD yönü düşük güvende bile genelde
# doğru, ama körlemesine uygulamak dik belgeyi bozabilir. OSD sıfırdan farklı açı önerir
# ama güveni MIN_CONF altındaysa: sayfa hem 0° hem önerilen açıda OCR'lanır, RapidOCR güven
# skoru toplamı bu MARJIN kadar yüksek olan açı seçilir. Sadece RapidOCR (auto/fatura/
# pdfimagev5) yolunda; fişlerin geçtiği yol orası. Emin/r0 durumunda tek geçiş (hız aynı).
AUTO_ROTATE_VERIFY = os.environ.get("AUTO_ROTATE_VERIFY", "1") == "1"
# Doğrulama OCR ile korunduğu için burada boyut eşiği DÜŞÜK (küçük fiş fotoğrafları geçsin).
AUTO_ROTATE_VERIFY_MIN_SIDE = int(os.environ.get("AUTO_ROTATE_VERIFY_MIN_SIDE", "400"))
# OSD yönüne GÜVEN; sadece 0° skoru önerilen açıyı bu marj kadar AŞARSA 0°'de kal (override).
# OSD yönü fişlerde bile doğru çıkıyor; ters mantık (dönmüş kazanmalı) ince farklarda kaçırıyordu.
AUTO_ROTATE_VERIFY_MARGIN = float(os.environ.get("AUTO_ROTATE_VERIFY_MARGIN", "0.04"))  # %4
# OSD ÇÖKERSE 4-yön OCR oylaması: OSD düşük çözünürlüklü fişte hata verip yönü hiç
# bulamayabiliyor (ör. 1080x506 fiş). Bu durumda 0/90/180/270 dördü de OCR'lanır, en çok
# gerçek kelime üreten seçilir (0°'ye küçük öncelik). 4 OCR maliyeti SADECE OSD çökünce.
AUTO_ROTATE_VOTE = os.environ.get("AUTO_ROTATE_VOTE", "1") == "1"
# 4-yön oylamada döndürülmüş yön, 0°'yi bu ORANDA aşmalı (yoksa 0°'de kal). BÜYÜK olması
# şart: gerçekten dönük fişte doğru yön 2-4 kat çok kelime verir; DİK belge (tablo/liste)
# yan okununca kelime sadece ~%5-10 şişer. %40 eşiği ikisini ayırır -> dik foto bozulmaz.
AUTO_ROTATE_VOTE_MARGIN = float(os.environ.get("AUTO_ROTATE_VOTE_MARGIN", "0.40"))

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
# BOZUK METIN KATMANI YENIDEN TARAMA: Bazi taranmis belgelere baska bir arac kotu OCR yapip
# metin katmanini gommus olur (orn. tarih "21/07/2026" yerine "2l l0'7 /2026"). Sayfa TAM SAYFA
# GORSEL ise VE metin katmani bozuk-OCR imzasi tasiyorsa o katman yok sayilir, sayfa yeniden
# OCR'lanir. IKI KOSUL DA sart: sirf supheli oran yetmez — fatura/adres kodlari ("EM12024000004020",
# "CK1S8 K.4 D.17") dogal olarak yuksek oran uretir ama o sayfalar tam-sayfa gorsel degildir.
HYBRID_RESCAN_BAD_TEXT = os.environ.get("HYBRID_RESCAN_BAD_TEXT", "1") == "1"
HYBRID_RESCAN_IMAGE_RATIO = float(os.environ.get("HYBRID_RESCAN_IMAGE_RATIO", "0.9"))  # tam sayfa görsel
HYBRID_RESCAN_SUSPECT_RATIO = float(os.environ.get("HYBRID_RESCAN_SUSPECT_RATIO", "0.10"))
HYBRID_RESCAN_MIN_TOKENS = int(os.environ.get("HYBRID_RESCAN_MIN_TOKENS", "40"))  # altı = oran anlamsız
# Bu uzunluğun altındaki OCR satırı yalnız birebir eşleşirse elenir (kısa antet koruması)
HYBRID_DEDUP_MIN_LEN = int(os.environ.get("HYBRID_DEDUP_MIN_LEN", "12"))
