#!/bin/bash
set -e

if [ "$1" = "worker" ]; then
    echo "[wendococr] Worker baslatiliyor..."
    exec python -m app.core.worker_pool
else
    echo "[wendococr] API baslatiliyor..."
    exec uvicorn app.main:app --host 0.0.0.0 --port 8099 --workers 1
fi
