#!/usr/bin/env bash
# Restauración REAL de un respaldo sobre producción. Reemplaza la base y el almacenamiento.
#
#     deploy/restaurar.sh respaldos/hub-cfdi-AAAAMMDDTHHMMSSZ.tar.gz.gpg
#
# Antes de usarlo en una emergencia, practica con deploy/ensayar_restauracion.sh.
# Requiere que la KEK de secrets/kek.bin sea LA MISMA con la que se cifró la bóveda del respaldo.
set -euo pipefail
cd "$(dirname "$0")/.."

ARCHIVO="${1:?Uso: deploy/restaurar.sh <respaldo.tar.gz.gpg>}"
PASSFILE="${HUB_BACKUP_PASSFILE:-/etc/hub-cfdi/respaldo.pass}"
HUB=deploy/hub.sh
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

echo "Esto REEMPLAZA la base de datos y el almacenamiento de producción con: $ARCHIVO"
read -r -p "Escribe RESTAURAR para continuar: " confirmacion
[[ "$confirmacion" == "RESTAURAR" ]] || { echo "Cancelado."; exit 1; }

gpg --batch --quiet --pinentry-mode loopback --passphrase-file "$PASSFILE" -d "$ARCHIVO" | tar -C "$TMP" -xzf -

echo "→ Deteniendo api, worker y beat para que nada escriba durante la restauración…"
$HUB stop api worker beat

$HUB exec -T mysql sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot' < "$TMP/hub_cfdi.sql"
echo "✓ Base restaurada."

$HUB run --rm -T --no-deps --entrypoint sh worker -c 'find /srv/storage -mindepth 1 -delete && tar -C /srv/storage -xf -' < "$TMP/storage.tar"
echo "✓ Almacenamiento restaurado."

$HUB up -d
echo "✓ Servicios arriba. Revisa: deploy/hub.sh ps && deploy/hub.sh logs --tail=50 api worker"
