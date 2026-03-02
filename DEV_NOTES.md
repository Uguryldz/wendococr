# Geliştirme Notları (wendococr)

Bu dosya proje geliştirirken tutulacak kararlar ve dikkat edilecek noktaları içerir.

---

## Karar Mantığı (Brain / Router)

- **Auto mod akışı (net):**
  1. MIME kontrol: Resim (image/jpeg, image/png) → doğrudan `pdfimagev5` (RapidOCR).
  2. PDF ise: PyMuPDF ile metin katmanı var mı bak.
  3. **Metin katmanı varsa:** pdfplumber ile sayfa bazlı tablo yoğunluğu (dikey/yatay çizgi) analiz et.
     - Tablo yoğun → `pdftexttable`.
     - Tablo yoğun değil → `pdftext`.
  4. **Metin katmanı yoksa (taranmış PDF):** Sayfayı resme çevir → `pdfimagev5`.

- **Sayfa bazlı karar:** Her sayfa için ayrı motor seçilebilir (aynı PDF’te 1. sayfa searchable, 2. taranmış olabilir). İlk implementasyonda sayfa bazlı yap; gerekirse sonra “belge bazlı” mod eklenebilir.

---

## Çıktı ve Hata Formatları

- **Tablo formatı:** `tables` her sayfa için liste. Her tablo: `{"rows": [["h1","h2"], ["v1","v2"]]}` veya `[[...], [...]]` (satır bazlı list of lists). Dokümanda örnek ver.
- **Hata yanıtları:** 400 (geçersiz dosya/format), 413 (dosya çok büyük), 422 (işlenemeyen içerik), 500 (sunucu hatası). Hepsi JSON: `{"detail": "...", "code": "..."}`.
- **Limitler:** Max dosya boyutu (örn. 50MB), max sayfa (örn. 500) config’den okunacak; aşımda 413/422.

---

## Paralelizasyon ve Bloklama

- **CPU-bound OCR:** Ana event loop’u bloklamamak için `run_in_executor` kullan. Varsayılan ThreadPoolExecutor yeterli başlangıç için; ileride yoğun yük için `ProcessPoolExecutor` (ayrı process) düşün.
- **run_in_executor:** Tüm engine çağrıları (pdftext, pdftexttable, ocr) async endpoint içinde `loop.run_in_executor(pool, sync_func, ...)` ile sar.
- **BackgroundTasks:** Sadece loglama, geçici dosya temizliği gibi hafif işler için; ağır OCR burada çalışmasın.

---

## Güvenlik ve Operasyon (İleride)

- Dosya: Sadece MIME’a güvenme; magic bytes / içerik kontrolü ekle (zararlı PDF riski).
- Rate limit, auth, request timeout: İlk sürümde yok; not olarak kalsın.
- **Health:** `GET /health` → 200. İsteğe bağlı `GET /ready` → Tesseract/RapidOCR yüklü mü kontrol et.

---

## Proje Yapısı (Kök: wendococr)

- Workspace adı `wendococr`; dizin yapısı Project.md ile uyumlu, kök = proje ana dizini.
- `app/main.py` → FastAPI uygulaması, `app.api` router’ı include eder.
- `app/core/router.py` → Sadece karar mantığı (hangi engine, hangi sayfa); engine’leri import edip çağırır.
- Engine’ler ortak imza: `(file_path veya bytes, sayfa_no/listesi) → list[PageResult]`. PageResult: `page_number`, `content`, `tables`.

---

## Motor İsimleri (API `mode`)

- `auto`, `pdftext`, `pdftexttable`, `pdfimagev5`, `pdfimagets`. Doc ile birebir aynı kullan.

---

## Bağımlılıklar

- requirements.txt: fastapi, uvicorn[standard], python-multipart, pymupdf, pdfplumber, rapidocr_onnxruntime, pytesseract, opencv-python-headless (sunucuda opencv-python yerine headless önerilir).
- Sistem: tesseract-ocr, tesseract-ocr-tur, poppler-utils, libgl1-mesa-glx.

---

## Türkçe ve Ön İşleme

- Tesseract: `lang='tur'` (pytesseract).
- RapidOCR: Varsayılan model latin/Türkçe uyumlu.
- Resim pipeline: utils’te grayscale → threshold (Otsu veya adaptive) → isteğe bağlı deskew; OCR’dan önce her zaman uygula (resim/PDF’ten gelen görüntüler için).
