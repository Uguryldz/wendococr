#!/bin/bash
set -e
echo "[wendococr] API baslatiliyor..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8099 --workers 1
