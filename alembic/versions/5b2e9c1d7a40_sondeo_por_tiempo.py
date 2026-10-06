"""sondeo por tiempo: jobs.solicitado_at + claves de configuración del backoff

El sondeo de estatus del SAT pasa de "cada `polling_espera_seg`, hasta `max_reintentos`
intentos" a una espera progresiva (×1.5 desde `polling_espera_seg` hasta
`polling_espera_max_seg`) con tope por **tiempo** transcurrido desde la solicitud
(`max_horas_sondeo`). Visto en producción el 2026-10-06: un mes de CFDI recibidos tardó más
de 3 h en el SAT y el tope de 180 intentos × 20 s (~1 h) mandó a ERROR una solicitud sana.

- `jobs.solicitado_at`: cuándo se envió la solicitud vigente (T1). Nulo en jobs previos; el
  worker empieza a contar en su siguiente sondeo.
- `max_reintentos` se elimina: ya nadie la lee.

Revision ID: 5b2e9c1d7a40
Revises: 671c56f611d6
Create Date: 2026-10-06 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "5b2e9c1d7a40"
down_revision: Union[str, None] = "671c56f611d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLA = sa.table(
    "configuracion",
    sa.column("clave", sa.String),
    sa.column("ejercicio_fiscal", sa.String),
    sa.column("valor", sa.JSON),
)
_NUEVAS = {"polling_espera_max_seg": 600, "max_horas_sondeo": 6}


def upgrade() -> None:
    op.add_column("jobs", sa.Column("solicitado_at", sa.DateTime(), nullable=True))
    op.bulk_insert(_TABLA, [{"clave": c, "ejercicio_fiscal": "vigente", "valor": v} for c, v in _NUEVAS.items()])
    op.execute(_TABLA.delete().where(_TABLA.c.clave == "max_reintentos", _TABLA.c.ejercicio_fiscal == "vigente"))


def downgrade() -> None:
    op.execute(_TABLA.delete().where(_TABLA.c.clave.in_(list(_NUEVAS)), _TABLA.c.ejercicio_fiscal == "vigente"))
    op.bulk_insert(_TABLA, [{"clave": "max_reintentos", "ejercicio_fiscal": "vigente", "valor": 180}])
    op.drop_column("jobs", "solicitado_at")
