"""add nota_revision a catalogo_percepcion_marca

Las 44 marcas del §3.1 se sembraron con **39 dudas declaradas**: cada una dice qué genera la
duda en ese tipo (una exención condicionada a un requisito que el CFDI no informa, un tope
parcial del art. 27 LSS que un booleano no puede expresar, un factor "por año de servicio"
que el modelo no tiene dónde poner). Las 39 estaban escritas con cuidado y verificadas contra
el texto oficial de la LISR y la LSS… **en comentarios `# REVISAR` del YAML de la semilla.**

Y los comentarios no se cargan. La consecuencia es que la pantalla de confirmación solo podía
mostrar 44 botones "Confirmar" sin ninguna de las 39 razones para dudar — pedir confirmar a
ciegas es exactamente lo que el invariante de confirmación existe para impedir, así que quien
construyó la pantalla decidió, con razón, no construir esa sección. Resultado: hoy no hay
ninguna forma de confirmar una marca desde la interfaz, y B-03 emitiría banderas que nadie
puede resolver.

Es el **segundo caso del mismo defecto en esta fase**: `sujeto_a_tope_conjunto`
(`c7a1e0b4d92f`) también era información necesaria para revisar guardada donde no llega al
dato. La lección general, escrita aquí para que quede en el rastro: **si algo tiene que verse
al confirmar, tiene que ser una columna.**

`TEXT` y no `VARCHAR(n)`: la nota más larga pasa de 780 caracteres y son párrafos con
subpuntos. Un ancho fijo mal elegido las truncaría justo en la parte que explica la duda.

**No se limpia ninguna confirmación**, a diferencia de `c7a1e0b4d92f`. Aquella agregaba un
campo que cambia el cálculo (si la exención cae bajo el tope conjunto), así que lo confirmado
antes se había confirmado sin verlo. Esta agrega procedencia: la nota explica por qué dudar de
unas marcas que no cambian. Es el mismo criterio con el que `guardar_param_fiscal` no tira la
confirmación cuando solo cambia la `fuente` — la cifra revisada sigue siendo la misma. En la
práctica da igual (las 44 filas están sin confirmar), pero el criterio es el que importa.

La migración se escribió **a mano** y no con `--autogenerate`: el autogenerado emite un
`op.drop_index` para los índices compuestos cuya primera columna respalda una llave foránea, y
MySQL lo rechaza con el error 1553. Aquí solo se agrega una columna nulable.

Para que las 39 notas lleguen a las filas ya sembradas hay que **recargar la semilla** con el
script de línea de comandos (`python -m app.scripts.cargar_configuracion_fiscal config/fiscal/catalogo_percepcion.yaml`).
La carga es idempotente y no confirma nada.

Revision ID: f92d4a1c7b06
Revises: e4b71c05a8d3
Create Date: 2026-08-06 23:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f92d4a1c7b06'
down_revision: Union[str, Sequence[str], None] = 'e4b71c05a8d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('catalogo_percepcion_marca', sa.Column('nota_revision', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('catalogo_percepcion_marca', 'nota_revision')
