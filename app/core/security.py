"""Verificación de ID tokens de Firebase (RF-AUTH-01, doc 04 §3.4).

El backend NUNCA confía en un uid que no haya sido verificado aquí: firma, expiración,
audiencia y revocación se validan contra Firebase (Admin SDK), no se decodifica el JWT
a mano. La inicialización del SDK es perezosa para que importar este módulo no falle en
tests (que sustituyen `verificar_id_token` por un doble) ni antes de tener credenciales.
"""

from __future__ import annotations

import logging
from functools import lru_cache

import firebase_admin
from fastapi import HTTPException, status
from firebase_admin import auth as firebase_auth
from firebase_admin import credentials

from app.core.config import get_settings

logger = logging.getLogger("app")


@lru_cache
def firebase_app() -> firebase_admin.App:
    """Pública — también la usan endpoints que llaman al Admin SDK directamente (p. ej.
    `POST /v1/usuarios`, que crea la cuenta de Firebase antes del registro local)."""
    settings = get_settings()
    cred = credentials.Certificate(settings.google_application_credentials)
    return firebase_admin.initialize_app(cred, {"projectId": settings.firebase_project_id})


def _extraer_token(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Falta el encabezado Authorization: Bearer <token>.")
    return authorization.removeprefix("Bearer ").strip()


def verificar_id_token(authorization: str | None) -> str:
    """Verifica el ID token y devuelve el `firebase_uid`. 401 ante cualquier falla.

    No distingue el motivo exacto en la respuesta (token ausente, expirado, inválido,
    revocado) — el detalle solo va a logs de servidor (doc 04 §3.4, sin fuga de info).
    """
    token = _extraer_token(authorization)
    try:
        # `clock_skew_seconds` es 0 por default en el SDK — cualquier desfase de reloj entre
        # este contenedor y los servidores de Google (visto en desarrollo: WSL2 puede
        # desincronizar su reloj unos segundos al suspender/reanudar la laptop) rechaza
        # tokens legítimos con "Token used too early". 10s es un margen estándar de tolerancia
        # de reloj para JWT, no debilita la verificación de firma/audiencia/revocación.
        decoded = firebase_auth.verify_id_token(token, app=firebase_app(), check_revoked=True, clock_skew_seconds=10)
    except Exception as e:  # noqa: BLE001 — cualquier fallo de verificación es 401, sin distinción
        logger.warning("verificar_id_token: verificación fallida (%s): %s", type(e).__name__, e)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Token inválido o expirado.") from e
    uid = decoded.get("uid")
    if not uid:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Token inválido o expirado.")
    return str(uid)
