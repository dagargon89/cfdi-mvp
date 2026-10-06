#!/usr/bin/env bash
# Respaldo cifrado de Hub CFDI: base de datos completa + almacenamiento (XML y paquetes del SAT).
#
#     deploy/respaldar.sh [carpeta-destino]        # por defecto ./respaldos
#
# Programado con cron (ver docs/despliegue/README.md). Cifra con GPG (AES-256) usando la frase de
# /etc/hub-cfdi/respaldo.pass y conserva los últimos $HUB_RESPALDOS_A_CONSERVAR (14 por defecto).
#
# NO incluye la KEK ni la cuenta de Firebase, a propósito: si la KEK viajara en el mismo archivo
# que la base, quien robe el respaldo podría abrir la bóveda de e.firmas. La KEK se resguarda
# aparte y fuera del servidor.
#
# Copiar los respaldos FUERA del VPS es parte del procedimiento: un respaldo que vive en el mismo
# disco que los datos no sobrevive a la pérdida del servidor.
set -euo pipefail
cd "$(dirname "$0")/.."

DESTINO="${1:-./respaldos}"
PASSFILE="${HUB_BACKUP_PASSFILE:-/etc/hub-cfdi/respaldo.pass}"
CONSERVAR="${HUB_RESPALDOS_A_CONSERVAR:-14}"
HUB=deploy/hub.sh
SELLO="$(date -u +%Y%m%dT%H%M%SZ)"

[[ -r "$PASSFILE" ]] || { echo "No puedo leer la frase de respaldos: $PASSFILE" >&2; exit 1; }
mkdir -p "$DESTINO"; chmod 700 "$DESTINO"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

echo "→ Volcando la base de datos…"
# --single-transaction: copia consistente sin bloquear a la aplicación (todas las tablas son InnoDB).
$HUB exec -T mysql sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysqldump -uroot --single-transaction --routines --triggers --set-gtid-purged=OFF --databases hub_cfdi' > "$TMP/hub_cfdi.sql"

echo "→ Empaquetando el almacenamiento…"
$HUB exec -T worker tar -C /srv/storage -cf - . > "$TMP/storage.tar"

ARCHIVO="$DESTINO/hub-cfdi-$SELLO.tar.gz.gpg"
echo "→ Cifrando…"
tar -C "$TMP" -czf - hub_cfdi.sql storage.tar \
  | gpg --batch --yes --quiet --pinentry-mode loopback --passphrase-file "$PASSFILE" \
        --symmetric --cipher-algo AES256 -o "$ARCHIVO"
chmod 600 "$ARCHIVO"
( cd "$DESTINO" && sha256sum "$(basename "$ARCHIVO")" > "$(basename "$ARCHIVO").sha256" )

echo "✓ $ARCHIVO ($(du -h "$ARCHIVO" | cut -f1))"

# Rotación: conserva los N más recientes.
ls -1t "$DESTINO"/hub-cfdi-*.tar.gz.gpg 2>/dev/null | tail -n +"$((CONSERVAR + 1))" | while read -r viejo; do
  rm -f "$viejo" "$viejo.sha256"; echo "· Rotado: $(basename "$viejo")"
done
