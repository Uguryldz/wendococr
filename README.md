# wendococr – Hybrid OCR & Document Parser (CPU Optimized)

PDF, JPG ve PNG belgelerini işleyen **FastAPI** tabanlı akıllı karar mekanizması. GPU olmadan CPU üzerinde çalışır; Türkçe karakter desteği vardır.

## Özellikler

- **Auto mod:** Belge türüne göre otomatik engine seçimi (sayfa bazlı)
- **Motorlar:** `pdftext` (PyMuPDF), `pdftexttable` (pdfplumber), `pdfimagev5` (RapidOCR), `pdfimagets` (Tesseract)
- **API:** Her motorun ayrı ucu – `POST /v1/auto`, `/v1/pdftext`, `/v1/pdftexttable`, `/v1/pdfimagev5`, `/v1/pdfimagets` (hepsinde sadece `file` gönderilir)
- **Çıktı:** Standart JSON (sayfa bazlı `content` + `tables`)

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

### Çalıştırma

**Önce sanal ortamı aktifleştirin** (paketler `.venv` içinde):

```bash
source .venv/bin/activate   # Linux/macOS
# Windows: .venv\Scripts\activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8099
```

Veya doğrudan venv’in uvicorn’unu kullanın (activate gerekmez):

```bash
.venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8099
```

Veya hazır script:

```bash
chmod +x run.sh && ./run.sh
```

- API: http://localhost:8099  
- Dokümantasyon: http://localhost:8099/docs  
- Sağlık: http://localhost:8099/health  

## Proje yapısı

```
wendococr/
├── app/
│   ├── api/           # routes: /v1/extract, /health
│   ├── core/           # router.py (Brain – karar motoru)
│   ├── engines/        # pdf_text, pdf_table, ocr_rapid, ocr_tesseract
│   ├── utils/          # image_preprocess, pdf_convert
│   ├── config.py
│   ├── main.py
│   └── schemas.py
├── DEV_NOTES.md        # Geliştirme notları
├── Project.md          # Proje spesifikasyonu
├── requirements.txt
└── README.md
```

## API örnekleri

```bash
# Otomatik karar (Brain)
curl -X POST "http://localhost:8099/v1/auto" -F "file=@fatura.pdf"

# Doğrudan PyMuPDF metin
curl -X POST "http://localhost:8099/v1/pdftext" -F "file=@rapor.pdf"

# Doğrudan tablo + metin
curl -X POST "http://localhost:8099/v1/pdftexttable" -F "file=@tablo.pdf"

# Doğrudan RapidOCR (taranmış / resim)
curl -X POST "http://localhost:8099/v1/pdfimagev5" -F "file=@taranmis.pdf"
```

Yanıt: `filename`, `method_used`, `processing_time_sec`, `pages[]` (her sayfada `page_number`, `content`, `tables`).

Detaylı mimari ve karar mantığı için `Project.md` ve `DEV_NOTES.md` dosyalarına bakın.
