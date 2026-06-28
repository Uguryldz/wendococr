#!/bin/bash
set -e

# KAYNAK KODU GIZLILIGI: Imaj icinde .py kaynak duz metin durur (Python imajlari kodu
# gizleyemez). Tek gercek koruma imaji PRIVATE registry'de tutmaktir — public Docker
# Hub'a ASLA push etme. Asagidaki hedef hayatfinans Nexus (private).
REGISTRY="nexusregistry.hayatfinans.com.tr/rpa"
IMAGE="${REGISTRY}/uguryldz/wendococr"
VERSION="v1.0.2"

echo "=== wendococr build: ${IMAGE}:${VERSION} (PRIVATE registry) ==="
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
echo "  KVKK             → gelen belgeler tmpfs (RAM) — diske yazilmaz"
echo ""
echo "Komutlar:"
echo "  docker compose up -d                              # Baslat (1 API + 3 worker)"
echo "  docker compose up -d --scale wendococr-worker=5   # 5 worker'a cikar"
echo "  docker compose up -d --scale wendococr-worker=10  # 10 worker'a cikar"
echo "  docker compose logs -f wendococr-worker           # Worker loglari"
echo "  curl http://localhost:8099/health                  # Durum"
echo ""
echo "PRIVATE registry'ye push (public'e ASLA basma):"
echo "  docker login ${REGISTRY%%/*}"
echo "  docker push ${IMAGE}:${VERSION}"
echo "  docker push ${IMAGE}:latest"
