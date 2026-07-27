"""Carga y validación de la e.firma al momento del alta (RF-BOV-01, doc 05 §4).

Adaptado de /home/dagargon89/CFDI-1/sat_hub/fiel.py (v1.0): misma disciplina (la
contraseña es efímera, nunca se persiste ni se loguea), pero sin `keyring` — aquí la
contraseña llega en el request y se usa una sola vez para validar+cifrar.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from app.sat_hub.errors import FielPasswordError, FielVencidaError

if TYPE_CHECKING:
    from satcfdi.models import Signer


class RfcNoCoincideError(Exception):
    """El RFC del certificado no coincide con el RFC de la empresa (doc 05 §4)."""


def cargar_signer(cer_bytes: bytes, key_bytes: bytes, password: str) -> "Signer":
    """Construye el `Signer` de `satcfdi`. Nunca incluye la contraseña en el mensaje de error."""
    from satcfdi.models import Signer  # import perezoso — mismo patrón que sat_hub

    try:
        return Signer.load(certificate=cer_bytes, key=key_bytes, password=password)
    except Exception as exc:  # noqa: BLE001 — se normaliza a error de dominio, sin exponer detalle
        raise FielPasswordError("La contraseña no abre la llave privada o los archivos están corruptos.") from exc


def _not_after_utc(signer: Any) -> datetime:
    cert = signer.certificate
    if not hasattr(cert, "not_valid_after_utc") and hasattr(cert, "to_cryptography"):
        cert = cert.to_cryptography()
    not_after = getattr(cert, "not_valid_after_utc", None) or getattr(cert, "not_valid_after", None)
    if not_after is None:
        raise FielPasswordError("No se pudo leer la vigencia del certificado.")
    if not_after.tzinfo is None:
        not_after = not_after.replace(tzinfo=timezone.utc)
    result: datetime = not_after
    return result


def _not_before_utc(signer: Any) -> datetime:
    cert = signer.certificate
    if not hasattr(cert, "not_valid_before_utc") and hasattr(cert, "to_cryptography"):
        cert = cert.to_cryptography()
    not_before = getattr(cert, "not_valid_before_utc", None) or getattr(cert, "not_valid_before", None)
    if not_before is None:
        raise FielPasswordError("No se pudo leer la vigencia del certificado.")
    if not_before.tzinfo is None:
        not_before = not_before.replace(tzinfo=timezone.utc)
    result: datetime = not_before
    return result


def validar_rfc(signer: "Signer", rfc_empresa: str) -> None:
    rfc_cert = str(signer.rfc).strip().upper()
    if rfc_cert != rfc_empresa.strip().upper():
        raise RfcNoCoincideError("El RFC del certificado no coincide con el RFC de la empresa.")


def validar_vigencia(signer: "Signer") -> tuple[datetime, datetime]:
    """Devuelve (not_before, not_after); lanza FielVencidaError si ya venció (RF-BOV-02)."""
    not_before = _not_before_utc(signer)
    not_after = _not_after_utc(signer)
    if datetime.now(timezone.utc) > not_after:
        raise FielVencidaError("El certificado está vencido. Renueva la e.firma en el SAT antes de registrarla.")
    return not_before, not_after
