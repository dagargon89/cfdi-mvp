"""jobs.cod_sat: código del SAT del último rechazo

Visto en producción el 2026-10-07: un job rechazado con `CodigoEstadoSolicitud=5002` ("se
agotaron las solicitudes de por vida" para esos mismos parámetros) mostraba solo "Solicitud
Aceptada" y se reintentó varias veces sin posibilidad de éxito. Con el código guardado, la API
explica el rechazo y bloquea el reintento cuando el SAT lo rechazaría idéntico (5002/5003).

Revision ID: 8c41d2e6f0b3
Revises: 5b2e9c1d7a40
Create Date: 2026-10-07 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "8c41d2e6f0b3"
down_revision: Union[str, None] = "5b2e9c1d7a40"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("cod_sat", sa.String(length=10), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "cod_sat")
