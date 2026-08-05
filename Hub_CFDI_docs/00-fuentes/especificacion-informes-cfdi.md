# Especificación de informes derivados de CFDI

**Versión del documento:** 1.0
**Ámbito:** CFDI 4.0 · Complemento Nómina 1.2 · Complemento de Pagos 2.0 · Complemento de Retenciones 2.0
**Propósito:** definir, con precisión suficiente para implementación directa, el catálogo de informes que puede generarse a partir de los XML que el SAT resguarda de un contribuyente, el contenido exacto de cada uno y el método de cálculo de cada campo derivado.

---

## Índice

1. [Convenciones del documento](#1-convenciones-del-documento)
2. [Modelo de datos base](#2-modelo-de-datos-base)
3. [Catálogos SAT requeridos](#3-catálogos-sat-requeridos)
4. [Reglas transversales de cálculo](#4-reglas-transversales-de-cálculo)
5. [Grupo A — Informes de comprobante](#grupo-a--informes-de-comprobante)
6. [Grupo B — Informes de nómina](#grupo-b--informes-de-nómina)
7. [Grupo C — Informes de cumplimiento y validación](#grupo-c--informes-de-cumplimiento-y-validación)
8. [Grupo D — Papeles de trabajo fiscales](#grupo-d--papeles-de-trabajo-fiscales)
9. [Grupo E — Informes analíticos](#grupo-e--informes-analíticos)
10. [Anexo I — Fórmulas fiscales](#anexo-i--fórmulas-fiscales)
11. [Anexo II — Matriz de trazabilidad informe ↔ tabla](#anexo-ii--matriz-de-trazabilidad-informe--tabla)

---

## 1. Convenciones del documento

### 1.1 Notación

| Símbolo | Significado |
|---|---|
| `tabla.campo` | Columna de la base de datos normalizada definida en §2 |
| `@Atributo` | Atributo de un nodo XML del CFDI |
| `c_Catalogo` | Catálogo publicado por el SAT |
| `⌊x⌉₂` | Redondeo de `x` a 2 decimales, medio arriba (`ROUND_HALF_UP`) |
| **[P]** | Parámetro de entrada del informe |
| **[D]** | Campo derivado (calculado, no existe en el XML) |
| **[X]** | Campo tomado literal del XML |
| ⚠ | Regla que produce una bandera de excepción en el informe |

### 1.2 Estructura de cada ficha de informe

Cada informe se especifica con estos siete bloques obligatorios:

1. **Identificador y nombre**
2. **Propósito** — la decisión o trámite que habilita
3. **Grano** — qué representa exactamente una fila
4. **Parámetros de entrada**
5. **Columnas** — tabla con nombre, tipo, origen y fórmula
6. **Reglas de cálculo** — el detalle que no cabe en la tabla de columnas
7. **Validaciones** — condiciones que generan bandera

### 1.3 Tipos de dato

| Tipo | Definición | Notas |
|---|---|---|
| `UUID` | `CHAR(36)` mayúsculas con guiones | Clave natural del comprobante |
| `MONTO` | `DECIMAL(18,6)` en almacenamiento, `DECIMAL(18,2)` en presentación | El XML admite hasta 6 decimales |
| `TASA` | `DECIMAL(9,6)` | `0.160000` = 16 % |
| `RFC` | `VARCHAR(13)` mayúsculas sin espacios | 12 posiciones para moral, 13 para física |
| `FECHA` | `DATE` | Zona horaria del lugar de expedición |
| `TS` | `DATETIME` | `@Fecha` y `@FechaTimbrado` incluyen hora |
| `CLAVE` | `VARCHAR(10)` | Se conserva con ceros a la izquierda; **nunca** como entero |

> **Regla dura:** todas las claves de catálogo (`001`, `002`, `04`, `P001`) se almacenan y comparan como texto. Convertirlas a entero destruye los ceros a la izquierda y rompe cualquier `JOIN` contra catálogo.

---

## 2. Modelo de datos base

Todos los informes de este documento se calculan sobre este esquema. La regla arquitectónica es: **almacenar normalizado (formato largo), pivotar solo en la capa de presentación.**

### 2.1 `cfdi_comprobante`

Un renglón por UUID. Es la tabla raíz.

| Campo | Tipo | Origen XPath | Notas |
|---|---|---|---|
| `uuid` | UUID **PK** | `//tfd:TimbreFiscalDigital/@UUID` | Normalizar a mayúsculas |
| `rfc_contribuyente` | RFC | — **[D]** | RFC dueño de la descarga; discrimina emitido/recibido |
| `origen` | ENUM | — **[D]** | `EMITIDO` si `rfc_emisor = rfc_contribuyente`, `RECIBIDO` en caso contrario |
| `version` | VARCHAR(5) | `cfdi:Comprobante/@Version` | `3.3` o `4.0` |
| `serie` | VARCHAR(25) | `@Serie` | Opcional en el estándar |
| `folio` | VARCHAR(40) | `@Folio` | Opcional; **no** numérico |
| `fecha` | TS | `@Fecha` | Fecha de expedición |
| `fecha_timbrado` | TS | `//tfd:TimbreFiscalDigital/@FechaTimbrado` | |
| `tipo_comprobante` | CHAR(1) | `@TipoDeComprobante` | `I` `E` `T` `N` `P` |
| `forma_pago` | VARCHAR(2) | `@FormaPago` | `c_FormaPago`; ausente en `T` y `P` |
| `metodo_pago` | VARCHAR(3) | `@MetodoPago` | `PUE` \| `PPD` |
| `moneda` | CHAR(3) | `@Moneda` | ISO 4217; `XXX` en `T` y `P` |
| `tipo_cambio` | DECIMAL(18,6) | `@TipoCambio` | `1` si `moneda = 'MXN'` |
| `subtotal` | MONTO | `@SubTotal` | |
| `descuento` | MONTO | `@Descuento` | `0` si ausente |
| `total` | MONTO | `@Total` | |
| `lugar_expedicion` | VARCHAR(5) | `@LugarExpedicion` | Código postal |
| `exportacion` | VARCHAR(2) | `@Exportacion` | Solo 4.0 |
| `no_certificado` | VARCHAR(20) | `@NoCertificado` | Certificado del emisor |
| `no_certificado_sat` | VARCHAR(20) | `//tfd:TimbreFiscalDigital/@NoCertificadoSAT` | |
| `rfc_emisor` | RFC | `cfdi:Emisor/@Rfc` | |
| `nombre_emisor` | VARCHAR(300) | `cfdi:Emisor/@Nombre` | |
| `regimen_emisor` | VARCHAR(3) | `cfdi:Emisor/@RegimenFiscal` | `c_RegimenFiscal` |
| `rfc_receptor` | RFC | `cfdi:Receptor/@Rfc` | |
| `nombre_receptor` | VARCHAR(300) | `cfdi:Receptor/@Nombre` | |
| `domicilio_receptor` | VARCHAR(5) | `cfdi:Receptor/@DomicilioFiscalReceptor` | Solo 4.0 |
| `regimen_receptor` | VARCHAR(3) | `cfdi:Receptor/@RegimenFiscalReceptor` | Solo 4.0 |
| `uso_cfdi` | VARCHAR(4) | `cfdi:Receptor/@UsoCFDI` | `c_UsoCFDI` |
| `estado_sat` | ENUM | — **[D]** | `VIGENTE` \| `CANCELADO` \| `NO_ENCONTRADO`; de la consulta al WS de estatus |
| `es_cancelable` | VARCHAR(40) | — **[D]** | Respuesta del WS: `Cancelable sin aceptación`, etc. |
| `estatus_cancelacion` | VARCHAR(40) | — **[D]** | `En proceso`, `Cancelado sin aceptación`, etc. |
| `fecha_cancelacion` | TS | — **[D]** | De metadata del SAT |
| `motivo_cancelacion` | CHAR(2) | — **[D]** | `01`–`04` |
| `uuid_sustitucion` | UUID | — **[D]** | Obligatorio cuando `motivo_cancelacion = '01'` |
| `xml_hash` | CHAR(64) | — **[D]** | SHA-256 del XML original; detecta reprocesos |

**Índices mínimos:** `(rfc_contribuyente, origen, fecha)`, `(rfc_emisor, fecha)`, `(rfc_receptor, fecha)`, `(tipo_comprobante, estado_sat)`, `(serie, folio, rfc_emisor)`.

### 2.2 `cfdi_concepto`

Un renglón por nodo `cfdi:Concepto`.

| Campo | Tipo | Origen | Notas |
|---|---|---|---|
| `id` | BIGINT **PK** | — | Autoincremental |
| `uuid` | UUID **FK** | — | |
| `num_linea` | INT | — **[D]** | Posición 1..n dentro del comprobante |
| `clave_prod_serv` | VARCHAR(8) | `@ClaveProdServ` | `c_ClaveProdServ` |
| `no_identificacion` | VARCHAR(100) | `@NoIdentificacion` | SKU interno del emisor |
| `cantidad` | DECIMAL(18,6) | `@Cantidad` | |
| `clave_unidad` | VARCHAR(3) | `@ClaveUnidad` | `c_ClaveUnidad` |
| `unidad` | VARCHAR(20) | `@Unidad` | Texto libre |
| `descripcion` | VARCHAR(1000) | `@Descripcion` | |
| `valor_unitario` | MONTO | `@ValorUnitario` | |
| `importe` | MONTO | `@Importe` | |
| `descuento` | MONTO | `@Descuento` | `0` si ausente |
| `objeto_imp` | VARCHAR(2) | `@ObjetoImp` | Solo 4.0: `01` no objeto, `02` sí, `03` sí no obligado |

### 2.3 `cfdi_concepto_impuesto`

Un renglón por `cfdi:Traslado` o `cfdi:Retencion` **a nivel concepto**.

| Campo | Tipo | Origen | Notas |
|---|---|---|---|
| `id` | BIGINT **PK** | — | |
| `concepto_id` | BIGINT **FK** | — | |
| `uuid` | UUID **FK** | — | Desnormalizado para agregaciones directas |
| `naturaleza` | CHAR(1) | — **[D]** | `T` traslado, `R` retención |
| `impuesto` | CHAR(3) | `@Impuesto` | `001` ISR, `002` IVA, `003` IEPS |
| `tipo_factor` | VARCHAR(10) | `@TipoFactor` | `Tasa`, `Cuota`, `Exento` |
| `tasa_o_cuota` | TASA | `@TasaOCuota` | `NULL` cuando `tipo_factor = 'Exento'` |
| `base` | MONTO | `@Base` | |
| `importe` | MONTO | `@Importe` | `NULL` cuando `Exento` |

> **Por qué a nivel concepto y no solo el resumen:** el nodo `cfdi:Impuestos` del comprobante agrega por impuesto y tasa, y pierde la relación con la línea. Los informes R-03, R-30 y R-31 requieren la base por tasa por concepto.

### 2.4 `cfdi_relacionado`

| Campo | Tipo | Origen |
|---|---|---|
| `uuid` | UUID **FK** | Comprobante que declara la relación |
| `tipo_relacion` | CHAR(2) | `cfdi:CfdiRelacionados/@TipoRelacion` |
| `uuid_relacionado` | UUID | `cfdi:CfdiRelacionado/@UUID` |

Clave primaria compuesta `(uuid, tipo_relacion, uuid_relacionado)`. En CFDI 4.0 puede haber **varios** nodos `CfdiRelacionados` con distinto `@TipoRelacion` en el mismo comprobante.

### 2.5 `pago` y `pago_docto` (Complemento de Pagos 2.0)

`pago` — un renglón por nodo `pago20:Pago`:

| Campo | Tipo | Origen |
|---|---|---|
| `id` | BIGINT **PK** | — |
| `uuid` | UUID **FK** | |
| `num_pago` | INT **[D]** | Posición del nodo |
| `fecha_pago` | TS | `@FechaPago` |
| `forma_de_pago_p` | VARCHAR(2) | `@FormaDePagoP` |
| `moneda_p` | CHAR(3) | `@MonedaP` |
| `tipo_cambio_p` | DECIMAL(18,6) | `@TipoCambioP` |
| `monto` | MONTO | `@Monto` |
| `num_operacion` | VARCHAR(100) | `@NumOperacion` |
| `rfc_emisor_cta_ord` | RFC | `@RfcEmisorCtaOrd` |
| `cta_ordenante` | VARCHAR(50) | `@CtaOrdenante` |
| `rfc_emisor_cta_ben` | RFC | `@RfcEmisorCtaBen` |
| `cta_beneficiario` | VARCHAR(50) | `@CtaBeneficiario` |

`pago_docto` — un renglón por `pago20:DoctoRelacionado`:

| Campo | Tipo | Origen | Notas |
|---|---|---|---|
| `id` | BIGINT **PK** | — | |
| `pago_id` | BIGINT **FK** | — | |
| `id_documento` | UUID | `@IdDocumento` | UUID de la factura pagada |
| `serie` | VARCHAR(25) | `@Serie` | |
| `folio` | VARCHAR(40) | `@Folio` | |
| `moneda_dr` | CHAR(3) | `@MonedaDR` | |
| `equivalencia_dr` | DECIMAL(18,10) | `@EquivalenciaDR` | Factor `MonedaDR → MonedaP` |
| `num_parcialidad` | INT | `@NumParcialidad` | |
| `imp_saldo_ant` | MONTO | `@ImpSaldoAnt` | |
| `imp_pagado` | MONTO | `@ImpPagado` | |
| `imp_saldo_insoluto` | MONTO | `@ImpSaldoInsoluto` | |
| `objeto_imp_dr` | VARCHAR(2) | `@ObjetoImpDR` | |

`pago_docto_impuesto` — impuestos trasladados/retenidos del documento relacionado, misma forma que §2.3 con `pago_docto_id` como FK.

`pago_totales` — un renglón por UUID, del nodo `pago20:Totales`: `total_traslados_base_iva16`, `total_traslados_impuesto_iva16`, `total_traslados_base_iva8`, `total_traslados_impuesto_iva8`, `total_traslados_base_iva0`, `total_traslados_impuesto_iva0`, `total_traslados_base_iva_exento`, `total_retenciones_iva`, `total_retenciones_isr`, `total_retenciones_ieps`, `monto_total_pagos`.

### 2.6 `nomina` (Complemento Nómina 1.2)

Un renglón por UUID de tipo nómina. Cardinalidad 1:1 con `cfdi_comprobante`.

| Campo | Tipo | Origen | Notas |
|---|---|---|---|
| `uuid` | UUID **PK/FK** | | |
| `version_nomina` | VARCHAR(5) | `nomina12:Nomina/@Version` | `1.2` |
| `tipo_nomina` | CHAR(1) | `@TipoNomina` | `O` ordinaria, `E` extraordinaria |
| `fecha_pago` | FECHA | `@FechaPago` | |
| `fecha_inicial_pago` | FECHA | `@FechaInicialPago` | |
| `fecha_final_pago` | FECHA | `@FechaFinalPago` | |
| `num_dias_pagados` | DECIMAL(9,3) | `@NumDiasPagados` | Admite fracción |
| `total_percepciones` | MONTO | `@TotalPercepciones` | `0` si no hay percepciones |
| `total_deducciones` | MONTO | `@TotalDeducciones` | |
| `total_otros_pagos` | MONTO | `@TotalOtrosPagos` | |
| `registro_patronal` | VARCHAR(20) | `nomina12:Emisor/@RegistroPatronal` | |
| `rfc_patron_origen` | RFC | `nomina12:Emisor/@RfcPatronOrigen` | Subcontratación |
| `origen_recurso` | VARCHAR(2) | `nomina12:EntidadSNCF/@OrigenRecurso` | `IP`, `IF`, `IM` |
| `monto_recurso_propio` | MONTO | `nomina12:EntidadSNCF/@MontoRecursoPropio` | |

### 2.7 `nomina_receptor`

Un renglón por UUID. Se separa de `nomina` por claridad, no por cardinalidad.

| Campo | Tipo | Origen | Notas |
|---|---|---|---|
| `uuid` | UUID **PK/FK** | | |
| `curp` | CHAR(18) | `nomina12:Receptor/@Curp` | **Dato personal** |
| `nss` | VARCHAR(15) | `@NumSeguridadSocial` | **Dato personal** |
| `fecha_inicio_rel_laboral` | FECHA | `@FechaInicioRelLaboral` | |
| `antiguedad` | VARCHAR(10) | `@Antigüedad` | Formato ISO 8601 duración: `P589W` |
| `tipo_contrato` | CHAR(2) | `@TipoContrato` | `c_TipoContrato` |
| `sindicalizado` | CHAR(2) | `@Sindicalizado` | `Sí` \| `No` |
| `tipo_jornada` | CHAR(2) | `@TipoJornada` | `c_TipoJornada` |
| `tipo_regimen` | CHAR(2) | `@TipoRegimen` | `c_TipoRegimen` |
| `num_empleado` | VARCHAR(15) | `@NumEmpleado` | Clave interna; **texto** |
| `departamento` | VARCHAR(100) | `@Departamento` | Texto libre |
| `puesto` | VARCHAR(100) | `@Puesto` | Texto libre |
| `riesgo_puesto` | CHAR(1) | `@RiesgoPuesto` | `1`–`5` |
| `periodicidad_pago` | CHAR(2) | `@PeriodicidadPago` | `c_PeriodicidadPago` |
| `banco` | VARCHAR(3) | `@Banco` | `c_Banco` |
| `cuenta_bancaria` | VARCHAR(18) | `@CuentaBancaria` | **Dato personal** |
| `salario_base_cot_apor` | MONTO | `@SalarioBaseCotApor` | SBC diario (IMSS) |
| `salario_diario_integrado` | MONTO | `@SalarioDiarioIntegrado` | SDI diario (LFT art. 84/89) |
| `clave_ent_fed` | VARCHAR(3) | `@ClaveEntFed` | `c_Estado` |

> **`@Antigüedad` no es numérico.** Viene como duración ISO 8601 (`P589W`, `P3Y2M`). Para cualquier cálculo, derivar de `fecha_inicio_rel_laboral` y `fecha_final_pago`, no de esta cadena. Nótese además que el atributo lleva diéresis en el nombre — es una fuente frecuente de fallos de parseo.

### 2.8 `nomina_percepcion`

Un renglón por nodo `nomina12:Percepcion`. **Formato largo — esta es la tabla que se pivota en R-11.**

| Campo | Tipo | Origen | Notas |
|---|---|---|---|
| `id` | BIGINT **PK** | — | |
| `uuid` | UUID **FK** | | |
| `tipo_percepcion` | CHAR(3) | `@TipoPercepcion` | `c_TipoPercepcion` |
| `clave` | VARCHAR(15) | `@Clave` | Clave **interna del patrón** |
| `concepto` | VARCHAR(100) | `@Concepto` | Descripción del patrón |
| `importe_gravado` | MONTO | `@ImporteGravado` | |
| `importe_exento` | MONTO | `@ImporteExento` | |

Nodos hijos condicionales, en tablas propias con `percepcion_id` como FK:

- `nomina_acciones_titulos`: `@ValorMercado`, `@PrecioAlOtorgarse` (solo `tipo_percepcion = '045'`)
- `nomina_horas_extra`: `@Dias`, `@TipoHoras`, `@HorasExtra`, `@ImportePagado` (solo `'019'`)

Totales del nodo `nomina12:Percepciones` en tabla `nomina_percepciones_tot`: `total_sueldos`, `total_separacion_indemnizacion`, `total_jubilacion_pension_retiro`, `total_gravado`, `total_exento`.

### 2.9 `nomina_deduccion`

| Campo | Tipo | Origen | Notas |
|---|---|---|---|
| `id` | BIGINT **PK** | — | |
| `uuid` | UUID **FK** | | |
| `tipo_deduccion` | CHAR(3) | `@TipoDeduccion` | `c_TipoDeduccion` |
| `clave` | VARCHAR(15) | `@Clave` | Clave interna |
| `concepto` | VARCHAR(100) | `@Concepto` | |
| `importe` | MONTO | `@Importe` | Siempre positivo en el XML |

Totales en `nomina_deducciones_tot`: `total_otras_deducciones`, `total_impuestos_retenidos`.

### 2.10 `nomina_otro_pago`

| Campo | Tipo | Origen | Notas |
|---|---|---|---|
| `id` | BIGINT **PK** | — | |
| `uuid` | UUID **FK** | | |
| `tipo_otro_pago` | CHAR(3) | `@TipoOtroPago` | `c_TipoOtroPago` |
| `clave` | VARCHAR(15) | `@Clave` | |
| `concepto` | VARCHAR(100) | `@Concepto` | |
| `importe` | MONTO | `@Importe` | |
| `subsidio_causado` | MONTO | `nomina12:SubsidioAlEmpleo/@SubsidioCausado` | Solo si `tipo_otro_pago = '002'` |
| `saldo_a_favor` | MONTO | `nomina12:CompensacionSaldosAFavor/@SaldoAFavor` | Solo si `'004'` |
| `anio` | INT | `nomina12:CompensacionSaldosAFavor/@Año` | |
| `remanente_sal_fav` | MONTO | `nomina12:CompensacionSaldosAFavor/@RemanenteSalFav` | |

### 2.11 `nomina_incapacidad`

| Campo | Tipo | Origen |
|---|---|---|
| `uuid` | UUID **FK** | |
| `dias_incapacidad` | INT | `@DiasIncapacidad` |
| `tipo_incapacidad` | CHAR(2) | `@TipoIncapacidad` |
| `importe_monetario` | MONTO | `@ImporteMonetario` |

### 2.12 Tablas de soporte

| Tabla | Contenido | Origen |
|---|---|---|
| `sat_efos` | `rfc`, `nombre`, `situacion`, `fecha_pub_presunto`, `fecha_pub_desvirtuado`, `fecha_pub_definitivo`, `fecha_pub_sentencia_favorable`, `oficio_global` | CSV del listado 69-B del SAT, refresco diario |
| `sat_metadata` | `uuid`, `rfc_emisor`, `rfc_receptor`, `fecha_emision`, `efecto_comprobante`, `estatus`, `fecha_cancelacion` | TXT de metadata de descarga masiva |
| `tarifa_isr` | `ejercicio`, `periodicidad`, `renglon`, `limite_inferior`, `limite_superior`, `cuota_fija`, `tasa_excedente` | Anexo 8 de la RMF vigente |
| `param_fiscal` | `ejercicio`, `clave`, `valor`, `vigencia_desde`, `vigencia_hasta` | UMA diaria/mensual/anual, salario mínimo, topes de exención, tope y monto del subsidio al empleo |
| `plantilla_rh` | `rfc`, `curp`, `nss`, `num_empleado`, `nombre`, `puesto`, `centro_costo`, `fecha_alta`, `fecha_baja`, `sueldo_mensual`, `activo` | Sistema de RH; externa al CFDI |
| `tipo_cambio_dof` | `fecha`, `moneda`, `valor` | DOF; para R-30 y conversión de moneda |

> **Ningún importe de tarifa, tope de exención, UMA o monto de subsidio se codifica en el programa.** Todo vive en `tarifa_isr` y `param_fiscal` con vigencia, y se resuelve por fecha. Los valores cambian por ejercicio y por decreto; hardcodearlos garantiza cálculos incorrectos en cuanto cambie la RMF.

---

## 3. Catálogos SAT requeridos

Cada catálogo se carga como tabla con clave textual y descripción. Sin ellos, cada informe reinventa las descripciones y produce inconsistencias entre reportes.

| Catálogo | Usado en | Nota de implementación |
|---|---|---|
| `c_TipoDeComprobante` | Todos | `I` `E` `T` `N` `P` |
| `c_FormaPago` | A, D | 22 claves; `99` = por definir |
| `c_MetodoPago` | A, C, D | `PUE`, `PPD` |
| `c_Moneda` | A, D | ISO 4217 + `XXX` |
| `c_UsoCFDI` | A, E | Restringido por régimen del receptor en 4.0 |
| `c_RegimenFiscal` | A, C | Marca si aplica a física, moral o ambas |
| `c_ClaveProdServ` | A, E | ~52 000 registros; incluye `IVATrasladado` e `IEPSTrasladado` |
| `c_ClaveUnidad` | A, E | UNECE Rec 20 |
| `c_TipoRelacion` | A, C | `01`–`07` |
| `c_Impuesto` | A, D | `001` ISR, `002` IVA, `003` IEPS |
| `c_TipoFactor` | A, D | `Tasa`, `Cuota`, `Exento` |
| `c_ObjetoImp` | A, D | Solo 4.0 |
| `c_TipoNomina` | B | `O`, `E` |
| `c_TipoPercepcion` | B | 001–046; incluye marca de gravado/exento por defecto |
| `c_TipoDeduccion` | B | 001–107 |
| `c_TipoOtroPago` | B | 001–999 |
| `c_TipoContrato` | B | 01–99 |
| `c_TipoJornada` | B | 01–99 |
| `c_TipoRegimen` | B | 02–99 |
| `c_PeriodicidadPago` | B | `01` diario … `10` decenal, `99` otra |
| `c_RiesgoPuesto` | B | 1–5 |
| `c_TipoIncapacidad` | B | 01–03 |
| `c_TipoHoras` | B | 01–03 |
| `c_Banco` | B | 3 dígitos |
| `c_Estado` | B, E | Clave de entidad federativa |
| `c_OrigenRecurso` | B | `IP`, `IF`, `IM` |
| `c_MotivoCancelacion` | C | `01`–`04` |

### 3.1 Marcas derivadas necesarias en `c_TipoPercepcion`

El catálogo oficial no basta. Se añaden estas columnas de configuración para habilitar R-12, R-14 y R-17:

| Columna añadida | Tipo | Uso |
|---|---|---|
| `es_ingreso_ordinario` | BOOL | Excluye separación/indemnización y jubilaciones del cálculo de ISR ordinario |
| `base_exencion` | ENUM | `UMA_DIAS`, `SM_DIAS`, `PORCENTAJE`, `NINGUNA` |
| `factor_exencion` | DECIMAL | Ej.: 30 días de UMA para aguinaldo, 15 para PTU |
| `integra_sbc` | BOOL | Para validación del SBC (R-19) |
| `es_provisionable` | BOOL | Entra en R-17 (pasivo laboral) |

---

## 4. Reglas transversales de cálculo

Estas reglas aplican a **todos** los informes. Cada ficha las asume y solo documenta desviaciones.

### R-T1 · Universo de comprobantes

Todo informe declara explícitamente su tratamiento de cancelados. El valor por defecto es:

```sql
WHERE estado_sat = 'VIGENTE'
```

Excepciones: R-21 (informe de cancelados) y R-24 (continuidad de folios, que **debe** incluir cancelados para no reportar huecos falsos).

### R-T2 · Signo de los importes

En el XML **todos** los importes son positivos; el signo lo determina el tipo de comprobante. Regla de normalización:

```
signo(comprobante) = -1  si tipo_comprobante = 'E'
                   = +1  en cualquier otro caso
importe_efectivo = importe × signo(comprobante)
```

Los egresos (notas de crédito) se presentan en negativo **solo en informes de suma**; en informes de detalle se muestran positivos con la columna `tipo_comprobante` como discriminador.

### R-T3 · Conversión de moneda

```
importe_mxn = ⌊importe × tipo_cambio⌉₂
```

Si `moneda = 'MXN'` entonces `tipo_cambio = 1`. Si `tipo_cambio` viene nulo o cero en un comprobante con moneda extranjera → ⚠ bandera `TC_INVALIDO` y se usa el tipo de cambio del DOF de `fecha` desde `tipo_cambio_dof`, marcando la fila como estimada.

### R-T4 · Redondeo

Todo cálculo intermedio se conserva a 6 decimales. El redondeo a 2 decimales ocurre **una sola vez**, al presentar. Redondear en cada paso intermedio produce descuadres de centavos que se acumulan y disparan falsas banderas en R-25.

### R-T5 · Deduplicación

La clave de unicidad es `uuid`. Si un mismo UUID llega por dos vías (descarga por fecha y por UUID, o emitido de una organización que es recibido de otra), se conserva un solo registro y se resuelve `origen` con la regla de §2.1. En un consolidado multi-RFC, un comprobante entre dos organizaciones del mismo grupo aparece dos veces con `rfc_contribuyente` distinto; **todo informe consolidado debe deduplicar por `uuid` o duplicará importes.**

### R-T6 · Periodo de asignación

| Informe | Fecha que determina el periodo |
|---|---|
| Grupo A (ingresos, egresos) | `cfdi_comprobante.fecha` |
| Grupo B (nómina) | `nomina.fecha_pago` |
| R-05, R-06, R-30 (flujo) | `pago.fecha_pago` |
| R-21 (cancelaciones) | `fecha_cancelacion` |
| R-24 (folios) | `cfdi_comprobante.fecha` |

Usar `fecha_timbrado` en lugar de `fecha` desplaza comprobantes de mes cuando el timbrado ocurre después de medianoche. `fecha_timbrado` solo se usa en R-25 para validar la ventana de 72 horas.

### R-T7 · Nulos en columnas pivotadas

En cualquier informe pivotado, la ausencia de un concepto para un empleado o periodo se representa como **cero, no como nulo**, y solo si el concepto existe en al menos una fila del conjunto. Un nulo en una columna de importe es indistinguible de "no aplica" y rompe cualquier suma en hoja de cálculo.

### R-T8 · Construcción de nombres de columna dinámicos

Cuando un informe genera columnas en tiempo de ejecución a partir de conceptos (R-11, R-13, R-16), el nombre se construye así:

```
etiqueta = tipo || SEP || clave || SEP || concepto
SEP = '\u00A6'   (barra vertical partida, U+00A6)
```

**No usar `/` como separador.** Los `@Concepto` del catálogo del SAT contienen diagonales (`Seguridad Social`, `Aportaciones Retiro, Cesantía y Vejez` aparecen abreviados con `/` en muchos sistemas), lo que hace ambiguo cualquier `split('/')`. Si el consumidor final exige compatibilidad con reportes existentes que usan `/`, se emite la columna con `/` **y además** una hoja `Diccionario` con el mapeo `etiqueta → (tipo, clave, concepto)` para que el parseo no dependa del nombre.

### R-T9 · Identidad de concepto

Dos conceptos son el mismo si y solo si coinciden `(tipo, clave)`. El `@Concepto` es texto libre del patrón y varía entre periodos por errores de captura. Agrupar por descripción produce columnas duplicadas del mismo concepto; agrupar solo por `tipo` colapsa conceptos distintos.

⚠ **Bandera `CONCEPTO_INCONSISTENTE`:** un mismo `(tipo, clave)` con más de una descripción distinta en el periodo. Se reporta la descripción más frecuente y se lista el conjunto.

### R-T10 · Doble conteo entre percepciones, deducciones y otros pagos

Un mismo flujo puede aparecer en las tres tablas. El caso canónico es el fondo de ahorro: se registra como percepción exenta (aportación patronal), como deducción (retención al trabajador) y como otro pago. Sumar las tres produce el triple del importe real.

**Regla:** ningún informe suma columnas de distinta naturaleza sin declararlo. Las agregaciones se hacen por naturaleza:

```
suma_percepciones = Σ nomina_percepcion.(gravado + exento)
suma_otros_pagos  = Σ nomina_otro_pago.importe
suma_deducciones  = Σ nomina_deduccion.importe
neto              = suma_percepciones + suma_otros_pagos - suma_deducciones
```

⚠ **Bandera `POSIBLE_ESPEJO`:** conceptos en distintas naturalezas cuyo importe agregado por `(uuid)` coincide exactamente. Se reporta como informativo, no como error.

---

## Grupo A — Informes de comprobante

### A-01 · Concentrado de comprobantes (emitidos / recibidos)

**Propósito.** Base de todo trabajo de conciliación: el listado plano de comprobantes de un periodo, con importes e impuestos, para cotejar contra contabilidad y contra el visor del SAT.

**Grano.** Una fila por `uuid`.

**Parámetros.** `rfc_contribuyente` **[P]**, `origen` (EMITIDO \| RECIBIDO \| AMBOS) **[P]**, `fecha_desde`–`fecha_hasta` **[P]**, `tipo_comprobante` (multiselección) **[P]**, `incluir_cancelados` (bool, default `false`) **[P]**, `moneda_presentacion` (ORIGINAL \| MXN) **[P]**.

**Columnas.**

| # | Columna | Tipo | Origen / Fórmula |
|---|---|---|---|
| 1 | Ejercicio | INT **[D]** | `YEAR(fecha)` |
| 2 | Periodo | INT **[D]** | `MONTH(fecha)` |
| 3 | Tipo comprobante | TEXT **[X]** | `tipo_comprobante` + descripción de `c_TipoDeComprobante` |
| 4 | Versión | TEXT **[X]** | `version` |
| 5 | Serie | TEXT **[X]** | `serie` |
| 6 | Folio | TEXT **[X]** | `folio` |
| 7 | UUID | UUID **[X]** | `uuid` |
| 8 | Fecha emisión | TS **[X]** | `fecha` |
| 9 | Fecha timbrado | TS **[X]** | `fecha_timbrado` |
| 10 | RFC emisor | RFC **[X]** | `rfc_emisor` |
| 11 | Nombre emisor | TEXT **[X]** | `nombre_emisor` |
| 12 | Régimen emisor | TEXT **[X]** | `regimen_emisor` + descripción |
| 13 | RFC receptor | RFC **[X]** | `rfc_receptor` |
| 14 | Nombre receptor | TEXT **[X]** | `nombre_receptor` |
| 15 | Régimen receptor | TEXT **[X]** | `regimen_receptor` + descripción |
| 16 | CP receptor | TEXT **[X]** | `domicilio_receptor` |
| 17 | Uso CFDI | TEXT **[X]** | `uso_cfdi` + descripción |
| 18 | Método de pago | TEXT **[X]** | `metodo_pago` |
| 19 | Forma de pago | TEXT **[X]** | `forma_pago` + descripción |
| 20 | Moneda | TEXT **[X]** | `moneda` |
| 21 | Tipo de cambio | DEC **[X]** | `tipo_cambio` |
| 22 | Subtotal | MONTO **[X]** | `subtotal` |
| 23 | Descuento | MONTO **[X]** | `descuento` |
| 24 | Base IVA 16 % | MONTO **[D]** | Σ `base` donde `naturaleza='T' AND impuesto='002' AND tasa_o_cuota=0.160000` |
| 25 | IVA 16 % | MONTO **[D]** | Σ `importe` con el mismo filtro |
| 26 | Base IVA 8 % | MONTO **[D]** | Igual con `tasa_o_cuota=0.080000` |
| 27 | IVA 8 % | MONTO **[D]** | |
| 28 | Base IVA 0 % | MONTO **[D]** | `tasa_o_cuota=0.000000` |
| 29 | Base IVA exento | MONTO **[D]** | `tipo_factor='Exento'` |
| 30 | IEPS trasladado | MONTO **[D]** | Σ `importe` donde `naturaleza='T' AND impuesto='003'` |
| 31 | IVA retenido | MONTO **[D]** | Σ `importe` donde `naturaleza='R' AND impuesto='002'` |
| 32 | ISR retenido | MONTO **[D]** | Σ `importe` donde `naturaleza='R' AND impuesto='001'` |
| 33 | IEPS retenido | MONTO **[D]** | Σ `importe` donde `naturaleza='R' AND impuesto='003'` |
| 34 | Total | MONTO **[X]** | `total` |
| 35 | Total MXN | MONTO **[D]** | `⌊total × tipo_cambio⌉₂` |
| 36 | Estado SAT | TEXT **[D]** | `estado_sat` |
| 37 | Fecha cancelación | TS **[D]** | `fecha_cancelacion` |
| 38 | Motivo cancelación | TEXT **[D]** | `motivo_cancelacion` + descripción |
| 39 | UUID sustitución | UUID **[D]** | `uuid_sustitucion` |
| 40 | Tipos de relación | TEXT **[D]** | `GROUP_CONCAT(DISTINCT tipo_relacion)` desde `cfdi_relacionado` |
| 41 | UUIDs relacionados | TEXT **[D]** | `GROUP_CONCAT(uuid_relacionado)` |
| 42 | EFOS | TEXT **[D]** | Situación en `sat_efos` de la contraparte a la fecha de emisión (ver A-01.R4) |

**Reglas de cálculo.**

- **A-01.R1 — Contraparte.** Se define `rfc_contraparte = rfc_receptor` si `origen='EMITIDO'`, y `rfc_emisor` si `origen='RECIBIDO'`. Las columnas de EFOS y los informes del Grupo E se agrupan por este campo.
- **A-01.R2 — Desglose de impuestos.** Se agrega desde `cfdi_concepto_impuesto`, no desde el nodo resumen. Cuando el comprobante trae `cfdi:Impuestos` a nivel comprobante pero los conceptos no traen desglose (permitido en 3.3), se usa el resumen y se marca ⚠ `IMPUESTO_SIN_DESGLOSE`.
- **A-01.R3 — Tasas no estándar.** Cualquier `tasa_o_cuota` distinta de 0.160000, 0.080000, 0.000000 se acumula en una columna `Otras tasas` con detalle en hoja anexa, y ⚠ `TASA_ATIPICA`.
- **A-01.R4 — EFOS.** `situacion` de `sat_efos` para `rfc_contraparte` evaluada contra `fecha`:
  ```
  si existe fecha_pub_definitivo <= fecha            → 'DEFINITIVO'
  sino si existe fecha_pub_presunto <= fecha
        y (fecha_pub_desvirtuado es nula o > fecha)   → 'PRESUNTO'
  sino si existe fecha_pub_sentencia_favorable <= fecha → 'SENTENCIA FAVORABLE'
  sino si existe fecha_pub_desvirtuado <= fecha       → 'DESVIRTUADO'
  sino                                                → ''
  ```
  La evaluación es **a la fecha del comprobante**, no a la fecha de hoy. Un proveedor publicado como definitivo tres años después de la operación tiene un tratamiento fiscal distinto al que ya lo estaba.

**Validaciones.**

| Bandera | Condición |
|---|---|
| `DESCUADRE_TOTAL` | `abs(total − (subtotal − descuento + Σimp_trasladados − Σimp_retenidos)) > 0.01` |
| `TC_INVALIDO` | `moneda ≠ 'MXN' AND (tipo_cambio IS NULL OR tipo_cambio <= 0)` |
| `PPD_CON_FORMA_PAGO` | `metodo_pago='PPD' AND forma_pago NOT IN ('99')` |
| `PUE_FORMA_99` | `metodo_pago='PUE' AND forma_pago='99'` |
| `USO_INCOMPATIBLE` | `uso_cfdi` no permitido para `regimen_receptor` según `c_UsoCFDI` (solo 4.0) |
| `EFOS_DEFINITIVO` | Columna 42 = `DEFINITIVO` |
| `TIMBRADO_TARDIO` | `fecha_timbrado − fecha > 72 h` |

---

### A-02 · Detalle de conceptos

**Propósito.** Analizar **qué** se factura, no solo cuánto. Es el insumo de los informes de producto/servicio del Grupo E y el único informe que permite auditar la clasificación `c_ClaveProdServ`.

**Grano.** Una fila por `cfdi_concepto.id`. Un comprobante con 12 líneas genera 12 filas con los datos de encabezado repetidos.

**Parámetros.** Los de A-01, más `clave_prod_serv` (filtro opcional, admite prefijo) **[P]** y `texto_descripcion` (búsqueda LIKE) **[P]**.

**Columnas.**

| # | Columna | Tipo | Origen / Fórmula |
|---|---|---|---|
| 1–21 | — | | Encabezado idéntico a A-01 columnas 1–21 |
| 22 | Núm. línea | INT **[D]** | `num_linea` |
| 23 | Clave ProdServ | TEXT **[X]** | `clave_prod_serv` |
| 24 | Descripción ProdServ | TEXT **[D]** | Descripción de `c_ClaveProdServ` |
| 25 | No. identificación | TEXT **[X]** | `no_identificacion` |
| 26 | Descripción | TEXT **[X]** | `descripcion` |
| 27 | Cantidad | DEC **[X]** | `cantidad` |
| 28 | Clave unidad | TEXT **[X]** | `clave_unidad` |
| 29 | Descripción unidad | TEXT **[D]** | De `c_ClaveUnidad` |
| 30 | Unidad (libre) | TEXT **[X]** | `unidad` |
| 31 | Valor unitario | MONTO **[X]** | `valor_unitario` |
| 32 | Importe | MONTO **[X]** | `importe` |
| 33 | Descuento línea | MONTO **[X]** | `descuento` |
| 34 | Importe neto | MONTO **[D]** | `importe − descuento` |
| 35 | Objeto impuesto | TEXT **[X]** | `objeto_imp` + descripción |
| 36 | Base IVA 16 % | MONTO **[D]** | De `cfdi_concepto_impuesto` filtrado a `concepto_id` |
| 37 | IVA 16 % | MONTO **[D]** | |
| 38 | Base IVA 8 % / IVA 8 % | MONTO **[D]** | |
| 39 | Base 0 % / Exento | MONTO **[D]** | |
| 40 | IEPS | MONTO **[D]** | |
| 41 | IVA ret. / ISR ret. | MONTO **[D]** | |
| 42 | Importe MXN | MONTO **[D]** | `⌊(importe − descuento) × tipo_cambio⌉₂` |
| 43 | Precio unitario MXN | MONTO **[D]** | `⌊valor_unitario × tipo_cambio⌉₂` |

**Reglas de cálculo.**

- **A-02.R1.** `importe` **debería** ser `⌊cantidad × valor_unitario⌉₂`. La diferencia es tolerada por el SAT hasta el margen de redondeo. ⚠ `IMPORTE_LINEA_DESCUADRE` si `|importe − cantidad × valor_unitario| > 0.01`.
- **A-02.R2.** La suma de `importe` de todas las líneas debe igualar `subtotal` del comprobante. ⚠ `SUBTOTAL_DESCUADRE` si difiere en más de 0.01. Esta validación es la que detecta XML manipulados post-timbrado.
- **A-02.R3.** Las claves `84111506` (servicios de facturación) y las genéricas `01010101` (no existe en el catálogo) se marcan ⚠ `CLAVE_GENERICA`: son válidas pero inutilizan cualquier análisis de producto.

---

### A-03 · Impuestos por tasa y contraparte

**Propósito.** Cuadrar el IVA e IEPS del periodo contra la declaración, con el desglose exacto por tasa que exige el formato de pago provisional.

**Grano.** Una fila por combinación `(periodo, origen, rfc_contraparte, impuesto, naturaleza, tipo_factor, tasa_o_cuota)`.

**Columnas.**

| # | Columna | Tipo | Fórmula |
|---|---|---|---|
| 1 | Ejercicio / Periodo | INT **[D]** | De `fecha` |
| 2 | Origen | TEXT **[D]** | `EMITIDO` \| `RECIBIDO` |
| 3 | RFC contraparte | RFC **[D]** | A-01.R1 |
| 4 | Nombre contraparte | TEXT **[D]** | |
| 5 | Impuesto | TEXT **[X]** | `impuesto` + descripción |
| 6 | Naturaleza | TEXT **[D]** | `Traslado` \| `Retención` |
| 7 | Tipo factor | TEXT **[X]** | `tipo_factor` |
| 8 | Tasa o cuota | TASA **[X]** | `tasa_o_cuota` |
| 9 | Núm. comprobantes | INT **[D]** | `COUNT(DISTINCT uuid)` |
| 10 | Base | MONTO **[D]** | `Σ ⌊base × tipo_cambio⌉₆ × signo` |
| 11 | Importe impuesto | MONTO **[D]** | `Σ ⌊importe × tipo_cambio⌉₆ × signo` |
| 12 | Impuesto teórico | MONTO **[D]** | `⌊base_total × tasa_o_cuota⌉₂` |
| 13 | Diferencia | MONTO **[D]** | `importe_impuesto − impuesto_teorico` |

**Reglas.**

- **A-03.R1.** `signo` según R-T2: los egresos restan de la base. Sin esto, las notas de crédito inflan el IVA trasladado.
- **A-03.R2.** El agrupamiento **debe** incluir `tasa_o_cuota` con 6 decimales. Un proveedor con tasa `0.160000` y otro con `0.16` textual son la misma tasa; normalizar en la carga, no en el reporte.
- **A-03.R3.** ⚠ `DIFERENCIA_TASA` cuando `|diferencia| > 0.01 × núm_comprobantes`. La tolerancia escala con el número de comprobantes porque el redondeo por comprobante es legítimo.

---

### A-04 · CFDI relacionados y egresos aplicados

**Propósito.** Rastrear notas de crédito, sustituciones y devoluciones. Responde: ¿qué factura afecta esta nota de crédito y qué queda del importe original?

**Grano.** Una fila por par `(uuid, uuid_relacionado)`.

**Columnas.**

| # | Columna | Tipo | Fórmula |
|---|---|---|---|
| 1 | Tipo relación | TEXT **[X]** | `tipo_relacion` + descripción de `c_TipoRelacion` |
| 2 | UUID origen | UUID **[X]** | `uuid` (el comprobante que declara la relación) |
| 3 | Tipo / Serie / Folio origen | TEXT **[X]** | Del comprobante origen |
| 4 | Fecha origen | TS **[X]** | |
| 5 | Total origen | MONTO **[X]** | |
| 6 | UUID relacionado | UUID **[X]** | `uuid_relacionado` |
| 7 | Tipo / Serie / Folio relacionado | TEXT **[D]** | `JOIN` a `cfdi_comprobante`; nulo si no está en la base |
| 8 | Fecha relacionado | TS **[D]** | |
| 9 | Total relacionado | MONTO **[D]** | |
| 10 | Estado relacionado | TEXT **[D]** | `estado_sat` del relacionado |
| 11 | Días entre comprobantes | INT **[D]** | `DATEDIFF(fecha_origen, fecha_relacionado)` |
| 12 | Egresos acumulados | MONTO **[D]** | Σ `total` de todos los `E` que apuntan al mismo `uuid_relacionado` con `tipo_relacion IN ('01','03')` |
| 13 | Importe neto de la factura | MONTO **[D]** | `total_relacionado − egresos_acumulados` |
| 14 | % afectado | DEC **[D]** | `egresos_acumulados / total_relacionado` |

**Validaciones.**

| Bandera | Condición |
|---|---|
| `RELACIONADO_INEXISTENTE` | El `uuid_relacionado` no está en la base — puede ser omisión de descarga o UUID inventado |
| `SOBREAPLICACION` | `egresos_acumulados > total_relacionado + 0.01` |
| `SUSTITUCION_SIN_CANCELAR` | `tipo_relacion='04'` y el relacionado sigue `VIGENTE` |
| `RELACION_CIRCULAR` | `uuid = uuid_relacionado`, o ciclo detectado en el grafo de relaciones |
| `EGRESO_EJERCICIO_ANTERIOR` | `YEAR(fecha_origen) > YEAR(fecha_relacionado)` |

---

### A-05 · Complemento de pago — vista tradicional

**Propósito.** Conciliar cobranza y pagos contra el flujo real, y determinar IVA por flujo de efectivo (insumo de D-01).

**Grano.** **Una fila por `pago_docto`** — es decir, una fila por cada documento pagado en cada pago. Un REP con 2 pagos que cubren 5 facturas cada uno genera 10 filas.

**Columnas.**

| # | Columna | Tipo | Origen / Fórmula |
|---|---|---|---|
| 1 | UUID del REP | UUID **[X]** | `cfdi_comprobante.uuid` |
| 2 | Serie / Folio REP | TEXT **[X]** | |
| 3 | Fecha emisión REP | TS **[X]** | `fecha` |
| 4 | Estado SAT del REP | TEXT **[D]** | |
| 5 | RFC / Nombre emisor | — **[X]** | |
| 6 | RFC / Nombre receptor | — **[X]** | |
| 7 | Núm. de pago | INT **[D]** | `pago.num_pago` |
| 8 | Fecha de pago | TS **[X]** | `pago.fecha_pago` |
| 9 | Forma de pago | TEXT **[X]** | `forma_de_pago_p` + descripción |
| 10 | Moneda del pago | TEXT **[X]** | `moneda_p` |
| 11 | Tipo de cambio del pago | DEC **[X]** | `tipo_cambio_p` |
| 12 | Monto del pago | MONTO **[X]** | `pago.monto` |
| 13 | Núm. de operación | TEXT **[X]** | `num_operacion` |
| 14 | Banco ordenante / cuenta | TEXT **[X]** | `rfc_emisor_cta_ord`, `cta_ordenante` |
| 15 | UUID documento pagado | UUID **[X]** | `id_documento` |
| 16 | Serie / Folio documento | TEXT **[X]** | |
| 17 | Fecha del documento | TS **[D]** | `JOIN` a `cfdi_comprobante` por `id_documento` |
| 18 | Total del documento | MONTO **[D]** | |
| 19 | Moneda del documento | TEXT **[X]** | `moneda_dr` |
| 20 | Equivalencia | DEC **[X]** | `equivalencia_dr` |
| 21 | Parcialidad | INT **[X]** | `num_parcialidad` |
| 22 | Saldo anterior | MONTO **[X]** | `imp_saldo_ant` |
| 23 | Importe pagado | MONTO **[X]** | `imp_pagado` |
| 24 | Saldo insoluto | MONTO **[X]** | `imp_saldo_insoluto` |
| 25 | Importe pagado en moneda del pago | MONTO **[D]** | `⌊imp_pagado / equivalencia_dr⌉₂` |
| 26 | Importe pagado MXN | MONTO **[D]** | `⌊imp_pagado / equivalencia_dr × tipo_cambio_p⌉₂` |
| 27 | % del documento cubierto | DEC **[D]** | `imp_pagado / total_documento` |
| 28 | Días de crédito | INT **[D]** | `DATEDIFF(fecha_pago, fecha_documento)` |
| 29 | Base IVA 16 % del pago | MONTO **[D]** | De `pago_docto_impuesto` |
| 30 | IVA 16 % del pago | MONTO **[D]** | |
| 31 | Bases y montos de otras tasas | MONTO **[D]** | Una pareja de columnas por tasa presente |
| 32 | Objeto impuesto DR | TEXT **[X]** | `objeto_imp_dr` |

**Reglas de cálculo.**

- **A-05.R1 — Dirección de `EquivalenciaDR`.** `@EquivalenciaDR` expresa cuántas unidades de `MonedaDR` equivalen a **una** unidad de `MonedaP`. Por tanto se **divide**, no se multiplica: `monto_en_moneda_pago = imp_pagado / equivalencia_dr`. Invertir esta operación es el error más frecuente en la implementación de este informe.
- **A-05.R2 — Coherencia del pago.** `pago.monto` debe igualar `Σ (imp_pagado / equivalencia_dr)` de sus documentos relacionados. ⚠ `PAGO_DESCUADRADO` si `|diferencia| > 0.01`.
- **A-05.R3 — Progresión de saldos.** Para un mismo `id_documento`, ordenando por `num_parcialidad`: `imp_saldo_ant(n) = imp_saldo_insoluto(n−1)` y `imp_saldo_insoluto(n) = imp_saldo_ant(n) − imp_pagado(n)`. ⚠ `SALDOS_INCONSISTENTES` ante cualquier ruptura.
- **A-05.R4 — Parcialidad 1.** En la primera parcialidad `imp_saldo_ant` debe igualar el `total` del documento original. ⚠ `SALDO_INICIAL_DISTINTO` en caso contrario; suele indicar que hubo una nota de crédito no considerada.

---

### A-06 · Complemento de pago — vista jerárquica

**Propósito.** Misma información que A-05 con presentación por documento, para revisión visual de la cobranza de una factura específica.

**Grano.** Jerarquía de tres niveles, con una columna `nivel` que discrimina:

```
nivel 1 → Documento original (una fila por factura PPD)
  nivel 2 → Pago (una fila por cada REP que la cubre)
    nivel 3 → Detalle del pago (parcialidad, impuestos)
```

**Columnas del nivel 1 (agregado por factura).**

| # | Columna | Tipo | Fórmula |
|---|---|---|---|
| 1 | UUID factura | UUID | |
| 2 | Serie / Folio / Fecha | TEXT | |
| 3 | RFC / Nombre contraparte | TEXT | |
| 4 | Total factura | MONTO | `total` |
| 5 | Total pagado | MONTO **[D]** | `Σ (imp_pagado / equivalencia_dr)` de todos los `pago_docto` con `id_documento = uuid` **y REP vigente** |
| 6 | Saldo | MONTO **[D]** | `total − total_pagado − egresos_aplicados` |
| 7 | Núm. de REP | INT **[D]** | `COUNT(DISTINCT rep.uuid)` |
| 8 | Núm. de parcialidades | INT **[D]** | `COUNT(pago_docto.id)` |
| 9 | Fecha del primer pago | FECHA **[D]** | `MIN(fecha_pago)` |
| 10 | Fecha del último pago | FECHA **[D]** | `MAX(fecha_pago)` |
| 11 | Días para liquidar | INT **[D]** | `DATEDIFF(MAX(fecha_pago), fecha_factura)` si saldo = 0, si no `NULL` |
| 12 | Días vencido | INT **[D]** | `DATEDIFF(HOY, fecha_factura)` si saldo > 0 |
| 13 | Estatus | TEXT **[D]** | Ver A-06.R1 |

**Reglas.**

- **A-06.R1 — Estatus de la factura.**
  ```
  LIQUIDADA          si |saldo| <= 0.01
  PARCIAL            si 0.01 < saldo < total
  SIN PAGO           si saldo == total y no hay REP
  SOBREPAGADA        si saldo < -0.01
  CANCELADA          si estado_sat = 'CANCELADO'
  ```
- **A-06.R2 — REP cancelados.** Un REP cancelado **no** cuenta como pago. Se excluye del cálculo de `total_pagado` y se reporta en una columna aparte `Pagos en REP cancelados` para que el descuadre sea explicable.
- **A-06.R3 — Universo del nivel 1.** Solo facturas con `metodo_pago = 'PPD'` **más** las facturas PUE que aparezcan referidas en algún REP (situación irregular que debe visibilizarse, no ocultarse). ⚠ `PUE_CON_REP`.

---

## Grupo B — Informes de nómina

Todos los informes de este grupo asumen `tipo_comprobante = 'N'` y la existencia del complemento Nómina 1.2. El periodo se determina por `nomina.fecha_pago` (R-T6).

### B-00 · Definiciones comunes al grupo

Estas definiciones se referencian desde todas las fichas del grupo.

```
-- Empleado: la identidad del trabajador
--   Clave primaria de negocio: rfc_receptor
--   Clave secundaria: curp (para detectar RFC duplicados o mal capturados)
--   Clave del patrón: num_empleado (NO es única entre organizaciones)

percepciones(uuid) = Σ nomina_percepcion.(importe_gravado + importe_exento)
gravado(uuid)      = Σ nomina_percepcion.importe_gravado
exento(uuid)       = Σ nomina_percepcion.importe_exento
otros_pagos(uuid)  = Σ nomina_otro_pago.importe
deducciones(uuid)  = Σ nomina_deduccion.importe
neto(uuid)         = percepciones + otros_pagos - deducciones

isr_retenido(uuid) = Σ nomina_deduccion.importe WHERE tipo_deduccion = '002'
imss_retenido(uuid)= Σ nomina_deduccion.importe WHERE tipo_deduccion = '001'
subsidio(uuid)     = Σ nomina_otro_pago.subsidio_causado WHERE tipo_otro_pago = '002'
subsidio_aplicado(uuid) = Σ nomina_otro_pago.importe WHERE tipo_otro_pago = '002'
```

**Identidades que el XML debe cumplir** (base de las validaciones de todo el grupo):

| Identidad | Tolerancia |
|---|---|
| `nomina.total_percepciones = percepciones(uuid)` | 0.01 |
| `nomina.total_deducciones = deducciones(uuid)` | 0.01 |
| `nomina.total_otros_pagos = otros_pagos(uuid)` | 0.01 |
| `nomina_percepciones_tot.total_gravado = gravado(uuid)` | 0.01 |
| `nomina_percepciones_tot.total_exento = exento(uuid)` | 0.01 |
| `cfdi_comprobante.subtotal = total_percepciones + total_otros_pagos` | 0.01 |
| `cfdi_comprobante.descuento = total_deducciones` | 0.01 |
| `cfdi_comprobante.total = subtotal − descuento` | 0.01 |
| `nomina_deducciones_tot.total_impuestos_retenidos = isr_retenido(uuid)` | 0.01 |

---

### B-01 · Nómina agrupada por catálogo SAT

**Propósito.** Vista estable en número de columnas, apta para contabilización: agrupa por tipo del catálogo del SAT y no depende de las claves internas del patrón. Es el formato correcto para alimentar pólizas contables porque el conjunto de columnas no cambia entre periodos.

**Grano.** Una fila por `uuid`.

**Columnas.**

| Bloque | Columnas | Fórmula |
|---|---|---|
| Identificación | Ejercicio, Periodo, UUID, Serie, Folio, Fecha emisión, Fecha timbrado, Versión CFDI, Versión nómina, Estado SAT | De `cfdi_comprobante` |
| Nómina | Tipo nómina, Fecha pago, Fecha inicial, Fecha final, Días pagados, Periodicidad | De `nomina` |
| Patrón | RFC emisor, Razón social, Régimen, Registro patronal, RFC patrón origen, Origen del recurso, Monto recurso propio | De `cfdi_comprobante` + `nomina` |
| Empleado | RFC, Nombre, CURP, NSS, Núm. empleado, Departamento, Puesto, Riesgo puesto, Tipo contrato, Tipo jornada, Tipo régimen, Sindicalizado, Entidad federativa, Banco, Fecha inicio relación laboral, SBC, SDI | De `nomina_receptor` |
| **Percepciones por tipo** | Una columna por cada `tipo_percepcion` presente **en el catálogo**, no en los datos | `Σ (gravado + exento)` agrupado por `tipo_percepcion` |
| Totales percepciones | Total sueldos, Total separación/indemnización, Total jubilación/pensión/retiro, Total gravado, Total exento, Total percepciones | De `nomina_percepciones_tot` y `nomina` |
| **Deducciones por tipo** | Una columna por cada `tipo_deduccion` presente en el catálogo | `Σ importe` agrupado por `tipo_deduccion` |
| Totales deducciones | Total otras deducciones, Total impuestos retenidos, Total deducciones | |
| **Otros pagos por tipo** | Una columna por cada `tipo_otro_pago` | `Σ importe` agrupado por `tipo_otro_pago` |
| Subsidio | Subsidio causado, Subsidio aplicado | Ver B-00 |
| Neto | Total | `nomina.total` |

**Reglas.**

- **B-01.R1 — Conjunto de columnas fijo.** Las columnas de tipo se generan desde el **catálogo**, con cero cuando no hay datos. Esto hace el informe comparable entre periodos y entre organizaciones. Es la diferencia esencial con B-02.
- **B-01.R2 — Opción de conjunto reducido.** Cuando el número de columnas es un problema práctico (46 tipos de percepción + 107 de deducción = 153 columnas), se admite el parámetro `solo_tipos_con_movimiento` **[P]**, que restringe al conjunto observado en el periodo. Al activarlo, el informe deja de ser comparable entre periodos y debe rotularse como tal en la cabecera.

---

### B-02 · Nómina agrupada por conceptos del patrón

> **Este es el informe que producen OneFacture ("Agrupado por conceptos en nóminas"), ezaudita, MiAdminXML ("Reporte especial de Nómina 1.2") y Audita CFDI ("reporte detallado por conceptos").** Es el más usado y el peor especificado de los tres.

**Propósito.** Reproducir la estructura de la nómina tal como la concibe el patrón, con sus claves y descripciones internas, para cotejar el CFDI timbrado contra el recibo del sistema de nómina, concepto por concepto.

**Grano.** Una fila por `uuid`. Cada concepto distinto del patrón es una **columna generada en tiempo de ejecución**.

**Parámetros.**

| Parámetro | Tipo | Default |
|---|---|---|
| `rfc_contribuyente` | RFC | — |
| `fecha_desde`, `fecha_hasta` | FECHA | — |
| `tipo_nomina` | `O` \| `E` \| AMBOS | AMBOS |
| `incluir_cancelados` | BOOL | `false` |
| `desglosar_gravado_exento` | BOOL | `false` |
| `separador_etiqueta` | CHAR | `\u00A6` |
| `emitir_diccionario` | BOOL | `true` |

**Algoritmo de construcción.**

```
FASE 1 — Determinar el universo de comprobantes
  U = { uuid : tipo_comprobante='N'
              AND rfc_contribuyente = [P]
              AND nomina.fecha_pago BETWEEN [P] AND [P]
              AND (tipo_nomina = [P] OR [P] = 'AMBOS')
              AND (estado_sat='VIGENTE' OR incluir_cancelados) }

FASE 2 — Determinar el conjunto de columnas dinámicas
  C = SELECT DISTINCT 'P' AS naturaleza, tipo_percepcion AS tipo, clave
        FROM nomina_percepcion WHERE uuid IN U
      UNION ALL
      SELECT DISTINCT 'D', tipo_deduccion, clave
        FROM nomina_deduccion  WHERE uuid IN U
      UNION ALL
      SELECT DISTINCT 'O', tipo_otro_pago, clave
        FROM nomina_otro_pago  WHERE uuid IN U

  Para cada (naturaleza, tipo, clave) en C:
      concepto_canonico = descripción con mayor frecuencia en U
                          (empate → la de fecha_pago más reciente)
      etiqueta = tipo || SEP || clave || SEP || concepto_canonico
      SI existen >1 descripciones distintas → bandera CONCEPTO_INCONSISTENTE

FASE 3 — Ordenar las columnas
  ORDER BY naturaleza (P, O, D), tipo ASC (como texto), clave ASC (como texto)
  Las percepciones primero, otros pagos después, deducciones al final.
  Este orden replica el orden de lectura de un recibo de nómina.

FASE 4 — Emitir filas
  Para cada uuid en U:
      columnas fijas (ver abajo)
      para cada columna c en C:
          si desglosar_gravado_exento = false:
              valor = COALESCE(Σ importe del concepto c en ese uuid, 0)
          si = true y naturaleza = 'P':
              se emiten dos columnas: c||' (G)' y c||' (E)'
      columnas de totales

FASE 5 — Emitir hoja Diccionario (si emitir_diccionario)
      etiqueta | naturaleza | tipo | descripción del catálogo SAT |
      clave del patrón | concepto canónico | descripciones alternas |
      núm. de comprobantes | importe total del periodo
```

**Columnas fijas.** Bloques de identificación, nómina, patrón y empleado idénticos a B-01. Bloque de totales al final:

| Columna | Fórmula |
|---|---|
| Total sueldos | `nomina_percepciones_tot.total_sueldos` |
| Total separación indemnización | `nomina_percepciones_tot.total_separacion_indemnizacion` |
| Total jubilación pensión retiro | `nomina_percepciones_tot.total_jubilacion_pension_retiro` |
| Total percepciones | `nomina.total_percepciones` |
| Total gravado | `nomina_percepciones_tot.total_gravado` |
| Total exento | `nomina_percepciones_tot.total_exento` |
| Total otros pagos | `nomina.total_otros_pagos` |
| Total deducciones | `nomina.total_deducciones` |
| Total (neto) | `cfdi_comprobante.total` |

**Reglas de cálculo.**

- **B-02.R1 — Concepto repetido en un mismo comprobante.** El esquema Nómina 1.2 **permite** varios nodos `Percepcion` con el mismo `(TipoPercepcion, Clave)` en un mismo CFDI (por ejemplo, dos bloques de horas extra en semanas distintas). El valor de la celda es la **suma**, no el último valor leído. Implementar con `SUM(...)` y no con asignación directa; sobrescribir es un error silencioso que subvalúa la nómina.
- **B-02.R2 — Identidad del concepto.** Ver R-T9. La celda se resuelve por `(tipo, clave)`, nunca por la descripción.
- **B-02.R3 — Colisión de claves entre naturalezas.** `tipo_percepcion='002'` (aguinaldo) y `tipo_deduccion='002'` (ISR) comparten el texto `002`. La etiqueta **debe** llevar el prefijo de naturaleza o incluir un sufijo distintivo; de lo contrario dos conceptos distintos colapsan en una columna. Este es el defecto más grave de los reportes comerciales que emiten solo `tipo/clave/concepto` sin naturaleza.
- **B-02.R4 — Nulos.** R-T7: cero, no vacío.
- **B-02.R5 — Estabilidad entre corridas.** Dos ejecuciones con el mismo periodo deben producir el mismo orden de columnas. Por eso el `ORDER BY` de la fase 3 es determinista y no depende del orden de aparición en la base.
- **B-02.R6 — Conceptos espejo.** Ver R-T10. En este informe el fondo de ahorro suele aparecer tres veces (percepción exenta, otro pago, deducción) por el mismo importe. **No se consolidan**: el informe refleja el XML. La hoja `Diccionario` marca el grupo espejo para que quien sume columnas manualmente lo advierta.

**Validaciones.**

| Bandera | Condición |
|---|---|
| `TOTALES_DESCUADRADOS` | Cualquiera de las identidades de B-00 fuera de tolerancia |
| `CONCEPTO_INCONSISTENTE` | Mismo `(naturaleza, tipo, clave)` con varias descripciones |
| `CLAVE_VACIA` | `clave` nula o cadena vacía — impide identificar el concepto |
| `PERIODO_TRASLAPADO` | Dos comprobantes del mismo empleado con rangos `[fecha_inicial_pago, fecha_final_pago]` que se intersectan y `tipo_nomina='O'` |
| `PERIODO_FALTANTE` | Hueco en la secuencia de periodos esperada según `periodicidad_pago` (ver B-04.R2) |
| `DIAS_PAGADOS_ATIPICO` | `num_dias_pagados` fuera del rango esperado para la periodicidad: quincenal → [1, 16], mensual → [1, 31], semanal → [1, 7] |
| `NETO_NEGATIVO` | `total < 0` |
| `DEDUCCION_MAYOR_PERCEPCION` | `deducciones > percepciones + otros_pagos` |

---

### B-03 · Desglose gravado / exento por percepción

**Propósito.** Verificar la correcta aplicación de las exenciones del artículo 93 de la LISR concepto por concepto. Es el informe que el SAT reconstruye para determinar diferencias de ISR de nómina.

**Grano.** Una fila por `nomina_percepcion.id` (formato largo, no pivotado).

**Columnas.**

| # | Columna | Tipo | Fórmula |
|---|---|---|---|
| 1 | UUID | UUID **[X]** | |
| 2 | Fecha pago / Periodo | — **[X]** | |
| 3 | RFC empleado / Nombre | — **[X]** | |
| 4 | Núm. empleado / Departamento / Puesto | — **[X]** | |
| 5 | Días pagados | DEC **[X]** | `num_dias_pagados` |
| 6 | Tipo percepción | TEXT **[X]** | `tipo_percepcion` |
| 7 | Descripción SAT | TEXT **[D]** | De `c_TipoPercepcion` |
| 8 | Clave patrón | TEXT **[X]** | `clave` |
| 9 | Concepto patrón | TEXT **[X]** | `concepto` |
| 10 | Importe gravado | MONTO **[X]** | `importe_gravado` |
| 11 | Importe exento | MONTO **[X]** | `importe_exento` |
| 12 | Importe total | MONTO **[D]** | `importe_gravado + importe_exento` |
| 13 | % exento | DEC **[D]** | `importe_exento / importe_total` |
| 14 | Base de exención aplicable | TEXT **[D]** | `c_TipoPercepcion.base_exencion` |
| 15 | Tope de exención | MONTO **[D]** | Ver B-03.R1 |
| 16 | Exceso sobre el tope | MONTO **[D]** | `MAX(0, importe_exento − tope_exencion)` |
| 17 | UMA aplicable | MONTO **[D]** | Valor de `param_fiscal` clave `UMA_DIARIA` vigente a `fecha_pago` |

**Reglas de cálculo.**

- **B-03.R1 — Tope de exención.** Se resuelve por tipo de percepción según `c_TipoPercepcion.base_exencion` y `factor_exencion`, evaluados con el valor de UMA vigente a `fecha_pago`:
  ```
  base_exencion = 'UMA_DIAS'    → tope = factor_exencion × UMA_DIARIA
  base_exencion = 'PORCENTAJE'  → tope = factor_exencion × importe_total
  base_exencion = 'NINGUNA'     → tope = 0    (todo el importe debe ser gravado)
  ```
  Los valores de `factor_exencion` **se cargan desde configuración**, no se codifican. Se auditan contra el artículo 93 de la LISR vigente al ejercicio.
- **B-03.R2 — Acumulación anual de topes.** Varias exenciones son anuales, no por periodo (el caso típico es el aguinaldo). El tope debe evaluarse contra el **acumulado del ejercicio** del mismo empleado y tipo de percepción, no contra el importe del periodo aislado:
  ```
  exento_acumulado(rfc, tipo, ejercicio) = Σ importe_exento
      WHERE rfc_receptor = rfc AND tipo_percepcion = tipo
        AND YEAR(fecha_pago) = ejercicio AND estado_sat='VIGENTE'
  ```
  ⚠ `EXENCION_EXCEDIDA` cuando `exento_acumulado > tope_anual`.
- **B-03.R3 — Percepciones que no admiten exención.** Los tipos marcados con `base_exencion='NINGUNA'` (sueldos, comisiones, entre otros) con `importe_exento > 0` generan ⚠ `EXENCION_INDEBIDA`. Es un hallazgo de auditoría directo.

---

### B-04 · Matriz empleado × periodo

**Propósito.** Detectar en una sola vista quincenas faltantes, altas y bajas no documentadas, y saltos anómalos de sueldo. Es el informe de control de completitud de la nómina.

**Grano.** Una fila por empleado. Una columna por periodo de pago.

**Algoritmo.**

```
FASE 1 — Construir el eje de periodos
  Determinar la periodicidad dominante del conjunto:
      periodicidad = MODA(nomina_receptor.periodicidad_pago)
  Generar la secuencia teórica de fechas de corte entre [fecha_desde, fecha_hasta]:
      04 Quincenal → días 15 y último de cada mes
      02 Semanal   → cada 7 días a partir del primer corte observado
      05 Mensual   → último día de cada mes
      03 Catorcenal→ cada 14 días
      06 Decenal   → días 10, 20 y último
  Etiqueta de columna = 'YYYY-MM Q1' | 'YYYY-MM Q2' | 'YYYY-Sxx' | 'YYYY-MM'

FASE 2 — Asignar cada CFDI a un periodo
  Se asigna por fecha_final_pago (no por fecha_pago), porque el pago puede
  adelantarse o retrasarse sin que cambie el periodo devengado.
  Si fecha_final_pago no cae en un corte teórico, se asigna al corte
  más cercano y se marca ⚠ CORTE_IRREGULAR.

FASE 3 — Emitir la matriz
  Celda(empleado, periodo) = métrica seleccionada [P]
  Métrica ∈ { NETO, TOTAL_PERCEPCIONES, GRAVADO, ISR_RETENIDO,
              DIAS_PAGADOS, NUM_CFDI }
  Celda vacía → '—' y bandera si el empleado estaba activo (ver B-04.R2)
```

**Columnas fijas.** RFC, CURP, Nombre, Núm. empleado, Departamento, Puesto, Fecha inicio relación laboral, Fecha del primer CFDI en el rango, Fecha del último CFDI, Núm. de periodos con pago, Núm. de periodos esperados, % de cobertura, Total del rango, Promedio por periodo, Desviación estándar, Coeficiente de variación.

**Reglas.**

- **B-04.R1 — Periodos esperados.** Se cuenta desde `MAX(fecha_desde, fecha_inicio_rel_laboral)` hasta `MIN(fecha_hasta, fecha_baja)` si se dispone de `plantilla_rh`; si no, hasta `fecha_hasta`.
- **B-04.R2 — Bandera de hueco.** ⚠ `PERIODO_FALTANTE` cuando la celda está vacía **y** existe al menos un CFDI del mismo empleado en un periodo posterior dentro del rango. Un hueco al final de la serie es una baja probable, no un error; un hueco intermedio es una omisión de timbrado.
- **B-04.R3 — Bandera de variación.** ⚠ `VARIACION_ANOMALA` cuando `|celda(n) − celda(n−1)| / celda(n−1) > 0.30` y ambos periodos tienen `num_dias_pagados` iguales. La condición sobre días evita marcar quincenas cortas legítimas.
- **B-04.R4 — Duplicados.** ⚠ `PERIODO_DUPLICADO` cuando `NUM_CFDI > 1` en una celda con `tipo_nomina='O'`. Dos nóminas ordinarias del mismo periodo para el mismo empleado casi siempre son un timbrado doble.

---

### B-05 · Acumulado anual por empleado

**Propósito.** Papel de trabajo del cálculo anual del ISR (art. 97 LISR) y base de la constancia de percepciones. Es el informe que consolida el ejercicio completo.

**Grano.** Una fila por `(rfc_receptor, ejercicio)`.

**Columnas.**

| # | Columna | Tipo | Fórmula |
|---|---|---|---|
| 1 | Ejercicio | INT **[P]** | |
| 2 | RFC / CURP / Nombre / Núm. empleado | — **[D]** | Del CFDI más reciente del ejercicio |
| 3 | Fecha inicio relación laboral | FECHA **[D]** | `MIN(fecha_inicio_rel_laboral)` |
| 4 | Fecha primer pago del ejercicio | FECHA **[D]** | `MIN(fecha_pago)` |
| 5 | Fecha último pago del ejercicio | FECHA **[D]** | `MAX(fecha_pago)` |
| 6 | Núm. de CFDI | INT **[D]** | `COUNT(DISTINCT uuid)` |
| 7 | Días pagados del ejercicio | DEC **[D]** | `Σ num_dias_pagados` |
| 8 | Total percepciones | MONTO **[D]** | `Σ percepciones(uuid)` |
| 9 | Total gravado | MONTO **[D]** | `Σ gravado(uuid)` |
| 10 | Total exento | MONTO **[D]** | `Σ exento(uuid)` |
| 11 | Gravado ordinario | MONTO **[D]** | `Σ importe_gravado` de percepciones con `es_ingreso_ordinario = true` |
| 12 | Ingreso por separación | MONTO **[D]** | `Σ total_separacion_indemnizacion` |
| 13 | Ingreso por jubilación | MONTO **[D]** | `Σ total_jubilacion_pension_retiro` |
| 14 | ISR retenido | MONTO **[D]** | `Σ isr_retenido(uuid)` |
| 15 | Subsidio causado | MONTO **[D]** | `Σ subsidio(uuid)` |
| 16 | Subsidio entregado en efectivo | MONTO **[D]** | `Σ subsidio_aplicado(uuid)` |
| 17 | IMSS retenido | MONTO **[D]** | `Σ imss_retenido(uuid)` |
| 18 | Aportaciones a fondo de ahorro | MONTO **[D]** | `Σ importe` donde `tipo_deduccion='004'` |
| 19 | Descuentos Infonavit | MONTO **[D]** | `Σ importe` donde `tipo_deduccion='009'` |
| 20 | Otras deducciones | MONTO **[D]** | `Σ deducciones − ISR − IMSS − 004 − 009` |
| 21 | Neto pagado | MONTO **[D]** | `Σ neto(uuid)` |
| 22 | SBC promedio ponderado | MONTO **[D]** | `Σ(SBC × días) / Σ días` |
| 23 | SDI promedio ponderado | MONTO **[D]** | `Σ(SDI × días) / Σ días` |
| 24 | ISR anual teórico | MONTO **[D]** | Ver Anexo I.2, sobre la columna 11 |
| 25 | Diferencia a cargo / favor | MONTO **[D]** | `ISR_anual_teórico − ISR_retenido − subsidio_causado` |
| 26 | Sujeto a cálculo anual | BOOL **[D]** | Ver B-05.R2 |

**Reglas.**

- **B-05.R1 — Universo.** Solo comprobantes `VIGENTE`. Un CFDI de nómina cancelado y sustituido debe contar **una** vez: se toma el sustituto. La cadena de sustitución se resuelve por `cfdi_relacionado` con `tipo_relacion='04'`.
- **B-05.R2 — Exclusión del cálculo anual.** El patrón no calcula el impuesto anual del trabajador que (a) inició la relación después del 1 de enero o la terminó antes del 1 de diciembre, (b) obtuvo ingresos anuales superiores al umbral vigente, o (c) comunicó por escrito que presentará declaración. Los criterios (a) y (b) son derivables de este informe; (c) requiere captura externa. Se emite la bandera `REVISAR_CALCULO_ANUAL` y **no** se afirma la obligación.
- **B-05.R3 — Ingresos de dos patrones.** Si el mismo `rfc_receptor` aparece con dos `rfc_emisor` distintos en el ejercicio, el cálculo anual de la columna 24 es incompleto por construcción. ⚠ `MULTI_PATRON`. Este caso es frecuente en redes de organizaciones que comparten personal.
- **B-05.R4 — Separación e indemnización.** Los ingresos de las columnas 12 y 13 tienen régimen fiscal propio (arts. 95 y 96 LISR) y **no** se acumulan al gravado ordinario para el cálculo de la columna 24. Sumarlos sobreestima el ISR anual.

---

### B-06 · Costo de nómina por centro de costo

**Propósito.** Determinar el costo laboral por departamento, programa o proyecto. Para organizaciones que ejecutan recursos etiquetados, es el insumo de la comprobación ante el financiador.

**Grano.** Una fila por `(periodo, centro_costo)`; con parámetro `detalle_empleado` **[P]**, una fila por `(periodo, centro_costo, rfc_receptor)`.

**Columnas.**

| # | Columna | Tipo | Fórmula |
|---|---|---|---|
| 1 | Ejercicio / Periodo | INT **[D]** | |
| 2 | Centro de costo | TEXT **[D]** | Ver B-06.R1 |
| 3 | Núm. de empleados | INT **[D]** | `COUNT(DISTINCT rfc_receptor)` |
| 4 | Núm. de CFDI | INT **[D]** | |
| 5 | Días pagados | DEC **[D]** | `Σ num_dias_pagados` |
| 6 | Sueldos | MONTO **[D]** | `Σ (gravado+exento)` con `tipo_percepcion='001'` |
| 7 | Prestaciones | MONTO **[D]** | `Σ (gravado+exento)` con `tipo_percepcion NOT IN ('001','046')` |
| 8 | Asimilados | MONTO **[D]** | `Σ` con `tipo_percepcion='046'` |
| 9 | Total percepciones | MONTO **[D]** | `Σ percepciones(uuid)` |
| 10 | Otros pagos | MONTO **[D]** | `Σ otros_pagos(uuid)` |
| 11 | Costo bruto | MONTO **[D]** | `columna 9 + columna 10` |
| 12 | ISR retenido | MONTO **[D]** | |
| 13 | IMSS obrero retenido | MONTO **[D]** | |
| 14 | Neto pagado | MONTO **[D]** | `Σ neto(uuid)` |
| 15 | Costo patronal estimado | MONTO **[D]** | Ver B-06.R2 |
| 16 | Costo total estimado | MONTO **[D]** | `columna 11 + columna 15` |
| 17 | Costo promedio por empleado | MONTO **[D]** | `columna 16 / columna 3` |
| 18 | % del total del periodo | DEC **[D]** | `columna 16 / Σ columna 16 del periodo` |

**Reglas.**

- **B-06.R1 — Resolución del centro de costo.** En orden de precedencia:
  1. `plantilla_rh.centro_costo` por `rfc` o `num_empleado`, si la tabla existe.
  2. Tabla de mapeo `map_departamento (departamento_texto → centro_costo)`, obligatoria porque `nomina_receptor.departamento` es texto libre y presenta variantes ortográficas del mismo departamento.
  3. `nomina_receptor.departamento` en crudo.
  ⚠ `DEPARTAMENTO_SIN_MAPEO` cuando se cae al nivel 3. El informe reporta el número de filas en cada nivel para que la calidad del agrupamiento sea auditable.
- **B-06.R2 — Costo patronal.** **No** es derivable del CFDI. El complemento de nómina solo contiene la parte obrera de las cuotas. La columna 15 se calcula con las tasas de cuotas patronales del IMSS, INFONAVIT y el impuesto estatal sobre nómina cargadas en `param_fiscal`, aplicadas sobre el SBC:
  ```
  costo_patronal ≈ Σ ( SBC × dias × Σ tasas_patronales_aplicables )
                 + Σ ( base_isn × tasa_isn_estatal )
  ```
  Se rotula explícitamente como **estimación** en la cabecera del informe. Presentarla como dato del CFDI es incorrecto.
- **B-06.R3 — Empleado en varios centros.** Si un empleado aparece con distinto departamento entre periodos, cada CFDI se asigna al departamento declarado en ese CFDI. No se retropropaga el departamento actual.

---

### B-07 · Cartera de préstamos y descuentos recurrentes

**Propósito.** Rastrear el saldo de préstamos (empresa, Infonavit, FONACOT) y descuentos recurrentes por empleado. Ninguna herramienta comercial lo hace porque el CFDI no contiene el saldo, solo el descuento del periodo.

**Grano.** Una fila por `(rfc_receptor, tipo_deduccion, clave)`.

**Columnas.**

| # | Columna | Tipo | Fórmula |
|---|---|---|---|
| 1 | RFC / Nombre / Núm. empleado | — **[D]** | |
| 2 | Tipo deducción | TEXT **[X]** | `tipo_deduccion` + descripción SAT |
| 3 | Clave / Concepto | TEXT **[X]** | |
| 4 | Primer descuento | FECHA **[D]** | `MIN(fecha_pago)` |
| 5 | Último descuento | FECHA **[D]** | `MAX(fecha_pago)` |
| 6 | Núm. de descuentos | INT **[D]** | `COUNT(*)` |
| 7 | Descuento promedio | MONTO **[D]** | `AVG(importe)` |
| 8 | Descuento modal | MONTO **[D]** | Valor más frecuente; identifica la amortización pactada |
| 9 | Total descontado | MONTO **[D]** | `Σ importe` |
| 10 | Monto original | MONTO **[P]** | Captura externa; el CFDI no lo contiene |
| 11 | Saldo estimado | MONTO **[D]** | `monto_original − total_descontado` |
| 12 | Descuentos restantes | INT **[D]** | `CEIL(saldo_estimado / descuento_modal)` |
| 13 | Fecha estimada de liquidación | FECHA **[D]** | `fecha_ultimo + descuentos_restantes × longitud_periodo` |
| 14 | Continuidad | TEXT **[D]** | Ver B-07.R1 |

**Reglas.**

- **B-07.R1 — Continuidad.** Se compara la serie de periodos con descuento contra la secuencia teórica de B-04:
  ```
  CONTINUO      sin huecos entre primer y último descuento
  INTERRUMPIDO  n huecos intermedios (se listan)
  CONCLUIDO     último descuento anterior al último periodo del rango
  ```
  ⚠ `DESCUENTO_INTERRUMPIDO` es un hallazgo relevante: un préstamo cuyo descuento se detuvo sin liquidarse.
- **B-07.R2 — Sin monto original.** Cuando la columna 10 no se captura, las columnas 11 a 13 quedan vacías y el informe conserva su valor como control de continuidad. No se estima el monto original a partir del descuento.
- **B-07.R3 — Cambio de amortización.** Si el `descuento modal` cambia a mitad de la serie, se emite ⚠ `AMORTIZACION_MODIFICADA` con las dos fases y sus fechas. Es lo esperado en créditos Infonavit al actualizarse el factor de descuento.

---

### B-08 · Provisión de pasivo laboral

**Propósito.** Cuantificar el pasivo devengado no pagado por aguinaldo, vacaciones y prima vacacional, con base en los CFDI timbrados. Es la cifra que el auditor externo solicita al cierre.

**Grano.** Una fila por `rfc_receptor`.

**Columnas.**

| # | Columna | Tipo | Fórmula |
|---|---|---|---|
| 1 | RFC / Nombre / Núm. empleado / Departamento | — **[D]** | |
| 2 | Fecha inicio relación laboral | FECHA **[D]** | |
| 3 | Antigüedad en años | DEC **[D]** | `DATEDIFF(fecha_corte, fecha_inicio) / 365.25` |
| 4 | Salario diario base | MONTO **[D]** | Ver B-08.R1 |
| 5 | Días de aguinaldo | INT **[P]** | Configuración por organización; mínimo legal 15 |
| 6 | Aguinaldo devengado | MONTO **[D]** | `salario_diario × dias_aguinaldo × (dias_trabajados_ejercicio / 365)` |
| 7 | Aguinaldo pagado en el ejercicio | MONTO **[D]** | `Σ (gravado+exento)` con `tipo_percepcion='002'` y `YEAR(fecha_pago)=ejercicio` |
| 8 | Provisión de aguinaldo | MONTO **[D]** | `MAX(0, columna 6 − columna 7)` |
| 9 | Días de vacaciones del año en curso | INT **[D]** | Tabla `tabla_vacaciones (años_antiguedad → días)`, configurable |
| 10 | Vacaciones pagadas en el ejercicio | MONTO **[D]** | `Σ` con `tipo_percepcion IN ('001' con clave de vacaciones, '021')` según mapeo |
| 11 | Días de vacaciones pendientes | DEC **[P/D]** | Requiere saldo de RH; si no existe, se estima con el devengo proporcional |
| 12 | Provisión de vacaciones | MONTO **[D]** | `salario_diario × dias_pendientes` |
| 13 | Prima vacacional devengada | MONTO **[D]** | `columna 12 × factor_prima` (mínimo legal 0.25) |
| 14 | Provisión total | MONTO **[D]** | `columna 8 + columna 12 + columna 13` |

**Reglas.**

- **B-08.R1 — Salario diario base de la provisión.** En orden de preferencia:
  1. `plantilla_rh.sueldo_mensual / 30`.
  2. `Σ (gravado+exento de tipo_percepcion='001') / Σ num_dias_pagados` de los últimos 3 periodos ordinarios. Esta es la opción derivable del CFDI y la preferida cuando no hay RH.
  3. `nomina_receptor.salario_diario_integrado` — **último recurso**: el SDI incluye la parte proporcional de aguinaldo y prima, por lo que usarlo sobreestima la provisión al integrar dos veces esos conceptos.
  El informe declara en cada fila qué fuente se usó.
- **B-08.R2 — Identificación de vacaciones.** El catálogo del SAT no tiene un tipo exclusivo de vacaciones: se timbran normalmente como `001` (sueldos) o `019`/`021` según la práctica del patrón. La identificación **requiere** una tabla de mapeo `map_concepto_provision (tipo, clave) → categoría` por organización. Sin ella el informe no es calculable; no se infiere por texto de la descripción.
- **B-08.R3 — Alcance.** Este informe es una **estimación con base en CFDI**, no un cálculo actuarial. No cubre prima de antigüedad ni obligaciones por beneficios al retiro (NIF D-3). Se rotula así en la cabecera.

---

### B-09 · Recálculo de ISR y subsidio al empleo

**Propósito.** Verificar que la retención timbrada corresponde a la tarifa aplicable. Convierte la revisión manual de nómina en un control automático sobre el universo completo de CFDI.

**Grano.** Una fila por `uuid`.

**Columnas.**

| # | Columna | Tipo | Fórmula |
|---|---|---|---|
| 1 | UUID / Fecha pago / Periodo | — **[X]** | |
| 2 | RFC / Nombre / Núm. empleado | — **[X]** | |
| 3 | Periodicidad | TEXT **[X]** | `periodicidad_pago` |
| 4 | Días pagados | DEC **[X]** | `num_dias_pagados` |
| 5 | Base gravable del periodo | MONTO **[D]** | `Σ importe_gravado` de percepciones con `es_ingreso_ordinario=true` |
| 6 | Tarifa aplicada | TEXT **[D]** | `ejercicio` + `periodicidad` resueltos en `tarifa_isr` |
| 7 | Renglón de la tarifa | INT **[D]** | Ver Anexo I.1 |
| 8 | Límite inferior | MONTO **[D]** | `tarifa_isr.limite_inferior` |
| 9 | Excedente | MONTO **[D]** | `base − limite_inferior` |
| 10 | Tasa sobre excedente | TASA **[D]** | `tarifa_isr.tasa_excedente` |
| 11 | Impuesto marginal | MONTO **[D]** | `⌊excedente × tasa⌉₂` |
| 12 | Cuota fija | MONTO **[D]** | `tarifa_isr.cuota_fija` |
| 13 | ISR determinado | MONTO **[D]** | `cuota_fija + impuesto_marginal` |
| 14 | Subsidio al empleo teórico | MONTO **[D]** | Ver Anexo I.3 |
| 15 | ISR a retener teórico | MONTO **[D]** | `MAX(0, ISR_determinado − subsidio_teorico)` |
| 16 | Subsidio a entregar teórico | MONTO **[D]** | `MAX(0, subsidio_teorico − ISR_determinado)` |
| 17 | ISR retenido en el CFDI | MONTO **[X]** | `isr_retenido(uuid)` |
| 18 | Subsidio en el CFDI | MONTO **[X]** | `subsidio_aplicado(uuid)` |
| 19 | Diferencia de ISR | MONTO **[D]** | `columna 17 − columna 15` |
| 20 | Diferencia de subsidio | MONTO **[D]** | `columna 18 − columna 16` |
| 21 | Bandera | TEXT **[D]** | Ver B-09.R4 |

**Reglas.**

- **B-09.R1 — Selección de tarifa.** La tarifa se resuelve por `(ejercicio, periodicidad_pago)` desde `tarifa_isr`. Las tarifas por periodicidad son las publicadas en el Anexo 8 de la RMF; **no** se derivan dividiendo la tarifa mensual entre dos, aunque el resultado sea cercano. Si no existe tarifa para la periodicidad declarada, se usa la mensual proporcionada por días y se marca ⚠ `TARIFA_PROPORCIONADA`.
- **B-09.R2 — Unidades de la tasa.** `tarifa_isr.tasa_excedente` se almacena como **fracción decimal** (`0.2136`), no como porcentaje (`21.36`). El error de dividir entre 100 un valor ya almacenado como decimal —o de omitir la división cuando está en porcentaje— produce una subvaluación del ISR de dos órdenes de magnitud. La carga de la tabla debe incluir una prueba: la tasa del último renglón debe caer en el rango `[0.30, 0.40]`.
- **B-09.R3 — Periodos irregulares.** Cuando `num_dias_pagados` difiere de los días nominales de la periodicidad (quincena de 13 días por alta a media quincena), la base debe proporcionarse antes de aplicar la tarifa, o aplicarse el procedimiento del artículo 96 con la tarifa diaria. Se implementa una sola de las dos vías, se declara cuál, y se marca ⚠ `PERIODO_IRREGULAR`.
- **B-09.R4 — Tolerancia y bandera.**
  ```
  COINCIDE            |diferencia_ISR| <= 0.02
  DIFERENCIA_MENOR    0.02 < |diferencia_ISR| <= 1.00
  DIFERENCIA_MAYOR    |diferencia_ISR| > 1.00
  ISR_CERO_CON_BASE   ISR_retenido = 0 y base > limite_inferior del renglón 2
  ```
  Una diferencia sistemática del mismo signo en todos los empleados apunta a un error en la implementación de la tarifa; diferencias dispersas apuntan a ajustes manuales por empleado.
- **B-09.R5 — Alcance.** Este informe compara contra la tarifa del periodo. **No** reproduce el procedimiento opcional del artículo 174 del Reglamento de la LISR (cálculo con ingreso mensual estimado y ajuste posterior). Si el patrón usa ese procedimiento —detectable por la presencia de un concepto de deducción con descripción tipo "ISR Art. 174"— las diferencias son esperadas y el informe debe rotularse como no concluyente para esos empleados. ⚠ `PROCEDIMIENTO_ART174`.

---

### B-10 · Validación de datos del receptor

**Propósito.** Auditar la calidad de los datos del trabajador timbrados. Los errores aquí generan requerimientos del SAT y problemas de acreditación ante el IMSS, y son invisibles en los informes de importes.

**Grano.** Una fila por `(rfc_receptor, campo_validado)` con hallazgo, o una fila por empleado con una columna por validación (parámetro `formato` **[P]**).

**Validaciones.**

| Clave | Regla | Severidad |
|---|---|---|
| `RFC_ESTRUCTURA` | `rfc_receptor` no cumple el patrón `^[A-ZÑ&]{4}[0-9]{6}[A-Z0-9]{3}$` para persona física | Alta |
| `RFC_CURP_INCONSISTENTE` | Las 10 primeras posiciones del RFC no coinciden con las 10 primeras de la CURP | Alta |
| `CURP_ESTRUCTURA` | No cumple `^[A-Z]{4}[0-9]{6}[HM][A-Z]{5}[A-Z0-9][0-9]$` | Alta |
| `CURP_ENTIDAD` | Las posiciones 12-13 de la CURP no son una clave de entidad válida | Media |
| `CURP_DUPLICADA` | Una CURP asociada a más de un RFC en el conjunto | Alta |
| `RFC_DUPLICADO` | Un RFC asociado a más de una CURP | Alta |
| `NSS_LONGITUD` | `nss` con longitud distinta de 11 | Media |
| `NSS_DIGITO_VERIFICADOR` | Falla el dígito verificador (algoritmo de Luhn sobre 10 posiciones) | Media |
| `NSS_FALTANTE` | `nss` vacío con `tipo_regimen='02'` (sueldos y salarios) | Alta |
| `NSS_DUPLICADO` | Un NSS asociado a más de un RFC | Alta |
| `SBC_CERO` | `salario_base_cot_apor <= 0` con `tipo_regimen='02'` | Alta |
| `SBC_SOBRE_TOPE` | `salario_base_cot_apor > 25 × UMA_DIARIA` vigente | Media |
| `SBC_BAJO_MINIMO` | `salario_base_cot_apor < salario_minimo_diario` de la zona | Alta |
| `SDI_MENOR_SBC` | `salario_diario_integrado < salario_base_cot_apor × 0.8` | Media |
| `SDI_CERO` | `salario_diario_integrado <= 0` | Alta |
| `SDI_MENOR_SD_IMPLICITO` | `SDI < (Σ percepción '001') / num_dias_pagados` | Alta |
| `FECHA_INICIO_POSTERIOR` | `fecha_inicio_rel_laboral > fecha_final_pago` | Alta |
| `ANTIGUEDAD_INCONSISTENTE` | La duración ISO de `@Antigüedad` difiere en más de 2 semanas del cálculo desde `fecha_inicio_rel_laboral` | Baja |
| `PUESTO_VACIO` | `puesto` nulo, vacío o con valor `Ninguno` / `N/A` | Baja |
| `DEPARTAMENTO_VACIO` | Igual para `departamento` | Baja |
| `CUENTA_INVALIDA` | `cuenta_bancaria` presente con longitud distinta de 10, 11, 16 o 18 | Baja |
| `BANCO_SIN_CUENTA` | `banco` presente y `cuenta_bancaria` vacía | Baja |
| `DATOS_CAMBIANTES` | Un mismo RFC con distinto CURP, NSS o fecha de inicio entre periodos | Alta |

**Reglas.**

- **B-10.R1 — SDI vs. SBC.** Son conceptos distintos: el SBC es la base de cotización ante el IMSS (topada a 25 UMA); el SDI es el salario diario integrado de los artículos 84 y 89 de la LFT, base de indemnizaciones. Un SDI **inferior** al SBC es teóricamente posible pero infrecuente; una razón `SDI/SBC < 0.8` es casi siempre un error de captura en el timbrado, no un dato válido. La validación se emite como severidad media, no como error absoluto.
- **B-10.R2 — Tratamiento de datos personales.** CURP, NSS y cuenta bancaria son datos personales. Este informe **debe** ofrecer el parámetro `enmascarar_datos_personales` **[P]** (default `true`), que sustituye por `****` conservando los últimos 4 caracteres. La versión sin enmascarar se genera únicamente bajo solicitud explícita y se registra en bitácora con usuario y fecha. La distribución del informe completo por correo o carpeta compartida es una fuga de datos personales, independientemente de la intención.

---

### B-11 · Conciliación CFDI de nómina contra plantilla de RH

**Propósito.** Detectar empleados timbrados que no están en plantilla y empleados en plantilla sin timbrado. Es el control cruzado que ninguna herramienta de CFDI puede hacer sola porque requiere la fuente externa.

**Grano.** Una fila por empleado del conjunto unión `CFDI ∪ plantilla_rh`.

**Columnas.**

| # | Columna | Tipo | Fórmula |
|---|---|---|---|
| 1 | Clave de cruce | TEXT **[D]** | Ver B-11.R1 |
| 2 | Situación | TEXT **[D]** | `SOLO_CFDI` \| `SOLO_RH` \| `AMBOS` |
| 3 | RFC (CFDI) / RFC (RH) | RFC **[D]** | |
| 4 | Nombre (CFDI) / Nombre (RH) | TEXT **[D]** | |
| 5 | Coincidencia de nombre | DEC **[D]** | Similitud normalizada 0–1 (ver B-11.R2) |
| 6 | Núm. empleado (CFDI) / (RH) | TEXT **[D]** | |
| 7 | Puesto (CFDI) / (RH) | TEXT **[D]** | |
| 8 | Centro de costo (RH) | TEXT **[D]** | |
| 9 | Fecha alta (RH) / Fecha inicio rel. laboral (CFDI) | FECHA **[D]** | |
| 10 | Diferencia de fechas en días | INT **[D]** | |
| 11 | Fecha baja (RH) | FECHA **[D]** | |
| 12 | Último CFDI | FECHA **[D]** | `MAX(fecha_pago)` |
| 13 | Núm. de CFDI en el rango | INT **[D]** | |
| 14 | Percepciones del rango (CFDI) | MONTO **[D]** | |
| 15 | Sueldo esperado del rango (RH) | MONTO **[D]** | `sueldo_mensual × meses_del_rango` prorrateado |
| 16 | Diferencia de importe | MONTO **[D]** | `columna 14 − columna 15` |
| 17 | % de diferencia | DEC **[D]** | |
| 18 | Bandera | TEXT **[D]** | Ver B-11.R3 |

**Reglas.**

- **B-11.R1 — Estrategia de cruce.** En cascada, deteniéndose en la primera coincidencia y registrando el nivel usado:
  1. `rfc` exacto.
  2. `curp` exacto.
  3. `nss` exacto.
  4. `num_empleado` exacto **dentro del mismo `rfc_emisor`** — nunca entre organizaciones.
  5. Similitud de nombre ≥ 0.90 sobre nombre normalizado.
  El nivel de cruce se reporta. Los cruces por nivel 5 se marcan como tentativos y requieren confirmación manual.
- **B-11.R2 — Normalización de nombre.** Mayúsculas, sin acentos, sin caracteres no alfabéticos, tokens ordenados alfabéticamente, colapso de espacios. La similitud se mide sobre el conjunto de tokens (Jaccard) y no sobre la cadena completa, porque el orden nombre/apellido varía entre sistemas.
- **B-11.R3 — Banderas.**
  ```
  TIMBRADO_SIN_PLANTILLA   situacion='SOLO_CFDI'
  PLANTILLA_SIN_TIMBRADO   situacion='SOLO_RH' y activo en el rango
  BAJA_CON_TIMBRADO        fecha_baja < MAX(fecha_pago)
  ALTA_SIN_TIMBRADO        fecha_alta + 1 periodo < primer CFDI
  IMPORTE_DISCREPANTE      |% de diferencia| > 10 %
  FECHA_INICIO_DISCREPANTE |diferencia de fechas| > 30 días
  ```

---

### B-12 · Incapacidades y horas extra

**Propósito.** Cuantificar el ausentismo subsidiado y el tiempo extraordinario. Ambos nodos son opcionales en el complemento y quedan fuera de todos los reportes comerciales por conceptos.

**Grano.** Una fila por nodo `nomina12:Incapacidad` o `nomina12:HorasExtra`, según el bloque.

**Bloque incapacidades.**

| Columna | Fórmula |
|---|---|
| UUID / Fecha pago / Periodo / RFC / Nombre / Departamento | Del comprobante |
| Tipo de incapacidad | `tipo_incapacidad` + descripción de `c_TipoIncapacidad` |
| Días de incapacidad | `dias_incapacidad` |
| Importe monetario | `importe_monetario` |
| Días pagados del periodo | `num_dias_pagados` |
| % del periodo incapacitado | `dias_incapacidad / dias_nominales_periodo` |
| Subsidio implícito por día | `importe_monetario / dias_incapacidad` |
| Deducción por incapacidad | `Σ importe` con `tipo_deduccion='006'` |
| Acumulado de días del ejercicio | Ventana acumulada por empleado y ejercicio |

⚠ `INCAPACIDAD_SIN_DEDUCCION` cuando hay nodo de incapacidad y no hay deducción tipo `006`.
⚠ `DIAS_INCAPACIDAD_EXCEDEN_PERIODO` cuando `dias_incapacidad > dias_nominales_periodo`.

**Bloque horas extra.**

| Columna | Fórmula |
|---|---|
| UUID / Fecha pago / RFC / Nombre / Departamento | |
| Días con horas extra | `dias` |
| Tipo de horas | `tipo_horas` + descripción (`01` dobles, `02` triples, `03` simples) |
| Horas extra | `horas_extra` |
| Importe pagado | `importe_pagado` |
| Importe por hora | `importe_pagado / horas_extra` |
| Salario por hora ordinario | `(Σ percepción '001' / num_dias_pagados) / horas_jornada` |
| Factor implícito | `importe_por_hora / salario_hora_ordinario` |
| Horas acumuladas del ejercicio | Ventana por empleado y ejercicio |

⚠ `FACTOR_HORAS_ATIPICO` cuando el factor implícito difiere en más de 10 % del esperado (2.0 para dobles, 3.0 para triples).
⚠ `LIMITE_SEMANAL_LFT` cuando `horas_extra / dias > 3` o el acumulado semanal excede 9 horas — es un indicio de incumplimiento del artículo 66 de la LFT, no un error de timbrado.
⚠ `HORAS_EXTRA_SIN_PERCEPCION` cuando existe el nodo y no hay percepción `tipo_percepcion='019'`.

---

### B-13 · Consolidado multi-organización

**Propósito.** Vista única de la nómina de varias entidades con RFC distinto. Es el hueco que dejan todas las herramientas comerciales: exportan por RFC, no consolidan.

**Grano.** Configurable: `(periodo, rfc_emisor)`, `(periodo, centro_costo)` o `(periodo, rfc_receptor)`.

**Columnas.**

| # | Columna | Tipo | Fórmula |
|---|---|---|---|
| 1 | Ejercicio / Periodo | INT **[D]** | Periodo **normalizado** — ver B-13.R2 |
| 2 | RFC emisor / Organización | TEXT **[D]** | Nombre corto desde tabla `organizacion` |
| 3 | Núm. de empleados | INT **[D]** | `COUNT(DISTINCT rfc_receptor)` |
| 4 | Núm. de CFDI | INT **[D]** | |
| 5 a 14 | Bloque de importes | MONTO **[D]** | Idéntico a B-06 columnas 5–14 |
| 15 | Empleados compartidos | INT **[D]** | Empleados con CFDI de más de un `rfc_emisor` en el periodo |
| 16 | Percepciones de empleados compartidos | MONTO **[D]** | |
| 17 | % del consolidado | DEC **[D]** | |

**Reglas.**

- **B-13.R1 — Deduplicación.** Ver R-T5. En un consolidado, un UUID debe contarse una sola vez aunque esté descargado desde dos cuentas. Se deduplica por `uuid` antes de agregar.
- **B-13.R2 — Normalización del periodo.** Si las organizaciones tienen periodicidades distintas (una quincenal, otra mensual), el eje temporal del consolidado es **mensual** y las quincenas se agregan al mes de `fecha_final_pago`. Consolidar periodicidades heterogéneas sobre un eje quincenal produce meses con una sola quincena para las entidades mensuales.
- **B-13.R3 — Empleados compartidos.** Un empleado con CFDI de dos organizaciones del grupo en el mismo ejercicio genera ⚠ `MULTI_PATRON_GRUPO`, con implicaciones en el cálculo anual (B-05.R3) y en el tope de SBC ante el IMSS. Es el hallazgo de mayor valor de este informe.
- **B-13.R4 — Homologación de catálogos.** Las claves internas de concepto (`nomina_percepcion.clave`) **no** son comparables entre organizaciones: la clave `001` puede ser "Sueldos" en una y "Sueldo base" en otra. El consolidado agrupa exclusivamente por `tipo_percepcion` / `tipo_deduccion` del catálogo del SAT, o por una tabla de homologación explícita `map_concepto_grupo`. Agrupar por clave interna entre organizaciones produce cifras sin significado.

---

## Grupo C — Informes de cumplimiento y validación

### C-01 · Operaciones con EFOS (art. 69-B CFF)

**Propósito.** Identificar comprobantes recibidos de contribuyentes publicados en el listado de operaciones simuladas, con la situación **vigente a la fecha de la operación**.

**Grano.** Una fila por `uuid` recibido cuya contraparte aparece en `sat_efos`.

**Columnas.** Datos del comprobante (UUID, serie, folio, fecha, total, IVA acreditado, estado SAT, uso CFDI) + situación EFOS + fechas de publicación de cada etapa + `oficio_global` + días entre la operación y la publicación + IVA en riesgo + monto deducido en riesgo.

**Reglas.**

- **C-01.R1 — Evaluación temporal.** Ver A-01.R4. La situación se evalúa a `cfdi_comprobante.fecha`. Además se emite la situación **actual** en columna aparte, porque una publicación posterior a la operación obliga a corregir dentro de los 30 días siguientes a la publicación del listado definitivo.
- **C-01.R2 — Clasificación de riesgo.**
  ```
  CRITICO   definitivo publicado ANTES de la fecha del comprobante
  ALTO      definitivo publicado DESPUÉS de la fecha del comprobante
  MEDIO     presunto vigente, sin definitivo ni desvirtuado
  BAJO      desvirtuado o sentencia favorable
  ```
- **C-01.R3 — Importes en riesgo.** `IVA en riesgo` = IVA trasladado del comprobante; `monto deducido en riesgo` = `subtotal − descuento`. Se agregan por proveedor y por ejercicio en la hoja resumen, porque la corrección fiscal se presenta por ejercicio.
- **C-01.R4 — Refresco.** `sat_efos` se recarga completa (no incremental) desde el CSV publicado por el SAT. Se conserva `fecha_carga` y se compara contra la carga anterior para generar el delta de nuevas publicaciones, que es lo que dispara la notificación.

### C-02 · Comprobantes cancelados

**Propósito.** Controlar cancelaciones propias y de terceros, en particular las que afectan ejercicios ya declarados.

**Grano.** Una fila por `uuid` con `estado_sat = 'CANCELADO'`.

**Columnas.** Identificación del comprobante + fecha de emisión + fecha de cancelación + días entre ambas + motivo + descripción del motivo + UUID de sustitución + existencia del sustituto en la base + total del sustituto + diferencia contra el original + ejercicio de emisión + ejercicio de cancelación + `¿afecta ejercicio cerrado?`.

**Validaciones.**

| Bandera | Condición |
|---|---|
| `CANCELA_EJERCICIO_ANTERIOR` | `YEAR(fecha_cancelacion) > YEAR(fecha)` |
| `SUSTITUCION_SIN_SUSTITUTO` | `motivo_cancelacion='01'` y `uuid_sustitucion` nulo o inexistente en la base |
| `SUSTITUTO_IMPORTE_DISTINTO` | `abs(total_sustituto − total_original) > 0.01` |
| `CANCELACION_TARDIA` | Más de 30 días entre emisión y cancelación en CFDI de ingreso |
| `NOMINA_CANCELADA_SIN_SUSTITUTO` | `tipo_comprobante='N'` cancelado sin sustituto — deja al trabajador sin comprobante del periodo |
| `EN_PROCESO` | `estatus_cancelacion` indica solicitud pendiente de aceptación |

### C-03 · Conciliación contra metadata del SAT

**Propósito.** Verificar que el acervo local está completo. Es el control previo indispensable: cualquier informe calculado sobre un universo incompleto es incorrecto sin advertirlo.

**Grano.** Una fila por `uuid` con diferencia entre `sat_metadata` y `cfdi_comprobante`.

**Columnas.** UUID + presencia en metadata + presencia en base local + presencia del XML en el almacén + situación (`FALTA_XML`, `FALTA_METADATA`, `SOLO_LOCAL`, `DIFERENCIA_IMPORTE`, `DIFERENCIA_ESTADO`) + valores comparados de cada lado.

**Reglas.**

- **C-03.R1 — Tres conjuntos.** La conciliación es entre tres universos y no dos: (a) metadata del SAT, (b) XML descargados, (c) registros parseados en base. Un XML descargado pero no parseado es tan invisible como uno no descargado.
- **C-03.R2 — Cobertura.** El informe encabeza con `% de cobertura = |base ∩ metadata| / |metadata|` por mes. Ningún informe de los grupos A, B, D o E debe presentarse sin este porcentaje visible, y cualquier valor menor a 100 % debe declararse en la cabecera.
- **C-03.R3 — Ventana de disponibilidad.** El SAT no expone de inmediato todos los comprobantes del día en curso. Se excluyen de la conciliación los últimos `n` días (`n` configurable, típico 3) para evitar falsos faltantes.

### C-04 · Continuidad de folios y duplicados

**Propósito.** Detectar huecos en la seriación de comprobantes emitidos y duplicados funcionales.

**Grano.** Bloque 1: una fila por hueco detectado. Bloque 2: una fila por grupo de duplicados.

**Reglas.**

- **C-04.R1 — Universo.** **Incluye cancelados** (excepción a R-T1). Un folio cancelado ocupa su lugar en la serie; excluirlo reporta un hueco falso.
- **C-04.R2 — Detección de huecos.** Solo aplica a series cuyo folio es íntegramente numérico. Se agrupa por `(rfc_emisor, serie)` y se compara el rango `[MIN, MAX]` contra los folios presentes. Las series con folio alfanumérico se listan como `NO_ANALIZABLE` en lugar de intentar heurísticas de extracción de número.
- **C-04.R3 — Duplicados.** Dos niveles:
  ```
  DUPLICADO_ESTRICTO   mismo (rfc_emisor, serie, folio) con UUID distinto
  DUPLICADO_FUNCIONAL  mismo (rfc_emisor, rfc_receptor, total, DATE(fecha))
                       con UUID distinto y ambos VIGENTE
  ```
  El funcional es informativo: facturar dos veces el mismo importe al mismo cliente el mismo día es legítimo. Se reporta con el detalle para revisión, no como error.

### C-05 · Validación estructural y aritmética

**Propósito.** Consolidar en un solo tablero todas las banderas de las validaciones definidas en este documento, con conteo por severidad y enlace al detalle.

**Grano.** Una fila por `(clave_validacion, periodo)`.

**Columnas.** Clave + descripción + severidad + informe donde se detalla + comprobantes evaluados + comprobantes con hallazgo + % de incidencia + importe involucrado + tendencia contra el periodo anterior.

**Reglas.**

- **C-05.R1 — Catálogo único de validaciones.** Todas las banderas de este documento viven en una tabla `catalogo_validacion (clave, descripcion, severidad, informe, expresion)`. Duplicar la lógica de validación en cada informe garantiza divergencia entre ellos.
- **C-05.R2 — Severidades.** `ALTA` bloquea la presentación de informes derivados; `MEDIA` se reporta en cabecera; `BAJA` solo en el detalle.
- **C-05.R3 — Validación de vigencia del certificado.** `fecha_timbrado` debe caer dentro del periodo de vigencia del certificado `no_certificado`. Requiere el catálogo de certificados; si no se dispone de él, la validación se omite y se declara omitida, no se aprueba por defecto.

---

## Grupo D — Papeles de trabajo fiscales

> Los informes de este grupo producen cifras que alimentan declaraciones. Se rotulan como **papeles de trabajo**: son insumo para la determinación, no la determinación misma, y su validación corresponde a quien firma la declaración.

### D-01 · IVA por flujo de efectivo

**Propósito.** Determinar el IVA trasladado cobrado y el acreditable pagado del periodo, conforme al principio de flujo de efectivo de la LIVA, para cotejar contra el prellenado del SAT.

**Grano.** Una fila por `(periodo, tipo_operacion, tasa)`.

**Algoritmo.**

```
IVA CAUSADO del periodo =
    (A) IVA de CFDI de ingreso EMITIDOS con metodo_pago='PUE'
        y fecha en el periodo
  + (B) IVA de los DoctoRelacionado de REP EMITIDOS
        con pago.fecha_pago en el periodo
  - (C) IVA de CFDI de egreso EMITIDOS (notas de crédito) aplicados en el periodo

IVA ACREDITABLE del periodo =
    (D) IVA de CFDI de ingreso RECIBIDOS con metodo_pago='PUE'
        y fecha en el periodo
  + (E) IVA de los DoctoRelacionado de REP RECIBIDOS
        con pago.fecha_pago en el periodo
  - (F) IVA de CFDI de egreso RECIBIDOS aplicados en el periodo
  - (G) IVA de comprobantes recibidos de EFOS con situación definitiva

IVA a cargo = IVA causado - IVA acreditable - IVA retenido a favor
```

**Reglas.**

- **D-01.R1 — Fuente del IVA en los bloques B y E.** Se toma de `pago_docto_impuesto`, **no** del comprobante original. El REP declara la proporción de impuesto correspondiente al pago parcial; usar el IVA total de la factura en un pago parcial sobrevalúa el impuesto del periodo.
- **D-01.R2 — Exclusión de doble conteo.** Una factura PPD **nunca** entra por los bloques A o D, solo por B o E cuando se paga. ⚠ `PPD_EN_PUE` si un comprobante PPD aparece en el bloque de PUE. Inversamente, una factura PUE referida en un REP se computa una sola vez (por A/D) y se marca ⚠ `PUE_CON_REP` (ver A-06.R3).
- **D-01.R3 — IVA no acreditable.** El bloque G resta el IVA de EFOS definitivos. Se presenta como línea explícita, no se elimina silenciosamente del bloque D, para que el papel de trabajo muestre la determinación completa.
- **D-01.R4 — Retenciones.** El IVA retenido al contribuyente (en comprobantes emitidos) y el retenido por el contribuyente (en recibidos, con obligación de entero) se presentan en líneas separadas. Confundir la dirección de la retención invierte el signo del resultado.
- **D-01.R5 — Alcance.** El informe **no** determina la proporción de acreditamiento de actividades mixtas (art. 5 fracción V LIVA), ni el ajuste de inversiones. Para una organización con actividades exentas y gravadas, la cifra del bloque D es el IVA pagado total, no el acreditable. Se rotula así.

### D-02 · Conciliación de ingresos por tasa

**Propósito.** Cuadrar los ingresos del periodo por tasa de impuesto para pagos provisionales y la declaración anual.

**Grano.** Una fila por `(periodo, tipo_comprobante, tasa, tipo_factor)`.

**Columnas.** Núm. de comprobantes + base + IVA + IEPS + ISR retenido + total + ingreso acumulable estimado + comparativo contra el mes anterior + acumulado del ejercicio.

**Reglas.**

- **D-02.R1 — Ingreso acumulable.** `Σ (subtotal − descuento)` de comprobantes `I` emitidos vigentes, menos `Σ (subtotal − descuento)` de comprobantes `E` emitidos vigentes con `tipo_relacion IN ('01','03')`. Se rotula como estimación: el ingreso acumulable fiscal admite partidas que no se facturan y excluye otras que sí.
- **D-02.R2 — Personas morales con fines no lucrativos.** Para régimen `603`, el concepto de "ingreso" fiscal difiere sustancialmente. El informe conserva su utilidad como control de facturación, pero **no** debe presentarse como base de un pago provisional de ISR. La cabecera lo declara en función del `regimen_emisor`.

### D-03 · Retenciones por proveedor

**Propósito.** Controlar las retenciones de ISR e IVA efectuadas a personas físicas y su entero, y detectar omisiones de retención.

**Grano.** Una fila por `(periodo, rfc_proveedor)`.

**Columnas.** RFC + nombre + régimen del emisor + núm. de comprobantes + base + IVA trasladado + IVA retenido + tasa efectiva de retención de IVA + ISR retenido + tasa efectiva de ISR + retención esperada + diferencia + bandera.

**Reglas.**

- **D-03.R1 — Retención esperada.** Se deriva de la combinación `(regimen_emisor, clave_prod_serv)` mediante una tabla configurable `regla_retencion (regimen, clave_prod_serv_prefijo, tasa_isr, tasa_iva, fundamento)`. No se codifican tasas en el informe: dependen del tipo de servicio y del régimen, y cambian por reforma.
- **D-03.R2 — Omisión de retención.** ⚠ `RETENCION_OMITIDA` cuando la regla aplicable indica retención y el comprobante no la trae. Es el hallazgo de mayor exposición del informe: la retención omitida es responsabilidad solidaria del retenedor.
- **D-03.R3 — Asimilados a salarios.** Los pagos por asimilados llegan por dos vías: CFDI de nómina con `tipo_percepcion='046'` (Grupo B) y CFDI de ingreso emitido por el prestador con retención. El informe debe cubrir ambas o declarar cuál cubre; medir solo una subvalúa el total de retenciones.

---

## Grupo E — Informes analíticos

> Estos informes no tienen finalidad fiscal. Su valor es de gestión: el acervo de CFDI es la serie histórica más completa y confiable de la operación de una entidad.

### E-01 · Ventas por cliente con análisis de concentración

**Grano.** Una fila por `(rfc_receptor, periodo)` o `(rfc_receptor, ejercicio)` según parámetro.

**Columnas.** RFC + nombre + CP + entidad derivada del CP + núm. de comprobantes + ticket promedio + ingreso bruto + notas de crédito + ingreso neto + días de crédito promedio (de A-05) + primera y última operación + antigüedad como cliente + **participación %** + **participación acumulada %** + **clasificación ABC** + variación contra periodo anterior + tendencia.

**Reglas.**

- **E-01.R1 — Clasificación ABC.** Se ordena descendente por ingreso neto, se acumula el porcentaje y se clasifica: `A` hasta 80 % acumulado, `B` de 80 a 95 %, `C` el resto. El corte se aplica sobre la participación **acumulada**, no sobre la individual.
- **E-01.R2 — Índice de concentración.** Se calcula HHI = `Σ (participación_i)²` sobre participaciones en fracción decimal. Un valor superior a 0.25 indica concentración alta. Para una organización financiada por donativos, este índice sobre los emisores de comprobantes recibidos mide dependencia de financiadores, que es una lectura de riesgo institucional.
- **E-01.R3 — Normalización de contraparte.** El mismo cliente puede aparecer con variantes de `nombre_receptor`. La agrupación es por `rfc_receptor`, nunca por nombre. Se reporta la variante más reciente del nombre y se listan las alternas.

### E-02 · Compras por proveedor y por producto

**Grano.** Una fila por `(rfc_emisor, clave_prod_serv, periodo)`.

**Columnas.** Proveedor + clave y descripción ProdServ + descripción más frecuente del concepto + núm. de comprobantes + cantidad total por `clave_unidad` + importe + precio unitario promedio ponderado + precio mínimo + precio máximo + coeficiente de variación del precio + variación del precio contra el periodo anterior + núm. de proveedores alternativos para la misma clave.

**Reglas.**

- **E-02.R1 — Precio unitario promedio.** Ponderado por cantidad: `Σ importe / Σ cantidad`, **solo** dentro del mismo `clave_unidad`. Promediar precios entre unidades distintas (kilogramo y pieza) produce una cifra sin significado. Cuando una clave ProdServ aparece con varias `clave_unidad`, se emiten filas separadas.
- **E-02.R2 — Inflación implícita.** `variación del precio unitario ponderado` interanual por clave ProdServ, comparable contra el INPC del rubro. Es la medición de inflación real de la canasta de compras de la entidad.
- **E-02.R3 — Concentración de proveeduría.** Número de RFC distintos que facturan la misma clave ProdServ. Un valor de 1 en claves de importe alto es un riesgo de dependencia de proveedor único.

### E-03 · Concentración geográfica

**Grano.** Una fila por `(codigo_postal, periodo)` o por entidad federativa derivada.

**Columnas.** CP + municipio y entidad (desde catálogo de CP) + núm. de contrapartes + núm. de comprobantes + importe + participación % + variación interanual.

**Reglas.**

- **E-03.R1 — Fuente del CP.** Para emitidos, `cfdi:Receptor/@DomicilioFiscalReceptor` (solo disponible en 4.0). Para recibidos, `cfdi:Comprobante/@LugarExpedicion` del emisor. Son conceptos distintos: el primero es el domicilio fiscal del cliente, el segundo el lugar de expedición del proveedor. Mezclarlos en un mismo mapa es un error de interpretación.
- **E-03.R2 — CFDI 3.3.** Los comprobantes 3.3 no traen domicilio del receptor. Se excluyen del informe y se reporta el porcentaje excluido; no se imputa el CP desde otra fuente.

### E-04 · Antigüedad de saldos y pronóstico de flujo

**Grano.** Una fila por factura con saldo pendiente (de A-06 nivel 1).

**Columnas.** Contraparte + UUID + serie/folio + fecha + total + pagado + saldo + días vencido + **cubeta de antigüedad** (`0-30`, `31-60`, `61-90`, `91-120`, `>120`) + días de crédito históricos de la contraparte + fecha esperada de cobro + probabilidad de cobro estimada + monto esperado ponderado.

**Reglas.**

- **E-04.R1 — Cubetas.** Se calculan sobre `DATEDIFF(fecha_corte, fecha_factura)`, no sobre la fecha de vencimiento, salvo que se disponga de los días de crédito pactados en tabla externa.
- **E-04.R2 — Días de crédito históricos.** `MEDIANA(DATEDIFF(fecha_pago, fecha_factura))` de las facturas ya liquidadas de esa contraparte (de A-06 columna 11). La mediana, no el promedio: un pago atípicamente tardío distorsiona el promedio y arruina el pronóstico.
- **E-04.R3 — Probabilidad de cobro.** Se estima como la proporción histórica de facturas de esa contraparte liquidadas dentro de la cubeta correspondiente. Con menos de 5 facturas liquidadas históricas, la estimación se omite y la celda queda vacía en lugar de reportar un valor sin soporte.
- **E-04.R4 — Alcance.** El informe refleja lo facturado, no la cartera contable. Anticipos, saldos previos a la implantación del CFDI y operaciones sin factura no aparecen. La diferencia contra la contabilidad es esperada y debe conciliarse, no ignorarse.

### E-05 · Serie de tiempo y comparativo interanual

**Grano.** Una fila por periodo, con métricas en columnas.

**Columnas.** Periodo + ingresos + egresos + ingreso neto + núm. de comprobantes + ticket promedio + núm. de clientes activos + clientes nuevos + clientes perdidos + costo de nómina (de B-06) + nómina como % del ingreso + mismo periodo del año anterior para cada métrica + variación absoluta y % + media móvil de 3 y 12 periodos + índice base 100.

**Reglas.**

- **E-05.R1 — Cliente nuevo / perdido.** Nuevo: primera aparición del RFC en toda la serie histórica, no solo en el rango consultado. Perdido: sin comprobantes en los últimos `n` periodos (configurable) habiéndolos tenido antes. La definición de "perdido" debe declararse en la cabecera porque cambia radicalmente la cifra.
- **E-05.R2 — Periodos incompletos.** El periodo en curso se marca como parcial y se excluye de medias móviles y comparativos, o se anualiza declarándolo. Incluirlo sin marca produce una caída aparente en el último punto de toda serie.

---

## Anexo I — Fórmulas fiscales

> **Advertencia de vigencia.** Ninguna de las cifras de tarifas, topes, UMA, salario mínimo o montos de subsidio se reproduce en este documento. Todas viven en `tarifa_isr` y `param_fiscal` con vigencia por ejercicio, y deben cargarse desde la RMF y los decretos vigentes al ejercicio que se calcula. Las fórmulas de este anexo son estables; los parámetros no.

### I.1 · Localización del renglón de la tarifa de ISR

```
Entrada: base (MONTO), ejercicio (INT), periodicidad (CHAR(2))

renglon = SELECT * FROM tarifa_isr
          WHERE ejercicio = :ejercicio
            AND periodicidad = :periodicidad
            AND :base >= limite_inferior
            AND (:base <= limite_superior OR limite_superior IS NULL)
          LIMIT 1

Si no hay renglón → error de configuración, NO cero.
El último renglón de cada tarifa tiene limite_superior NULL (o 'En adelante').
```

**Prueba de carga obligatoria de la tabla:**

```
1. El limite_inferior del primer renglón debe ser 0.01
2. limite_inferior(n) = limite_superior(n-1) + 0.01  para todo n > 1
3. cuota_fija(1) = 0
4. tasa_excedente estrictamente creciente
5. tasa_excedente del último renglón ∈ [0.30, 0.40]
6. tasa_excedente almacenada como fracción decimal, nunca como porcentaje
```

La prueba 6 es la que evita el error de escala: un valor `21.36` almacenado donde se espera `0.2136` produce un ISR cien veces mayor; el error inverso —dividir entre 100 un valor ya decimal— produce un ISR cien veces menor y pasa desapercibido porque el resultado sigue siendo un número plausiblemente pequeño.

### I.2 · ISR del periodo

```
ISR_determinado = cuota_fija + ⌊(base - limite_inferior) × tasa_excedente⌉₂
```

### I.3 · Subsidio para el empleo

El mecanismo cambió de modelo. La implementación **debe** soportar ambos y seleccionar por vigencia:

```
modelo = param_fiscal('MODELO_SUBSIDIO', fecha_pago)

CASO modelo = 'TABLA':
    -- Modelo histórico: tabla de rangos con monto por renglón
    subsidio = SELECT monto FROM tabla_subsidio
               WHERE ejercicio = :ej AND periodicidad = :per
                 AND :ingreso_gravado BETWEEN para_ingresos_de AND para_ingresos_hasta

CASO modelo = 'MONTO_FIJO':
    -- Modelo vigente a partir de la reforma de 2024:
    -- monto fijo expresado como porcentaje de la UMA mensual,
    -- aplicable solo si el ingreso no excede un tope
    tope     = param_fiscal('SUBSIDIO_TOPE_INGRESO', fecha_pago)
    factor   = param_fiscal('SUBSIDIO_FACTOR_UMA',   fecha_pago)
    uma_mens = param_fiscal('UMA_MENSUAL',           fecha_pago)
    subsidio_mensual = SI ingreso_mensualizado <= tope
                       ENTONCES ⌊factor × uma_mens⌉₂
                       SINO 0
    subsidio = subsidio_mensual × (dias_del_periodo / dias_del_mes)

Aplicación (ambos modelos):
    ISR_a_retener       = MAX(0, ISR_determinado - subsidio)
    subsidio_a_entregar = MAX(0, subsidio - ISR_determinado)
```

**Nota de interpretación aplicable al conjunto analizado.** Un subsidio de cero en todos los comprobantes de un patrón **no** es por sí mismo un hallazgo: con el modelo de monto fijo, todo empleado cuyo ingreso mensualizado supere el tope tiene subsidio cero por construcción. La validación correcta es:

```
⚠ SUBSIDIO_OMITIDO   subsidio_en_CFDI = 0
                     Y ingreso_mensualizado <= tope vigente
⚠ SUBSIDIO_INDEBIDO  subsidio_en_CFDI > 0
                     Y ingreso_mensualizado > tope vigente
```

Donde `ingreso_mensualizado = gravado_del_periodo × (dias_del_mes / num_dias_pagados)`.

### I.4 · Cálculo anual del ISR (art. 97 LISR)

```
1. ingreso_anual_gravado = B-05 columna 11 (gravado ordinario del ejercicio)
2. renglon = I.1 con periodicidad = 'ANUAL'
3. ISR_anual = I.2
4. subsidio_anual_acreditable = B-05 columna 15
5. diferencia = ISR_anual - subsidio_anual_acreditable - ISR_retenido_ejercicio
   diferencia > 0 → a cargo del trabajador
   diferencia < 0 → a favor
```

Los ingresos por separación, indemnización, jubilación y pensión **no** entran en el paso 1 (ver B-05.R4).

### I.5 · Días nominales por periodicidad

Se usa en la validación `DIAS_PAGADOS_ATIPICO`, en el prorrateo del subsidio y en la construcción del eje de B-04.

| `c_PeriodicidadPago` | Descripción | Días nominales | Rango válido |
|---|---|---|---|
| `01` | Diario | 1 | [1, 1] |
| `02` | Semanal | 7 | [1, 7] |
| `03` | Catorcenal | 14 | [1, 14] |
| `04` | Quincenal | 15 | [1, 16] |
| `05` | Mensual | 30 | [1, 31] |
| `06` | Bimestral | 60 | [1, 62] |
| `07` | Unidad de obra | — | sin validación |
| `08` | Comisión | — | sin validación |
| `09` | Precio alzado | — | sin validación |
| `10` | Decenal | 10 | [1, 11] |
| `99` | Otra | — | sin validación |

La quincena admite 16 días porque el corte de fin de mes en meses de 31 días abarca del 16 al 31.

### I.6 · Interpretación de `@Antigüedad`

El atributo viene como duración ISO 8601 y **no** debe usarse para cálculos.

```
Formatos observados:  P589W   P3Y2M   P1Y   P52W   P0W

Parseo:  ^P(?:(\d+)Y)?(?:(\d+)M)?(?:(\d+)W)?(?:(\d+)D)?$

Cálculo correcto de la antigüedad (independiente del atributo):
    semanas = FLOOR( DATEDIFF(fecha_final_pago, fecha_inicio_rel_laboral) / 7 )
    años    = DATEDIFF(fecha_final_pago, fecha_inicio_rel_laboral) / 365.25

Validación ANTIGUEDAD_INCONSISTENTE:
    |semanas_declaradas - semanas_calculadas| > 2
```

### I.7 · Tolerancias de validación

| Contexto | Tolerancia | Justificación |
|---|---|---|
| Identidades de totales de un comprobante | 0.01 | Redondeo a centavos |
| Suma de conceptos vs. subtotal | 0.01 | Idem |
| Impuesto vs. base × tasa (un comprobante) | 0.01 | Idem |
| Impuesto vs. base × tasa (agregado de n comprobantes) | `0.01 × n` | El redondeo se acumula linealmente |
| Recálculo de ISR | 0.02 | Dos redondeos independientes en cadena |
| Coherencia de pago vs. documentos relacionados | 0.01 | |
| Conversión de moneda | `0.01 × tipo_cambio` | El error escala con el tipo de cambio |

---

## Anexo II — Matriz de trazabilidad informe ↔ tabla

| Informe | Tablas fuente | Dependencias externas |
|---|---|---|
| A-01 | `cfdi_comprobante`, `cfdi_concepto_impuesto`, `cfdi_relacionado`, `sat_efos` | Catálogos SAT |
| A-02 | `cfdi_concepto`, `cfdi_concepto_impuesto` | `c_ClaveProdServ`, `c_ClaveUnidad` |
| A-03 | `cfdi_concepto_impuesto` | — |
| A-04 | `cfdi_relacionado`, `cfdi_comprobante` | — |
| A-05 | `pago`, `pago_docto`, `pago_docto_impuesto` | — |
| A-06 | A-05 + `cfdi_comprobante` | — |
| B-01 | `nomina*` completo | Catálogos de nómina |
| B-02 | `nomina_percepcion`, `nomina_deduccion`, `nomina_otro_pago` | — |
| B-03 | `nomina_percepcion` | `c_TipoPercepcion` extendido, `param_fiscal` (UMA) |
| B-04 | `nomina`, `nomina_receptor` | `plantilla_rh` (opcional) |
| B-05 | Todo el grupo nómina | `tarifa_isr`, `param_fiscal` |
| B-06 | `nomina*` | `map_departamento`, `param_fiscal` (tasas patronales), `plantilla_rh` (opcional) |
| B-07 | `nomina_deduccion` | Captura de monto original |
| B-08 | `nomina_percepcion`, `nomina_receptor` | `map_concepto_provision`, `tabla_vacaciones`, `plantilla_rh` |
| B-09 | `nomina_percepcion`, `nomina_deduccion`, `nomina_otro_pago` | `tarifa_isr`, `param_fiscal` |
| B-10 | `nomina_receptor` | `param_fiscal` (UMA, salario mínimo), `c_Estado` |
| B-11 | `nomina*` | **`plantilla_rh` obligatoria** |
| B-12 | `nomina_incapacidad`, `nomina_hora_extra` | — |
| B-13 | `nomina*` de varios RFC | `organizacion`, `map_concepto_grupo` |
| C-01 | `cfdi_comprobante`, `sat_efos` | CSV 69-B diario |
| C-02 | `cfdi_comprobante`, `cfdi_relacionado` | WS de estatus |
| C-03 | `cfdi_comprobante`, `sat_metadata` | TXT de metadata |
| C-04 | `cfdi_comprobante` | — |
| C-05 | `catalogo_validacion` + todos | — |
| D-01 | `cfdi_comprobante`, `pago_docto_impuesto`, `sat_efos` | — |
| D-02 | `cfdi_comprobante`, `cfdi_concepto_impuesto` | — |
| D-03 | `cfdi_concepto_impuesto`, `cfdi_concepto` | `regla_retencion` |
| E-01 | `cfdi_comprobante` | Catálogo de CP |
| E-02 | `cfdi_concepto` | `c_ClaveProdServ`, INPC (opcional) |
| E-03 | `cfdi_comprobante` | Catálogo de CP |
| E-04 | A-06 | — |
| E-05 | `cfdi_comprobante` + B-06 | — |

### Orden de implementación recomendado

| Fase | Informes | Criterio |
|---|---|---|
| 1 | C-03, C-05 | Sin control de completitud, ningún informe posterior es confiable |
| 2 | A-01, A-02, B-01, B-02 | Base plana; sustituyen de inmediato la dependencia de herramienta externa |
| 3 | C-01, C-02, C-04, B-10 | Cumplimiento y calidad de datos; alto valor, baja complejidad |
| 4 | A-05, A-06, D-01 | Flujo de efectivo; requieren el parseo completo de Pagos 2.0 |
| 5 | B-04, B-05, B-06, B-09 | Analítica de nómina; requieren `param_fiscal` y `tarifa_isr` cargados |
| 6 | B-07, B-08, B-11, B-13 | Requieren fuentes externas (RH, mapeos, captura manual) |
| 7 | D-02, D-03, E-01 a E-05 | Valor de gestión; construibles sobre lo anterior sin ingesta nueva |
