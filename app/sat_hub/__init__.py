"""sat_hub — núcleo de dominio heredado de v1.0 (Hub_CFDI_docs/CLAUDE.md: "el núcleo se conserva").

Subconjunto portado en Sprint 0 desde /home/dagargon89/CFDI-1/sat_hub/ (ver plan de
implementación): domain.py, daterange.py, errors.py, sat_facade.py, sin modificar su
lógica interna. `store.py`/`engine.py` (SQLite+sync) y `secrets.py` (keyring del SO)
NO se portaron — se reescriben contra MySQL/Celery/bóveda en Sprint 2.
"""

from __future__ import annotations

from .daterange import trocear
from .domain import (
    Client,
    Comprobante,
    Estado,
    Estatus,
    Job,
    Progreso,
    ResultadoValidacion,
    Solicitud,
    Tipo,
)
from .errors import (
    ConfigError,
    FielError,
    FielPasswordError,
    FielVencidaError,
    HubError,
    SatError,
    SatRechazoError,
    SatReintentableError,
    StoreError,
    TransicionIlegalError,
)
from .sat_facade import CamposCFDI, ResultadoVerificacion, SatFacade, consultar_estatus_xml, parse_cfdi

__all__ = [
    "Client",
    "Job",
    "Comprobante",
    "ResultadoValidacion",
    "Progreso",
    "Estado",
    "Tipo",
    "Solicitud",
    "Estatus",
    "HubError",
    "FielError",
    "FielVencidaError",
    "FielPasswordError",
    "SatError",
    "SatRechazoError",
    "SatReintentableError",
    "StoreError",
    "TransicionIlegalError",
    "ConfigError",
    "trocear",
    "SatFacade",
    "ResultadoVerificacion",
    "CamposCFDI",
    "parse_cfdi",
    "consultar_estatus_xml",
]
