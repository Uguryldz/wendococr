#!/bin/bash
# Proje sanal ortamı (.venv) ile uvicorn çalıştırır
cd "$(dirname "$0")"
if [[ ! -d .venv ]]; then
  echo "Sanal ortam yok. Oluşturuluyor: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
fi

# Önceki uvicorn sürecini öldür
PID=$(lsof -ti tcp:8099 2>/dev/null)
if [[ -n "$PID" ]]; then
  echo "Port 8099 kullanımda (PID: $PID), kapatılıyor..."
  kill $PID 2>/dev/null
  sleep 1
fi

exec .venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8099
