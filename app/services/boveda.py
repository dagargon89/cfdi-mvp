"""Bóveda de e.firmas — envelope encryption AES-256-GCM (doc 04 §3.3, A02).

DEK aleatoria de 256 bits por e.firma; cifra `.key` y contraseña. La DEK se envuelve
con la KEK maestra (fuera de la BD, archivo 600). Nonce de 12 bytes prefijado al blob;
GCM autentica (tag inválido → excepción, nunca descifra basura silenciosamente).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings
from app.services.fiel import cargar_signer, validar_rfc, validar_vigencia

_NONCE_LEN = 12


def generar_dek() -> bytes:
    return os.urandom(32)


def cifrar(clave: bytes, dato: bytes) -> bytes:
    nonce = os.urandom(_NONCE_LEN)
    return nonce + AESGCM(clave).encrypt(nonce, dato, None)


def descifrar(clave: bytes, blob: bytes) -> bytes:
    nonce, ciphertext = blob[:_NONCE_LEN], blob[_NONCE_LEN:]
    result: bytes = AESGCM(clave).decrypt(nonce, ciphertext, None)
    return result


def envolver_dek(kek: bytes, dek: bytes) -> bytes:
    return cifrar(kek, dek)


def desenvolver_dek(kek: bytes, blob: bytes) -> bytes:
    return descifrar(kek, blob)


@lru_cache
def cargar_kek() -> bytes:
    """Lee la KEK maestra del archivo (fuera de la BD, doc 04 §3.5).

    En desarrollo la genera `app/scripts/generar_kek_dev.py`; en producción es un
    procedimiento manual documentado en Hub_CFDI_docs/04-seguridad/04_plan_de_seguridad.md §3.5.
    """
    with open(get_settings().kek_path, "rb") as f:
        return f.read()


@dataclass(frozen=True, slots=True)
class EfirmaCifrada:
    num_serie: str
    not_before: datetime
    not_after: datetime
    cer_pem: bytes
    key_cifrada: bytes
    password_cifrada: bytes
    dek_envuelta: bytes


def preparar_efirma(cer_bytes: bytes, key_bytes: bytes, password: str, rfc_empresa: str) -> EfirmaCifrada:
    """Valida (abre/RFC/vigencia) y cifra la e.firma para persistir (RF-BOV-01).

    Lanza `FielPasswordError` (EFIRMA_NO_ABRE), `RfcNoCoincideError` (RFC_NO_COINCIDE)
    o `FielVencidaError` (EFIRMA_VENCIDA) — la capa de API las traduce a 422.
    """
    signer = cargar_signer(cer_bytes, key_bytes, password)
    validar_rfc(signer, rfc_empresa)
    not_before, not_after = validar_vigencia(signer)

    dek = generar_dek()
    kek = cargar_kek()
    return EfirmaCifrada(
        num_serie=str(signer.serial_number),
        not_before=not_before,
        not_after=not_after,
        cer_pem=cer_bytes,
        key_cifrada=cifrar(dek, key_bytes),
        password_cifrada=cifrar(dek, password.encode()),
        dek_envuelta=envolver_dek(kek, dek),
    )
