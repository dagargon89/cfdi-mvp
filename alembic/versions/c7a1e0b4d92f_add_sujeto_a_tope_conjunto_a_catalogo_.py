"""add sujeto_a_tope_conjunto a catalogo_percepcion_marca

El penúltimo párrafo del art. 93 de la LISR limita la SUMA de las exenciones de previsión
social de un trabajador a 1 UMA anual cuando el sueldo más la exención pasan de 7 UMA
anuales. Es un tope por trabajador y por año sobre varios tipos de percepción a la vez, no
un factor por tipo, así que `factor_exencion` no puede expresarlo.

Sin esta columna, los seis tipos sujetos al tope (015, 029, 030, 034, 035 y 037) son
INDISTINGUIBLES en la base de los otros diez que también tienen `base_exencion: PORCENTAJE`
pero están exceptuados del tope. La distinción solo vivía en los comentarios del YAML de la
semilla, y los comentarios no se cargan: quien calculara la exención tendría que llevar la
lista escrita en el código, que es exactamente la lista fiscal codificada en el programa que
el §2.12 prohíbe.

La columna nace `NOT NULL DEFAULT FALSE` porque es el caso de la mayoría de los tipos y así
el YAML solo la declara donde aplica.

**Y se limpia la confirmación de todas las marcas existentes.** No es celo: una marca
confirmada antes de esta migración fue confirmada por alguien que no pudo ver este campo, y
el valor que la migración le acaba de poner (`false`) no lo revisó nadie. Si esa fila es uno
de los seis, el cálculo dejaría de aplicar el tope y exentaría de más, en silencio. Es la
misma regla que ya aplica el cargador cuando el contenido de un renglón cambia (vuelve a la
cola de revisión), y cuesta como mucho volver a confirmar 44 renglones.

Revision ID: c7a1e0b4d92f
Revises: aa2dd57754e8
Create Date: 2026-08-06 18:05:12.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7a1e0b4d92f'
down_revision: Union[str, Sequence[str], None] = 'aa2dd57754e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'catalogo_percepcion_marca',
        sa.Column('sujeto_a_tope_conjunto', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # Ver el docstring: lo confirmado se confirmó sin este campo a la vista.
    op.execute(
        "UPDATE catalogo_percepcion_marca SET confirmado_por = NULL, confirmado_en = NULL "
        "WHERE confirmado_en IS NOT NULL"
    )


def downgrade() -> None:
    """Downgrade schema."""
    # No se restauran las confirmaciones que limpió `upgrade`: no quedó registro de cuáles
    # eran, y reinventarlas sería peor que pedir que se vuelvan a confirmar.
    op.drop_column('catalogo_percepcion_marca', 'sujeto_a_tope_conjunto')
