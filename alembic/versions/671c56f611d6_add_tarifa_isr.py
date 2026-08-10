"""add tarifa_isr y tarifa_isr_renglon

Agrega las dos tablas que guardan la tarifa del ISR (Anexo 8 de la RMF): `tarifa_isr` es la
cabecera de una tarifa (`ejercicio` + `periodicidad`) y `tarifa_isr_renglon` son sus renglones
(límite inferior, límite superior, cuota fija, tasa de excedente).

**La cabecera va aparte de los renglones a propósito**, divergiendo de la tabla plana que
describe el §12 del documento fuente. La procedencia (`origen`, `fuente`,
`documento_sha256`) y la confirmación (`confirmado_por`, `confirmado_en`) son propiedades de
*la tarifa completa*, no de cada renglón: con una tabla plana existiría el estado "renglón 3
confirmado, renglón 4 no", que no significa nada, que ningún cálculo puede usar y que habría
que excluir a mano en cada consulta. Con la cabecera separada ese estado es inexpresable —
se confirma la tarifa entera o no se confirma nada.

La migración se escribe **a mano** y no con `--autogenerate`, siguiendo el precedente de
`f92d4a1c7b06`: el autogenerado emite `op.drop_index` para los índices compuestos que
respaldan llaves foráneas y MySQL lo rechaza con el error 1553. Aquí se crean dos tablas
nuevas, así que el riesgo no aplica todavía, pero se mantiene el mismo criterio para toda
esta serie de migraciones sobre la tarifa ISR.

`tarifa_isr_renglon` tiene una llave foránea compuesta hacia `tarifa_isr` (`ejercicio`,
`periodicidad`) con `ondelete="CASCADE"`: borrar una tarifa borra sus renglones, nunca al
revés — por eso `downgrade` borra primero `tarifa_isr_renglon` y después `tarifa_isr`.

Revision ID: 671c56f611d6
Revises: a1d93f27e5b8
Create Date: 2026-08-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '671c56f611d6'
down_revision: Union[str, Sequence[str], None] = 'a1d93f27e5b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tarifa_isr",
        sa.Column("ejercicio", sa.Integer(), nullable=False),
        sa.Column(
            "periodicidad",
            sa.Enum("DIARIA", "DIAS_7", "DIAS_10", "DIAS_15", "MENSUAL", "EJERCICIO", name="periodicidadtarifa"),
            nullable=False,
        ),
        sa.Column("origen", sa.Enum("IMPORTADA", "MANUAL", name="origentarifa"), nullable=False),
        sa.Column("fuente", sa.String(length=500), nullable=False),
        sa.Column("documento_sha256", sa.CHAR(length=64), nullable=True),
        sa.Column("encabezado", sa.String(length=1000), nullable=False),
        sa.Column("importado_en", sa.DateTime(), nullable=False),
        sa.Column("confirmado_por", sa.String(length=128), nullable=True),
        sa.Column("confirmado_en", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("ejercicio", "periodicidad"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_table(
        "tarifa_isr_renglon",
        sa.Column("ejercicio", sa.Integer(), nullable=False),
        sa.Column(
            "periodicidad",
            sa.Enum("DIARIA", "DIAS_7", "DIAS_10", "DIAS_15", "MENSUAL", "EJERCICIO", name="periodicidadtarifa"),
            nullable=False,
        ),
        sa.Column("renglon", sa.Integer(), nullable=False),
        sa.Column("limite_inferior", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("limite_superior", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("cuota_fija", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("tasa_excedente", sa.Numeric(precision=7, scale=6), nullable=False),
        sa.ForeignKeyConstraint(
            ["ejercicio", "periodicidad"],
            ["tarifa_isr.ejercicio", "tarifa_isr.periodicidad"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("ejercicio", "periodicidad", "renglon"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )


def downgrade() -> None:
    op.drop_table("tarifa_isr_renglon")
    op.drop_table("tarifa_isr")
