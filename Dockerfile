# wendococr - Hybrid OCR & Document Parser
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-tur \
    libgomp1 \
    libgl1 \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

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

# PaddleOCR model preload (offline çalışsın diye)
RUN if [ "$PRELOAD_PADDLE_MODELS" = "1" ]; then \
      python -c "from paddleocr import PaddleOCR; PaddleOCR(use_doc_orientation_classify=False, use_doc_unwarping=False, use_textline_orientation=False, enable_mkldnn=False, device='cpu', text_det_limit_side_len=960, text_det_limit_type='min'); print('PaddleOCR model preload tamamlandi.')" \
    ; fi

COPY app/ ./app/
COPY entrypoint.sh .

EXPOSE 8099

HEALTHCHECK --interval=15s --timeout=5s --retries=3 --start-period=30s \
    CMD curl -sf http://localhost:8099/health || exit 1

CMD ["bash", "entrypoint.sh"]
