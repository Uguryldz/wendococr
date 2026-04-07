#!/bin/bash
set -e

IMAGE="uguryldz/wendococr"
VERSION="v1.0.0"

echo "=== wendococr build: ${IMAGE}:${VERSION} ==="
echo ""

docker compose build

docker tag "${IMAGE}:${VERSION}" "${IMAGE}:latest"

echo ""
echo "Build tamamlandi: ${IMAGE}:${VERSION}"
echo ""
echo "Mimari:"
echo "  wendococr        → API (HTTP alir, Redis'e atar)"
echo "  wendococr-worker → Worker (Redis'ten alir, OCR isler)"
echo "  redis            → Kuyruk (islem kaybi yok)"
echo ""
echo "Komutlar:"
echo "  docker compose up -d                              # Baslat (1 API + 3 worker + Redis)"
echo "  docker compose up -d --scale wendococr-worker=5   # 5 worker'a cikar"
echo "  docker compose up -d --scale wendococr-worker=10  # 10 worker'a cikar"
echo "  docker compose logs -f wendococr-worker           # Worker loglari"
echo "  curl http://localhost:8099/health                  # Durum"
echo ""
echo "  docker push ${IMAGE}:${VERSION}"
echo "  docker push ${IMAGE}:latest"
