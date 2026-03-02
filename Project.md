# Hybrid OCR & Document Parser (CPU Optimized)

## Proje Özeti

Bu proje; **PDF**, **JPG** ve **PNG** formatındaki belgeleri en yüksek verimlilikle işlemek için tasarlanmış, **FastAPI** tabanlı bir **Akıllı Karar Mekanizması (Decision Engine)** projesidir.

- Çıktılar **standartlaştırılmış JSON** formatında sunulur.
- **GPU yok:** Tamamen CPU üzerinde yüksek performansla çalışacak şekilde optimize edilmiştir.
- **Türkçe odaklı:** Türkçe karakterler için optimize edilmiştir.

Sistem, gelen belgenin içeriğine göre dinamik olarak en uygun işleme motorunu (engine) seçer. Böylece hem **işlem hızı (latency)** optimize edilir hem de **veri doğruluğu** maksimize edilir.

---

## Mimari ve Modül Yapısı

Proje **Strategy Pattern** ile modüler yapıdadır.

### 1. Karar Motoru (Auto-Router Logic – “Brain”)

`core/router.py` içindeki **Brain** modülü, belgeyi şu hiyerarşi ile analiz eder:

1. **Dijital PDF (Searchable)** → PyMuPDF ile saniyeler içinde metin çıkarımı.
2. **Tablo odaklı PDF** → pdfplumber ile koordinat bazlı tablo verisi çekimi.
3. **Taranmış PDF / Resim** → RapidOCR veya Tesseract ile optik karakter tanıma.

`mode: auto` olduğunda teknik akış:

1. **MIME türü kontrolü** – Dosya resim ise doğrudan RapidOCR’a gider.
2. **PDF analizi (PyMuPDF)** – PDF’te metin katmanı (text layer) var mı kontrol edilir.
3. **Tablo kontrolü (pdfplumber)** – Metin katmanı varsa, sayfada dikey/yatay çizgi yoğunluğu analiz edilerek tablo olup olmadığına bakılır.
4. **Resim PDF kontrolü** – Metin katmanı yoksa sayfa resme dönüştürülüp RapidOCR’a gönderilir.

### 2. Kullanılan Motorlar (Engines)

| Modül İsmi     | Kütüphane        | Kullanım Senaryosu                         | Neden? |
|----------------|------------------|---------------------------------------------|--------|
| `pdftext`      | PyMuPDF (fitz)   | Saf metin içeren dijital PDF’ler            | En hızlı (C++ tabanlı) metin çıkarıcı. |
| `pdftexttable` | pdfplumber       | Karmaşık tablo yapısı olan dijital PDF’ler   | Tablo çizgilerini ve hücre yapısını korur. |
| `pdfimagev5`   | RapidOCR         | Taranmış belgeler ve resimler (CPU)          | PaddleOCR’ın ONNX versiyonudur, CPU’da rakipsizdir. |
| `pdfimagets`   | Tesseract        | Basit metinler ve yedekleme (Legacy)         | Yaygın destek ve basitlik. |

---

## Proje Dizini

```
ocr-service/
├── app/
│   ├── api/                 # FastAPI endpoint'leri
│   ├── core/
│   │   └── router.py        # Akıllı yönlendirme mantığı (Brain)
│   ├── engines/             # OCR ve extraction modülleri
│   │   ├── pdf_text.py
│   │   ├── pdf_table.py
│   │   ├── ocr_rapid.py
│   │   └── ocr_tesseract.py
│   └── utils/               # Image pre-processing & PDF conversion
├── requirements.txt
└── README.md
```

---

## API Uç Noktaları

Her motorun **kendi endpoint’i** vardır; tek bir “extract + mode” yok. İstediğin motoru doğrudan çağırırsın.

Tüm uçlar: **Content-Type:** `multipart/form-data`, tek parametre: **`file`** (UploadFile).

| Endpoint | Motor | Ne zaman kullanılır? |
|----------|--------|----------------------|
| `POST /v1/auto` | Karar motoru (Brain) | Türü bilmiyorsan; sistem kendisi seçer. |
| `POST /v1/pdftext` | PyMuPDF | Dijital PDF, sadece metin. |
| `POST /v1/pdftexttable` | pdfplumber | Dijital PDF, tablo + metin. |
| `POST /v1/pdfimagev5` | RapidOCR | Taranmış PDF veya resim (JPG/PNG). |
| `POST /v1/pdfimagets` | Tesseract | Aynı içerik, Tesseract ile (yedek). |

**Ortak yanıt (JSON) — tüm veriler koordinatlarıyla:**

- **`content`:** Sayfadaki tüm metnin birleşik hali.
- **`text_blocks`:** Her metin parçası ve konumu (`text` + `bbox`: x0, y0, x1, y1). PDF’te birim point, resimde piksel.
- **`tables`:** Her tablo için `rows` (metin), `bbox` (tablo kutusu), `cells_bbox` (satır/sütun bazlı hücre koordinatları).
- **`page_width` / `page_height`:** Sayfa boyutu (koordinat birimiyle aynı).

```json
{
  "filename": "fatura.pdf",
  "method_used": "pdfimagev5",
  "processing_time_sec": 1.5,
  "pages": [
    {
      "page_number": 1,
      "content": "Fatura Numarası: ABC12345",
      "text_blocks": [
        { "text": "Fatura Numarası: ABC12345", "bbox": { "x0": 72, "y0": 100, "x1": 220, "y1": 115 } }
      ],
      "tables": [
        {
          "rows": [["Ürün", "Tutar"], ["Kalem", "10 TL"]],
          "bbox": { "x0": 72, "y0": 200, "x1": 300, "y1": 250 },
          "cells_bbox": [
            [{ "x0": 72, "y0": 200, "x1": 186, "y1": 220 }, { "x0": 186, "y0": 200, "x1": 300, "y1": 220 }],
            [{ "x0": 72, "y0": 220, "x1": 186, "y1": 250 }, { "x0": 186, "y0": 220, "x1": 300, "y1": 250 }]
          ]
        }
      ],
      "page_width": 595,
      "page_height": 842
    }
  ]
}
```

---

## Kurulum ve Gereksinimler

### 1. Sistem bağımlılıkları (Linux/Debian)

CPU üzerinde OCR performansı ve PDF dönüşümleri için Tesseract ve Poppler gereklidir:

```bash
sudo apt-get update
sudo apt-get install tesseract-ocr tesseract-ocr-tur poppler-utils libgl1-mesa-glx
```

### 2. Python bağımlılıkları

```bash
pip install fastapi uvicorn[standard] python-multipart pymupdf pdfplumber rapidocr_onnxruntime pytesseract opencv-python
```

---

## Geliştirici Notları (Optimization)

- **Türkçe karakter desteği:** OCR modülleri `-l tur` (Tesseract) ve varsayılan latin modelleriyle (RapidOCR) Türkçe karakter setine duyarlı hale getirilmiştir.
- **Pre-processing:** Resim tabanlı belgeler, OCR’a girmeden önce OpenCV ile **grayscale** ve **thresholding** (eşikleme) işlemlerinden geçirilir; gerekirse **deskewing** (eğiklik düzeltme) uygulanarak başarı oranı artırılır.
- **CPU paralelizasyonu:** Yoğun yük altında FastAPI’nin **BackgroundTasks** yapısı veya **ProcessPoolExecutor** kullanılması önerilir. İşlemler **async** fonksiyonlar içinde **`run_in_executor`** ile çalıştırılarak API’nin kilitlenmesi önlenmelidir.

---

Bu README dosyası projenin ana dizininde (ör. `README.md`) kullanılabilir. İstersen bir sonraki adımda **router.py (Karar Mekanizması)** için hazır bir kod bloğu yazılabilir; ekibe “işte mantık bu” diyerek doğrudan sunulabilir.

Daha fazla teknik detay veya implementasyon örneği için geliştirici ekibiyle iletişime geçebilirsiniz.
