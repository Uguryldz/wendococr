#!/bin/bash
# Proje sanal ortamı (.venv) ile uvicorn çalıştırır
cd "$(dirname "$0")"
if [[ ! -d .venv ]]; then
  echo "Sanal ortam yok. Oluşturuluyor: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
fi
exec .venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8099
