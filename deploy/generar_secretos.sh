#!/usr/bin/env bash
# Genera los secretos de producción la PRIMERA vez. Se corre una sola vez en el VPS:
#
#     sudo deploy/generar_secretos.sh
#
# Qué hace:
#   1. Crea secrets/kek.bin — la llave maestra que cifra la bóveda de e.firmas (256 bits).
#   2. Crea .env.production a partir de .env.production.example con contraseñas y secretos aleatorios.
#   3. Crea la frase de cifrado de los respaldos (/etc/hub-cfdi/respaldo.pass).
#
# Se niega a sobrescribir cualquiera de los tres. Sobre todo la KEK: generar una nueva encima de
# la existente deja TODAS las e.firmas de la bóveda imposibles de descifrar, sin vuelta atrás.
set -euo pipefail
cd "$(dirname "$0")/.."

SECRETS_DIR="${HUB_SECRETS_DIR:-./secrets}"
ENV_FILE="${HUB_ENV_FILE:-.env.production}"
PASSFILE="${HUB_BACKUP_PASSFILE:-/etc/hub-cfdi/respaldo.pass}"
UID_APP=1000   # el `appuser` de la imagen (Dockerfile): tiene que poder leer la KEK

aleatorio() { openssl rand -hex "$1"; }   # hex: alfabeto que no necesita escape en ningún lado

dueno_app() {
  if [[ $EUID -eq 0 ]]; then chown "$UID_APP:$UID_APP" "$1"
  elif [[ $(id -u) -ne $UID_APP ]]; then
    echo "AVISO: $1 no pertenece al uid $UID_APP y los contenedores no podrán leerlo. Corre con sudo." >&2
  fi
}

mkdir -p "$SECRETS_DIR"
chmod 700 "$SECRETS_DIR"
dueno_app "$SECRETS_DIR"

# 1. KEK
if [[ -e "$SECRETS_DIR/kek.bin" ]]; then
  echo "· La KEK ya existe ($SECRETS_DIR/kek.bin): NO se toca."
else
  ( umask 077; head -c 32 /dev/urandom > "$SECRETS_DIR/kek.bin" )
  chmod 600 "$SECRETS_DIR/kek.bin"; dueno_app "$SECRETS_DIR/kek.bin"
  echo "✓ KEK creada: $SECRETS_DIR/kek.bin (600)."
  echo "  ⚠ Guarda una copia FUERA del servidor (gestor de contraseñas o medio offline) y NUNCA"
  echo "    junto a los respaldos de la base: sin la KEK las e.firmas no se pueden recuperar, y"
  echo "    con la KEK al lado del respaldo el cifrado de la bóveda no protege de nada."
fi

# 2. .env.production
if [[ -e "$ENV_FILE" ]]; then
  echo "· $ENV_FILE ya existe: NO se toca."
else
  ( umask 077; cp .env.production.example "$ENV_FILE" )
  sed -i \
    -e "s/^MYSQL_ROOT_PASSWORD=$/MYSQL_ROOT_PASSWORD=$(aleatorio 24)/" \
    -e "s/^MYSQL_APP_PASSWORD=$/MYSQL_APP_PASSWORD=$(aleatorio 24)/" \
    -e "s/^SIGNING_SECRET=$/SIGNING_SECRET=$(aleatorio 32)/" \
    -e "s/^BOOTSTRAP_ADMIN_TOKEN=$/BOOTSTRAP_ADMIN_TOKEN=$(aleatorio 24)/" \
    "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  echo "✓ $ENV_FILE creado (600) con contraseñas y secretos aleatorios."
  echo "  Completa a mano lo marcado [TÚ]: DOMAIN, ACME_EMAIL, FIREBASE_PROJECT_ID y las VITE_FIREBASE_*."
fi

# 3. Frase de los respaldos
if [[ -e "$PASSFILE" ]]; then
  echo "· La frase de respaldos ya existe ($PASSFILE): NO se toca."
else
  mkdir -p "$(dirname "$PASSFILE")"
  ( umask 077; aleatorio 32 > "$PASSFILE" )
  chmod 600 "$PASSFILE"
  echo "✓ Frase de respaldos creada: $PASSFILE (600). Guárdala también fuera del servidor:"
  echo "  sin ella, los respaldos cifrados son ilegibles."
fi

if [[ ! -e "$SECRETS_DIR/firebase-service-account.json" ]]; then
  echo
  echo "FALTA: copia la cuenta de servicio de Firebase a $SECRETS_DIR/firebase-service-account.json"
  echo "  sudo install -m 600 -o $UID_APP -g $UID_APP <archivo.json> $SECRETS_DIR/firebase-service-account.json"
fi
