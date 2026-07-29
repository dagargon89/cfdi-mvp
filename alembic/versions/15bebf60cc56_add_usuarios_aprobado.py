"""add usuarios aprobado

Revision ID: 15bebf60cc56
Revises: 707ce82c3acb
Create Date: 2026-07-29 14:22:14.408272

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


# revision identifiers, used by Alembic.
revision: str = '15bebf60cc56'
down_revision: Union[str, Sequence[str], None] = '707ce82c3acb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("usuarios", sa.Column("aprobado", mysql.TINYINT(1), nullable=False, server_default="0"))
    op.execute("UPDATE usuarios SET aprobado = 1")  # las filas existentes ya son legítimas


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("usuarios", "aprobado")
