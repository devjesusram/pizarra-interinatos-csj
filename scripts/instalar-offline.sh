#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────
# Instala o ACTUALIZA la Pizarra en un servidor sin internet.
# Ejecútelo dentro de la carpeta descomprimida del paquete:
#
#   cd /opt/pizarra && ./scripts/instalar-offline.sh
#
# Los datos (base de datos y adjuntos) se conservan entre actualizaciones.
# ─────────────────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")/.."

if ! command -v docker >/dev/null; then
  echo "✖ Docker no está instalado. Vea docs/INSTALACION.md, paso «Instalar Docker sin internet»."
  exit 1
fi

if [ -f VERSION ]; then export $(cat VERSION); fi

ARCHIVO=""
for f in imagenes.tar.gz imagenes.tar; do [ -f "$f" ] && ARCHIVO="$f" && break; done
if [ -n "${ARCHIVO}" ]; then
  echo "▶ Cargando las imágenes de Docker (${ARCHIVO})…"
  docker load -i "${ARCHIVO}"
else
  echo "▶ No hay archivo de imágenes: se usan las que ya están cargadas."
fi

if [ ! -f .env ]; then
  echo "▶ Creando el archivo .env con una contraseña de base de datos aleatoria…"
  CLAVE="$(od -An -tx1 -N24 /dev/urandom | tr -d ' \n')"
  sed "s|^DB_PASSWORD=.*|DB_PASSWORD=${CLAVE}|" .env.example > .env
  chmod 600 .env
fi

echo "▶ Iniciando los servicios…"
docker compose up -d --no-build

echo "▶ Esperando a que el sistema responda…"
PUERTO="$(grep -E '^PUERTO=' .env | cut -d= -f2)"; PUERTO="${PUERTO:-8080}"
for i in $(seq 1 60); do
  if curl -fs "http://localhost:${PUERTO}/salud" >/dev/null 2>&1; then
    echo
    echo "✔ La Pizarra está funcionando en: http://$(hostname -I 2>/dev/null | awk '{print $1}'):${PUERTO}"
    echo "  Si es la primera instalación, cree el administrador:"
    echo "    ./scripts/crear-admin.sh admin \"Nombre y Apellido\""
    exit 0
  fi
  sleep 2
done
echo "✖ El sistema no respondió. Revise los mensajes con:  docker compose logs app"
exit 1
