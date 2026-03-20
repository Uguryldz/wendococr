# wendococr – Hybrid OCR & Document Parser (CPU Optimized)

PDF, JPG ve PNG belgelerini işleyen **FastAPI** tabanlı akıllı karar mekanizması. GPU olmadan CPU üzerinde çalışır; Türkçe karakter desteği vardır.

## Özellikler

- **Auto mod:** Belge türüne göre otomatik engine seçimi (sayfa bazlı)
- **Motorlar:** `pdftext` (PyMuPDF), `pdftexttable` (pdfplumber), `pdfimagev5` (RapidOCR), `pdfimagets` (Tesseract Türkçe), `pdftxtimage` (hibrit), `pdfimagetable` (tablo korumalı hibrit)
- **API:** Her motorun ayrı ucu – `POST /v1/auto`, `/v1/pdftext`, `/v1/pdftexttable`, `/v1/pdfimagev5`, `/v1/pdfimagets`, `/v1/pdftxtimage`, `/v1/pdfimagetable`
- **Parametreler:** `page_range` (1-5, 1,3,7), `format` (json/text)
- **Çıktı:** JSON veya düz metin (sayfa bazlı `content` + `tables`)

## Kurulum

### Sistem (Linux/Debian)

```bash
sudo apt-get update
sudo apt-get install tesseract-ocr tesseract-ocr-tur poppler-utils libgl1-mesa-glx
```

### Python

```bash
cd wendococr
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Docker

```bash
docker build -t uguryldz/wendococr:v1.0.0 .
docker run -p 8099:8099 uguryldz/wendococr:v1.0.0
```

### Docker Compose (offline runtime uyumlu)

```bash
docker compose build
docker compose up -d
```

Notlar:
- `Dockerfile` build aşamasında PaddleOCR modellerini preload eder (`PRELOAD_PADDLE_MODELS=1`).
- Bu sayede container internetsiz ortamda çalışırken model indirmeye ihtiyaç duymaz.
- Build ortamında internet yoksa `PRELOAD_PADDLE_MODELS=0` kullanın ve `/root/.paddlex` cache'ini dışarıdan mount edin.

### Ortam değişkenleri

```bash
cp .env.example .env
# .env içinde: UPLOAD_DIR, MAX_FILE_SIZE_MB, MAX_PAGES, LOG_LEVEL, DEBUG, CORS_ORIGINS
```

## Çalıştırma

```bash
source .venv/bin/activate   # Linux/macOS
uvicorn app.main:app --reload --host 0.0.0.0 --port 8099
```

- API: http://localhost:8099  
- Dokümantasyon: http://localhost:8099/docs  
- Sağlık: http://localhost:8099/health  

## API örnekleri

```bash
# Otomatik karar (Brain)
curl -X POST "http://localhost:8099/v1/auto" -F "file=@fatura.pdf"

# Sadece 1–5. sayfalar, düz metin çıktı
curl -X POST "http://localhost:8099/v1/auto?page_range=1-5&format=text" -F "file=@rapor.pdf"

# PyMuPDF metin
curl -X POST "http://localhost:8099/v1/pdftext" -F "file=@rapor.pdf"

# Tablo + metin
curl -X POST "http://localhost:8099/v1/pdftexttable" -F "file=@tablo.pdf"

# RapidOCR (taranmış / resim)
curl -X POST "http://localhost:8099/v1/pdfimagev5" -F "file=@taranmis.pdf"

# PaddleOCR low bellek (Docker için önerilen)
curl -X POST "http://localhost:8099/v1/pdfimagepaddleocrlow" -F "file=@taranmis.pdf"

# Türkçe OCR (Tesseract)
curl -X POST "http://localhost:8099/v1/pdfimagets" -F "file=@taranmis.pdf"

# Hibrit: metin + gömülü resim (Findeks vb.)
curl -X POST "http://localhost:8099/v1/pdftxtimage" -F "file=@findeks.pdf"

# Tablo yapısı korumalı hibrit
curl -X POST "http://localhost:8099/v1/pdfimagetable" -F "file=@tablo.pdf"
```

Yanıt (JSON): `filename`, `method_used`, `processing_time_sec`, `pages[]` (her sayfada `page_number`, `content`, `tables`, `text_blocks`).

## Proje yapısı

```
wendococr/
├── app/
│   ├── api/           # routes: /v1/*, /health
│   ├── core/           # router.py (Brain – karar motoru)
│   ├── engines/        # pdf_text, pdf_table, ocr_rapid, ocr_tesseract, ocr_txtimage, ocr_imagetable
│   ├── utils/          # image_preprocess, pdf_convert, page_range
│   ├── config.py
│   ├── main.py
│   └── schemas.py
├── Dockerfile
├── .env.example
├── requirements.txt
└── README.md
```

Detaylı mimari için `Project.md` ve `DEV_NOTES.md` dosyalarına bakın.
