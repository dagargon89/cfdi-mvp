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
  clave del informe y rango solicitado.

## 9. Manejo de errores

Ningún fallo individual aborta una corrida.

| Situación | Tratamiento |
|---|---|
| XML corrupto o ilegible | Se marca el comprobante; bandera `SIN_NORMALIZAR` en el informe |
| XML ausente en disco | Igual; no lanza excepción |
| CFDI tipo `N` sin complemento de nómina | Bandera `COMPLEMENTO_AUSENTE` |
| Informe sin filas | Libro con hoja de Parámetros y aviso, no un `500` |
| Volumen grande | Consulta por lotes, como el export actual |

## 10. Estructura del libro de Excel

Cuatro hojas en todo informe:

1. **Datos** — el informe. Fila de encabezado congelada, formatos numéricos por tipo de columna.
2. **Parámetros** — usuario, fecha y hora, filtros exactos, `etl_version`, número de filas. Sin esta hoja
   un Excel circulando por correo no se puede reproducir ni auditar después.
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
patrón), con complemento de Nómina 1.2. El periodo se determina por `nomina.fecha_pago` (R-T6), salvo B-04
que asigna por `fecha_final_pago` (B-04, fase 2). Por defecto solo `VIGENTE` (R-T1).

| Clave | Nombre | Fase | Completitud |
|---|---|---|---|
| B-02 | Nómina agrupada por conceptos del patrón | 1 | Completo |
| B-01 | Nómina agrupada por catálogo SAT | 2 | Completo, con `solo_tipos_con_movimiento` |
| B-04 | Matriz empleado × periodo | 2 | Completo |
| B-05 | Acumulado anual por empleado | 2 | Columnas 1–23; 24–26 (ISR anual teórico) requieren `tarifa_isr` |
| B-07 | Cartera de préstamos y descuentos recurrentes | 2 | Columnas 1–9 y 14; 10–13 requieren capturar el monto original |
| B-10 | Validación de datos del receptor | 2 | 21 de 23 reglas; solo `SBC_SOBRE_TOPE` (UMA) y `SBC_BAJO_MINIMO` (salario mínimo) esperan a `param_fiscal` en la fase 3 |
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

**Verificación contra datos reales, en vivo, sin que nada entre a git:** las **9 identidades de B-00**
(`total_percepciones = Σ percepciones`, `subtotal = total_percepciones + total_otros_pagos`,
`descuento = total_deducciones`, `total = subtotal − descuento`, etc.) evaluadas sobre los 8 CFDI de la
empresa 11 tras el reproceso. Si el ETL lee mal cualquier nodo, ahí truena.

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
