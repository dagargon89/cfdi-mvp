"""seed dias_re_verificacion config

Revision ID: 6cd129c28602
Revises: b3f4410d8f5c
Create Date: 2026-07-29 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '6cd129c28602'
down_revision: Union[str, Sequence[str], None] = 'b3f4410d8f5c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLA = sa.table(
    "configuracion",
    sa.column("clave", sa.String),
    sa.column("ejercicio_fiscal", sa.String),
    sa.column("valor", sa.JSON),
)


def upgrade() -> None:
    # RF-VAL-03 (Sprint 4): umbral de "antigüedad" de la última verificación de un
    # comprobante vigente antes de que la re-verificación programada lo vuelva a checar.
    op.bulk_insert(_TABLA, [{"clave": "dias_re_verificacion", "ejercicio_fiscal": "vigente", "valor": 30}])


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(_TABLA.delete().where(_TABLA.c.clave == "dias_re_verificacion", _TABLA.c.ejercicio_fiscal == "vigente"))
