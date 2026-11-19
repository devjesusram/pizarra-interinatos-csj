#!/usr/bin/env bash
# Crea (o restablece la contraseña de) un usuario ADMINISTRADOR.
#   ./scripts/crear-admin.sh <usuario> "<Nombre y Apellido>"
# Si olvida la contraseña del administrador, vuelva a ejecutarlo con el mismo usuario.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ $# -lt 2 ]; then
  echo "Uso: $0 <usuario> \"<Nombre y Apellido>\""
  exit 1
fi
docker compose exec app python -m app.cli crear-admin "$1" "$2"
