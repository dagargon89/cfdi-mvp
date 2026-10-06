#!/usr/bin/env bash
# Ensayo de restauración (runbook A.7): demuestra que un respaldo SÍ se puede restaurar, sin tocar
# los datos de producción.
#
#     deploy/ensayar_restauracion.sh respaldos/hub-cfdi-AAAAMMDDTHHMMSSZ.tar.gz.gpg
#
# Descifra el respaldo, lo carga en una base aparte (hub_cfdi_ensayo), compara el número de filas
# de cada tabla contra la base viva, revisa que el paquete de almacenamiento esté íntegro y borra
# la base de ensayo. Si algo no cuadra, sale con error.
#
# Las cuentas pueden diferir si la aplicación escribió algo entre el respaldo y el ensayo (la
# bitácora, una descarga en curso). Por eso conviene ensayar justo después de respaldar.
set -euo pipefail
cd "$(dirname "$0")/.."

ARCHIVO="${1:?Uso: deploy/ensayar_restauracion.sh <respaldo.tar.gz.gpg>}"
PASSFILE="${HUB_BACKUP_PASSFILE:-/etc/hub-cfdi/respaldo.pass}"
HUB=deploy/hub.sh
TMP="$(mktemp -d)"

mysql_root() { $HUB exec -T mysql sh -c "MYSQL_PWD=\"\$MYSQL_ROOT_PASSWORD\" mysql -uroot $*"; }
limpiar() { mysql_root -e "'DROP DATABASE IF EXISTS hub_cfdi_ensayo'" >/dev/null 2>&1 || true; rm -rf "$TMP"; }
trap limpiar EXIT

if [[ -f "$ARCHIVO.sha256" ]]; then
  ( cd "$(dirname "$ARCHIVO")" && sha256sum -c --quiet "$(basename "$ARCHIVO").sha256" ) \
    || { echo "✗ La suma SHA-256 no coincide: el archivo está dañado o alterado." >&2; exit 1; }
  echo "✓ Suma SHA-256 correcta."
fi

gpg --batch --quiet --pinentry-mode loopback --passphrase-file "$PASSFILE" -d "$ARCHIVO" | tar -C "$TMP" -xzf -
echo "✓ Descifrado."

tar -tf "$TMP/storage.tar" > /dev/null || { echo "✗ El paquete de almacenamiento está dañado." >&2; exit 1; }
echo "✓ Almacenamiento íntegro: $(tar -tf "$TMP/storage.tar" | grep -vc '/$') archivos."

mysql_root -e "'DROP DATABASE IF EXISTS hub_cfdi_ensayo; CREATE DATABASE hub_cfdi_ensayo'"
# El volcado trae `CREATE DATABASE hub_cfdi` / `USE hub_cfdi`: se redirige a la base de ensayo.
sed -e 's/^CREATE DATABASE .*`hub_cfdi`.*;$//' -e 's/^USE `hub_cfdi`;$/USE `hub_cfdi_ensayo`;/' "$TMP/hub_cfdi.sql" | mysql_root
echo "✓ Cargado en hub_cfdi_ensayo."

contar() {
  # `< /dev/null` es imprescindible: `docker compose exec` lee la entrada estándar y, dentro del
  # `while read`, se comería el resto de la lista de tablas. Sin esto el ensayo comparaba UNA sola
  # tabla y declaraba éxito (visto en el ensayo del 2026-10-06).
  mysql_root -N -e "'SELECT table_name FROM information_schema.tables WHERE table_schema=\"$1\" ORDER BY table_name'" < /dev/null | while read -r t; do
    printf '%s %s\n' "$t" "$(mysql_root -N -e "'SELECT COUNT(*) FROM \`$1\`.\`$t\`'" < /dev/null)"
  done
}
# `join` exige el mismo orden que `sort`; MySQL ordena los `_` distinto.
contar hub_cfdi | sort > "$TMP/vivo.txt"
contar hub_cfdi_ensayo | sort > "$TMP/ensayo.txt"

# Defensa contra el falso positivo: si se comparan menos tablas de las que hay, el ensayo no
# demostró nada aunque las cuentas "coincidan".
ESPERADAS=$(mysql_root -N -e "'SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=\"hub_cfdi\"'" < /dev/null | tr -d '[:space:]')
COMPARADAS=$(wc -l < "$TMP/ensayo.txt" | tr -d '[:space:]')
if [[ "$COMPARADAS" -ne "$ESPERADAS" || "$ESPERADAS" -lt 2 ]]; then
  echo "✗ Se compararon $COMPARADAS tablas de $ESPERADAS: el ensayo no es concluyente." >&2
  exit 3
fi

printf '%-28s %10s %10s\n' TABLA VIVA ENSAYO
join "$TMP/vivo.txt" "$TMP/ensayo.txt" | awk '{ printf "%-28s %10s %10s%s\n", $1, $2, $3, ($2==$3 ? "" : "   ← DIFIERE") }'
if diff -q "$TMP/vivo.txt" "$TMP/ensayo.txt" > /dev/null; then
  echo "✓ ENSAYO EXITOSO: las $COMPARADAS tablas restauradas tienen las mismas filas que la base viva."
else
  echo "✗ Hay diferencias (ver arriba). Si la app escribió después del respaldo, es esperable." >&2
  exit 2
fi
