"""seed configuracion defaults

Revision ID: b3f4410d8f5c
Revises: 7baf380a4c55
Create Date: 2026-07-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b3f4410d8f5c'
down_revision: Union[str, Sequence[str], None] = '7baf380a4c55'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLA = sa.table(
    "configuracion",
    sa.column("clave", sa.String),
    sa.column("ejercicio_fiscal", sa.String),
    sa.column("valor", sa.JSON),
)

# Valores por defecto (doc 03 §2.2, doc 09) — troceo de ventanas, polling del worker y
# umbral de alerta de vigencia de e.firma. `ejercicio_fiscal="vigente"` = configuración
# activa sin versionar por año fiscal (RF-CFG-01 completo queda para un sprint futuro).
#
# polling_espera_seg=60 / max_reintentos=60 (~1 hora de sondeo): un ciclo real contra el
# SAT (Sprint 2, empresa de producción) mostró que 15s/20 intentos (~5 min) es demasiado
# agresivo — el WS del SAT puede tardar varios minutos en terminar de generar los paquetes.
_DEFAULTS = {
    "max_meses_ventana": 12,
    "max_anios_antiguedad": 5,
    "polling_espera_seg": 60,
    "max_reintentos": 60,
    "umbral_vigencia_dias": 15,
    "hora_sync": "02:00",
}


def upgrade() -> None:
    op.bulk_insert(
        _TABLA,
        [{"clave": clave, "ejercicio_fiscal": "vigente", "valor": valor} for clave, valor in _DEFAULTS.items()],
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        _TABLA.delete().where(_TABLA.c.clave.in_(list(_DEFAULTS.keys())), _TABLA.c.ejercicio_fiscal == "vigente")
    )
