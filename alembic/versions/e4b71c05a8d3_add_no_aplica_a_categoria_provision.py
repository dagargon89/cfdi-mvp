"""add NO_APLICA a categoria_provision

Amplía el ENUM de `map_concepto_provision.categoria` con un cuarto valor: `NO_APLICA`.

**Por qué no es cosmético.** B-08 (provisión de pasivo laboral) necesita saber cuánto
aguinaldo se pagó ya en el ejercicio. Mientras exista un solo concepto de nómina sin
clasificar, "aguinaldo pagado = 0" es indistinguible de "sí se pagó y no sé en cuál concepto
viene", y el informe no se puede generar: un pasivo calculado sobre un cero que en realidad
es un hueco es un número que alguien podría llevar a sus estados financieros.

Cuando **todos** los conceptos que la nómina emitió tienen categoría —incluidos los que
explícitamente no son ninguna de las tres provisiones: sueldo, horas extra, despensa…— ese
cero pasa a ser un hecho conocido y B-08 puede generarse. Sin `NO_APLICA`, marcar "este
concepto no es provisión" solo se podría hacer *no capturándolo*, que es exactamente lo
mismo que hace quien todavía no lo ha revisado. La opción existe para que esos dos estados
dejen de ser el mismo estado.

Es una ampliación del ENUM, no un cambio de datos: ninguna fila existente se toca y ninguna
confirmación se invalida (`map_concepto_provision` no lleva puerta de confirmación — es un
mapeo de la organización, no un valor fiscal de la ley).

La migración se escribió **a mano** y no con `--autogenerate`: el autogenerado emite un
`op.drop_index` para los índices compuestos cuya primera columna respalda una llave foránea,
y MySQL lo rechaza con el error 1553 ("cannot drop index needed in a foreign key
constraint"). Aquí solo se altera una columna.

Revision ID: e4b71c05a8d3
Revises: c7a1e0b4d92f
Create Date: 2026-08-06 21:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e4b71c05a8d3'
down_revision: Union[str, Sequence[str], None] = 'c7a1e0b4d92f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ANTES = ('AGUINALDO', 'VACACIONES', 'PRIMA_VACACIONAL')
_DESPUES = ('AGUINALDO', 'VACACIONES', 'PRIMA_VACACIONAL', 'NO_APLICA')


def upgrade() -> None:
    op.alter_column(
        'map_concepto_provision',
        'categoria',
        existing_type=sa.Enum(*_ANTES, name='categoriaprovision'),
        type_=sa.Enum(*_DESPUES, name='categoriaprovision'),
        existing_nullable=False,
    )


def downgrade() -> None:
    # Un valor que el ENUM ya no admite no se puede representar: MySQL lo truncaría a cadena
    # vacía (o fallaría en modo estricto) y el mapeo quedaría corrupto sin avisar. Se borran
    # los renglones marcados `NO_APLICA`, que es la traducción honesta de "en el mundo
    # anterior, este concepto simplemente no estaba capturado" — el mismo estado del que
    # `NO_APLICA` vino a distinguirse.
    op.execute("DELETE FROM map_concepto_provision WHERE categoria = 'NO_APLICA'")
    op.alter_column(
        'map_concepto_provision',
        'categoria',
        existing_type=sa.Enum(*_DESPUES, name='categoriaprovision'),
        type_=sa.Enum(*_ANTES, name='categoriaprovision'),
        existing_nullable=False,
    )
