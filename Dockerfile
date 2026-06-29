# wendococr - Hybrid OCR & Document Parser
FROM python:3.12-slim

# Guvenlik: base image OS paketlerini patch'le + pip'i guncelle (Scout CVE'leri).
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-tur \
    libgomp1 \
    libgl1 \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root kullanici (Scout: container root calismamali).
# HOME ayarlanir cunku PaddleOCR/RapidOCR modelleri ~/.paddlex, ~/.cache altina iner.
RUN useradd --create-home --uid 10001 appuser
ENV HOME=/home/appuser

WORKDIR /app

# pip guncel (5 CVE: PYSEC-2026-196, CVE-2025-8869, CVE-2026-1703/3219/6357)
RUN pip install --no-cache-dir --upgrade pip

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

ARG PRELOAD_PADDLE_MODELS=1
ENV PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True
ENV FLAGS_use_mkldnn=0
ENV UPLOAD_DIR=/tmp/wendococr
ENV PYTHONUNBUFFERED=1

# Worker defaults
ENV OCR_MAX_WORKERS=3
ENV OCR_QUEUE_MAX_SIZE=20
ENV OCR_QUEUE_TIMEOUT=120

COPY app/ ./app/
COPY entrypoint.sh .

# Uygulama dosyalari + home appuser'a ait olsun (model preload appuser olarak calissin).
RUN chown -R appuser:appuser /app /home/appuser

# Guvenlik: perl'i imajdan kaldir. Scout'taki tek Critical (CVE-2026-12087) +
# birkac High/Medium perl 5.40.1-6'dan geliyor ve Debian'da yamasi YOK (Fixable:0).
# Python OCR stack'i (Tesseract/RapidOCR/PaddleOCR) perl kullanmaz — test edildi.
# Bu artik son apt islemi; sonrasinda paket kurulmuyor.
RUN dpkg --purge --force-depends perl perl-base perl-modules-5.40 2>/dev/null || true \
    && rm -rf /usr/share/perl* /usr/bin/perl* /var/lib/apt/lists/*

# Bundan sonraki adimlar ve runtime non-root.
USER appuser

# PaddleOCR model preload — appuser olarak, modeller /home/appuser altina iner
# (runtime'da ayni user okur, offline calisir).
RUN if [ "$PRELOAD_PADDLE_MODELS" = "1" ]; then \
      python -c "from paddleocr import PaddleOCR; PaddleOCR(use_doc_orientation_classify=False, use_doc_unwarping=False, use_textline_orientation=False, enable_mkldnn=False, device='cpu', text_det_limit_side_len=960, text_det_limit_type='min'); print('PaddleOCR model preload tamamlandi.')" \
    ; fi

EXPOSE 8099

HEALTHCHECK --interval=15s --timeout=5s --retries=3 --start-period=30s \
    CMD curl -sf http://localhost:8099/health || exit 1

CMD ["bash", "entrypoint.sh"]
