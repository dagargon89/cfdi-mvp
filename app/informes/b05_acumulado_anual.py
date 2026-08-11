"""B-05 · Acumulado anual por empleado (§B-05 del documento fuente).

**Propósito.** Papel de trabajo del cálculo anual del ISR (art. 97 LISR) y base de la
constancia de percepciones que el patrón entrega al trabajador. A diferencia de B-01/B-02
(una fila por CFDI) y B-04 (una fila por empleado × periodo), aquí una fila es un
`(rfc_receptor, ejercicio)`: el ejercicio completo, consolidado.

**Por qué su exactitud importa más que la de los otros informes del grupo.** Un importe mal
acumulado aquí no se queda en el Excel: viaja a la constancia de percepciones, y de ahí a la
declaración anual del trabajador. Un CFDI contado dos veces no es un error de reporte, es un
ingreso duplicado que el empleado declara ante el SAT.

**B-05.R1 — Resolución de sustituciones, la regla más delicada de este informe.** Un CFDI de
nómina cancelado y sustituido debe contar **una** vez: se toma el sustituto, se descarta el
sustituido. La cadena se resuelve por `cfdi_relacionado` con `tipo_relacion='04'`: se obtienen
los `uuid_relacionado` que los comprobantes del universo declaran con esa relación, y se
excluye del acumulado cualquier comprobante cuyo propio UUID caiga en ese conjunto — sin
importar su estatus. Si el sustituido no está en la base (nunca se descargó, o quedó fuera
del ejercicio), no hay nada que excluir y el acumulado ya es correcto.

**El mecanismo vive en `universo_nomina.uuids_sustituidos`, no aquí.** Nació en este módulo como
`_sustituidos`, y B-03 —que hace el mismo acumulado anual por `(rfc, tipo, ejercicio)`— resultó no
tenerlo: contaba dos veces un aguinaldo corregido por sustitución y emitía una `EXENCION_EXCEDIDA`
de severidad alta acusando al patrón de un exceso inexistente. Cualquier informe que sume importes
de varios CFDI del mismo empleado tiene el mismo problema, así que la resolución es de
`universo_nomina` y este módulo la consume. La clave de la bandera también es compartida
(`universo_nomina.CLAVE_CFDI_SUSTITUIDO`): es la columna por la que se filtra la hoja `Banderas`,
y dos ortografías la volverían inútil. El **mensaje** sí lo redacta cada informe, porque la
consecuencia de excluir no es la misma: aquí es un ingreso anual duplicado que viaja a la
constancia de percepciones.

**El alcance que se le pasa tiene que ser el de la suma que protege**, y aquí lo es: se le dan los
ids del **ejercicio completo** (`ids_universo`, antes de filtrar sustituidos y cancelados), que es
exactamente el alcance sobre el que acumula este informe. Pasarle solo un subconjunto dejaría una
sustitución de enero duplicando el acumulado sin ninguna fila que lo delate.

Esta exclusión se aplica **siempre**, independientemente de `incluir_cancelados`. La razón es
que la regla protege exactamente el caso en el que el estatus por sí solo NO basta: un
sustituido cuyo `estatus` local todavía no se ha re-verificado contra el SAT (sigue
`no_verificado`, o incluso `vigente` si la corrida de verificación no ha llegado a él) pasaría
cualquier filtro basado solo en `estatus`, y las dos versiones —la buena y la mala— se
sumarían las dos. La única señal confiable de que un comprobante fue reemplazado es la
relación `tipo_relacion='04'` que el sustituto declara, no el estatus del sustituido.

**Por qué `no_verificado` es el caso que importa de verdad, no un caso de borde.** La
verificación de estatus contra el SAT en este sistema es asíncrona (la misma divergencia que
`universo_nomina` documenta para R-T1): descargar un CFDI y confirmar ante el SAT si sigue
vigente son dos pasos separados en el tiempo, no uno. Un timbrado corregido casi siempre se
sustituye ANTES de que la siguiente corrida de verificación alcance al sustituido — así que,
en la práctica, el sustituido suele estar todavía `no_verificado` en el momento en que este
informe se corre, no `cancelado`. Para ese estatus, ningún filtro basado en "estatus ==
cancelado" hace nada: no hay nada cancelado que filtrar. R1 (la relación, no el estatus) es
la única defensa que existe contra la duplicación en ese momento — y por eso
`tests/test_informe_b05.py::test_sustituido_no_verificado_cuenta_una_vez` prueba justo ese
estatus, aislada de `test_cancelado_sustituido_cuenta_una_vez` (que cubre la segunda defensa:
un sustituido que sí llegó a marcarse `cancelado`, y a la que también protege el filtro de
huérfanos cancelados de más abajo). La verificación por mutación de la ronda de corrección 1
de esta tarea lo confirmó de forma empírica: desactivar R1 hace fallar la prueba de
`no_verificado` (importe duplicado) pero NO la de `cancelado` (la salva el otro filtro) — el
contraste es la evidencia de que cada prueba aísla la defensa que dice proteger.

**Semántica de las banderas de cancelación: la clave compartida significa lo mismo aquí que en
B-01/B-02.** Corrección de la revisión final. Antes este módulo usaba `COMPROBANTE_CANCELADO`
para decir "se **excluyó** del acumulado", mientras que `universo_nomina.banderas_de_estatus`
—la que emiten B-01 y B-02— la usa para decir lo contrario: "se **incluyó** y sus importes
suman". Quien filtrara la hoja `Banderas` por esa clave en B-02 y en B-05 del mismo periodo
sacaba conclusiones opuestas del mismo dato. Y peor: con `incluir_cancelados=True` este informe
metía el cancelado al acumulado **sin emitir ninguna bandera**, así que un CFDI cancelado y no
sustituido inflaba el ingreso anual del empleado en su constancia sin una sola advertencia. Ahora:

- `CANCELADO_EXCLUIDO` (alta) — cancelado, no sustituido, `incluir_cancelados=False`: **no** suma.
- `COMPROBANTE_CANCELADO` (alta, vía `universo_nomina.banderas_de_estatus`) — cancelado incluido
  con `incluir_cancelados=True`: **sí** suma, exactamente como en B-01/B-02.
- `CFDI_SUSTITUIDO` (baja) — excluido por B-05.R1, independientemente del parámetro.

**B-05.R3 — Multipatrón.** Si el mismo `rfc_receptor` aparece con dos `rfc_emisor` distintos
en el ejercicio (después de resolver R1), el cálculo anual es incompleto por construcción:
el patrón que genera este informe solo ve una parte de los ingresos del empleado. Se emite
`MULTI_PATRON` y el acumulado se conserva (no se descarta el empleado): es mejor un total
parcial con la advertencia visible que ningún total.

**Por qué el universo NO filtra por `rfc_emisor == rfc_empresa`, a diferencia de B-01/B-02/
B-04.** Esos tres informes reportan CFDI del patrón hacia sus propios empleados y acotan el
universo a "emitidos por la empresa" (`app.informes.universo_nomina.universo`). B-05 existe
para detectar precisamente el caso en que ese supuesto no se sostiene (R3): un empleado que
cobra de más de un RFC dentro de los datos de esta empresa. Filtrar por `rfc_emisor` haría
invisible la mitad del problema que esta regla existe para señalar. Por esa misma razón este
módulo no reutiliza `universo_nomina.universo()` (que sí filtra por `rfc_emisor`); construye
su propia consulta, acotada por `empresa_id` y por **ejercicio** (`YEAR(fecha_pago)`), no por
`fecha_desde`/`fecha_hasta`.

**Identidad del empleado: del CFDI más reciente, y con el nombre correcto.** Los campos de
identidad (columna 2) salen del CFDI con `fecha_pago` máxima del ejercicio, no del primero:
si el empleado cambió de puesto o departamento a media año, interesa su último estado. El
nombre se toma de `comprobante_detalle.nombre_receptor`, el campo correcto. B-01/B-02 usaban
`comprobante.razon_social_emisor` (la razón social del **emisor**, no del empleado) bajo una
etiqueta "Nombre empleado" que prometía algo que no era; la revisión final de la fase 2 los
corrigió, así que los seis informes del grupo B usan hoy el mismo campo.

**SBC y SDI son promedios ponderados por días pagados**, no promedios simples
(`Σ(valor × días) / Σ días`, con guarda de división por cero): un periodo de 5 días pesa
menos que uno de 15 en el promedio del ejercicio.

**Gravado y exento se recalculan de los nodos, no del encabezado.** A diferencia de B-01/B-02
(que reportan `nomina_totales.total_gravado/total_exento` tal cual los declara el CFDI), aquí
se suma `NominaPercepcion.importe_gravado`/`importe_exento` directamente — mismo criterio que
`app.informes.identidades_b00`: es lo que se puede verificar contra los nodos, y una constancia
fiscal no debe heredar sin cotejar un descuadre del encabezado que la identidad B-00 #4/#5 ya
sabe detectar.

**Y ese descuadre ahora se reporta al generar el informe**, no solo en las pruebas
(`universo_nomina.banderas_de_gravado_y_exento_descuadrados`, corrección de la revisión final).
Las dos lecturas —encabezado en B-01/B-02, nodos aquí— son correctas cada una para su propósito y
no se cambian, pero con un CFDI descuadrado daban cifras distintas del mismo concepto para el
mismo periodo sin advertencia; y dentro de una misma fila de este informe "Total percepciones"
viene del encabezado y "Total gravado"/"Total exento" de los nodos, así que la fila no cuadraba
consigo misma en silencio.

**B-05.R4 — La columna 11, "Gravado ordinario", y por qué no es "Total gravado".** Es
`Σ importe_gravado` de las percepciones cuyo tipo trae `es_ingreso_ordinario = true` en
`catalogo_percepcion_marca` (§3.1), y es la base del cálculo anual del ISR del artículo 97.
Los ingresos por **separación** (art. 95) y por **jubilación** (art. 96) tienen régimen
fiscal propio y **no se acumulan** al ordinario: sumarlos —que es lo que hace "Total
gravado"— sobreestima el ISR anual del trabajador. Cuáles son esos tipos **lo dice el dato**,
no el programa: son los que la marca declara con `es_ingreso_ordinario = false` (ocho en la
semilla actual). Escribir aquí la lista sería una lista fiscal codificada en el programa, que
es lo que prohíbe el §2.12, y dejaría de valer en cuanto una reforma moviera un tipo de lado.

**La columna exige marcas CONFIRMADAS, y es una decisión, no una herencia.** `es_ingreso_ordinario`
no es un importe, así que se podría argumentar que basta con que la marca exista. No basta, por
dos razones. (1) El **cargador ya trata un cambio de `es_ingreso_ordinario` como invalidante**: si
una recarga de la semilla cambia esa bandera, limpia `confirmado_por`/`confirmado_en` de la fila
(ver `configuracion_fiscal.cargar_desde_yaml_detallado`). Si la lectura ignorara la confirmación,
esa invalidación no tendría ningún efecto sobre esta columna: el sistema declararía que el dato
volvió a la cola de revisión y seguiría calculando con él. (2) El daño de equivocarse es del
mismo orden que el de un factor de exención mal capturado —una base de ISR anual inflada que
viaja a la constancia de percepciones y de ahí a la declaración del trabajador—, y las marcas son
44 derivaciones hechas a mano, el dato más propenso a error de la fase. Mismo criterio que B-03,
que consume el mismo catálogo por `marcas_de_percepcion` (solo confirmadas).

**Cómo degrada, y por qué nunca sale cero.** La columna vale `None` en **todas** las filas
mientras no haya marca confirmada para todos los tipos de percepción que **aportan importe
gravado** en el ejercicio, con **una** bandera por causa y ámbito `informe` (no una por fila: es
la lección del colapso de banderas de la fase 2):

- **Confirmado para todos los tipos que aportan gravado** → calcula.
- **Propuesto sin confirmar** → `MARCA_SIN_CONFIRMAR`, citando los tipos y lo que dice cada
  propuesta: el arreglo es un clic.
- **Ausente** → `FALTA_MARCA`, diciendo qué capturar.

Un cero ahí diría "este empleado no tuvo ingreso ordinario", que es una afirmación fiscal falsa
sobre alguien que cobró todo el año. Y se exige el catálogo **completo** para esos tipos —no se
suma "lo que se pueda"— porque una suma parcial no se distingue de una completa al mirar la
celda: sería una base de ISR corta con apariencia de correcta, el error espejo del que R4 existe
para evitar.

**Y la puerta solo cubre los tipos que pueden mover la suma** (corrección de la ronda 2, y era un
defecto vivo contra los datos reales de este cliente). `Σ importe_gravado` de un tipo cuyo gravado
es cero es cero, valga lo que valga su `es_ingreso_ordinario`, así que exigir su marca condiciona
el cálculo a un valor que el cálculo **no usa**. Es la regla general que el docstring de
`b03_gravado_exento` dejó escrita después de tres defectos del mismo tipo —*antes de condicionar
algo a que un valor esté confirmado, pregúntate si ese algo usa el valor*—, y este fue el cuarto.

El caso concreto no era hipotético: de las 44 marcas solo dos le aplican a esta empresa, `001`
Sueldos (todo el gravado, sin duda declarada, confirmable ya) y `005` Fondo de Ahorro (gravado
0.00, todo exento, **con** duda declarada sobre si integra el SBC y por tanto en la cola hasta que
alguien haga esa revisión fiscal). La única marca destinada a quedarse sin confirmar era
justamente la que no puede cambiar el resultado, y vaciaba la base del cálculo anual del ISR para
toda la plantilla. El acotamiento **es exacto, no una heurística**: los importes del CFDI son no
negativos, así que un agregado de cero significa que todos los renglones son cero. Se mide sobre
el **ejercicio completo**, no por comprobante: un tipo que aporta gravado en julio necesita su
marca aunque en junio venga en cero.

**Las dos claves son las de B-03, no unas propias.** La primera versión de esta tarea emitía
`MARCAS_SIN_CONFIRMAR`/`FALTA_CATALOGO_DE_MARCAS` (en plural), que describen mejor la degradación
todo-o-nada de esta columna pero rompen lo único que hace útil una clave de bandera: que quien
filtra la hoja `Banderas` por un hueco encuentre **todos** los informes que lo tienen. El hueco es
literalmente el mismo —no hay marca confirmada para un tipo—, así que gana el nombre que ya
estaba en producción. Lo que sí difiere, a propósito, es el **ámbito**: en B-03 es `tipo:0NN`
porque cada tipo pierde solo su propio tope y la acción es por tipo; aquí es `informe` porque la
columna se vacía entera para todos los empleados, así que el daño y la acción son de la corrida.

**Lo que esta columna NO cotejar contra las 12 y 13, declarado.** "Ingreso por separación" y
"Ingreso por jubilación" salen del **encabezado** (`nomina_totales`) y el gravado ordinario sale de
los **nodos** marcados, así que no existe entre ellos ninguna identidad exacta que se pueda
aseverar: los tipos con régimen propio no son exactamente los que alimentan esos dos totales del
complemento, y una parte de ellos puede venir exenta. No se emite bandera de descuadre entre las
tres columnas porque no habría umbral defendible; quien concilie el papel de trabajo tiene que
saber que son dos lecturas de origen distinto. El descuadre que sí se puede afirmar —encabezado
contra nodos para gravado y exento— lo reporta `TOTALES_DESCUADRADOS`.

**Alcance.** Columnas 1–23 del documento fuente, más el bloque anual del art. 97 LISR (Anexo I.4)
que la tarifa `EJERCICIO` desbloquea: "ISR anual teórico", "Subsidio anual acreditable" y
"Diferencia a cargo / favor" (§7 de `docs/superpowers/specs/2026-08-11-b09-isr-design.md`). Estas
tres sustituyen, por decisión de diseño, a la columna 26 de la especificación ("Sujeto a cálculo
anual", B-05.R2): esa columna exige datos que este informe no tiene —fecha de baja, umbral vigente
del ejercicio, aviso por escrito del trabajador— y afirmarla sin ellos sería una aseveración fiscal
sin sustento, así que sigue fuera de alcance. En su lugar se hace explícita la columna que la
fórmula del art. 97 ya necesitaba y que antes solo se podía deducir leyendo la columna 15 (ver el
docstring de `_COLUMNAS_ANUALES`, más abajo, para la decisión sobre cuál es el subsidio
"acreditable"). Las tres se declaran siempre —igual que "Gravado ordinario"— y degradan juntas: si
falta la base ordinaria o la tarifa `EJERCICIO`, las tres van vacías con la bandera que dice por
qué, nunca con un cero que se leería como "sin obligación".

**Sin `round()` ni `quantize()`** (el redondeo lo hace `app.informes.excel` al escribir la
celda), salvo en el bloque anual, que sí redondea **dentro de sí mismo** porque reproduce
`tarifa_isr.isr_de` (Anexo I.2), que ya redondea internamente; `Decimal` de punta a punta en todo
lo demás.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.informes import configuracion_isr, universo_nomina
from app.informes.base import Bandera, Columna, ResultadoInforme
from app.informes.identidades_b00 import CLAVE_TIPO_DEDUCCION_ISR
from app.models.cfdi_detalle import ComprobanteDetalle
from app.models.comprobante import Comprobante
from app.models.empresa import Empresa
from app.models.enums import EstatusCfdi, PeriodicidadTarifa
from app.models.nomina import Nomina, NominaDeduccion, NominaOtroPago, NominaPercepcion, NominaReceptor, NominaTotales
from app.services import configuracion_fiscal as cfg
from app.services import tarifa_isr

CLAVE = "B-05"
NOMBRE = "Acumulado anual por empleado"
GRUPO = "B"
DESCRIPCION = (
    "Una fila por empleado y ejercicio: el papel de trabajo del cálculo anual del ISR (art. "
    "97 LISR) y la base de la constancia de percepciones. Resuelve sustituciones (un CFDI "
    "cancelado y reemplazado cuenta una vez) y avisa cuando el mismo empleado cobra de más "
    "de un patrón en el ejercicio."
)

TIPOS_COMPROBANTE: tuple[str, ...] = ("N",)
"""Ver la constante homónima de `app.informes.b02_conceptos_patron`: mismo razonamiento
(todo el grupo B declara `("N",)`) y mismo consumidor (el pre-vuelo del ETL en
`app.worker.tasks._generar_informe_async`)."""

_CERO = Decimal("0")

_CLAVE_DEDUCCION_ISR = CLAVE_TIPO_DEDUCCION_ISR
"""`"002"` (catálogo `c_TipoDeduccion`), reexportado de `identidades_b00` para no declarar
dos veces la misma clave."""

_CLAVE_DEDUCCION_IMSS = "001"
"""Clave del catálogo `c_TipoDeduccion` de "Seguridad social" (columna 17, IMSS retenido)."""

_CLAVE_DEDUCCION_FONDO_AHORRO = "004"
"""Clave del catálogo `c_TipoDeduccion` de "Aportaciones a Fondo de ahorro" (columna 18)."""

_CLAVE_DEDUCCION_INFONAVIT = "009"
"""Clave del catálogo `c_TipoDeduccion` de "Descuento por incapacidad... Infonavit" — en la
práctica, el descuento de crédito Infonavit (columna 19)."""

_CLAVE_OTRO_PAGO_SUBSIDIO = "002"
"""Clave del catálogo `c_TipoOtroPago` de "Subsidio para el empleo efectivamente entregado al
trabajador" (columnas 15–16). Mismo valor que `b01_catalogo_sat._CLAVE_OTRO_PAGO_SUBSIDIO`,
declarado aparte a propósito: es una clave de catálogo, no lógica compartida entre módulos."""

class Parametros(BaseModel):
    ejercicio: int = Field(description="Año fiscal sobre `YEAR(nomina.fecha_pago)`. El grano del informe es (empleado, ejercicio).")
    incluir_cancelados: bool = Field(
        False,
        description=(
            "Un CFDI cancelado que no fue sustituido (B-05.R1) es un recibo huérfano: no representa "
            "un pago que subsista. Por defecto se excluye del acumulado, marcado con `CANCELADO_EXCLUIDO`; "
            "con este parámetro en True se incluye y sus importes suman, marcado con `COMPROBANTE_CANCELADO` "
            "—la misma clave y el mismo significado que en B-01/B-02. Los cancelados que SÍ fueron "
            "sustituidos se excluyen siempre, sin importar este parámetro (ver B-05.R1 en el docstring "
            "del módulo)."
        ),
    )
    enmascarar_datos_personales: bool = Field(
        True,
        description=(
            "Enmascara CURP (spec §8). Lo aplica el motor de informes "
            "(`app.informes.excel.escribir_libro`) sobre las columnas que esta consulta marca "
            "como `sensible=True`, no esta consulta directamente."
        ),
    )


# Columnas 1 a 10 del **documento fuente** (identidad, fechas del ejercicio y los tres totales
# del encabezado), que son **quince** columnas del Excel: la numeración del documento agrupa
# varios campos en un solo renglón numerado —su renglón 2 es "RFC / CURP / Nombre / Núm.
# empleado", cuatro columnas— y aquí se despliegan una por una. Por eso la "columna 11" sale en
# la posición 16 de la hoja: los nombres de estas constantes citan el documento, no el índice
# del Excel. Ver la tabla del §B-05 en `Hub_CFDI_docs/00-fuentes/especificacion-informes-cfdi.md`.
_COLUMNAS_UNO_A_DIEZ: tuple[tuple[str, str, bool], ...] = (
    ("Ejercicio", "entero", False),
    ("RFC empleado", "texto", False),
    ("CURP", "texto", True),
    ("Nombre empleado", "texto", False),
    ("Núm. empleado", "texto", False),
    ("Departamento", "texto", False),
    ("Puesto", "texto", False),
    ("Fecha inicio relación laboral", "fecha", False),
    ("Fecha primer pago del ejercicio", "fecha", False),
    ("Fecha último pago del ejercicio", "fecha", False),
    ("Núm. de CFDI", "entero", False),
    ("Días pagados del ejercicio", "decimal", False),
    ("Total percepciones", "monto", False),
    ("Total gravado", "monto", False),
    ("Total exento", "monto", False),
)

# Columna 11 (B-05.R4). Va aquí, entre "Total exento" y "Ingreso por separación", en el mismo
# orden del documento fuente: al lado de los dos ingresos de régimen propio que precisamente
# **no** entran en ella.
_COLUMNA_ONCE: tuple[tuple[str, str, bool], ...] = (("Gravado ordinario", "monto", False),)

# Columnas 12 a 23.
_COLUMNAS_DOCE_A_VEINTITRES: tuple[tuple[str, str, bool], ...] = (
    ("Ingreso por separación", "monto", False),
    ("Ingreso por jubilación", "monto", False),
    ("ISR retenido", "monto", False),
    ("Subsidio causado", "monto", False),
    ("Subsidio entregado en efectivo", "monto", False),
    ("IMSS retenido", "monto", False),
    ("Aportaciones a fondo de ahorro", "monto", False),
    ("Descuentos Infonavit", "monto", False),
    ("Otras deducciones", "monto", False),
    ("Neto pagado", "monto", False),
    ("SBC promedio ponderado", "monto", False),
    ("SDI promedio ponderado", "monto", False),
)

# El bloque anual (Anexo I.4, art. 97 LISR), al FINAL de `_COLUMNAS` y no intercalado con las
# columnas 24-25 del documento fuente: intercalar habría corrido el índice de las 23 columnas ya
# publicadas y roto cualquier hoja de cálculo que alguien ya tenga armada sobre este informe.
#
# **El paso de lectura del plan, resuelto: cuál de las dos columnas de subsidio es la
# "acreditable".** B-05 ya trae "Subsidio causado" (columna 15 del documento fuente,
# `Σ subsidio_causado` de `nomina_otro_pago`: lo que la tabla del Anexo I.3 determina para el
# periodo — `subsidio_del_periodo` en `tarifa_isr`) y "Subsidio entregado en efectivo" (columna
# 16, `Σ importe`: solo el excedente que se entrega en efectivo cuando el subsidio del periodo
# supera al ISR del periodo — `subsidio_a_entregar`). No son lo mismo, y la diferencia se ve en
# la propia aritmética de `tarifa_isr`: de `isr_a_retener = max(0, isr − subsidio)` y
# `subsidio_a_entregar = max(0, subsidio − isr)` se sigue que
# `subsidio_causado = min(isr, subsidio) + subsidio_a_entregar` para cualquier periodo. Es decir,
# "Subsidio causado" es el monto COMPLETO que en cada periodo se aplicó contra la obligación del
# trabajador —ya sea acreditándose contra el ISR retenido, o entregándose en efectivo cuando lo
# rebasa—, mientras que "Subsidio entregado en efectivo" es solo la segunda de esas dos partes: en
# todo periodo donde el ISR alcanza a cubrir el subsidio (`isr >= subsidio`) esta columna vale
# 0.00 aunque el subsidio sí se haya acreditado por completo. Usar la columna 16 aquí subestimaría
# el subsidio acreditable del ejercicio en exactamente esos periodos — que, con un sueldo típico,
# son la mayoría. Y es lo que dice el documento fuente sin ambigüedad, fuera de toda deducción:
# el Anexo I.4 define `subsidio_anual_acreditable = B-05 columna 15`, y la columna 15 de la
# especificación es "Subsidio causado". Por eso "Subsidio anual acreditable" toma
# `acc.subsidio_causado`, nunca `acc.subsidio_entregado`.
#
# **Las tres degradan juntas**, y no cada una por su cuenta: sin base ordinaria (B-05.R4, marcas
# sin confirmar) o sin tarifa `EJERCICIO` confirmada no hay ISR anual que calcular, y mostrar solo
# el subsidio acreditable sin el ISR anual ni la diferencia sería un fragmento del cálculo del
# art. 97, no el cálculo — se leería como un avance parcial que no existe. Ver
# `_tarifa_del_ejercicio` y el bloque del bucle principal en `consultar` para el punto exacto de
# la puerta.
_COLUMNAS_ANUALES: tuple[tuple[str, str, bool], ...] = (
    ("ISR anual teórico", "monto", False),
    ("Subsidio anual acreditable", "monto", False),
    ("Diferencia a cargo / favor", "monto", False),
)

_COLUMNAS: tuple[tuple[str, str, bool], ...] = (
    _COLUMNAS_UNO_A_DIEZ + _COLUMNA_ONCE + _COLUMNAS_DOCE_A_VEINTITRES + _COLUMNAS_ANUALES
)


def _columnas() -> list[Columna]:
    return [Columna(titulo=titulo, tipo=tipo, sensible=sensible) for titulo, tipo, sensible in _COLUMNAS]  # type: ignore[arg-type]


@dataclass(slots=True)
class _ParametrosUniverso:
    """Adaptador a `universo_nomina.ParametrosUniverso` para poder reusar
    `banderas_de_no_normalizables` (§9 del diseño) desde un informe cuyo grano es el
    **ejercicio**, no un rango de fechas.

    Traduce `ejercicio` al rango `[1 de enero, 31 de diciembre]` de ese año, que es el mismo
    universo que la consulta principal acota con `YEAR(fecha_pago) = ejercicio`, y fija
    `tipo_nomina="AMBOS"` (B-05 no expone ese filtro: el acumulado anual es de todo lo cobrado).
    El RFC del emisor **no** viaja aquí: se le pasa `None` a `banderas_de_no_normalizables` para
    que tampoco filtre por emisor, igual que la consulta principal de este informe (ver el
    docstring del módulo sobre B-05.R3).

    **Por qué B-05 no podía seguir sin estas banderas.** Era el único informe del grupo que no
    las emitía: los otros cinco reportan con `SIN_NORMALIZAR`/`COMPLEMENTO_AUSENTE` el CFDI de
    nómina que el `join` con `nomina` deja fuera de la hoja `Datos`. En B-05 ese recibo
    desaparecía sin rastro y el acumulado del empleado salía corto por él, así que el patrón
    emitía la **constancia de percepciones** —el documento con el que el trabajador declara ante
    el SAT— con una quincena de menos, creyendo que estaba completa. El §9 del diseño lo exige
    para todo informe del grupo B, y en este es donde más cuesta callarlo."""

    fecha_desde: date
    fecha_hasta: date
    incluir_cancelados: bool
    tipo_nomina: Literal["O", "E", "AMBOS"] = "AMBOS"


def _a_decimal(valor: Decimal | float | None) -> Decimal:
    """`Numeric` puede llegar como `Decimal` o `float` según el atributo mapeado; nunca se
    opera en binario (mismo patrón que `identidades_b00._dec`)."""
    if valor is None:
        return _CERO
    return valor if isinstance(valor, Decimal) else Decimal(str(valor))


@dataclass(slots=True)
class _Acumulador:
    """Lo que se va sumando por `rfc_receptor` a lo largo de la iteración del universo ya
    resuelto (post B-05.R1). Un campo por columna agregada; los campos de identidad (fecha de
    inicio, nombre, etc.) se resuelven aparte porque no se suman."""

    uuids: set[str]
    dias_pagados: Decimal = _CERO
    total_percepciones: Decimal = _CERO
    total_gravado: Decimal = _CERO
    total_exento: Decimal = _CERO
    # B-05.R4. Se acumula siempre, y se **imprime** solo si el catálogo de marcas alcanzó para
    # clasificar todos los tipos presentes (`_Ordinario.calculable`); si no, la celda va vacía.
    gravado_ordinario: Decimal = _CERO
    total_separacion: Decimal = _CERO
    total_jubilacion: Decimal = _CERO
    isr_retenido: Decimal = _CERO
    subsidio_causado: Decimal = _CERO
    subsidio_entregado: Decimal = _CERO
    imss_retenido: Decimal = _CERO
    fondo_ahorro: Decimal = _CERO
    infonavit: Decimal = _CERO
    total_deducciones: Decimal = _CERO
    neto_pagado: Decimal = _CERO
    suma_sbc_dias: Decimal = _CERO
    suma_sdi_dias: Decimal = _CERO
    fecha_primer_pago: date | None = None
    fecha_ultimo_pago: date | None = None
    fecha_inicio_rel_laboral: date | None = None
    rfc_emisores: set[str] = field(default_factory=set)


@dataclass(frozen=True, slots=True)
class _Sumas:
    """Lo que devuelve `_sumas_por_comprobante`, en dos vistas del mismo agregado.

    `por_comprobante` es lo que consumen las columnas de totales; `gravado_por_tipo` es el
    mismo gravado desglosado por `tipo_percepcion`, que es lo que la columna 11 necesita para
    quedarse solo con los tipos ordinarios (B-05.R4). Sale del **mismo** `GROUP BY`, no de una
    segunda consulta.
    """

    por_comprobante: dict[int, dict[str, Decimal]]
    gravado_por_tipo: dict[int, dict[str, Decimal]]


async def _sumas_por_comprobante(db: AsyncSession, ids: list[int]) -> _Sumas:
    """Los agregados por comprobante que no vienen ya resueltos en el encabezado (gravado,
    exento, ISR, IMSS, fondo de ahorro, Infonavit, total de deducciones, subsidio) — una sola
    consulta agregada por tabla hija, para todo el universo del ejercicio (regla 11: cero
    N+1, nunca un `SELECT` por comprobante)."""
    sumas: dict[int, dict[str, Decimal]] = {}
    gravado_por_tipo: dict[int, dict[str, Decimal]] = {}
    if not ids:
        return _Sumas(sumas, gravado_por_tipo)

    # `GROUP BY (comprobante_id, tipo_percepcion)` y no solo por comprobante: el desglose por
    # tipo es lo único que distingue el gravado ordinario del que tiene régimen propio, y
    # agregarlo aquí evita una segunda pasada sobre `nomina_percepcion`. El total por
    # comprobante se reconstruye sumando en memoria, que es exacto (`Decimal`) y gratis.
    percepciones = await db.execute(
        select(
            NominaPercepcion.comprobante_id,
            NominaPercepcion.tipo_percepcion,
            func.sum(NominaPercepcion.importe_gravado).label("gravado"),
            func.sum(NominaPercepcion.importe_exento).label("exento"),
        )
        .where(NominaPercepcion.comprobante_id.in_(ids))
        .group_by(NominaPercepcion.comprobante_id, NominaPercepcion.tipo_percepcion)
    )
    for comprobante_id, tipo_percepcion, gravado, exento in percepciones:
        cid_percepcion = int(comprobante_id)
        tipo = str(tipo_percepcion)
        gravado_dec = _a_decimal(gravado)
        fila_sumas = sumas.setdefault(cid_percepcion, {})
        fila_sumas["gravado"] = fila_sumas.get("gravado", _CERO) + gravado_dec
        fila_sumas["exento"] = fila_sumas.get("exento", _CERO) + _a_decimal(exento)
        por_tipo = gravado_por_tipo.setdefault(cid_percepcion, {})
        por_tipo[tipo] = por_tipo.get(tipo, _CERO) + gravado_dec

    deducciones = await db.execute(
        select(
            NominaDeduccion.comprobante_id,
            NominaDeduccion.tipo_deduccion,
            func.sum(NominaDeduccion.importe).label("importe"),
        )
        .where(NominaDeduccion.comprobante_id.in_(ids))
        .group_by(NominaDeduccion.comprobante_id, NominaDeduccion.tipo_deduccion)
    )
    clave_a_campo = {
        _CLAVE_DEDUCCION_ISR: "isr",
        _CLAVE_DEDUCCION_IMSS: "imss",
        _CLAVE_DEDUCCION_FONDO_AHORRO: "fondo_ahorro",
        _CLAVE_DEDUCCION_INFONAVIT: "infonavit",
    }
    for comprobante_id, tipo_deduccion, importe in deducciones:
        cid = int(comprobante_id)
        fila = sumas.setdefault(cid, {})
        importe_dec = _a_decimal(importe)
        fila["deducciones"] = fila.get("deducciones", _CERO) + importe_dec
        campo = clave_a_campo.get(str(tipo_deduccion))
        if campo is not None:
            fila[campo] = fila.get(campo, _CERO) + importe_dec

    otros_pagos = await db.execute(
        select(
            NominaOtroPago.comprobante_id,
            func.sum(NominaOtroPago.subsidio_causado).label("subsidio_causado"),
            func.sum(NominaOtroPago.importe).label("subsidio_entregado"),
        )
        .where(NominaOtroPago.comprobante_id.in_(ids), NominaOtroPago.tipo_otro_pago == _CLAVE_OTRO_PAGO_SUBSIDIO)
        .group_by(NominaOtroPago.comprobante_id)
    )
    for comprobante_id, subsidio_causado, subsidio_entregado in otros_pagos:
        cid = int(comprobante_id)
        fila = sumas.setdefault(cid, {})
        fila["subsidio_causado"] = _a_decimal(subsidio_causado)
        fila["subsidio_entregado"] = _a_decimal(subsidio_entregado)

    return _Sumas(sumas, gravado_por_tipo)


# --------------------------------------------------------------------------------------
# B-05.R4: la columna 11, o la razón por la que no se pudo calcular
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Ordinario:
    """El gravado ordinario por comprobante, o el motivo por el que la columna 11 va vacía.

    `calculable` no es redundante con `por_comprobante`: un comprobante cuyos tipos son todos
    de régimen propio suma cero **de verdad**, y eso es distinto de "no se pudo clasificar".
    Sin la bandera explícita las dos situaciones darían el mismo diccionario.
    """

    calculable: bool
    por_comprobante: dict[int, Decimal]
    banderas: list[Bandera]


async def _gravado_ordinario(db: AsyncSession, gravado_por_tipo: dict[int, dict[str, Decimal]]) -> _Ordinario:
    """B-05.R4: `Σ importe_gravado` de los tipos con `es_ingreso_ordinario = true`.

    Dos consultas como máximo y ninguna por fila (regla 11): las marcas confirmadas se traen
    de una vez, y las propuestas solo cuando hace falta explicar un hueco.

    **Solo marcas confirmadas** (`marcas_de_percepcion`), y **todas o ninguna** para los tipos
    que aportan gravado: ver el bloque de B-05.R4 en el docstring del módulo para las tres
    decisiones y su argumento. Un tipo sin clasificar **que aporta gravado** no se puede "dejar
    fuera": si es ordinario y se omite, la base del ISR anual sale corta con apariencia de
    completa.
    """
    # **Solo los tipos que pueden mover la suma**, y no todos los que aparecen en el `GROUP BY`.
    # `Σ importe_gravado` de un tipo cuyo gravado es cero es cero, valga lo que valga su
    # `es_ingreso_ordinario`: exigir su marca condicionaría el cálculo a un valor que el cálculo
    # no usa. Es la regla general que el docstring de `b03_gravado_exento` dejó escrita tras tres
    # defectos del mismo tipo, y esta fue el cuarto.
    #
    # **Es exacto, no una heurística.** Los importes del CFDI son no negativos (`t_Importe` del
    # esquema del SAT), así que un agregado de cero significa que **todos** los renglones de ese
    # tipo son cero. Aquí se comprueba directamente esa forma —que ningún renglón agregado por
    # comprobante sea distinto de cero— para no depender del supuesto: si un negativo se colara
    # por un ETL roto, el tipo seguiría exigiendo su marca en vez de desaparecer por
    # compensación.
    #
    # El criterio es del **ejercicio completo**, no de cada comprobante: un tipo que aporta
    # gravado en julio necesita su marca confirmada aunque en junio venga en cero, o la fila de
    # junio calcularía con un tipo sin clasificar.
    tipos_presentes = {
        tipo
        for por_tipo in gravado_por_tipo.values()
        for tipo, gravado in por_tipo.items()
        if gravado != _CERO
    }
    marcas = await cfg.marcas_de_percepcion(db)
    faltantes = sorted(tipos_presentes - set(marcas))

    if faltantes:
        propuestas = await cfg.marcas_propuestas(db)
        sin_confirmar = [tipo for tipo in faltantes if tipo in propuestas]
        ausentes = [tipo for tipo in faltantes if tipo not in propuestas]
        banderas: list[Bandera] = []
        if sin_confirmar:
            detalle = "; ".join(
                f"{tipo} → ingreso ordinario: {'sí' if propuestas[tipo].es_ingreso_ordinario else 'no'}"
                for tipo in sin_confirmar
            )
            banderas.append(
                Bandera(
                    clave="MARCA_SIN_CONFIRMAR",
                    severidad="alta",
                    ambito="informe",
                    mensaje=(
                        "La columna «Gravado ordinario» salió vacía en todas las filas: hay marcas capturadas "
                        f"para {len(sin_confirmar)} de los tipos de percepción **con importe gravado** en el "
                        f"ejercicio pero nadie las ha confirmado, y un valor sin confirmar no calcula. Los tipos "
                        f"que solo traen importe exento no hacen falta: no pueden mover esta suma. La propuesta "
                        f"dice: {detalle}. "
                        "Revísalas y confírmalas en Configuración › Fiscal › Marcas de percepción; es un clic."
                    ),
                )
            )
        if ausentes:
            banderas.append(
                Bandera(
                    clave="FALTA_MARCA",
                    severidad="alta",
                    ambito="informe",
                    mensaje=(
                        "La columna «Gravado ordinario» salió vacía en todas las filas: no hay marca de "
                        f"`es_ingreso_ordinario` capturada para el/los tipo(s) de percepción {', '.join(ausentes)}, "
                        "que sí aportan importe gravado en el ejercicio (los que solo traen exento no hacen falta), "
                        "así que no se puede distinguir el ingreso que acumula al cálculo anual del ISR (art. 97 "
                        "LISR) del que tiene régimen propio (separación, art. 95; jubilación, art. 96). No se suma "
                        "solo lo conocido a propósito: daría una base anual corta con apariencia de completa. "
                        "Cárgalas con la semilla `config/fiscal/catalogo_percepcion.yaml` o captúralas en "
                        "Configuración › Fiscal › Marcas de percepción."
                    ),
                )
            )
        return _Ordinario(calculable=False, por_comprobante={}, banderas=banderas)

    ordinarios = {tipo for tipo in tipos_presentes if marcas[tipo].es_ingreso_ordinario}
    por_comprobante = {
        cid: sum((importe for tipo, importe in por_tipo.items() if tipo in ordinarios), _CERO)
        for cid, por_tipo in gravado_por_tipo.items()
    }
    return _Ordinario(calculable=True, por_comprobante=por_comprobante, banderas=[])


# --------------------------------------------------------------------------------------
# El bloque anual (Anexo I.4): la tarifa `EJERCICIO`, o la razón por la que el bloque va vacío
# --------------------------------------------------------------------------------------


async def _tarifa_del_ejercicio(
    db: AsyncSession, *, ejercicio: int, tipos_presentes: set[str]
) -> tuple[tuple[tarifa_isr.Renglon, ...], list[Bandera]]:
    """La tarifa `EJERCICIO` confirmada para el bloque anual, vía el mismo ayudante que consume
    B-09 (`app.informes.configuracion_isr.resolver`) — para que los dos informes digan
    exactamente lo mismo cuando falta, en vez de que cada uno redacte su propio aviso.

    `en_fecha` se fija al 31 de diciembre del `ejercicio`: la tarifa `EJERCICIO` se identifica por
    `(ejercicio, periodicidad)`, no por una fecha dentro del año (a diferencia de la UMA o el
    subsidio, que sí varían por vigencia), así que cualquier fecha del propio ejercicio serviría —
    el cierre es la más representativa. `tipos_presentes` no cambia lo que esta función devuelve
    (las marcas de percepción ya las resuelve `_gravado_ordinario` por su cuenta, con su propia
    bandera); se le pasa igual para que `ConfiguracionIsr.faltantes` quede completo si algún
    consumidor futuro lo necesita.

    **Corrección de la revisión final (I4): el aviso se cita, no se redacta aquí.** La primera
    versión de esta función escribía su propia frase, casi idéntica a
    `configuracion_isr.AVISO_SIN_TARIFA` — y el docstring del módulo `configuracion_isr` declara
    justo lo contrario: que los textos de qué falta viven ahí una sola vez y los informes los
    citan, para que dos informes digan lo mismo cuando falta lo mismo. Los dos ya habían
    divergido ("confírmala" vs. "confírmalo") y B-05 metía `` `EJERCICIO` `` —el nombre de un
    valor del enum `PeriodicidadTarifa`— en crudo dentro de un texto que una persona lee, que la
    restricción global prohíbe. Ahora se usa `AVISO_SIN_TARIFA` tal cual, con la etiqueta legible
    de `tarifa_isr.ETIQUETAS_TARIFA` en vez del nombre del enum; el párrafo que sigue solo agrega
    el contexto propio de B-05 (qué tres columnas quedan vacías), sin tocar el texto compartido.
    """
    config = await configuracion_isr.resolver(
        db,
        ejercicio=ejercicio,
        en_fecha=date(ejercicio, 12, 31),
        periodicidades=[PeriodicidadTarifa.EJERCICIO],
        tipos_presentes=tipos_presentes,
    )
    renglones = config.tarifas.get(PeriodicidadTarifa.EJERCICIO, ())
    if renglones:
        return renglones, []
    return (), [
        Bandera(
            clave="FALTA_TARIFA_EJERCICIO",
            severidad="alta",
            ambito="informe",
            mensaje=(
                "El bloque anual del art. 97 LISR («ISR anual teórico», «Subsidio anual "
                "acreditable» y «Diferencia a cargo / favor») salió vacío en todas las filas. "
                + configuracion_isr.AVISO_SIN_TARIFA.format(
                    etiquetas=tarifa_isr.ETIQUETAS_TARIFA[PeriodicidadTarifa.EJERCICIO], ejercicio=ejercicio
                )
            ),
        )
    ]


async def consultar(db: AsyncSession, empresa_id: int, p: Parametros) -> ResultadoInforme:
    rfc_empresa = await db.scalar(select(Empresa.rfc).where(Empresa.empresa_id == empresa_id))
    if rfc_empresa is None:
        return ResultadoInforme(columnas=_columnas(), aviso="La empresa no existe.")

    # Universo por ejercicio (YEAR(fecha_pago) = p.ejercicio), no por rango de fechas — y sin
    # filtrar por `rfc_emisor` (ver docstring del módulo: B-05.R3 depende de verlos todos).
    # Orden ascendente por fecha_pago: permite resolver "identidad del CFDI más reciente"
    # sobrescribiendo en el orden de iteración (mismo patrón que B-04).
    filas_universo = list(
        (
            await db.execute(
                select(Comprobante, Nomina, NominaReceptor, NominaTotales, ComprobanteDetalle)
                .join(Nomina, Nomina.comprobante_id == Comprobante.comprobante_id)
                .outerjoin(NominaReceptor, NominaReceptor.comprobante_id == Comprobante.comprobante_id)
                .outerjoin(NominaTotales, NominaTotales.comprobante_id == Comprobante.comprobante_id)
                .outerjoin(ComprobanteDetalle, ComprobanteDetalle.comprobante_id == Comprobante.comprobante_id)
                .where(
                    Comprobante.empresa_id == empresa_id,
                    Comprobante.tipo_comprobante == "N",
                    func.extract("year", Nomina.fecha_pago) == p.ejercicio,
                )
                .order_by(Comprobante.rfc_receptor, Nomina.fecha_pago, Comprobante.comprobante_id)
            )
        ).all()
    )

    # §9 del diseño: los CFDI de nómina que el `join` con `nomina` deja fuera de la hoja `Datos`
    # se reportan por bandera para que ninguno desaparezca en silencio. Se resuelve ANTES del
    # retorno temprano (mismo criterio que los otros cinco informes del grupo): si el ETL falló
    # en TODOS los CFDI del ejercicio, la hoja Datos sale vacía y estas banderas son el único
    # rastro de que había nómina que acumular. `rfc_empresa=None`: sin filtro de emisor, igual
    # que la consulta de arriba (ver `_ParametrosUniverso`).
    p_universo = _ParametrosUniverso(
        fecha_desde=date(p.ejercicio, 1, 1),
        fecha_hasta=date(p.ejercicio, 12, 31),
        incluir_cancelados=p.incluir_cancelados,
    )
    banderas_fuera = await universo_nomina.banderas_de_no_normalizables(db, empresa_id, None, p_universo)

    if not filas_universo:
        return ResultadoInforme(
            columnas=_columnas(),
            banderas=banderas_fuera,
            aviso=f"Sin CFDI de nómina en el ejercicio {p.ejercicio}.",
        )

    ids_universo = [fila[0].comprobante_id for fila in filas_universo]

    # B-05.R1: se resuelve ANTES de acumular nada, y se aplica siempre — no depende de
    # `incluir_cancelados` (ver docstring del módulo: protege justo el caso en el que el
    # estatus del sustituido todavía no refleja la cancelación).
    sustituidos = await universo_nomina.uuids_sustituidos(db, ids_universo)

    banderas: list[Bandera] = list(banderas_fuera)
    filas_resueltas: list[Any] = []
    for fila in filas_universo:
        comprobante = fila[0]
        if comprobante.uuid in sustituidos:
            banderas.append(
                Bandera(
                    clave=universo_nomina.CLAVE_CFDI_SUSTITUIDO,
                    severidad="baja",
                    ambito=f"uuid:{comprobante.uuid}",
                    mensaje=(
                        "Excluido del acumulado: otro CFDI del ejercicio lo declara sustituido "
                        "(`cfdi_relacionado.tipo_relacion='04'`). Su sustituto ya cuenta este ingreso "
                        "(B-05.R1); incluir ambos duplicaría el ingreso anual del empleado."
                    ),
                )
            )
            continue
        if comprobante.estatus == EstatusCfdi.CANCELADO and not p.incluir_cancelados:
            # `CANCELADO_EXCLUIDO`, no `COMPROBANTE_CANCELADO`: la clave compartida significa lo
            # contrario (ver el bloque "Semántica de las banderas de cancelación" en el docstring
            # del módulo). Aquí el CFDI **no** suma; cuando sí suma, la bandera la emite
            # `universo_nomina.banderas_de_estatus` más abajo con la clave compartida.
            banderas.append(
                Bandera(
                    clave="CANCELADO_EXCLUIDO",
                    severidad="alta",
                    ambito=f"uuid:{comprobante.uuid}",
                    mensaje=(
                        "El CFDI está cancelado ante el SAT y no fue sustituido por otro; se excluyó "
                        "del acumulado porque `incluir_cancelados=False`. No representa un pago vigente, "
                        "así que sus importes NO suman en este informe."
                    ),
                )
            )
            continue
        filas_resueltas.append(fila)

    if not filas_resueltas:
        return ResultadoInforme(
            columnas=_columnas(),
            banderas=banderas,
            aviso=f"Sin CFDI de nómina vigentes en el ejercicio {p.ejercicio} tras resolver sustituciones y cancelados.",
        )

    ids_resueltos = [fila[0].comprobante_id for fila in filas_resueltas]
    agregados = await _sumas_por_comprobante(db, ids_resueltos)
    sumas_por_cid = agregados.por_comprobante
    # B-05.R4: la columna 11 y, si no se pudo calcular, la bandera que dice qué falta. Se
    # resuelve una vez por corrida sobre los tipos que de verdad aparecen en el acumulado.
    ordinario = await _gravado_ordinario(db, agregados.gravado_por_tipo)
    banderas.extend(ordinario.banderas)
    # Bloque anual (Anexo I.4): la tarifa `EJERCICIO`, resuelta una vez para la corrida completa
    # (es la misma tarifa para todos los empleados), no por fila. Reusa el mismo conjunto de tipos
    # con gravado distinto de cero que `_gravado_ordinario` ya calculó — no otra pasada sobre
    # `gravado_por_tipo` con distinto criterio, regla 11.
    tipos_presentes_ejercicio = {
        tipo for por_tipo in agregados.gravado_por_tipo.values() for tipo, gravado in por_tipo.items() if gravado != _CERO
    }
    tarifa_ejercicio, banderas_tarifa_ejercicio = await _tarifa_del_ejercicio(
        db, ejercicio=p.ejercicio, tipos_presentes=tipos_presentes_ejercicio
    )
    banderas.extend(banderas_tarifa_ejercicio)
    # Identidades #4 y #5 de B-00 sobre lo que SÍ entra al acumulado: sin ellas, una fila de este
    # informe podía no cuadrar consigo misma en silencio ("Total percepciones" viene del
    # encabezado y "Total gravado"/"Total exento" de los nodos), y diferir de B-01/B-02 para el
    # mismo periodo sin aviso. Ver `universo_nomina.banderas_de_gravado_y_exento_descuadrados`.
    banderas.extend(await universo_nomina.banderas_de_gravado_y_exento_descuadrados(db, ids_resueltos))

    # `ESTATUS_NO_VERIFICADO` / `COMPROBANTE_CANCELADO` / `DATOS_DE_CORRIDA_ANTERIOR` sobre lo
    # que SÍ entra al acumulado: es la condición con la que el §11 del diseño acepta la
    # divergencia de R-T1 ("todo comprobante incluido que no sea vigente lleva bandera"), y
    # este informe no la cumplía. Sin ella, un cancelado con `incluir_cancelados=True` inflaba
    # el ingreso anual del empleado en su constancia de percepciones sin una sola advertencia,
    # y el acumulado mezclaba `vigente` con `no_verificado` sin distinguirlos. Recibe el
    # universo resuelto completo, no un comprobante: el colapso por umbral de
    # `ESTATUS_NO_VERIFICADO` es una decisión sobre el conjunto (ver su docstring), y en este
    # informe es donde más pesaba —4 filas de datos contra ~96 banderas de un ejercicio recién
    # descargado—.
    banderas.extend(universo_nomina.banderas_de_estatus(universo_nomina.comprobantes_y_detalles(filas_resueltas)))

    acumuladores: dict[str, _Acumulador] = {}
    identidad: dict[str, tuple[str | None, str | None, str | None, str | None, str | None]] = {}

    for comprobante, nomina, receptor, totales, detalle in filas_resueltas:
        rfc = comprobante.rfc_receptor
        acc = acumuladores.setdefault(rfc, _Acumulador(uuids=set()))
        sumas = sumas_por_cid.get(comprobante.comprobante_id, {})

        acc.uuids.add(comprobante.uuid)
        acc.rfc_emisores.add(comprobante.rfc_emisor)
        acc.dias_pagados += _a_decimal(nomina.num_dias_pagados)
        acc.total_percepciones += _a_decimal(nomina.total_percepciones)
        acc.total_gravado += sumas.get("gravado", _CERO)
        acc.total_exento += sumas.get("exento", _CERO)
        acc.gravado_ordinario += ordinario.por_comprobante.get(comprobante.comprobante_id, _CERO)
        acc.total_separacion += _a_decimal(totales.total_separacion_indemnizacion if totales else None)
        acc.total_jubilacion += _a_decimal(totales.total_jubilacion_pension_retiro if totales else None)
        acc.isr_retenido += sumas.get("isr", _CERO)
        acc.subsidio_causado += sumas.get("subsidio_causado", _CERO)
        acc.subsidio_entregado += sumas.get("subsidio_entregado", _CERO)
        acc.imss_retenido += sumas.get("imss", _CERO)
        acc.fondo_ahorro += sumas.get("fondo_ahorro", _CERO)
        acc.infonavit += sumas.get("infonavit", _CERO)
        acc.total_deducciones += sumas.get("deducciones", _CERO)
        acc.neto_pagado += _a_decimal(comprobante.total)

        sbc = _a_decimal(receptor.salario_base_cot_apor if receptor else None)
        sdi = _a_decimal(receptor.salario_diario_integrado if receptor else None)
        dias = _a_decimal(nomina.num_dias_pagados)
        acc.suma_sbc_dias += sbc * dias
        acc.suma_sdi_dias += sdi * dias

        if nomina.fecha_pago is not None:
            if acc.fecha_primer_pago is None or nomina.fecha_pago < acc.fecha_primer_pago:
                acc.fecha_primer_pago = nomina.fecha_pago
            if acc.fecha_ultimo_pago is None or nomina.fecha_pago >= acc.fecha_ultimo_pago:
                acc.fecha_ultimo_pago = nomina.fecha_pago

        fecha_inicio = receptor.fecha_inicio_rel_laboral if receptor else None
        if fecha_inicio is not None and (acc.fecha_inicio_rel_laboral is None or fecha_inicio < acc.fecha_inicio_rel_laboral):
            acc.fecha_inicio_rel_laboral = fecha_inicio

        # Identidad (columna 2): del CFDI más reciente del ejercicio. `filas_resueltas` viene
        # ordenado por `fecha_pago` ascendente (mismo `order_by` de la consulta principal), así
        # que sobrescribir en el orden de iteración deja la fotografía más reciente.
        identidad[rfc] = (
            receptor.curp if receptor else None,
            detalle.nombre_receptor if detalle else None,
            receptor.num_empleado if receptor else None,
            receptor.departamento if receptor else None,
            receptor.puesto if receptor else None,
        )

    # B-05.R3: multipatrón, sobre el acumulado ya resuelto (post R1).
    for rfc, acc in acumuladores.items():
        if len(acc.rfc_emisores) > 1:
            banderas.append(
                Bandera(
                    clave="MULTI_PATRON",
                    severidad="alta",
                    ambito=f"rfc:{rfc}",
                    mensaje=(
                        f"{rfc} tiene CFDI de nómina de {len(acc.rfc_emisores)} RFC emisores distintos "
                        f"en el ejercicio {p.ejercicio} ({', '.join(sorted(acc.rfc_emisores))}); el "
                        "cálculo anual es incompleto por construcción: este informe solo ve una parte "
                        "de sus ingresos."
                    ),
                )
            )

    filas: list[list[Any]] = []
    for rfc in sorted(acumuladores):
        acc = acumuladores[rfc]
        curp, nombre, num_empleado, departamento, puesto = identidad[rfc]

        otras_deducciones = acc.total_deducciones - acc.isr_retenido - acc.imss_retenido - acc.fondo_ahorro - acc.infonavit
        sbc_promedio = (acc.suma_sbc_dias / acc.dias_pagados) if acc.dias_pagados else _CERO
        sdi_promedio = (acc.suma_sdi_dias / acc.dias_pagados) if acc.dias_pagados else _CERO

        # Bloque anual (Anexo I.4): las tres columnas degradan JUNTAS (ver el comentario de
        # `_COLUMNAS_ANUALES`). Sin base ordinaria (B-05.R4) o sin tarifa `EJERCICIO` confirmada,
        # ISR anual no tiene con qué calcularse, y mostrar solo el subsidio acreditable sería un
        # fragmento del cálculo del art. 97, no el cálculo — así que el bloque completo va `None`.
        isr_anual: Decimal | None = None
        subsidio_acreditable: Decimal | None = None
        diferencia_ejercicio: Decimal | None = None
        if ordinario.calculable and tarifa_ejercicio:
            # `isr_de`, no `isr_del_periodo`: el Anexo I.4 aplica la tarifa del ejercicio
            # directamente sobre el acumulado anual, sin elevar ni prorratear — no hay "días
            # pagados" que prorratear en un cálculo que ya es del año completo, y
            # `tarifa_isr.DIAS_NOMINALES` ni siquiera tiene entrada para `EJERCICIO`.
            isr_anual = tarifa_isr.isr_de(tarifa_ejercicio, acc.gravado_ordinario)
            # El subsidio "acreditable" es `subsidio_causado` (columna 15), no
            # `subsidio_entregado` (columna 16) — la decisión del paso de lectura del plan, con
            # su razón completa en el comentario de `_COLUMNAS_ANUALES`.
            subsidio_acreditable = acc.subsidio_causado
            # Anexo I.4, paso 5: positiva es a cargo del trabajador, negativa es a favor.
            diferencia_ejercicio = isr_anual - subsidio_acreditable - acc.isr_retenido

        filas.append(
            [
                p.ejercicio,
                rfc,
                curp,
                nombre,
                num_empleado,
                departamento,
                puesto,
                acc.fecha_inicio_rel_laboral,
                acc.fecha_primer_pago,
                acc.fecha_ultimo_pago,
                len(acc.uuids),
                acc.dias_pagados,
                acc.total_percepciones,
                acc.total_gravado,
                acc.total_exento,
                # Columna 11: `None`, nunca cero, mientras el catálogo de marcas no alcance
                # para clasificar todos los tipos del ejercicio (B-05.R4).
                acc.gravado_ordinario if ordinario.calculable else None,
                acc.total_separacion,
                acc.total_jubilacion,
                acc.isr_retenido,
                acc.subsidio_causado,
                acc.subsidio_entregado,
                acc.imss_retenido,
                acc.fondo_ahorro,
                acc.infonavit,
                otras_deducciones,
                acc.neto_pagado,
                sbc_promedio,
                sdi_promedio,
                isr_anual,
                subsidio_acreditable,
                diferencia_ejercicio,
            ]
        )

    return ResultadoInforme(columnas=_columnas(), filas=filas, banderas=banderas)
