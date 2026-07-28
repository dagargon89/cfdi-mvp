"""Enlaces firmados de descarga (doc 05 §6: "URL firmada temporal, acotada a la empresa").

HMAC-SHA256 con expiración — no es material de e.firma, usa `SIGNING_SECRET` (nunca la KEK).
Sirve tanto para el resultado de `exportar_excel` como para `Comprobante.xml_path` (doc 05 §9:
"el drawer de comprobante lo necesita para el enlace de descarga") — ambos casos son "abre este
archivo bajo storage_root, acotado a esta empresa, por un rato".
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

from app.core.config import get_settings


class EnlaceInvalidoError(Exception):
    """Token alterado, mal formado o vencido (doc 05 §6)."""


def _clave() -> bytes:
    return get_settings().signing_secret.encode()


def _b64_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64_decode(data: str) -> bytes:
    relleno = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + relleno)


def firmar(payload: dict[str, Any], *, ttl_seg: int = 600) -> str:
    """Genera un token `<payload>.<firma>` con expiración embebida (`exp`)."""
    cuerpo = {**payload, "exp": int(time.time()) + ttl_seg}
    crudo = json.dumps(cuerpo, separators=(",", ":"), sort_keys=True).encode()
    firma = hmac.new(_clave(), crudo, hashlib.sha256).digest()
    return f"{_b64_encode(crudo)}.{_b64_encode(firma)}"


def verificar(token: str) -> dict[str, Any]:
    """Valida firma y expiración; devuelve el payload. Lanza `EnlaceInvalidoError` si no."""
    try:
        crudo_b64, firma_b64 = token.split(".", 1)
        crudo = _b64_decode(crudo_b64)
        firma = _b64_decode(firma_b64)
    except Exception as exc:  # noqa: BLE001 — cualquier token mal formado es inválido
        raise EnlaceInvalidoError("Enlace mal formado.") from exc

    firma_esperada = hmac.new(_clave(), crudo, hashlib.sha256).digest()
    if not hmac.compare_digest(firma, firma_esperada):
        raise EnlaceInvalidoError("Firma inválida.")

    payload: dict[str, Any] = json.loads(crudo)
    if payload.get("exp", 0) < time.time():
        raise EnlaceInvalidoError("El enlace venció.")
    return payload


def url_descarga(ruta_relativa: str, *, ttl_seg: int = 600) -> str:
    """URL absoluta y firmada para `GET /v1/descargas-archivo/{token}` — absoluta porque el
    navegador la abre directo (no vía `fetch` desde apps/web), nunca contra el host de la SPA."""
    token = firmar({"ruta": ruta_relativa}, ttl_seg=ttl_seg)
    return f"{get_settings().public_base_url}/v1/descargas-archivo/{token}"
