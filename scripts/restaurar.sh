#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────
# Restaura un respaldo. ¡REEMPLAZA todos los datos actuales!
#   ./scripts/restaurar.sh respaldos/pizarra-db-AAAAMMDD-HHMM.dump [respaldos/pizarra-adjuntos-AAAAMMDD-HHMM.tar.gz]
#
# Recomendación: pruebe una restauración una vez al mes en un equipo de pruebas.
# ─────────────────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")/.."

DUMP="${1:-}"
ADJ="${2:-}"
if [ -z "${DUMP}" ] || [ ! -f "${DUMP}" ]; then
  echo "Uso: $0 <archivo .dump> [archivo de adjuntos .tar.gz]"
  exit 1
fi

echo "⚠ Esto REEMPLAZA todos los datos actuales de la Pizarra por los del respaldo:"
echo "   ${DUMP} ${ADJ}"
read -r -p "Escriba RESTAURAR para continuar: " OK
[ "${OK}" = "RESTAURAR" ] || { echo "Cancelado."; exit 1; }

echo "▶ Deteniendo la aplicación…"
docker compose stop app

echo "▶ Restaurando la base de datos…"
docker compose exec -T db dropdb -U pizarra --if-exists pizarra
docker compose exec -T db createdb -U pizarra pizarra
docker compose exec -T db pg_restore -U pizarra -d pizarra --no-owner < "${DUMP}"

if [ -n "${ADJ}" ]; then
  echo "▶ Restaurando adjuntos…"
  docker compose run --rm -T --no-deps --entrypoint sh app -c "tar -C /data -xzf -" < "${ADJ}"
fi

echo "▶ Iniciando la aplicación…"
docker compose start app
echo "✔ Restauración terminada."
