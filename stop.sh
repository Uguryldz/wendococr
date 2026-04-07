#!/bin/bash
# wendococr durdur
PID=$(lsof -ti tcp:8099 2>/dev/null)
if [[ -n "$PID" ]]; then
  echo "Port 8099 kapatılıyor (PID: $PID)..."
  kill $PID 2>/dev/null
  sleep 1
  echo "Durduruldu."
else
  echo "Port 8099 zaten boş."
fi
