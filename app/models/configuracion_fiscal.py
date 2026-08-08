"""Configuración fiscal para los informes de nómina B-03, B-06 y B-08 (§12 del diseño,
§2.12 y §3.1 del documento fuente): UMA, salario mínimo, marcas de exención por tipo de
percepción, y los mapeos de cada organización (departamento -> centro de costo, concepto
de nómina -> categoría de provisión).

`param_fiscal` frente a la tabla `Configuracion` que ya existe
----------------------------------------------------------------
`Configuracion` (`app/models/configuracion.py`) versiona por `ejercicio_fiscal` en texto
y guarda `valor` como JSON; le basta un valor por ejercicio porque sirve a las reglas
operativas del propio Hub CFDI (ventanas de descarga, reintentos, hora de sync, etc.),
que no cambian a mitad de año. `param_fiscal` resuelve un problema distinto: la UMA
cambia de valor el 1 de febrero, a mitad del ejercicio fiscal, así que un solo valor por
`ejercicio_fiscal` no alcanza para expresar los dos tramos de vigencia que coexisten en
un mismo año (ver la prueba `test_param_fiscal_admite_dos_tramos_en_un_ejercicio`).
Además cada fila de `param_fiscal` carga procedencia (`origen`, `fuente`,
`confirmado_por`, `confirmado_en`): quién sembró el valor, de dónde salió, quién lo
confirmó antes de usarlo en un informe. `Configuracion` no necesita nada de eso para sus
propios valores. Son dos mecanismos para dos necesidades distintas — aunque las dos
tablas se administren desde la misma pantalla (tarea 5), **no deben fusionarse**:
fusionarlas perdería la vigencia partida de la UMA o la procedencia de cada valor.

`configuracion_empresa` nace con sus tres campos en NULL — decisión explícita
--------------------------------------------------------------------------------
Ninguno de `zona_salarial`, `dias_aguinaldo` ni `factor_prima_vacacional` tiene default.
Para `zona_salarial`: el mínimo aplicable cambia el resultado de una validación de
cumplimiento. Ciudad Juárez está en la Zona Libre de la Frontera Norte, donde el mínimo
2026 es 440.87 contra 315.04 del régimen general — si el campo naciera en "GENERAL" por
default, una empresa de zona frontera que nunca configuró el valor obtendría falsos
negativos en "empleado por debajo del mínimo". Un default plausible aquí es peor que un
hueco visible que obliga a configurar el dato antes de confiar en el informe. Lo mismo
aplica a `dias_aguinaldo` (el mínimo legal son 15 días, pero cada organización puede dar
más) y a `factor_prima_vacacional` (mínimo legal 0.25, art. 80 LFT): la ley pone un piso,
no un valor único, y adivinar cuál aplica en cada empresa es responsabilidad de quien
configura el sistema, no de este modelo. **No le pongas default a estos tres campos.**

Por qué esta tabla y no columnas en `empresas`
-------------------------------------------------
`empresas` es la tabla caliente del listado de la UI; la fase 1 de los informes CFDI
estableció no tocarla y colgar los datos nuevos de una tabla aparte. Además estos tres
valores son política laboral de cada organización, no identidad de la empresa.

Reglas duras que aplican a todo este módulo: las claves de catálogo (`tipo_percepcion`,
`tipo`, `naturaleza`) son texto, nunca entero — los ceros a la izquierda son
significativos. Los importes usan `Decimal`/`Numeric`, nunca `float`.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CHAR, Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, false
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import BaseExencion, CategoriaProvision, OrigenValor, ZonaSalarial, enum_column

_TABLA_ARGS = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"}


class ParamFiscal(Base):
    """UMA, salario mínimo y tipo de cambio, con vigencia y procedencia.

    PK compuesta `(clave, vigencia_desde)`: una misma clave (p. ej. `UMA_DIARIA`) puede
    tener varios tramos de vigencia dentro del mismo `ejercicio`, porque la UMA cambia el
    1 de febrero mientras que el ejercicio fiscal corre de enero a diciembre.
    `vigencia_hasta` nulo significa "vigente hasta nuevo aviso", no "sin vigencia" — es
    el estado normal del tramo más reciente.

    Claves esperadas: `UMA_DIARIA`, `UMA_MENSUAL`, `UMA_ANUAL`, `SALARIO_MINIMO_GENERAL`,
    `SALARIO_MINIMO_ZLFN`, `TIPO_CAMBIO_USD`.
    """

    __tablename__ = "param_fiscal"
    __table_args__ = (_TABLA_ARGS,)

    clave: Mapped[str] = mapped_column(String(40), primary_key=True)
    vigencia_desde: Mapped[date] = mapped_column(Date, primary_key=True)
    ejercicio: Mapped[int] = mapped_column(Integer, nullable=False)
    valor: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    vigencia_hasta: Mapped[date | None] = mapped_column(Date, nullable=True)
    origen: Mapped[OrigenValor] = mapped_column(enum_column(OrigenValor), nullable=False)
    # Procedencia: de dónde salió el valor. Sin esto nadie puede revisar una semilla.
    fuente: Mapped[str] = mapped_column(String(500), nullable=False)
    sincronizado_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Sembrar propone, no activa: `confirmado_en` nulo es el estado inicial legítimo,
    # distinto de "no hay valor" (el valor sí existe, solo falta que alguien lo revise).
    confirmado_por: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confirmado_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class CatalogoPercepcionMarca(Base):
    """Marcas por tipo de percepción de nómina (§3.1 del documento fuente) que el catálogo
    `c_TipoPercepcion` del SAT no trae: si es ingreso ordinario, sobre qué base se calcula
    su tramo exento, si integra al SBC y si es provisionable (aguinaldo/vacaciones/etc.).

    Lleva confirmación como `param_fiscal`, y por la misma razón, solo que aquí pesa más:
    `factor_exencion` alimenta el cálculo de exenciones igual que la UMA, los factores del
    art. 93 de la LISR también cambian por reforma, y —a diferencia de la UMA, que se
    verifica contra un único boletín oficial— son 44 derivaciones hechas a mano (una por
    cada tipo del catálogo `c_TipoPercepcion`), el dato más propenso a error de toda la
    fase. Sin esta puerta, la UMA exigiría un clic y los 44 factores se aplicarían solos en
    cuanto alguien los cargara.
    """

    __tablename__ = "catalogo_percepcion_marca"
    __table_args__ = (_TABLA_ARGS,)

    # Clave del catálogo del SAT como texto: '002' no puede volverse 2.
    tipo_percepcion: Mapped[str] = mapped_column(CHAR(3), primary_key=True)
    es_ingreso_ordinario: Mapped[bool] = mapped_column(Boolean, nullable=False)
    base_exencion: Mapped[BaseExencion] = mapped_column(enum_column(BaseExencion), nullable=False)
    # NULL cuando `base_exencion` es NINGUNA: no hay tramo exento que calcular.
    #
    # UNIDAD DE `factor_exencion`, según `base_exencion` — leer antes de multiplicar:
    #   UMA_DIAS / SM_DIAS  número de días (30 = treinta días de UMA).
    #   PORCENTAJE          **porcentaje en escala 0-100**, NO una fracción: 100 significa
    #                       exento total y 50 la mitad. `importe * factor / 100`.
    # La distinción no es cosmética: tratar el 100 como fracción exenta cien veces de menos
    # en los 16 tipos con base PORCENTAJE, y el error no rompe nada, solo produce un número
    # incorrecto. La convención la fija la semilla (`config/fiscal/catalogo_percepcion.yaml`)
    # y está explicada en `config/fiscal/README.md`.
    factor_exencion: Mapped[Decimal | None] = mapped_column(Numeric(9, 4), nullable=True)
    integra_sbc: Mapped[bool] = mapped_column(Boolean, nullable=False)
    es_provisionable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # Si la exención de este tipo está sujeta al TOPE CONJUNTO de previsión social del
    # penúltimo párrafo del art. 93 de la LISR: la suma de las exenciones de previsión
    # social se limita a 1 UMA anual cuando el sueldo más la exención pasan de 7 UMA
    # anuales. Es un tope por trabajador y por año sobre la SUMA de varios tipos, no un
    # factor por tipo, así que `factor_exencion` no puede expresarlo y quien calcule tiene
    # que aplicarlo aparte.
    #
    # Existe como columna, y no como una lista en el código de B-03, porque cuáles tipos
    # caen bajo el tope es materia fiscal que cambia por reforma (§2.12: los valores
    # fiscales viven en tablas y YAML, nunca en código). Sin esta columna los seis tipos
    # sujetos al tope son indistinguibles de los otros diez con base PORCENTAJE en todo lo
    # que llega a la base de datos.
    #
    # `default=False`: es el caso de la enorme mayoría de los tipos, y así el renglón del
    # YAML solo lo declara donde aplica. Una marca sin exención (`NINGUNA`) no puede
    # llevarlo — no hay exención que topar; el cargador lo rechaza.
    sujeto_a_tope_conjunto: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    # Si el `factor_exencion` de este tipo lleva un multiplicador que **el CFDI no trae**, de
    # modo que `factor × UMA` no es su tope: son los nueve tipos cuyo número de la ley viene
    # "por" algo que el comprobante no dice —"90 UMA **por año de servicio**" (022, 023, 025,
    # 039, 053), "15 UMA **diarias**" (044, 051, 052) y "1 UMA **por domingo laborado**" (020)—.
    # Calcular ahí supone un multiplicador de 1 y publica un tope muy por debajo del legal, que
    # el informe presentaría como un exceso del patrón que no existe.
    #
    # **Tercera vez que hace falta esta columna en la misma fase**, después de
    # `sujeto_a_tope_conjunto` y `nota_revision`, y la lección general ya está escrita: *si el
    # cálculo lo necesita, o si quien confirma tiene que verlo, tiene que ser una columna.* Un
    # comentario del YAML no se carga y una lista de tipos en el programa viola el §2.12.
    #
    # **Qué reemplaza.** B-03 usaba `nota_revision` como aproximación —una marca con duda
    # abierta no calcula tope—, que falla del lado seguro pero tiene dos defectos: es más
    # conservadora de la cuenta (39 de 44 marcas traen nota y solo estas nueve por este motivo,
    # así que tipos perfectamente calculables salían vacíos) y **se desactiva sin querer** si
    # alguien resuelve la nota sin corregir el modelo. Con esta columna, lo que apaga el tope es
    # el hecho fiscal y no un texto que alguien puede borrar.
    #
    # `default=False`: es el caso de 35 de los 44 tipos, y así el renglón del YAML solo lo
    # declara donde aplica. Una marca sin exención (`NINGUNA`) no puede llevarlo: no hay factor
    # cuyo multiplicador falte, así que el cargador y el endpoint lo rechazan — igual que con
    # `sujeto_a_tope_conjunto` y por el mismo motivo (una bandera que no puede ser cierta es un
    # error de captura, no una opción).
    multiplicador_no_derivable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    # La duda declarada de este renglón: qué la genera y qué habría que verificar antes de
    # confirmarlo. 39 de los 44 tipos traen una.
    #
    # **No es lo mismo que `multiplicador_no_derivable` y por eso son dos columnas.** La nota es
    # prosa para una persona ("verifica esto antes de confirmar") y puede resolverse borrándola;
    # la bandera es un hecho fiscal que el cálculo consulta y que solo cambia si cambia la ley.
    # Nueve renglones traen las dos, y esa coincidencia es justo la que hacía pasar por buena la
    # aproximación de B-03.
    #
    # Es una columna por la misma razón que `sujeto_a_tope_conjunto`, y el defecto que la
    # motiva es idéntico: estas 39 dudas vivían en comentarios `# REVISAR` del YAML de la
    # semilla, los comentarios no se cargan, y la pantalla de confirmación acababa mostrando
    # 44 botones "Confirmar" sin una sola de las razones para dudar — pidiendo confirmar a
    # ciegas justo lo que el invariante de confirmación existe para impedir. **Si algo tiene
    # que verse al confirmar, tiene que ser un campo.**
    #
    # `Text` y no `String(n)`: la nota más larga de la semilla pasa de 780 caracteres y son
    # párrafos con subpuntos, no una etiqueta. Un ancho fijo mal elegido las truncaría en
    # silencio (`DataError 1406` en el mejor caso) justo en la parte que explica la duda.
    #
    # Una duda **nueva o distinta** limpia la confirmación; que la duda desaparezca, no. La
    # asimetría es el punto: confirmar significa "una persona revisó esto y responde por ello",
    # y una duda que esa persona no tenía delante invalida esa revisión, mientras que resolver
    # una duda no invalida nada. No aplica aquí el precedente de la `fuente` de `param_fiscal`
    # —que sí conserva la confirmación al cambiar—: la fuente dice de dónde salió el valor,
    # esta nota dice que el valor podría estar mal.
    nota_revision: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Mismo invariante que `param_fiscal`: sembrar propone, solo una persona activa.
    confirmado_por: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confirmado_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class MapDepartamento(Base):
    """Traduce el texto libre de `departamento` en la nómina (`nomina_receptor.departamento`)
    al centro de costo de cada organización. El mismo texto puede mapear a centros de
    costo distintos en empresas distintas — por eso cuelga de `empresa_id`, no es global."""

    __tablename__ = "map_departamento"
    __table_args__ = (_TABLA_ARGS,)

    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.empresa_id", ondelete="CASCADE"), primary_key=True)
    departamento_texto: Mapped[str] = mapped_column(String(100), primary_key=True)
    centro_costo: Mapped[str] = mapped_column(String(100), nullable=False)


class MapConceptoProvision(Base):
    """Asocia un concepto de nómina de la organización (`naturaleza` + `tipo` + `clave`,
    la clave interna del patrón de percepción/deducción) con la categoría de provisión
    contable a la que corresponde (aguinaldo, vacaciones, prima vacacional)."""

    __tablename__ = "map_concepto_provision"
    __table_args__ = (_TABLA_ARGS,)

    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.empresa_id", ondelete="CASCADE"), primary_key=True)
    naturaleza: Mapped[str] = mapped_column(CHAR(1), primary_key=True)
    tipo: Mapped[str] = mapped_column(CHAR(3), primary_key=True)
    clave: Mapped[str] = mapped_column(String(15), primary_key=True)
    categoria: Mapped[CategoriaProvision] = mapped_column(enum_column(CategoriaProvision), nullable=False)


class TablaVacaciones(Base):
    """Días de vacaciones por año de antigüedad, art. 76 de la LFT. Es ley federal, no una
    regla de cada patrón: por eso es una tabla global, sin `empresa_id`.

    **No lleva confirmación**, a diferencia de `param_fiscal` y `catalogo_percepcion_marca`
    — decisión explícita, no olvido. Los otros dos exigen confirmación porque son valores
    que cambian por decreto (la UMA, cada febrero) o derivaciones con criterio (los 44
    factores del art. 93). Esta tabla es la transcripción literal de un solo artículo, con
    dos columnas de enteros, estable desde la reforma de 2023 y verificable de un vistazo
    contra la ley; un error de captura aquí lo atrapa
    `test_la_tabla_de_vacaciones_reproduce_la_progresion_del_articulo_76`, que reconstruye
    la progresión completa desde el texto del artículo, no una revisión humana renglón por
    renglón. Poner una puerta de confirmación donde el dato no puede sorprender solo enseña
    a la gente a confirmar sin mirar, y eso desgasta la puerta donde sí importa.

    **El alcance de esa red es el archivo del repositorio, no la fila de la base.** La
    prueba lee `config/fiscal/tabla_vacaciones.yaml`; no protege contra una edición del YAML
    hecha directamente en el servidor ni contra un `UPDATE` a mano sobre esta tabla. Para
    esos dos casos no hay red, y es el precio consciente de no poner puerta de confirmación.
    """

    __tablename__ = "tabla_vacaciones"
    __table_args__ = (_TABLA_ARGS,)

    anios_antiguedad: Mapped[int] = mapped_column(Integer, primary_key=True)
    dias: Mapped[int] = mapped_column(Integer, nullable=False)


class ConfiguracionEmpresa(Base):
    """Política laboral de cada organización. Los tres campos nacen en NULL a propósito
    — ver la justificación completa en el docstring del módulo: un default aquí puede
    esconder un falso negativo en una validación de cumplimiento."""

    __tablename__ = "configuracion_empresa"
    __table_args__ = (_TABLA_ARGS,)

    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.empresa_id", ondelete="CASCADE"), primary_key=True)
    zona_salarial: Mapped[ZonaSalarial | None] = mapped_column(enum_column(ZonaSalarial), nullable=True)
    dias_aguinaldo: Mapped[int | None] = mapped_column(Integer, nullable=True)
    factor_prima_vacacional: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
