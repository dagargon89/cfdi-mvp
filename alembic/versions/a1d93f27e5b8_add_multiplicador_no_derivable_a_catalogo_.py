"""add multiplicador_no_derivable a catalogo_percepcion_marca

Nueve tipos capturan el número que dice la ley pero **no el multiplicador**, porque el
multiplicador no viene en el CFDI de nómina: "90 UMA **por año de servicio**" (022, 023, 025,
039, 053), "15 UMA **diarias**" (044, 051, 052) y "1 UMA **por domingo laborado**" (020). El
comprobante no trae los años de antigüedad ni el número de domingos trabajados, así que
`factor × UMA` supone un multiplicador de 1 y produce un tope muy por debajo del legal — que
un informe presentaría como un exceso del patrón que no existe.

Sin esta columna esos nueve son **indistinguibles** de los otros tipos con
`base_exencion: UMA_DIAS`: la advertencia solo vivía en los comentarios del YAML de la semilla
y en la prosa del README, y los comentarios no se cargan. Quien calculara tendría que llevar
la lista de nueve tipos escrita en el programa, que es la lista fiscal codificada que prohíbe
el §2.12.

**Tercera vez en la misma fase**, después de `sujeto_a_tope_conjunto` y `nota_revision`. La
lección general: *si el cálculo lo necesita, o si quien confirma tiene que verlo, tiene que
ser una columna.*

**Qué reemplaza.** B-03 usaba `nota_revision` como aproximación —una marca con duda declarada
abierta no calcula su tope—, que falla del lado seguro pero es más conservadora de la cuenta
(39 de las 44 marcas traen nota y solo estas nueve por este motivo) y **se desactiva sin
querer** si alguien resuelve la nota sin corregir el modelo. El caso concreto: la nómina real
de este cliente solo usa `001` y `005`, y la nota del `005` es sobre si integra el salario base
de cotización —no sobre un multiplicador incalculable—, así que su tope salía vacío por la
aproximación y no porque fuera incalculable.

La columna nace `NOT NULL DEFAULT FALSE` porque es el caso de 35 de los 44 tipos y así el YAML
solo la declara donde aplica.

**Y se limpia la confirmación de todas las marcas existentes**, por el mismo argumento —y con
el mismo precedente— que `c7a1e0b4d92f`: una marca confirmada antes de esta migración la
confirmó alguien que no pudo ver este campo, y el `false` que la migración le acaba de poner no
lo revisó nadie. Para los nueve tipos afectados, ese `false` es justamente el valor que hace
que B-03 publique un tope calculado con un multiplicador supuesto. Cuesta como mucho volver a
confirmar 44 renglones; publicar un tope inventado, no.

Revision ID: a1d93f27e5b8
Revises: f92d4a1c7b06
Create Date: 2026-08-07 10:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1d93f27e5b8'
down_revision: Union[str, Sequence[str], None] = 'f92d4a1c7b06'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'catalogo_percepcion_marca',
        sa.Column('multiplicador_no_derivable', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # Ver el docstring: lo confirmado se confirmó sin este campo a la vista, y para los nueve
    # tipos afectados el default que acaba de entrar es el que hace calcular un tope supuesto.
    op.execute(
        "UPDATE catalogo_percepcion_marca SET confirmado_por = NULL, confirmado_en = NULL "
        "WHERE confirmado_en IS NOT NULL"
    )


def downgrade() -> None:
    """Downgrade schema."""
    # No se restauran las confirmaciones que limpió `upgrade`: no quedó registro de cuáles eran,
    # y reinventarlas sería peor que pedir que se vuelvan a confirmar.
    op.drop_column('catalogo_percepcion_marca', 'multiplicador_no_derivable')
