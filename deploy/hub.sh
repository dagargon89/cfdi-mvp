#!/usr/bin/env bash
# Envoltorio de `docker compose` para producción: siempre el mismo archivo de compose y el mismo
# archivo de variables. Úsalo en lugar de `docker compose` directo; olvidar `--env-file` es la
# forma más fácil de levantar algo con la configuración equivocada.
#
#   deploy/hub.sh up -d --build     # desplegar o actualizar
#   deploy/hub.sh ps                # estado
#   deploy/hub.sh logs -f worker    # bitácora de un servicio
set -euo pipefail
cd "$(dirname "$0")/.."
ENV_FILE="${HUB_ENV_FILE:-.env.production}"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "No existe $ENV_FILE. Créalo con: sudo deploy/generar_secretos.sh" >&2
  exit 1
fi
exec docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml "$@"
