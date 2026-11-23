#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────
# Respaldo de la base de datos y de los adjuntos (PDF / correos).
#   ./scripts/respaldo.sh [carpeta-destino]      (por defecto: ./respaldos)
#
# Guarda los últimos 30 días. Para que corra solo cada noche a las 23:30:
#   crontab -e
#   30 23 * * * bash /opt/pizarra/scripts/respaldo.sh /opt/pizarra-respaldos >> /opt/pizarra-respaldos/respaldo.log 2>&1
#
# IMPORTANTE: copie también la carpeta de respaldos a OTRO equipo (NAS, servidor
# de archivos o disco externo). Un respaldo en el mismo servidor no sirve si el
# servidor se daña.
# ─────────────────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")/.."

DESTINO="${1:-./respaldos}"
DIAS_A_GUARDAR=30
FECHA="$(date +%Y%m%d-%H%M)"
mkdir -p "${DESTINO}"

echo "[$(date '+%F %T')] Respaldando base de datos…"
docker compose exec -T db pg_dump -U pizarra -d pizarra --format=custom > "${DESTINO}/pizarra-db-${FECHA}.dump"

echo "[$(date '+%F %T')] Respaldando adjuntos…"
docker compose exec -T app tar -C /data -czf - adjuntos > "${DESTINO}/pizarra-adjuntos-${FECHA}.tar.gz"

# Borra solo respaldos de la Pizarra con más de DIAS_A_GUARDAR días
find "${DESTINO}" -maxdepth 1 -type f \( -name 'pizarra-db-*.dump' -o -name 'pizarra-adjuntos-*.tar.gz' \) \
  -mtime +"${DIAS_A_GUARDAR}" -print -delete

echo "[$(date '+%F %T')] ✔ Respaldo listo en ${DESTINO}"
ls -lh "${DESTINO}"/pizarra-*-"${FECHA}".* | awk '{print "   " $5 "  " $9}'
