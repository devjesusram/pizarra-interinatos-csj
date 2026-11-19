#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────
# Prepara el paquete de instalación para un servidor SIN internet.
# Ejecútelo en una computadora CON internet y con Docker instalado.
#
#   ./scripts/preparar-paquete-offline.sh
#
# Resultado: paquete-offline/pizarra-offline-<fecha>.tar.gz
# Copie ese archivo al servidor (pendrive, carpeta compartida, etc.).
# ─────────────────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION="${VERSION:-1.0}"
FECHA="$(date +%Y%m%d)"
DESTINO="paquete-offline/pizarra"

echo "▶ 1/4 Construyendo la imagen de la aplicación (pizarra-interinatos:${VERSION})…"
# Se fuerza amd64, que es la arquitectura de los servidores habituales
docker build --platform linux/amd64 -t "pizarra-interinatos:${VERSION}" backend

echo "▶ 2/4 Descargando PostgreSQL 16…"
docker pull --platform linux/amd64 postgres:16

echo "▶ 3/4 Exportando las imágenes a un archivo (puede tardar unos minutos)…"
mkdir -p "${DESTINO}/scripts"
docker save "pizarra-interinatos:${VERSION}" postgres:16 | gzip > "${DESTINO}/imagenes.tar.gz"

echo "▶ 4/4 Copiando la configuración y los scripts…"
cp docker-compose.yml .env.example README.md "${DESTINO}/"
cp -r docs "${DESTINO}/"
cp scripts/instalar-offline.sh scripts/crear-admin.sh scripts/respaldo.sh scripts/restaurar.sh "${DESTINO}/scripts/"
echo "VERSION=${VERSION}" > "${DESTINO}/VERSION"

tar -C paquete-offline -czf "paquete-offline/pizarra-offline-${FECHA}.tar.gz" pizarra
echo
echo "✔ Listo: paquete-offline/pizarra-offline-${FECHA}.tar.gz ($(du -h "paquete-offline/pizarra-offline-${FECHA}.tar.gz" | cut -f1))"
echo "  Cópielo al servidor y siga docs/INSTALACION.md (sección «Instalar en el servidor»)."
