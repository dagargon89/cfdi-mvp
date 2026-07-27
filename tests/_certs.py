"""Generación de certificados de PRUEBA autofirmados — copiado de
/home/dagargon89/CFDI-1/tests/_certs.py (mismo patrón ya usado y probado en sat_hub v1.0).

NUNCA se usa material de FIEL real (regla no negociable 12 de CLAUDE.md). Estos
certificados son autofirmados, efímeros y solo ejercitan el camino de carga/validación
contra `satcfdi` real, sin tocar el SAT.
"""

from __future__ import annotations

import datetime
import secrets

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

RFC_PRUEBA = "EKU9003173C9"


def generar_fiel_prueba(
    *,
    rfc: str = RFC_PRUEBA,
    not_before: datetime.datetime | None = None,
    not_after: datetime.datetime | None = None,
    password: str = "12345678a",
) -> tuple[bytes, bytes, str]:
    """Crea un par .cer/.key autofirmado. Devuelve (cer_bytes, key_bytes, password)."""
    not_before = not_before or datetime.datetime(2020, 1, 1)
    not_after = not_after or datetime.datetime(2035, 1, 1)

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nombre = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, rfc),
            x509.NameAttribute(NameOID.X500_UNIQUE_IDENTIFIER, f"{rfc} / TEST"),
        ]
    )
    cert = (
        x509.CertificateBuilder()
        .subject_name(nombre)
        .issuer_name(nombre)
        .public_key(key.public_key())
        # Los seriales reales del SAT son de 20 dígitos (ver fixtures de doc 09) — a
        # diferencia de x509.random_serial_number() (hasta ~50 dígitos), que rebasaría
        # `efirmas.num_serie VARCHAR(40)` del DDL congelado (doc 03).
        .serial_number(secrets.randbelow(9 * 10**18) + 3 * 10**19)
        .not_valid_before(not_before)
        .not_valid_after(not_after)
        .sign(key, hashes.SHA256())
    )

    cer_bytes = cert.public_bytes(serialization.Encoding.DER)
    key_bytes = key.private_bytes(
        serialization.Encoding.DER,
        serialization.PrivateFormat.PKCS8,
        serialization.BestAvailableEncryption(password.encode()),
    )
    return cer_bytes, key_bytes, password
