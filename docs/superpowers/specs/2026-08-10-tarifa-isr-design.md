# Diseño — Tarifa del ISR y subsidio al empleo como configuración administrable

**Fecha:** 2026-08-10
**Estado:** Aprobado, listo para plan de implementación
**Documento fuente:** `Hub_CFDI_docs/00-fuentes/especificacion-informes-cfdi.md` §12 (tablas de
configuración fiscal), Anexo I.1 (localización del renglón y pruebas de carga) y Anexo I.3 (subsidio)
**Antecedente:** `docs/superpowers/specs/2026-08-05-informes-cfdi-nomina-design.md` y las tres fases
de informes ya cerradas. Este diseño paga una de las tres deudas que la fase 3 dejó anotadas.

> **Advertencia de vigencia.** Las cifras que aparecen en este documento son **ilustrativas del
> formato**, no fuente de verdad. Ningún importe fiscal se codifica en `app/`: la regla §2.12 del
> documento fuente sigue vigente y un valor fiscal literal en un `.py` es un defecto Critical.

## 1. Problema

`tarifa_isr` es la única de las tablas de configuración fiscal del §12 que nunca se construyó. La razón
declarada en la fase 3 fue que el Anexo 8 de la RMF se publica en PDF, y el módulo
`app/services/sincronizacion_fiscal.py` tiene escrito en su docstring por qué no se raspan fuentes
oficiales: *"un valor fiscal viejo con cara de vigente es el modo de falla exacto que este subsistema
existe para impedir"*. Su tabla de fuentes clasifica la tarifa del ISR como **"Anexo 8 en PDF · fuera de
alcance"**.

Sin esa tabla quedan bloqueados el informe **B-09** (recálculo de ISR y subsidio) y las columnas 24-26 de
**B-05** (ISR anual teórico y diferencia).

## 2. Qué cambió respecto de esa decisión, verificado el 2026-08-10

Se descargó el documento oficial y se comprobó lo siguiente. No se asumió nada.

**El PDF del Anexo 8 tiene capa de texto y las tarifas salen limpias.** Fuente:
`https://www.sat.gob.mx/minisitio/NormatividadRMFyRGCE/documentos2026/rmf/anexos/Anexo-8-RMF-2026_DOF-28122025.pdf`
(19 páginas, 301 KB, DOF del 28-dic-2025). Extraído con `pypdfium2`, el rubro B.IV se lee así:

```
IV. Tarifa aplicable cuando hagan pagos que correspondan a un periodo de 15 días, correspondiente a 2026
a que se refieren los artículos 96 de la Ley del ISR y 175 de su Reglamento, así como la regla 3.12.2.
Límite inferior Límite superior Cuota fija  Por ciento ...
0.01            416.70          0.00        1.92
416.71          3,537.15        7.95        6.40
3,537.16        6,216.15        207.75      10.88
```

**Dos diferencias con el caso de la UMA, y son las que justifican revisar la decisión:**

1. **La tarifa se auto-verifica; un escalar no.** Las 6 pruebas del Anexo I.1 (continuidad de los
   límites, cuota fija del primer renglón en cero, tasas estrictamente crecientes, última tasa en
   `[0.30, 0.40]`) hacen que una extracción corrupta sea **detectable**. Una UMA mal raspada es un número
   plausible y no hay redundancia interna que la contradiga; una tarifa mal extraída rompe la aritmética
   de la tabla.
2. **El documento lo aporta una persona, no un raspador.** No hay una URL que el sistema visite sola y
   que un día devuelva otra cosa: hay un archivo que alguien sube deliberadamente, cuya huella se guarda.

**La doctrina del módulo de sincronización no se contradice, se acota:** sigue siendo cierto que no se
raspan páginas ni se derivan valores por fórmula, y sigue siendo el **calendario** —no la red— lo que
avisa de que hay que actualizar.

### 2.1 Dos hallazgos del documento que cambian el diseño del extractor

**Un Anexo 8 contiene tarifas de dos ejercicios distintos.** Su rubro C trae la tarifa anual del
**ejercicio 2025** (C.I, arts. 97 y 152, para la declaración que se presenta en 2026) y la del
**ejercicio 2026** (C.II). Si el ejercicio se tomara del nombre del archivo o del año de la RMF, la
anual de 2025 se guardaría como si fuera de 2026 — y **las 6 pruebas no lo detectarían**, porque ambas
tablas son internamente coherentes. **El ejercicio se lee del encabezado de cada tabla.**

**Los encabezados de nómina no nombran la periodicidad como la nombra el CFDI.** El rubro B.IV no dice
"quincenal", dice *"pagos que correspondan a un periodo de 15 días"*. El contenido real del documento es:

| Rubro | Encabezado (abreviado) | ¿Es de nómina? |
|---|---|---|
| A.I | Enajenación de inmuebles, art. 126 | **No** |
| B.I | En función de la cantidad de trabajo realizado, calculada en días — arts. 96 LISR y 175 Reglamento | Sí |
| B.II / B.III / B.IV | Periodo de 7 / 10 / 15 días — arts. 96 y 175 | Sí |
| B.V | Pagos provisionales mensuales — arts. 96 y 175 | Sí |
| B.VI y ss. | Tarifas mensuales del art. 106 (actividad empresarial, Título IV Cap. II Sec. I) | **No** |
| — | Art. 116 (arrendamiento) | **No** |
| C.I / C.II | Impuesto del ejercicio 2025 / 2026 — arts. 97 y 152 | Sí (anual) |

Todas tienen la misma forma de cuatro columnas. **Una tabla equivocada pasaría las 6 pruebas sin
problema**, así que la selección no puede depender de la forma.

## 3. Alcance

**Dentro:** las tablas `tarifa_isr` y `tarifa_isr_renglon`; el importador del Anexo 8; la corrección
manual de renglones; la confirmación por tarifa; las dos claves del subsidio al empleo en `param_fiscal`;
la alarma de calendario; la pantalla y los endpoints.

**Fuera, y por qué:**

| Fuera de alcance | Razón |
|---|---|
| El informe **B-09** | Tiene 5 reglas propias (periodos irregulares, art. 174 del Reglamento, tolerancias) y riesgo fiscal alto. La calidad de la carga es su prerrequisito y merece cerrarse por separado |
| Columnas 24-26 de **B-05** | Consumen esta tabla; se abordan con B-09 |
| `tabla_subsidio` (modelo histórico de rangos) | Solo hace falta para recalcular ejercicios anteriores a 2025. Para 2026 el modelo de monto fijo es el único aplicable |
| Descarga automática del PDF | Decisión explícita: alarma de calendario, la importación la dispara una persona |
| Cargar la UMA de 2025 | Decisión aparte del dueño del repo (ver §7.2) |

## 4. Esquema de datos

**Dos tablas, no una — divergencia declarada del §12 del documento fuente**, que describe `tarifa_isr`
como una tabla plana de renglones. Es la cuarta divergencia declarada de esta línea de trabajo, en la
misma línea que las tres de la fase 1.

```
tarifa_isr                              -- la tarifa como unidad
  ejercicio          INT            NOT NULL   ┐ PK
  periodicidad       ENUM(...)      NOT NULL   ┘
  origen             ENUM('IMPORTADA','MANUAL')  NOT NULL
  fuente             VARCHAR(500)   NOT NULL   -- nombre del documento oficial y su fecha de DOF
  documento_sha256   CHAR(64)       NULL       -- huella del PDF del que salió
  encabezado         VARCHAR(1000)  NOT NULL   -- el texto del documento, citado literal
  importado_en       DATETIME       NOT NULL
  confirmado_por     VARCHAR(128)   NULL       ┐ nulos hasta que una persona confirme
  confirmado_en      DATETIME       NULL       ┘

tarifa_isr_renglon
  ejercicio, periodicidad, renglon   PK, FK → tarifa_isr ON DELETE CASCADE
  limite_inferior    DECIMAL(14,2)  NOT NULL
  limite_superior    DECIMAL(14,2)  NULL       -- NULL = "En adelante"
  cuota_fija         DECIMAL(14,2)  NOT NULL
  tasa_excedente     DECIMAL(7,6)   NOT NULL   -- fracción decimal: 0.352000, nunca 35.00
```

**Por qué la cabecera aparte.** La procedencia y la confirmación son propiedades de *la tarifa*, no de
cada renglón. Con una tabla plana existiría el estado "renglón 3 confirmado, renglón 4 no", que no
significa nada, que ningún cálculo puede usar y que habría que excluir a mano en cada consulta. Con la
cabecera ese estado es **inexpresable**.

**`periodicidad` se nombra por lo que publica el Anexo, no por el catálogo del CFDI:** `DIARIA`,
`DIAS_7`, `DIAS_10`, `DIAS_15`, `MENSUAL`, `EJERCICIO`. Traducir de `c_PeriodicidadPago` a estos valores
es trabajo de B-09. Mezclarlos haría que la tabla mintiera sobre su fuente: el catálogo del SAT tiene
periodicidades (catorcenal, bimestral) para las que el Anexo **no publica tarifa**, y una columna que
las admite sugiere que existen.

**La confirmación es por tarifa completa y cada tarifa se confirma por separado.** Una nómina quincenal
necesita la de 15 días; obligar a revisar las otras seis para poder usarla convierte el acto de confirmar
en un trámite, que es como se gasta la puerta que el invariante protege.

Del Anexo 8 de 2026 salen **7 tarifas**: cinco del ejercicio 2026 (diaria, 7, 10, 15 días y mensual) más
la anual de 2026 y la anual de 2025.

Las dos tablas entran en **una migración de Alembic**, y el ciclo `upgrade` → `downgrade -1` → `upgrade`
se corre **de verdad** contra MySQL, no solo se escribe: es el procedimiento que la fase 3 ya exige para
cada columna nueva. El DDL se sincroniza con el doc 03.

## 5. El importador

Módulo **puro, sin acceso a BD**: `app/services/anexo8.py`. Recibe los bytes del PDF y devuelve tarifas
extraídas o lanza. Se prueba completo contra el PDF real sin tocar MySQL.

### 5.1 El ancla

Para cada tarifa se exige, en el mismo encabezado, la periodicidad **y** el fundamento legal:

| Tarifa | Ancla exigida |
|---|---|
| `DIARIA` | `cantidad de trabajo realizado` + `calculada en días` + `96 de la Ley del ISR` + `175 de su Reglamento` |
| `DIAS_7` / `DIAS_10` / `DIAS_15` | `periodo de N días` + `96 de la Ley del ISR` + `175 de su Reglamento` |
| `MENSUAL` | `pagos provisionales mensuales` + `96 de la Ley del ISR` + `175 de su Reglamento` |
| `EJERCICIO` | `impuesto correspondiente al ejercicio de <AAAA>` + `97 y 152 de la Ley del ISR` |

El texto se normaliza antes de comparar (espacios colapsados, saltos de línea eliminados, acentos
indiferentes) para no romperse por el salto de línea que el PDF mete a media frase. **Los números de
artículo se exigen literales.** Sin ancla no se lee ningún bloque de números: es lo que impide cargar la
tarifa de enajenación de inmuebles o la del art. 106 como si fueran de sueldos.

El encabezado que casó se **guarda citado literal** en `tarifa_isr.encabezado` y se muestra al confirmar.
La persona que confirma ve de qué tabla del documento salieron los renglones.

### 5.2 La conversión de escala

El Anexo publica el porcentaje (`21.36`) y la columna guarda la fracción (`0.213600`). **La división
entre 100 ocurre en un solo lugar de todo el sistema**, con la prueba 5 del Anexo I.1 encima. Es el error
contra el que advierte B-09.R2: una tasa en la escala equivocada subvalúa o sobrevalúa el ISR en dos
órdenes de magnitud, y en un sentido pasa desapercibida porque el resultado sigue siendo un número
pequeño y plausible.

### 5.3 Todo o nada por documento

Si cualquiera de las tarifas del PDF falla una prueba, **no se importa ninguna**, y el error dice qué
tarifa, qué prueba y con qué valores. Un Anexo 8 a medio cargar deja un estado que nadie pidió y que
después nadie sabe interpretar: no se distingue de un documento que legítimamente traía menos tablas.

### 5.4 Todo entra sin confirmar

Es el invariante central de la configuración fiscal, heredado sin cambios: **importar propone, solo una
persona activa.** `origen: IMPORTADA`, `confirmado_por` y `confirmado_en` nulos. Ninguna tarifa calcula
nada hasta que alguien la confirme, y el resolutor devuelve la ausencia de forma accionable en lugar de
un cero.

### 5.5 Importar sobre una tarifa que ya existe

El caso es real: una resolución posterior puede modificar un Anexo 8 a mitad de ejercicio.

| Estado de la tarifa existente | Qué hace la importación |
|---|---|
| Propuesta, renglones idénticos | Nada (idempotente); no toca la confirmación |
| Propuesta, renglones distintos | La reemplaza; sigue sin confirmar |
| **Confirmada**, renglones idénticos | Nada. La confirmación se conserva |
| **Confirmada**, renglones distintos | La reemplaza y **limpia la confirmación** — regla 2 de `guardar_param_fiscal` |
| Corregida a mano (`origen: MANUAL`) | Se detiene con `CorreccionManualProtegida`, sin pisar nada |

## 6. La corrección manual

Requisito del dueño del repo: **donde haya extracción automática debe poder corregirse a mano**, por si
la automática no queda bien. Además de resolver ese caso, es el plan B si un año el SAT reformula los
encabezados: se importa lo que se pueda y se corrige el resto, sin quedar bloqueado esperando un cambio
de código.

La condición para que la corrección no reintroduzca el error que el importador evita: **entra por la
misma puerta de validación.**

1. **Se re-validan las 6 pruebas sobre la tarifa completa**, no sobre el renglón editado. Cambiar un
   `limite_superior` rompe la continuidad con el renglón siguiente; validar solo lo editado dejaría pasar
   el hueco.
2. **La corrección limpia la confirmación.** Es la regla 2 de `guardar_param_fiscal`: un valor distinto
   es un valor nuevo y necesita que alguien lo mire otra vez.
3. **Reimportar el PDF no pisa una corrección manual en silencio.** Reutiliza el patrón
   `CorreccionManualProtegida` que ya existe para las semillas: la importación se detiene y dice qué
   renglón se corrigió a mano y qué dice el documento.
4. **La pantalla dice cuándo la tarifa ya no es el documento.** No solo con `origen = MANUAL` y la
   bitácora, sino como texto visible: *"2 renglones corregidos a mano; difiere del PDF importado"*. Una
   tarifa editada que se ve igual que una importada es una trampa.

Se pueden **agregar y quitar renglones**, no solo editar celdas: un ejercicio futuro puede traer un
número distinto de renglones, y sin eso la corrección serviría de poco. El `PUT` recibe la lista
completa de renglones, no un parche, para que no exista el estado intermedio de una tarifa con un
renglón menos.

## 7. Flujo, endpoints y pantalla

```
PDF oficial ──POST /importar──> extractor puro ──> N tarifas propuestas, sin confirmar
                                                        │
                      ┌─────────────────────────────────┤
                      ▼                                 ▼
            PUT (corrección manual)           POST /confirmar
            re-valida las 6 pruebas           exige la huella de lo revisado
            origen → MANUAL                   a partir de aquí, calcula
            limpia la confirmación
```

### 7.1 Endpoints

Todos de administrador, con el mismo guardián que los de configuración fiscal que ya existen. **Actualizan
el contrato `ApiClient` del doc 05 §9 en la misma sesión** (regla no negociable 10).

| Endpoint | Qué hace |
|---|---|
| `POST /v1/configuracion/tarifa-isr/importar` | Recibe el PDF como archivo (`UploadFile`, patrón de `efirma.py`). Devuelve las tarifas extraídas, sin confirmar |
| `GET /v1/configuracion/tarifa-isr` | Las tarifas con su estado, su encabezado citado y sus renglones |
| `PUT /v1/configuracion/tarifa-isr/{ejercicio}/{periodicidad}` | Corrección manual: lista completa de renglones |
| `POST /v1/configuracion/tarifa-isr/{ejercicio}/{periodicidad}/confirmar` | Confirma, exigiendo la huella de los renglones revisados |
| `DELETE /v1/configuracion/tarifa-isr/{ejercicio}/{periodicidad}` | Descarta una tarifa **sin confirmar**, para limpiar una importación equivocada |

**Solo archivo subido, no URL.** Descargar desde una URL que llega en la petición es un SSRF con pasos
extra (validar dominio, seguir redirecciones, límites de tamaño y tiempo); el archivo subido no tiene ese
problema y el trabajo para la persona es el mismo. La URL oficial se guarda en `fuente` como texto.

**El `DELETE` solo opera sobre tarifas sin confirmar.** Para retirar una confirmada hay que importar o
corregir encima, que deja rastro; un borrado que hace desaparecer una tarifa confirmada sin sustituto
convierte un cálculo que funcionaba en un cálculo ausente sin explicación.

La confirmación **exige la huella de los renglones que se revisaron** y rechaza si no coincide con lo
almacenado, con `ValorCambio`. Es el mismo mecanismo que `confirmar_param_fiscal` con su parámetro
`valor`: sin él, una propuesta que cambió entre la lectura y el clic se confirmaría a ciegas.

La huella es el **SHA-256 de la forma canónica** de los renglones: `renglon|limite_inferior|
limite_superior|cuota_fija|tasa_excedente` por línea, en orden de renglón, con los decimales normalizados
a la escala de la columna y `limite_superior` vacío cuando es nulo. Se normaliza la escala porque
`Decimal("0.35") == Decimal("0.350000")` numéricamente pero no como texto, y quien confirma no tiene que
adivinar con cuántos ceros devolvió la columna cada cifra — el mismo argumento que ya está escrito en
`confirmar_param_fiscal`. Se calcula con `huella_de_marcas` como precedente de estilo.

Todo escribe `bitacora` **en la misma transacción** (regla 8), con entidad
`tarifa_isr:{ejercicio}/{periodicidad}` y acciones `IMPORTAR`, `CORREGIR` (con el diff renglón por
renglón, valor anterior → nuevo) y `CONFIRMAR`.

### 7.2 Pantalla

En `/admin/config` → pestaña Fiscal, siguiendo los patrones que ya existen ahí (`ChipEstadoFiscal`,
`ConfiguracionFiscalPage`): botón de importar, una tarjeta por tarifa con su chip de estado y su
encabezado citado, y la rejilla de renglones editable. La tarjeta de la tarifa que aplica a la nómina
observada se señala como tal, derivado de la periodicidad que los CFDI timbran realmente
(`observados_de_empresa` ya resuelve ese tipo de pregunta).

## 8. Subsidio al empleo

Dos claves nuevas en la lista blanca `CLAVES_PARAM_FISCAL`: **`SUBSIDIO_FACTOR_UMA`** y
**`SUBSIDIO_TOPE_INGRESO`**. Usan el mecanismo que ya funciona: semilla con liga al decreto, un clic para
confirmar, vigencia por fecha, alarma el 1 de enero. No son una tabla: en el modelo vigente son dos
escalares.

**`MODELO_SUBSIDIO` no se crea — divergencia declarada del Anexo I.3.** El documento fuente pide
`param_fiscal('MODELO_SUBSIDIO')` con valores `'TABLA'` / `'MONTO_FIJO'`, pero `param_fiscal.valor` es
`DECIMAL(18,6)` y una etiqueta no cabe ahí. El modelo se **deriva** de qué configuración existe: hay
factor vigente y confirmado, entonces es monto fijo. Una etiqueta puede quedar desalineada de los datos
que describe; una derivación no puede. El día que alguien necesite el modelo histórico, la presencia de
`tabla_subsidio` lo resolverá por la misma vía.

**Dos tramos de vigencia**, porque el factor cambia junto con la UMA: enero de 2026 por un lado, del
1 de febrero de 2026 en adelante por otro. La semilla propone el factor (≈15.02 % de la UMA mensual
desde febrero) y el tope de ingreso (≈$11,492.66 mensuales) con su liga al decreto del DOF del
31-dic-2025. **Las cifras las valida el dueño del repo: son política fiscal, no código.** Como los tramos
no se cierran solos (regla 1 de `guardar_param_fiscal`), la semilla trae `vigencia_hasta` explícita en el
tramo de enero.

**Consecuencia declarada ahora, no descubierta después:** el subsidio de enero de 2026 no será
calculable, porque `UMA_MENSUAL` solo tiene un tramo que arranca el 1-feb-2026 y la UMA de 2025 no está
cargada. `valor_vigente` devolverá `None` y el faltante quedará visible como valor ausente, nunca como un
cero silencioso. Cargar la UMA de 2025 es una decisión aparte del dueño del repo y no entra aquí.

## 9. La alarma de calendario

`tarifa_isr` no es una clave de `param_fiscal`, así que entra en `alertas_de_vigencia` como **clave
sintética** `TARIFA_ISR`, igual que ya existen `CATALOGO_SAT_PERCEPCIONES`, `VERSION_SATCFDI` y
`SINCRONIZACION_BANXICO`. Fecha de actualización: **1 de enero**.

La regla: si el ejercicio en curso no tiene tarifa **confirmada** para las periodicidades que los CFDI de
nómina realmente timbran, se emite `AUSENTE` (no hay ninguna) o `SIN_CONFIRMAR` (hay propuesta esperando
un clic).

**Solo las periodicidades observadas, no las seis.** Alertar por la tarifa de 10 días que ninguna empresa
usa es exactamente la alarma permanentemente encendida que el docstring del módulo de sincronización ya
argumenta que no hay que construir: *"una alarma siempre encendida es una alarma que se aprende a
ignorar"*. Si no hay nómina normalizada todavía, no hay nada que recalcular y no se alerta.

## 10. Errores

Cada mensaje dice qué documento, qué tarifa, qué renglón y qué se esperaba. Un fallo al cargar es
barato; un cálculo incorrecto tres meses después no.

| Situación | Qué pasa |
|---|---|
| PDF sin capa de texto (escaneo) | Rechazo explícito: *"el PDF no tiene texto extraíble; ¿es un escaneo?"* |
| El archivo no es el Anexo 8 | Ancla no encontrada: dice qué encabezados esperaba y no importa nada |
| Una tarifa falla una prueba | No se importa **ninguna**; se nombra la tarifa, la prueba y los valores |
| Corrección que rompe la continuidad | Rechazo con el hueco exacto: *"`limite_inferior` del renglón 4 debía ser 6,216.16 y llegó 6,216.00"* |
| Reimportar sobre una corrección manual | `CorreccionManualProtegida`, sin pisar nada |
| Confirmar algo que cambió mientras se revisaba | `ValorCambio`, con la huella de renglones |
| Tarifa sin renglones, o con uno solo | Rechazo: una tarifa de un renglón es una tabla que se extrajo a medias |

## 11. Pruebas

**Las 6 obligatorias del Anexo I.1** (límite inferior del primer renglón `0.01`;
`limite_inferior(n) = limite_superior(n-1) + 0.01`; `cuota_fija(1) = 0`; `tasa_excedente` estrictamente
creciente; última tasa en `[0.30, 0.40]`; tasa almacenada como fracción) se corren **tanto al importar
como al corregir a mano**.

**Cuatro pruebas nuevas que salen de lo verificado en §2.1:**

7. El ejercicio de cada tarifa sale de su encabezado. Contra el PDF real: la anual del rubro C.I debe
   quedar con `ejercicio = 2025`, no 2026.
8. Del PDF real salen exactamente 7 tarifas, y **ninguna** es la de enajenación de inmuebles ni las de
   los arts. 106 / 116.
9. Reimportar el mismo PDF es idempotente: misma huella, mismos renglones, no toca la confirmación.
10. **Por mutación:** si se quita el `/ 100`, la prueba 5 **debe fallar**. Se exige mirar el conteo de
    selección de `-k`, no el código de salida — un `-k` que no selecciona nada sale con código 5 y se ve
    igual que una prueba muerta (cuatro trampas documentadas en `tests/test_cli_configuracion.py`).

**El PDF oficial se versiona como fixture** (`tests/fixtures/anexo8-2026.pdf`, 301 KB). La regla no
negociable 12 lo permite: es un documento público del DOF, sin datos de terceros ni personales. Sin él,
la prueba del extractor no es reproducible. `pypdfium2` pasa de dependencia de desarrollo a dependencia
de la aplicación, porque el importador la usa en tiempo de ejecución.

**Semilla limpia donde el mundo real tiene datos sucios** es la clase de defecto que se repitió cuatro
veces en la fase 3: las pruebas del extractor se escriben contra el **PDF real completo**, no contra un
fragmento recortado a mano con solo las tablas buenas.

## 12. Verificación en vivo (criterio de cierre)

Contra el sistema corriendo y la BD real, no contra dobles:

1. Importar el PDF real del Anexo 8 de 2026 y ver **7 tarifas propuestas** con sus ejercicios correctos
   (la anual de C.I como 2025).
2. Comprobar que la tarifa de 15 días coincide renglón por renglón con el documento, y que las tasas
   están guardadas como fracción.
3. Corregir un renglón a mano y ver que la confirmación se limpia y que la pantalla avisa que la tarifa
   difiere del PDF.
4. Reimportar el mismo PDF y ver que la corrección manual **no** se pisa.
5. Confirmar la tarifa de 15 días y comprobar que el resolutor por fecha la devuelve, y que antes de
   confirmarla devolvía ausencia.
6. Comprobar que la alerta `TARIFA_ISR` pasa de `AUSENTE`/`SIN_CONFIRMAR` a apagada.
7. Sembrar y confirmar las dos claves del subsidio; comprobar que enero de 2026 queda declarado como no
   calculable por falta de UMA de enero.
8. `.venv/bin/mypy --strict app` limpio; `config/fiscal/README.md` actualizado con el estado real de lo
   confirmado y lo que falta.

## 13. Riesgos

| Riesgo | Mitigación |
|---|---|
| El SAT reformula los encabezados en un ejercicio futuro | La importación falla en seco sin cargar nada (ruidoso, no silencioso), y la corrección manual permite avanzar sin esperar un cambio de código |
| Una corrección manual introduce un error de transcripción | Las 6 pruebas se re-corren completas; la confirmación se limpia; la bitácora guarda el valor anterior |
| Se importa el Anexo 8 de otro año por error | Las tarifas entran con el ejercicio de su propio encabezado, sin confirmar, y se pueden descartar con el `DELETE`; nada calcula mientras no se confirmen |
| Un PDF enorme o malicioso subido al endpoint | Límites en la puerta, antes de pasarlo al extractor: **10 MB** y **100 páginas** (el Anexo 8 real pesa 301 KB y trae 19). Se rechaza con un mensaje que dice el límite, no con un 500 |

## 14. Divergencias declaradas del documento fuente

1. **`tarifa_isr` se parte en cabecera y renglones** (§4). El §12 la describe plana; la confirmación y la
   procedencia son de la tarifa, no del renglón.
2. **`MODELO_SUBSIDIO` no existe como clave de `param_fiscal`** (§8). El Anexo I.3 lo pide, pero la
   columna `valor` es decimal y el modelo se deriva de la configuración presente.
3. **`periodicidad` usa los nombres del Anexo 8, no `c_PeriodicidadPago`** (§4). La traducción es trabajo
   de B-09.
