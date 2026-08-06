# Diseño — Informes derivados de CFDI (capa normalizada + Grupo B nómina)

**Fecha:** 2026-08-05
**Estado:** Aprobado, listo para plan de implementación
**Documento fuente:** `Hub_CFDI_docs/00-fuentes/especificacion-informes-cfdi.md` (v1.0, 32 informes en 5 grupos)

## 1. Problema y objetivo

Hub CFDI descarga, resguarda y valida CFDI, pero no produce **informes derivados**. Hoy la única salida
tabular es `exportar_excel` (`app/worker/tasks.py:350`), que emite 10 columnas del índice local: UUID,
folio, RFC, total, fecha, tipo, estatus. Nada del contenido del XML — ni conceptos, ni impuestos por
tasa, ni el complemento de nómina — llega nunca a un reporte.

La razón es estructural: `comprobantes` es un **índice delgado** de 12 columnas. Todo el contenido rico
vive únicamente en los XML en disco (`comprobante.xml_path`), que se leen al vuelo para generar el PDF y
el "Detalle del CFDI", pero cuyos datos jamás se persisten de forma consultable.

**Objetivo:** construir la capa de datos normalizada que el §2 del documento fuente especifica, y sobre
ella los nueve informes viables del Grupo B (nómina), entregados como libros de Excel descargables.

## 2. Estado actual verificado (2026-08-05, contra la BD y los XML reales)

Todo lo de esta sección se comprobó en vivo, no se asumió.

**Datos en la BD** (empresa 11 = `CHL960913IX9` = CENTRO HUMANO DE LIDERAZGO):

| Tipo | Vigentes | No verificados | Con XML en disco |
|---|---|---|---|
| `I` Ingreso | 180 | 59 | 239 / 239 |
| `P` Pago | 69 | 27 | 96 / 96 |
| `N` Nómina | 8 | 0 | 8 / 8 |
| `E` Egreso | 7 | 1 | 8 / 8 |

**Los 8 CFDI de nómina:** 4 empleados (núms. 035, 038, 039, 040), 2 quincenas (16–30 jun y 1–15 jul de
2026), todas `tipo_nomina='O'`, periodicidad `04` quincenal, 15 días pagados, 12 conceptos distintos.
La empresa es el patrón, así que son **emitidos**.

**Dos advertencias del documento fuente se cumplen literalmente en estos datos:**

- **Caso espejo del fondo de ahorro (R-T10):** existe como percepción `P/005/031` "Fondo ahorro empresa"
  *y* como deducciones `D/004/067` "Fondo de ahorro Empresa" y `D/004/177` "Fondo de Ahorro Empleado".
  Sumar naturalezas triplicaría el importe.
- **Colisión de claves entre naturalezas (B-02.R3):** "Ajuste al neto" aparece como `D/004/099` y como
  `O/999/099`. Sin prefijo de naturaleza en la etiqueta, las dos columnas colapsan en una.

**Capacidad de parseo:** `satcfdi==26.7.4` extrae todo lo que el §2 requiere. Verificado sobre XML reales
de los cuatro tipos: conceptos con impuestos **por línea** (base, tipo de factor, tasa, importe),
complemento de Pagos 2.0 completo (`Pago`, `DoctoRelacionado`, `Totales`) y complemento de Nómina 1.2
completo (`Percepciones`, `Deducciones`, `OtrosPagos`, `Receptor` con CURP, NSS, SBC, SDI, antigüedad).

**Catálogos SAT (§3):** vienen incluidos en satcfdi como objetos `Code`, con clave y descripción
(`Code('002','IVA')`, `Code('001','Sueldos, Salarios Rayas y Jornales')`). No hay que cargar tablas de
catálogo para las 27 entradas del §3. Sí hacen falta las **marcas derivadas** del §3.1, que el catálogo
oficial no tiene.

**Infraestructura reutilizable, ya funcionando:**

- Tareas asíncronas Celery (worker + beat en docker compose) con `GET /v1/tareas/{id}` leyendo el estado
  del backend de Redis (`app/api/v1/tareas.py:26`).
- Enlaces firmados HMAC-SHA256 con expiración (`app/services/enlaces.py:37`) y
  `GET /v1/descargas-archivo/{token}` que sirve el archivo acotado a `storage_root`.
- `openpyxl` (modo `write_only`), `xlsxwriter` y `weasyprint` en `requirements.txt`.
- Bitácora de auditoría (`app/services/bitacora.py`).
- Patrón de export por lotes de 5 000 filas contra el repositorio.

**Huecos de datos identificados (no bloquean el Grupo B, se anotan para los grupos A/C):**

- El WS de estatus del SAT devuelve `EsCancelable` y `EstatusCancelacion`, pero
  `app/sat_hub/sat_facade.py:199` conserva solo `Estado`.
- La metadata del SAT se parsea al vuelo (`app/services/metadata_export.py`) y no se persiste.
- De la lista 69-B se guardan solo `rfc + situacion` vigente (`sat_facade.py:277` lee las columnas 1 y 3
  del CSV), sin las fechas de publicación que exige la regla A-01.R4 (evaluar EFOS *a la fecha del
  comprobante*, no a la de hoy).

## 3. Decisiones tomadas (brainstorming)

| Decisión | Elección |
|---|---|
| Grupo prioritario | **Grupo B — nómina** |
| Alcance de informes | **Los nueve viables:** B-01 a B-08 y B-10 |
| Arquitectura de datos | **Tablas normalizadas + ETL** (enfoque A del §2), **modelo completo**, no solo nómina |
| Medio de entrega | **Excel descargable** vía tarea en segundo plano + enlace firmado |
| Llave de las tablas nuevas | **`comprobante_id`** (PK local), no `uuid` — ver §4.1 |
| Encabezado extendido | **Tabla 1:1 aparte**, sin tocar `comprobantes` — ver §4.2 |
| Aritmética | **`Decimal` de punta a punta**, `DECIMAL(18,6)`, redondeo único al presentar |
| Enmascaramiento de datos personales | **Transversal a todos los informes de nómina**, default activado — ver §8 |
| B-09 (recálculo de ISR) | **Fuera de alcance** — requiere `tarifa_isr` por ejercicio y periodicidad; riesgo fiscal alto |
| B-11 (contra plantilla de RH) | **Fuera de alcance** — requiere una fuente externa que no existe en el sistema |

## 4. Adaptaciones al documento fuente

El documento fue escrito sin conocer este esquema. Estas tres divergencias son deliberadas.

### 4.1 La llave es `comprobante_id`, no `uuid`

El §2 asume `cfdi_comprobante.uuid` como PK global, con un campo `rfc_contribuyente` como discriminador
de propiedad y la regla R-T5 para deduplicar consolidados.

Nuestro esquema declara `UNIQUE(empresa_id, uuid)` a propósito (`app/models/comprobante.py:20`): el mismo
CFDI puede aparecer legítimamente en dos empresas, una como emitido y otra como recibido.

**Todas las tablas nuevas cuelgan de `comprobante_id`.** Esto resuelve R-T5 por construcción y conserva el
aislamiento por empresa que ya tiene el sistema, sin necesidad de `rfc_contribuyente`. El campo `origen`
(EMITIDO/RECIBIDO) del §2.1 se sigue derivando por comparación contra `empresas.rfc`, como ya hace
`app/worker/tasks.py:442`.

### 4.2 El encabezado extendido va en una tabla 1:1, no en columnas nuevas de `comprobantes`

`comprobantes` es la tabla del listado de la UI, con cuatro índices para paginación y filtros. Agregarle
~18 columnas de reporte la engrosaría sin beneficio para su uso real.

`comprobante_detalle` (1:1 por `comprobante_id`) aísla lo nuevo: un fallo del ETL no puede dañar el índice
del que depende la aplicación.

### 4.3 Enmascaramiento transversal, no solo en B-10

El documento pide `enmascarar_datos_personales` únicamente en B-10.R2. Es insuficiente: el bloque
"Empleado" de B-01, B-02, B-03, B-04 y B-05 también incluye CURP y NSS. Ver §8.

## 5. Esquema de datos

15 tablas nuevas (4 de comprobante, 4 de pagos, 7 de nómina). Reglas duras que aplican a todas:

- **Claves de catálogo como texto** (`VARCHAR`), nunca entero: `001` ≠ `1`. Convertirlas destruye los ceros
  a la izquierda y rompe todo cruce con catálogo.
- **`DECIMAL(18,6)` para importes, `DECIMAL(9,6)` para tasas.** `Decimal` de Python de punta a punta; nunca
  `float`. El redondeo a 2 decimales ocurre una sola vez, al escribir la celda (R-T4).
- Todas llevan FK a `comprobantes.comprobante_id` con `ON DELETE CASCADE`.
- `mysql_charset=utf8mb4`, como el resto del esquema.

### 5.1 Encabezado y cuerpo del comprobante

| Tabla | Cardinalidad | Contenido |
|---|---|---|
| `comprobante_detalle` | 1:1 | `version`, `serie`, `fecha_timbrado`, `forma_pago`, `metodo_pago`, `moneda`, `tipo_cambio`, `subtotal`, `descuento`, `lugar_expedicion`, `exportacion`, `regimen_emisor`, `nombre_receptor`, `domicilio_receptor`, `regimen_receptor`, `uso_cfdi`, `no_certificado`, `no_certificado_sat`, `xml_hash`, `normalizado_at`, `etl_version`, `error_normalizacion` |
| `cfdi_concepto` | 1:N | `num_linea`, `clave_prod_serv`, `no_identificacion`, `cantidad`, `clave_unidad`, `unidad`, `descripcion`, `valor_unitario`, `importe`, `descuento`, `objeto_imp` |
| `cfdi_concepto_impuesto` | 1:N de concepto | `naturaleza` (`T`/`R`), `impuesto`, `tipo_factor`, `tasa_o_cuota`, `base`, `importe`; `comprobante_id` desnormalizado para agregaciones directas |
| `cfdi_relacionado` | 1:N | `tipo_relacion`, `uuid_relacionado`; PK compuesta con `comprobante_id` |

`xml_hash` (SHA-256 del XML) vive en `comprobante_detalle` y es la base de la idempotencia (§6).

### 5.2 Complemento de Pagos 2.0

`pago` (`num_pago`, `fecha_pago`, `forma_de_pago_p`, `moneda_p`, `tipo_cambio_p`, `monto`,
`num_operacion`, cuentas ordenante y beneficiaria), `pago_docto` (`id_documento`, `serie`, `folio`,
`moneda_dr`, `equivalencia_dr`, `num_parcialidad`, `imp_saldo_ant`, `imp_pagado`, `imp_saldo_insoluto`,
`objeto_imp_dr`), `pago_docto_impuesto` (misma forma que `cfdi_concepto_impuesto`) y `pago_totales`
(1:1, los 11 campos del nodo `Totales`).

### 5.3 Complemento de Nómina 1.2

| Tabla | Cardinalidad | Notas |
|---|---|---|
| `nomina` | 1:1 | `version_nomina`, `tipo_nomina`, `fecha_pago`, `fecha_inicial_pago`, `fecha_final_pago`, `num_dias_pagados`, totales de percepciones/deducciones/otros pagos, `registro_patronal`, `rfc_patron_origen`, `origen_recurso`, `monto_recurso_propio` |
| `nomina_receptor` | 1:1 | `curp`, `nss`, `fecha_inicio_rel_laboral`, `antiguedad` (texto ISO 8601), `tipo_contrato`, `sindicalizado`, `tipo_jornada`, `tipo_regimen`, `num_empleado`, `departamento`, `puesto`, `riesgo_puesto`, `periodicidad_pago`, `banco`, `cuenta_bancaria`, `salario_base_cot_apor`, `salario_diario_integrado`, `clave_ent_fed` |
| `nomina_percepcion` | 1:N | `tipo_percepcion`, `clave`, `concepto`, `importe_gravado`, `importe_exento` |
| `nomina_deduccion` | 1:N | `tipo_deduccion`, `clave`, `concepto`, `importe` |
| `nomina_otro_pago` | 1:N | `tipo_otro_pago`, `clave`, `concepto`, `importe`, `subsidio_causado`, `saldo_a_favor`, `anio`, `remanente_sal_fav` |
| `nomina_incapacidad` | 1:N | `dias_incapacidad`, `tipo_incapacidad`, `importe_monetario` |
| `nomina_totales` | 1:1 | Fusiona `nomina_percepciones_tot` y `nomina_deducciones_tot` del §2.8/2.9: `total_sueldos`, `total_separacion_indemnizacion`, `total_jubilacion_pension_retiro`, `total_gravado`, `total_exento`, `total_otras_deducciones`, `total_impuestos_retenidos` |

Los nodos hijos condicionales `nomina_acciones_titulos` y `nomina_horas_extra` del §2.8 quedan fuera de
esta fase: dependen de percepciones tipo `045` y `019` que no existen en los datos actuales, y solo
alimentan B-12, que está fuera de alcance. Se anotan como extensión trivial cuando aparezcan.

**Índices:** `nomina(comprobante_id)`, `nomina(fecha_pago)`, `nomina_receptor(curp)`,
`nomina_receptor(nss)`, `nomina_percepcion(comprobante_id, tipo_percepcion, clave)` y sus equivalentes en
deducciones y otros pagos — son los agrupamientos de B-02 y B-07.

**`@Antigüedad` se almacena como texto y nunca se usa para calcular.** Viene como duración ISO 8601
(`P589W`) y el atributo lleva diéresis en el nombre. Cualquier antigüedad se deriva de
`fecha_inicio_rel_laboral`.

## 6. El ETL

### 6.1 Estructura

- `app/services/normalizacion.py` — **función pura**: `bytes` del XML → árbol de dataclasses. Sin BD, sin
  I/O, sin sesión. Es lo único que toca `satcfdi` y es lo que se prueba a fondo.
- `app/repositories/normalizacion.py` — persiste las dataclasses. Borra los hijos por `comprobante_id` e
  inserta de nuevo, todo en una transacción.

### 6.2 Idempotencia

Se calcula el SHA-256 del XML. Si `comprobante_detalle.xml_hash` coincide **y** `etl_version` es la
vigente, se omite el comprobante. Un cambio de `etl_version` (constante en el módulo) fuerza el
reproceso de todo sin borrar nada a mano.

**Los fallos también se persisten.** Cuando el parseo falla, la fila de `comprobante_detalle` se crea de
todos modos con el `xml_hash`, el `etl_version` y el mensaje en `error_normalizacion`. Sin esto, el
pre-vuelo del §6.3 reintentaría el mismo XML corrupto en cada corrida de cada informe, para siempre. Un
cambio de `etl_version` sí lo vuelve a intentar, que es el comportamiento correcto: significa que el ETL
cambió y quizá ya sabe leerlo.

### 6.3 Tres disparadores

1. **En la descarga:** al resguardar cada CFDI nuevo (`app/services/resguardo.py`), se normaliza. Lo nuevo
   entra listo.
2. **Tarea de reproceso:** `normalizar_comprobantes(empresa_id, alcance)` con alcance `pendientes` |
   `todos` | lista de ids, por lotes, para los 351 XML que ya están en disco.
3. **Pre-vuelo del informe:** antes de generar, se normaliza lo que falte en el rango solicitado. Así
   nunca sale un informe vacío porque el ETL no corrió; el sistema se autocura.

## 7. Motor de informes

### 7.1 Contrato

`app/informes/` con un registro (`registro.py`). Cada informe es un módulo que expone:

```python
CLAVE = "B-02"
NOMBRE = "Nómina agrupada por conceptos del patrón"
GRUPO = "B"
DESCRIPCION = "..."          # el "Propósito" de la ficha del documento fuente

class Parametros(BaseModel):  # pydantic: la API valida y el frontend genera el formulario
    ...                       # desde el JSON Schema

async def consultar(db, empresa_id: int, p: Parametros) -> ResultadoInforme
def escribir(wb, resultado: ResultadoInforme) -> None    # o el escritor por defecto
```

`ResultadoInforme` lleva las filas, las columnas (fijas y dinámicas, en orden determinista), las banderas
y los metadatos del diccionario. Agregar un informe es un archivo y una línea en el registro; el frontend
no se modifica.

### 7.2 Endpoints

| Endpoint | Rol | Devuelve |
|---|---|---|
| `GET /v1/informes` | CONSULTA | Catálogo: clave, nombre, grupo, descripción y JSON Schema de parámetros |
| `POST /v1/empresas/{empresa_id}/informes/{clave}` | CONSULTA (ver §8) | `202` + `tarea_id` |

El resultado se recoge con `GET /v1/tareas/{tarea_id}`, que ya construye el enlace firmado a partir del
`{"ruta": ...}` que devuelve la tarea. **No se agrega infraestructura de entrega.**

## 8. Datos personales y permisos

Parámetro `enmascarar_datos_personales`, default `true`, aplicable a **todos** los informes de nómina que
emitan CURP, NSS o cuenta bancaria (B-01, B-02, B-03, B-04, B-05, B-10). Enmascarar sustituye por `****`
conservando los últimos 4 caracteres.

- Generar **enmascarado**: rol `CONSULTA`.
- Generar **sin enmascarar**: rol `OPERADOR` o superior, y se registra en bitácora con usuario, fecha,
  clave del informe y los **parámetros validados** (con sus defaults resueltos).

**Un informe sin datos personales NO declara el parámetro** (revisión final de la fase 2). B-07 lo
declaraba con la nota "sin efecto en este informe" y ninguna columna `sensible=True`. No era cosmético: el
endpoint gatea por el **parámetro**, no por si hay algo que enmascarar, así que desmarcar la casilla en B-07
devolvía `403` a un `CONSULTA` y, a un `OPERADOR`, escribía en bitácora un asiento de divulgación de datos
personales que nunca ocurrió — peor que una casilla inútil. Sin el parámetro, el endpoint lee el default con
`getattr(..., True)` y el motor con `.get(..., True)`, así que nada cambia. Los informes que sí lo declaran
son los que emiten CURP, NSS o cuenta bancaria.

**El enmascaramiento no se puede burlar por el texto de una celda no sensible** (revisión final de la fase 2,
el hallazgo más grave del conjunto). Marcar la columna es condición necesaria pero no suficiente: B-10
interpolaba la CURP y el NSS crudos en el mensaje de su columna "Descripción del hallazgo" —que no es
sensible y no puede serlo sin volverse ilegible—, así que 6 de 7 filas salían con el dato completo con el
default `enmascarar_datos_personales=true`. **Regla: ningún mensaje de hallazgo ni de bandera interpola un
dato que alguna columna del mismo informe declara sensible.** El dato ya viaja en su columna; el mensaje
describe el problema. La regla se audita desde fuera con
`app.informes.validadores.fugas_de_datos_personales_en_libro`, **una sola implementación** que usan sus dos
llamadores: la suite (`tests/test_informe_b10.py`) y `scripts/verificar_informes.py`. Antes cada uno tenía
su copia, y cada copia un hueco distinto; los dos están cerrados (fase 2, cierre de mejoras — no había fuga
viva por ninguno, es blindaje de regresión):

- **Por patrón y por valor, contra el universo completo.** La búsqueda estructural
  (`dato_personal_en_texto`) no puede ver una CURP **mal formada** interpolada en un mensaje, y la
  comparación por valor era **por fila**: contra la CURP y el NSS de *ese* empleado. Una CURP mal formada
  **de otro** empleado se escapaba de las dos redes a la vez. Ahora se recoge el conjunto de CURP y NSS de
  todos los empleados del universo una vez y se busca cualquiera de ellos en cualquier celda de texto (con
  un piso de `LONGITUD_MINIMA_VALOR_PERSONAL` = 8 caracteres para que un valor basura de dos caracteres no
  convierta la red en ruido).
- **Las cuatro hojas, no solo `Datos`.** `Banderas`, `Parámetros` y `Diccionario` viajan en el **mismo
  archivo**, así que un mensaje de bandera que interpolara un dato personal salía igual de la empresa. Es
  donde el riesgo es más real: los mensajes de bandera son texto libre, y el incidente de B-10 fue
  exactamente así.

**Un reporte de fuga no puede reproducir el dato que denuncia** (ronda 1 de arreglos). Auditar la fila 1
como una fila cualquiera es correcto, pero el nombre de columna con el que se reporta una fuga sale de esa
misma fila 1: cuando la celda que dispara la fuga **es** el encabezado, el campo `columna` acababa siendo el
dato personal. Y los títulos dinámicos de B-01/B-02 se construyen con el `@Concepto` del XML —texto libre no
controlado, la misma clase de contenido que causó el incidente de B-10—, así que un título contaminado
también se publicaría al reportar una fuga de otra fila. Dos capas:

1. `_nombre_de_columna` certifica la etiqueta con el **mismo** detector que encuentra las fugas
   (`_datos_personales_en_celda`, una sola función para que no puedan divergir) y cae a `columna N` si no es
   segura. Es la garantía principal.
2. `FugaDatoPersonal.__post_init__` levanta `ValueError` si algo con estructura de CURP/NSS llega a cualquier
   campo por cualquier otra ruta de construcción. **Falla, no censura:** recortar el valor en silencio
   dejaría la red aparentando funcionar.
3. **`__repr__` y `descripcion` pasan por `_publicable`** (ronda 2). Un dataclass con `slots=True` puebla sus
   campos **antes** de correr `__post_init__`, así que cuando la capa 2 lanza, `self` ya tiene el valor
   crudo — y el formateador de tracebacks de pytest imprime los argumentos del marco donde se levantó la
   excepción. El mensaje nunca llevaba el valor; **el `repr` del objeto sí**, y lo imprimía otra herramienta:
   `self = FugaDatoPersonal(..., columna='VECJ...', ...)`. El incidente original por otro mecanismo. Se usa
   `repr=False` + `__repr__` propio y no `repr=False` a secas porque el `repr` se usa en el camino sano (las
   premisas `assert fugas == []`), y `<FugaDatoPersonal object at 0x...>` perdería el diagnóstico entero.

**La afirmación exacta.** No es "la excepción nombra el campo, nunca el valor" —cierto del mensaje, falso de
lo que CI imprimiría—, sino: *ninguna forma de convertir el objeto en texto reproduce el valor*, y con el
`--tb=auto` por defecto (el de CI: `pyproject.toml` no fija ninguno) el objeto es lo único que se renderiza
del marco donde salta el cable trampa, así que la salida real queda limpia. **Residual declarado:** con
`--tb=long` o `--showlocals` —acciones deliberadas de quien depura, no el default— pytest renderiza también
los marcos que *recibieron* el valor: el `__init__` que genera `@dataclass` y el del propio auditor, donde
`valores_por_tipo` trae las CURP y los NSS de todo el universo. Son locales de marcos de CPython, fuera del
alcance de cualquier método del objeto, y la segunda exposición existiría igual aunque el cable trampa no
lanzara nunca. Por eso la capa 1 es la garantía y las otras dos son la red.

`excel.HOJAS_CON_ENCABEZADO` (`Datos`, `Banderas`, `Diccionario`) es la fuente de verdad de qué hoja tiene
fila de títulos, y vive en el módulo que **escribe** el libro porque es un hecho de su estructura.
`Parámetros` no la tiene —su fila 1 ya es contenido— así que sus fugas se reportan por **posición**; antes se
reportaban como si la columna se llamara "B-05 · Acumulado anual", un diagnóstico que manda a mirar donde no
es.

**El script sí maneja CURP y NSS reales, y nunca los imprime.** El razonamiento anterior —que
`scripts/verificar_informes.py` no debía tocar datos personales reales, y por eso solo buscaba por patrón—
se descartó: el script ya lee la BD real (calcula las identidades de B-00 sobre los datos de nómina, que
incluyen al receptor), compararlos en memoria sin imprimirlos es seguro, y es la única forma de atrapar una
CURP mal formada. **Requisito duro:** cuando encuentra una fuga reporta la hoja, la fila, la columna y el
tipo de dato, **nunca el valor** — igual que `dato_personal_en_texto`, que devuelve el tipo y no el dato.

**Falla cerrado.** La decisión de enmascarar la toma el motor (`app.informes.excel.escribir_libro`) leyendo
`ContextoInforme.parametros`, y lo hace con `get("enmascarar_datos_personales", True)`: si la clave no está
—un llamador que no pase por el endpoint HTTP— se enmascara igual. Además la tarea de generación pasa al
contexto los parámetros ya validados, nunca el dict crudo del cliente, así que el default declarado en el
JSON Schema y el efectivo en el libro son el mismo por construcción.

## 9. Manejo de errores

Ningún fallo individual aborta una corrida.

| Situación | Tratamiento |
|---|---|
| XML corrupto o ilegible | Se marca el comprobante; bandera `SIN_NORMALIZAR` en el informe |
| XML resguardado que ya no está en disco | Igual (es pérdida de datos); no lanza excepción |
| Comprobante sin `xml_path` (nunca se descargó) | **Se omite**: no hay nada que normalizar y eso no es un error |
| CFDI tipo `N` sin complemento de nómina | Bandera `COMPLEMENTO_AUSENTE` |
| CFDI ya normalizado cuyo reproceso falló | Se conservan los hijos de la última corrida buena y la fila entra al informe con bandera `DATOS_DE_CORRIDA_ANTERIOR` |
| Dos normalizaciones concurrentes del mismo comprobante | El perdedor (deadlock 1213 / `IntegrityError`) re-verifica `necesita_normalizar` y cuenta como omitido: nunca se marca error sobre un comprobante sano. **Residual conocido**, ver abajo |
| Informe sin filas | Libro con hoja de Parámetros y aviso, no un `500` |
| Volumen grande | Consulta por lotes, como el export actual; el pre-vuelo se acota con los `TIPOS_COMPROBANTE` que declara el informe |

**Cómo llegan `SIN_NORMALIZAR` y `COMPLEMENTO_AUSENTE` al informe.** La consulta del universo
de todo informe del grupo B hace `join` con `nomina`, así que un tipo `N` sin fila ahí no puede
aparecer en la hoja `Datos` — no hay datos que poner. Cada informe emite estas banderas con una
**segunda consulta** sobre los `N` de la empresa que no pueden entrar, acotada por
`Comprobante.fecha_emision` (los comprobantes sin normalizar no tienen `nomina.fecha_pago` con
la que acotarlos). Las banderas se resuelven **antes** del retorno por informe vacío: un libro
sin filas y sin banderas es indistinguible de un periodo en el que no hubo nómina.

**Los seis informes la llaman, incluido B-05** (revisión final de la fase 2). B-05 era el único que no lo
hacía, y es el que menos podía permitírselo: un CFDI de nómina del ejercicio cuyo XML el ETL no pudo leer
desaparecía sin rastro, el acumulado del empleado salía corto por ese recibo y el patrón emitía la
**constancia de percepciones** —el documento con el que el trabajador declara ante el SAT— con una quincena
de menos, creyendo que estaba completa. Su universo es por ejercicio y sin filtro de `rfc_emisor` (B-05.R3
depende de ver todos los patrones), así que usa un adaptador que traduce el ejercicio a
`[1 de enero, 31 de diciembre]` y pasa `rfc_empresa=None` para que la consulta de banderas tampoco filtre
por emisor: un `N` roto de un segundo patrón es exactamente el caso que ese informe existe para señalar.

**La ventana de esas banderas lleva 31 días de margen a cada lado, y no es opcional.** La fecha
de timbrado no coincide con la de pago: en la BD real de la empresa 11 los 8 CFDI de nómina
están timbrados **al día siguiente** del pago (pago 2026-06-30 → emisión 2026-07-01), y la RMF
(regla 2.7.5.3) admite hasta 11 días hábiles de desfase, además del timbrado anticipado. Sin
margen, un informe de `[2026-06-01, 2026-06-30]` con una nómina pagada el 30 de junio, timbrada
el 1 de julio y con el ETL fallido salía con 0 filas y 0 banderas. El criterio para dimensionar
el margen es asimétrico a propósito: **una bandera de más se ve y se descarta; una de menos no
se ve nunca.** Lo único que la ventana debe seguir acotando es que un `N` roto de un ejercicio
ajeno no aparezca en el informe de este mes, porque una hoja `Banderas` con decenas de entradas
irrelevantes deja de leerse.

**`ESTATUS_NO_VERIFICADO` se colapsa por umbral, y solo esa clave** (fase 2, cierre de mejoras). La
verificación de estatus contra el SAT es asíncrona por diseño, así que `no_verificado` es el estado
**normal** de un ejercicio recién descargado, no un caso de borde: con la nómina real de la empresa (4
empleados × 24 quincenas) una bandera por comprobante son ~96 filas idénticas en la hoja `Banderas` de cada
uno de los cinco informes que llaman a `universo_nomina.banderas_de_estatus` — en B-05 serían 96 banderas
para **4 filas** de datos. El daño no es cosmético: **entierra** las banderas de severidad alta de la misma
hoja (`SIN_NORMALIZAR`, `TOTALES_DESCUADRADOS`, `MULTI_PATRON`, `TIPO_FUERA_DE_CATALOGO`), que son los
hallazgos accionables. Es el mismo criterio del párrafo anterior aplicado al revés: allá el margen se elige
holgado porque el riesgo es perder un aviso; aquí el umbral se elige bajo porque el riesgo es *sepultar* los
avisos que sí importan.

- Con **menos de `UMBRAL_COLAPSO_NO_VERIFICADO` = 15** comprobantes afectados: una bandera por UUID, como
  antes. Retrocompatible — el `ambito` por UUID es la columna por la que se filtra la hoja `Banderas` y la
  aseveran las pruebas de B-02, B-04, B-05 y B-07, así que reemplazarla *siempre* por un resumen sería un
  cambio del contrato de salida, no una mejora.
- A partir de 15: **una sola** bandera con `ambito="informe"`, cuyo mensaje lleva el conteo de comprobantes
  afectados, por qué importa (la verificación es asíncrona; conviene correrla y regenerar el informe antes
  de conciliar) y una **muestra** de 3 UUID declarada como muestra, con el total.
- El umbral es 15 porque el piso lo fija el caso cotidiano —un mes del histórico real son 8 comprobantes, y
  ese caso debe seguir trazable por UUID, con margen para crecer— y el techo la legibilidad: con ~15 filas
  de la misma clave media, una `SIN_NORMALIZAR` todavía se ve en la primera pantalla de la hoja.
- **`COMPROBANTE_CANCELADO` y `DATOS_DE_CORRIDA_ANTERIOR` no se colapsan.** El primero exige que el usuario
  pida `incluir_cancelados=True` explícitamente, así que su volumen es una decisión suya y no una
  consecuencia del calendario de la verificación asíncrona. El segundo exige un fallo del ETL sobre ese CFDI
  concreto: es raro, y cada caso importa individualmente porque su mensaje trae el `error_normalizacion`
  propio — colapsarlos perdería información, no ruido.

El colapso es una decisión sobre el **conjunto**, así que `banderas_de_estatus` recibe el universo completo
en vez de un comprobante. Al no existir ya un punto de entrada por comprobante, ningún informe puede emitir
esta clave con un grano distinto al de los otros cuatro: aplica a los cinco por construcción.

**Residual conocido de la protección contra carreras (deuda anotada).** La protección consiste
en re-consultar `necesita_normalizar` al detectar un fallo de concurrencia, y eso solo funciona
si el proceso ganador ya commiteó. Con `IntegrityError` (1062) el orden es forzoso — la clave
duplicada solo existe si commiteó — así que la protección es completa. Con un deadlock (1213)
no: InnoDB aborta a la víctima **mientras** el ganador sigue con su transacción abierta, y en
ese orden la re-consulta no ve nada y sí se marca el error sobre un comprobante sano. **Lo
robusto sería reintentar la normalización una vez** en lugar de consultar el estado de
inmediato: el reintento espera de forma natural a que el ganador termine. Se acepta dejarlo
documentado porque el residual ya no produce un dato falso silencioso: con
`DATOS_DE_CORRIDA_ANTERIOR`, el comprobante marcado por error sigue entrando al informe con sus
importes y llega al patrón como un aviso visible.

## 10. Estructura del libro de Excel

Cuatro hojas en todo informe:

1. **Datos** — el informe. Fila de encabezado congelada, formatos numéricos por tipo de columna.
2. **Parámetros** — usuario, fecha y hora (UTC naive, misma convención que la bitácora), **filtros
   efectivos** (los parámetros ya validados, con sus defaults resueltos, no el dict crudo del cliente),
   `etl_version`, número de filas. Sin esta hoja un Excel circulando por correo no se puede reproducir ni
   auditar después.
3. **Banderas** — una fila por hallazgo: clave, severidad, ámbito (UUID o empleado), mensaje. Filtrable, y
   no se pierde al copiar celdas, como sí ocurre con el coloreado.
4. **Diccionario** — en B-02 y en B-01 con conjunto reducido:
   `etiqueta → naturaleza / tipo / descripción SAT / clave del patrón / concepto canónico / descripciones
   alternas / núm. de comprobantes / importe del periodo`.

**Etiquetas de columnas dinámicas (R-T8):** `tipo ¦ clave ¦ concepto`, con separador U+00A6 y **prefijo de
naturaleza**. El prefijo no es opcional: sin él, `D/004/099` y `O/999/099` ("Ajuste al neto" en los datos
reales de la empresa 11) colapsan en una sola columna. Los nulos se emiten como **cero, no vacío** (R-T7).

## 11. Informes en alcance

**Universo del Grupo B:** comprobantes `tipo_comprobante='N'` **emitidos** por la empresa (la empresa es el
patrón, así que `rfc_emisor = empresa.rfc`), con complemento de Nómina 1.2. El periodo se determina por
`nomina.fecha_pago` (R-T6), salvo B-04 que asigna por `fecha_final_pago` (B-04, fase 2).

**R-T1, divergencia declarada (decisión del dueño del repo, revisión final de la fase 1).** El criterio
original era "por defecto solo `VIGENTE`". Lo implementado excluye únicamente los `CANCELADO`: los
`no_verificado` **sí entran**. Razón: la verificación de estatus contra el SAT es un proceso asíncrono e
independiente de la descarga, así que exigir `VIGENTE` borraría del informe toda la nómina cuyo estatus
todavía no se ha consultado. Una fila que desaparece en silencio es peor que una fila presente con su
estatus a la vista — y en este dominio una fila que falta es un error fiscal, no un detalle de producto.
Para que la inclusión sea explícita, todo comprobante incluido que no sea `vigente` lleva bandera:
`ESTATUS_NO_VERIFICADO` (media) o `COMPROBANTE_CANCELADO` (alta, solo alcanzable con
`incluir_cancelados=True`).

**Esa condición la cumplen cinco de los seis informes desde la revisión final de la fase 2** (B-01, B-02,
B-04, B-05 y B-07; la sexta, B-10, es la excepción declarada del final de este párrafo). Antes solo B-01 y B-02
llamaban a `universo_nomina.banderas_de_estatus`; B-04, B-05 y B-07 la omitían **sin declararlo** y ninguno
tiene columna de estatus en `Datos` (B-01/B-02 sí: "Estado SAT"), así que no había forma de saberlo: una
celda de la matriz de B-04 llena por un CFDI cancelado ante el SAT decía "esa quincena está cubierta" sin
marca, un hueco de B-07 podía quedar tapado por un CFDI que el SAT ya no reconoce (`DESCUENTO_INTERRUMPIDO`
no se disparaba) y el acumulado de B-05 mezclaba `vigente` con `no_verificado` sin distinguirlos. Y no es un
borde: la verificación contra el SAT es asíncrona por diseño, así que `no_verificado` es el estado **normal**
de un ejercicio recién descargado. **B-10 es la única excepción y la declara y argumenta en su docstring**:
su grano es el hallazgo, no el comprobante.

**`COMPROBANTE_CANCELADO` significa lo mismo en todos: "se incluyó y sus importes suman".** B-05 la usaba
para lo contrario ("se excluyó del acumulado"), así que quien filtrara la hoja `Banderas` por esa clave en
B-02 y en B-05 del mismo periodo sacaba conclusiones opuestas del mismo dato; y con `incluir_cancelados=true`
metía el cancelado al acumulado **sin emitir ninguna bandera**, inflando el ingreso anual del empleado en su
constancia sin advertencia. El caso propio de B-05 ("cancelado no sustituido, excluido del acumulado") lleva
ahora su propia clave, `CANCELADO_EXCLUIDO` (alta).

| Clave | Nombre | Fase | Completitud |
|---|---|---|---|
| B-02 | Nómina agrupada por conceptos del patrón | 1 | Completo |
| B-01 | Nómina agrupada por catálogo SAT | 2 | Completo, con `solo_tipos_con_movimiento` |
| B-04 | Matriz empleado × periodo | 2 | Completo |
| B-05 | Acumulado anual por empleado | 2 | Columnas 1–23; 24–26 (ISR anual teórico) requieren `tarifa_isr` |
| B-07 | Cartera de préstamos y descuentos recurrentes | 2 | Columnas 1–9 y 14; 10–13 requieren capturar el monto original |
| B-10 | Validación de datos del receptor | 2 | 21 de 23 reglas; solo `SBC_SOBRE_TOPE` (UMA) y `SBC_BAJO_MINIMO` (salario mínimo) esperan a `param_fiscal` en la fase 3. `DATOS_CAMBIANTES` ya no cubre la CURP: ese caso lo reporta `RFC_DUPLICADO` y las dos claves generaban dos filas para un solo defecto (revisión final de la fase 2) |
| B-03 | Desglose gravado / exento por percepción | 3 | Completo con las tablas de configuración |
| B-06 | Costo de nómina por centro de costo | 3 | Sin la columna 15 (costo patronal): no es derivable del CFDI |
| B-08 | Provisión de pasivo laboral | 3 | Estimación con base en CFDI, no cálculo actuarial (B-08.R3) |

Reglas de cálculo que se implementan con especial cuidado porque el documento las señala como los defectos
típicos de las herramientas comerciales:

- **B-02.R1** — concepto repetido con el mismo `(tipo, clave)` en un CFDI: la celda es la **suma**, no el
  último valor. Sobrescribir subvalúa la nómina en silencio.
- **B-02.R3** — prefijo de naturaleza en la etiqueta (arriba).
- **R-T9** — identidad de concepto por `(tipo, clave)`, nunca por descripción; la descripción canónica es
  la más frecuente, con bandera `CONCEPTO_INCONSISTENTE` si hay varias.
- **R-T10** — no se consolidan los conceptos espejo; el informe refleja el XML y el Diccionario marca el
  grupo espejo. Aplica al fondo de ahorro de la empresa 11.
- **B-04.R2** — hueco intermedio es omisión de timbrado; hueco al final es baja probable. No se marcan
  igual.

**Las identidades #4 y #5 de B-00 (gravado y exento) se cotejan al generar cualquier informe**, no solo en
las pruebas y en el script (revisión final de la fase 2:
`universo_nomina.banderas_de_gravado_y_exento_descuadrados`, que emite `TOTALES_DESCUADRADOS`). "Total
gravado" y "Total exento" significan dos cosas distintas a propósito: B-01/B-02 reportan lo que **declara el
encabezado** (`nomina_totales`), B-05 lo **recalcula de los nodos** porque una constancia de percepciones no
debe heredar sin cotejar un descuadre del encabezado. Las dos lecturas son correctas para su propósito y no
se cambian, pero con un CFDI descuadrado daban cifras distintas del mismo concepto para el mismo periodo sin
que ningún informe avisara; y dentro de una misma fila de B-05 "Total percepciones" (encabezado) no cuadraba
con gravado + exento (nodos) en silencio.

**Un tipo fuera del catálogo no desaparece de B-01 (`TIPO_FUERA_DE_CATALOGO`, alta).** B-01.R1 genera las
columnas iterando **el catálogo** y filtrando por lo observado, nunca iterando lo observado: un tipo que la
versión pinada de `satcfdi` no trae (el SAT publica uno nuevo, un PAC timbra con uno desconocido) no tiene
columna —ni con `solo_tipos_con_movimiento`, porque el filtro no cambia la fuente de la iteración— y su
importe desaparecía de la hoja. `TOTALES_DESCUADRADOS` no lo atrapaba, porque las sumas de la fila recorren
todos los nodos observados, incluido el invisible, y cuadran contra el encabezado; el único síntoma era que
las más de 150 columnas no sumaban el "Total percepciones" de su propia fila, en el informe cuyo propósito es
alimentar pólizas contables. Basta 1 CFDI para que ocurra.

**"Nombre empleado" es `comprobante_detalle.nombre_receptor` en los cinco informes que declaran la columna**
(B-01, B-02, B-05, B-07 y B-10, que la llama "Nombre"; B-04 no la declara: su matriz se identifica por RFC).
B-01 y B-02 usaban
`comprobante.razon_social_emisor` —el nombre del **patrón**— con la justificación de que "no hay campo de
razón social del receptor en el modelo", falsa desde la fase 2. El resultado era un papel de trabajo fiscal
con el nombre de la empresa repetido en todas las filas de esa columna, y nada lo detectaba porque el helper
de pruebas nunca insertaba una fila de `comprobante_detalle` (con `detalle is None` el campo correcto y el
equivocado daban los dos `None`). Corregido en la revisión final de la fase 2, junto con el helper.

**B-04 y B-07 NO ubican el mismo CFDI en el mismo periodo, y hay que documentarlo en los dos.** B-04 asigna
por `fecha_final_pago` (el fin del periodo devengado define si esa quincena tuvo nómina); B-07 por
`fecha_pago` (para la continuidad de un préstamo importa en qué periodo apareció el descuento). Cada elección
es correcta para su propósito y ninguna se cambia, pero con el patrón real de la empresa (pago y timbrado
desfasados del cierre) **las etiquetas no coinciden**: un `PERIODO_FALTANTE` de `2026-06 Q2` en B-04 se lee
como hueco de `2026-07 Q1` en B-07 — que además habla de comparar contra "la secuencia teórica de B-04". Al
cruzar los dos informes hay que traducir la etiqueta.

## 12. Tablas de configuración (fase 3)

| Tabla | Para | Contenido |
|---|---|---|
| `param_fiscal` | B-03, B-10 (2 reglas de SBC) | `ejercicio`, `clave`, `valor`, `vigencia_desde`, `vigencia_hasta` — UMA diaria, salario mínimo |
| `catalogo_percepcion_marca` | B-03, B-05, B-08 | Las marcas del §3.1: `es_ingreso_ordinario`, `base_exencion`, `factor_exencion`, `integra_sbc`, `es_provisionable` |
| `map_departamento` | B-06 | `departamento_texto → centro_costo` (el campo del XML es texto libre) |
| `map_concepto_provision` | B-08 | `(tipo, clave) → categoría` (aguinaldo, vacaciones, prima) |
| `tabla_vacaciones` | B-08 | `años_antiguedad → días` |

**Ningún importe fiscal se codifica en el programa** (regla explícita del §2.12). Las semillas las valida
David antes de cargarse: son política fiscal, no código.

## 13. Pruebas

Convención del proyecto: TDD, `mypy --strict app` limpio, MySQL real vía testcontainers.

**Privacidad en los fixtures.** Los 8 XML reales contienen CURP, NSS y cuentas bancarias de 4 personas
reales. **No se commitean.** Los fixtures son sintéticos y cubren exactamente lo que el documento advierte:

- Concepto repetido con el mismo `(tipo, clave)` → debe sumarse.
- Colisión de clave entre naturalezas (`D/004/099` vs `O/999/099`).
- Espejo del fondo de ahorro en tres naturalezas.
- `@Antigüedad` con diéresis en el nombre del atributo.
- Nodos opcionales ausentes (sin `OtrosPagos`, sin `Incapacidades`).
- Percepción con importe exento > 0 y tipo que no admite exención.

**Las 9 identidades de B-00** (`total_percepciones = Σ percepciones`,
`subtotal = total_percepciones + total_otros_pagos`, `descuento = total_deducciones`,
`total = subtotal − descuento`, etc.) son la comprobación más fuerte que existe sobre el ETL y la única que
detecta que lee mal un nodo. Su implementación es **una sola** (`app/informes/identidades_b00.py`) con dos
llamadores:

- `tests/test_identidades_b00.py`, sobre XML sintéticos que pasan por el ETL completo. Está dentro de
  `testpaths`, así que cada corrida de la suite las mantiene verdes. Incluye un caso negativo que altera un
  total ya normalizado y exige que la verificación lo señale.
  **`verificar()` devuelve además cuántos cotejos ejecutó**, y las pruebas lo aseveran. Sin ese conteo,
  "cero fallas" no distingue "todo cuadra" de "no se comprobó nada": un cotejo que no corre no puede
  fallar, así que borrar ocho de las nueve identidades dejaría la suite verde. Un atributo que el XML no
  trae no se compara y no cuenta — la prueba de ese caso asevera su número exacto, uno menos.
- `scripts/verificar_informes.py` (renombrado desde `verificar_fase1.py` en la fase 2, Task 8, al
  extenderlo a los seis informes del catálogo), **en vivo contra los datos reales, sin que nada entre
  a git**: los mismos cotejos sobre los CFDI de la empresa 11 tras el reproceso.

**El mismo remedio del conteo se aplica a las 21 validaciones de B-10** (revisión final de la fase 2), por la
misma razón y con la misma evidencia empírica: el revisor borró **siete** validaciones del módulo y
`pytest tests/test_informe_b10.py tests/test_informes_validadores.py -q` siguió dando 26 passed. Diez de las
21 no tenían ninguna prueba que verificara que disparan, y lo único que las "cubría" era
`test_datos_correctos_no_generan_hallazgos`, que asevera `filas == []` — el patrón exacto donde borrar una
comprobación no rompe la prueba, **la hace pasar más fácil**. Dos medidas complementarias:

- `consultar()` emite `VALIDACIONES_EJECUTADAS` (baja, ámbito `informe`) con **cuántas validaciones se
  ejecutaron de verdad** en la corrida, y una prueba asevera ese número contra las constantes del módulo
  (`VALIDACIONES_POR_EMPLEADO_COMPLETO` + `VALIDACIONES_DE_CONJUNTO` + `VALIDACIONES_ENTRE_PERIODOS_POR_RFC`).
  Una validación omitida por falta de dato no cuenta, igual que un atributo ausente en `identidades_b00`. Esto
  protege contra **borrados**.
- Una prueba por validación que verifica que **dispara** con el dato malo correspondiente, y en varios casos
  su gemela negativa (dato bueno → no dispara). Esto protege contra una **condición invertida**, que el conteo
  no ve.

Los informes se prueban comparando valores de celda, no bytes del archivo.

## 14. Fases

**Fase 1 — Cimientos y el informe emblemático.** Las 15 tablas con su migración Alembic,
`normalizacion.py`, el escritor idempotente, los tres disparadores, la tarea de reproceso, el motor de
informes con las cuatro hojas, y **B-02** completo con su Diccionario. Cierre: reprocesar los 351 XML
reales y validar las identidades de B-00.

**Fase 2 — Informes sin configuración.** B-01, B-04, B-05, B-07, B-10, más el enmascaramiento transversal
y su registro en bitácora.

**Fase 3 — Informes con configuración fiscal.** Las cinco tablas del §12 y sus cargadores, que habilitan
B-03 completo, B-06 y B-08.

**Frontend (fases 1–3, incremental):** sección nueva "Informes" con el catálogo agrupado por grupo y
formularios generados desde `GET /v1/informes`. El patrón tarea → sondeo → enlace firmado ya lo usan
Descargas y Comprobantes.

## 15. Fuera de alcance

| Qué | Por qué |
|---|---|
| **B-09** Recálculo de ISR y subsidio | Requiere `tarifa_isr` por ejercicio y periodicidad del Anexo 8 de la RMF. El riesgo fiscal de una tarifa mal cargada es alto (B-09.R2 advierte de errores de dos órdenes de magnitud) |
| **B-11** Conciliación contra plantilla de RH | Requiere el archivo de RH; no existe fuente en el sistema |
| **B-12** Incapacidades y horas extra | El código es barato, pero los XML actuales no traen esos nodos: saldría vacío. Se agrega cuando aparezcan |
| **B-13** Consolidado multi-organización | Solo hay una empresa dada de alta |
| **Grupos A, C, D, E** | La capa normalizada de este diseño es su cimiento; cada grupo tendrá su propio spec |
| `nomina_acciones_titulos`, `nomina_horas_extra` | Solo alimentan B-12 |

## 16. Pendientes relacionados (no bloquean, se anotan)

- **Descargar más historia de nómina del SAT.** Con 2 quincenas los informes son correctos pero casi
  vacíos, y B-05 (acumulado anual) no tiene sentido hasta tener el ejercicio completo. Es una descarga
  real contra el SAT con la e.firma de producción.
- **Conservar `EsCancelable` y `EstatusCancelacion`** del WS de estatus (`sat_facade.py:199`) — los
  necesita C-02.
- **Persistir la metadata del SAT** — la necesita C-03.
- **Leer las fechas de publicación del CSV 69-B** (`sat_facade.py:277` toma solo las columnas 1 y 3) — las
  necesita la regla A-01.R4 para evaluar EFOS a la fecha del comprobante.
