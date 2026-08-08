# 05 — Especificación de la API

| Campo | Valor |
|---|---|
| Documento | 05 — Especificación de API |
| Versión | 2.1 (**congelada** — freeze de Fase 1, 2026-07-27; ver README/CLAUDE.md tabla de fase) |
| Fecha | 2026-07-27 |
| Auth | Bearer — Firebase ID token verificado server-side |
| Base URL | `/v1` |
| Formato | JSON UTF-8 |
| Depende de | [`01_SRS`](../01-vision/01_SRS_especificacion_requisitos.md) · [`03_modelo_de_datos`](../03-datos/03_modelo_de_datos.md) · [`04_plan_de_seguridad`](../04-seguridad/04_plan_de_seguridad.md) |

> FastAPI genera OpenAPI automáticamente; este documento incluye la interfaz `ApiClient` literal (§9, **congelada**) y cualquier cambio de firma la actualiza en la misma sesión (Gobernanza v3 mejora 4).

---

## 1. Convenciones

### 1.1 Versionado
Prefijo `/v1` en URL. Cambios incompatibles ⇒ `/v2` (no previsto en MVP).

### 1.2 Autenticación
`Authorization: Bearer <firebase_id_token>` en toda petición (salvo `/health`). El backend verifica firma/exp/aud/revocación y resuelve usuario local activo + permiso sobre la empresa de la ruta (doc 04 §3.2). No hay API keys ni sesiones de cookie.

### 1.3 Códigos de estado
| Código | Semántica en este sistema |
|---|---|
| 200 | Lectura/actualización exitosa |
| 201 | Recurso creado |
| 202 | Trabajo asíncrono aceptado (descargas, validaciones, export) |
| 400 | Payload inválido (validación Pydantic) |
| 401 | Token ausente/inválido/expirado |
| 403 | Usuario inactivo, sin permiso sobre la empresa, o rol insuficiente |
| 404 | No existe **o no pertenece a una empresa autorizada** (respuesta idéntica, anti-enumeración) |
| 409 | Conflicto (RFC duplicado, transición ilegal de job) |
| 422 | Regla de negocio violada (rango inválido, e.firma vencida) |
| 429 | Rate limit excedido |
| 500 | Error no controlado (sin detalle interno al cliente) |

### 1.4 Formato de error estándar
```json
{
  "error": {
    "codigo": "EFIRMA_VENCIDA",
    "mensaje": "La e.firma de la empresa venció el 2026-06-30.",
    "detalle": {"not_after": "2026-06-30T23:59:59"},
    "trace_id": "8f2c…"
  }
}
```

### 1.5 Rate limiting
| Grupo | Endpoints | Límite |
|---|---|---|
| Auth-sensibles | alta e.firma, usuarios/permisos | 10/min/usuario |
| Mutantes | descargas, validaciones, reintentos, notificaciones | 30/min/usuario |
| Lectura | listados, monitoreo | 120/min/usuario |
| Export | export Excel | 5/min/usuario |

### 1.6 Paginación
`?page=1&per_page=50` (máx 200). Respuesta: `{ "data": [...], "page": 1, "per_page": 50, "total": 1234 }`. Orden por defecto documentado por recurso; estable (desempate por id).

---

## 2. Recurso: Sesión y usuarios (prioridad 1)

### GET /v1/me — Perfil y permisos del usuario autenticado
Resuelve el usuario local y sus empresas autorizadas; primera llamada de la SPA tras login.
**Autenticación:** Bearer. **Rate limit:** lectura.
**Respuesta 200:**
```json
{ "usuario_id": 3, "correo": "ana@demo.test", "nombre": "Ana Torres",
  "rol_global": "operador",
  "empresas": [ {"empresa_id": 7, "nombre": "Comercializadora Demo", "rfc": "EKU9003173C9", "rol": "operador"} ] }
```
**Errores:** 401 · 403 (uid sin usuario local o inactivo).
**Seguridad:** es el único endpoint que no requiere `empresa_id`; no revela usuarios ajenos.

### POST /v1/usuarios — Alta de usuario *(admin)*
Body: `{ "correo": "...", "nombre": "...", "rol_global": "operador" }` → 201. Bitácora. **Errores:** 403 (no admin) · 409 (correo existente).

### PUT /v1/usuarios/{usuario_id}/permisos — Asignar empresas *(admin)*
Body: `{ "permisos": [ {"empresa_id": 7, "rol": "operador"} ] }` → 200. Reemplaza el conjunto; bitácora.

### PATCH /v1/usuarios/{usuario_id} — Activar/desactivar, rol *(admin)*
`{ "activo": false }` → 200; efecto inmediato (RF-AUTH-04). Bitácora.

## 3. Recurso: Empresas (prioridades 1–2)

### GET /v1/empresas — Empresas autorizadas del usuario
**Respuesta 200:** lista con `empresa_id, nombre, rfc, activo, efirma: {presente, not_after} | null`.

### POST /v1/empresas — Alta *(admin)*
Body: `{ "nombre": "...", "rfc": "EKU9003173C9", "plantilla_nomenclatura": null }` → 201. **Errores:** 409 RFC duplicado · 400 RFC malformado. Bitácora.

### PATCH /v1/empresas/{empresa_id} — Edición / baja lógica *(admin)*
`{ "activo": false }` desactiva sin borrar historial (RF-EMP-02). Bitácora.

### DELETE /v1/empresas/{empresa_id} — Borrado real *(admin)* — añadido post-freeze (2026-07-28)
204 si la empresa nunca tuvo e.firma/jobs/comprobantes. **Errores:** 409 `EMPRESA_CON_HISTORIAL` si ya
tiene alguno — el historial fiscal nunca se borra vía API (doc 04 §4.4); usar PATCH `activo:false` en
ese caso. Bitácora (`eliminar_empresa`) dentro de la misma transacción.

## 4. Recurso: Bóveda de e.firmas (prioridad 1)

### POST /v1/empresas/{empresa_id}/efirma — Alta/reemplazo *(operador+)*
`multipart/form-data`: `cer` (archivo), `key` (archivo), `password` (campo). El backend valida (abre, RFC coincide, vigente), cifra y persiste (RF-BOV-01).
**Respuesta 201:**
```json
{ "num_serie": "30001000000400002325", "not_before": "2024-08-01T00:00:00",
  "not_after": "2028-08-01T00:00:00", "dias_para_vencer": 735 }
```
**Errores:** 422 (`EFIRMA_NO_ABRE`, `RFC_NO_COINCIDE`, `EFIRMA_VENCIDA`) · 403.
**Seguridad:** nunca devuelve material de llave; la contraseña no se loguea; alta en bitácora; rate limit auth-sensible.

### GET /v1/empresas/{empresa_id}/efirma — Metadatos
200 con serie/vigencia, o 404 si no hay e.firma. Nunca contenido.

### DELETE /v1/empresas/{empresa_id}/efirma — Eliminar *(operador+)*
204; el historial de jobs/comprobantes permanece (RF-BOV-04). Bitácora.

## 5. Recurso: Descargas / jobs (prioridad 2)

### POST /v1/empresas/{empresa_id}/descargas — Crear descarga *(operador+)*
Trocea el rango en jobs (≤ 12 meses) y los encola (RF-DESC-01/03).
Body: `{ "tipo": "recibido", "solicitud": "CFDI", "desde": "2023-01-01", "hasta": "2025-12-31" }`
**Respuesta 202:** `{ "job_ids": [41, 42, 43], "ventanas": 3 }`
**Errores:** 422 (`EFIRMA_VENCIDA`, `RANGO_INVALIDO`, `EMPRESA_INACTIVA`) · 403. Bitácora del disparo (RF-SYNC-02).

### GET /v1/empresas/{empresa_id}/jobs — Monitoreo (RF-SYNC-03)
Query: `estado?, origen?, desde?, hasta?, page`. **200:** paginado con `job_id, tipo, solicitud, origen, ventana {desde, hasta}, estado, intentos, paquetes, mensaje, updated_at`.

### GET /v1/empresas/{empresa_id}/jobs/{job_id} — Detalle
200 con la fila completa (incluye `id_solicitud`). 404 si no es de la empresa.

### POST /v1/empresas/{empresa_id}/jobs/{job_id}/reintentar — Re-encolar ERROR *(operador+)*
202. **Errores:** 409 si el job no está en `ERROR` (transición ilegal). Bitácora.

## 6. Recurso: Comprobantes (prioridades 2–3)

### GET /v1/empresas/{empresa_id}/comprobantes — Listado (RF-LIST-01)
Query: `desde?, hasta?, tipo_comprobante?, estatus?, rfc_contraparte?, direccion? ('emitido'|'recibido'), q? (razón social), page, per_page, orden?`.
**200:** paginado con las columnas del índice (uuid, folio, emisor/receptor, razón social, total, fecha, tipo, estatus, estatus_verificado_at).
**Seguridad:** consulta siempre acotada a la empresa del contexto; sin N+1.
**`direccion` añadido tras el freeze (2026-07-28):** relativo al RFC de la propia empresa (no de la
contraparte) — `emitido` filtra `rfc_emisor = empresa.rfc`, `recibido` filtra `rfc_receptor = empresa.rfc`.
También soportado en `GET .../export`. `ApiClient.listarComprobantes` (doc 05 §9) documenta el campo
`direccion` en su firma.

### POST /v1/empresas/{empresa_id}/comprobantes/validar — Validación en lote *(operador+)* (RF-VAL-02)
Body: `{ "alcance": "no_verificados" | "todos" | {"uuids": [...]}}` → 202 `{ "tarea_id": "..." }`.

### GET /v1/empresas/{empresa_id}/comprobantes/export — Export a Excel (RF-LIST-02)
Mismos filtros del listado. **202** `{ "tarea_id": "..." }` → al completar, `GET /v1/tareas/{tarea_id}` responde `{ "estado": "completada", "descarga_url": "/v1/descargas-archivo/…" }` (URL firmada temporal, acotada a la empresa).

## 7. Recurso: Vigilancia y eventos (prioridad 3)

### GET /v1/empresas/{empresa_id}/eventos — Alertas (RF-RIES)
Query: `tipo? (cancelacion_tardia|efos|efirma_por_vencer|error_descarga|resumen_sync), desde?, page`.
**200:** paginado con `evento_id, tipo, detalle, created_at`. El `detalle` de EFOS incluye RFC, situación y UUIDs afectados.

### GET /v1/efos/estado — Versión de la lista 69-B cargada
**200:** `{ "version_lista": "2026-07-25", "registros": 12873 }`. Lectura global (cualquier usuario autenticado).

## 8. Recursos: Notificaciones, configuración y bitácora

### GET·PUT /v1/empresas/{empresa_id}/notificaciones — Destinos y suscripciones *(operador+)* (RF-NOT-01)
PUT body: `{ "destinos": [ {"correo": "conta@demo.test", "eventos": ["efos","cancelacion_tardia"]} ] }` → 200. Bitácora.

### GET·PUT /v1/configuracion — Parámetros operativos *(admin)* (RF-CFG-01)
Claves JSON versionadas por ejercicio (`max_meses_ventana`, `hora_sync`, `umbral_vigencia_dias`, …). PUT en bitácora.

### GET /v1/bitacora — Consulta *(admin)* (RF-BIT-01)
Query: `actor?, accion?, entidad?, desde?, hasta?, page`. Solo lectura.

## 8bis. Recurso: Configuración fiscal — añadido post-freeze (2026-08-06, informes CFDI fase 3)

Valores fiscales con **vigencia por fecha** y **procedencia**: UMA, salarios mínimos, tipo de cambio
(`param_fiscal`), las marcas de exención por tipo de percepción del §3.1 (`catalogo_percepcion_marca`)
y la política laboral de cada organización (`configuracion_empresa`, `map_departamento`,
`map_concepto_provision`). Es un recurso distinto del `/v1/configuracion` operativo de arriba (que
versiona reglas del SAT por ejercicio en JSON) y **no deben fusionarse**: ese no puede expresar la
vigencia de la UMA, que cambia el 1 de febrero, a mitad de ejercicio, ni lleva procedencia.

**Invariante que gobierna todo el recurso: un valor sin confirmar no calcula.** Sembrar, cargar o
sincronizar *proponen*; solo una persona confirma. Los informes leen **solo** lo confirmado.

**Capturar y confirmar son dos llamadas.** Un `PUT` guarda con `origen: MANUAL` y **sin** confirmación.

**Los importes viajan como cadena JSON** (`"117.310000"`), en las dos direcciones. Un número JSON se
rechaza con `422`: se convierte pasando por `float` y pierde precisión antes de que el servidor pueda
revisarlo (verificado: `12345678901.123456` llega ya redondeado). Misma regla que el YAML de semillas.

### GET /v1/configuracion/fiscal — Parámetros con procedencia, confirmación y alertas *(admin)*
**200:** `{ "parametros": [ {clave, ejercicio, valor, vigencia_desde, vigencia_hasta, origen, fuente, sincronizado_en, confirmado, confirmado_por, confirmado_en} ], "claves_sin_valor": ["UMA_MENSUAL", …], "alertas": [ {clave, motivo, vigencia_desde, fecha_esperada, detalle} ] }`.
`origen` ∈ `SEMILLA|MANUAL|SINCRONIZADO`. `claves_sin_valor` son las claves conocidas de las que no hay
**ni propuesta**: es el tercer estado (ausente) que la pantalla tiene que poder mostrar.

`alertas` es lo que `claves_sin_valor` **no puede decir: que un valor confirmado ya caducó.** Una UMA de
2025 confirmada aparece "confirmada" en todas las columnas y no está en `claves_sin_valor`, aunque el 1 de
febrero de 2026 ya pasó y ese valor esté mal. `motivo` ∈
`AUSENTE|SIN_CONFIRMAR|CADUCADO|CATALOGO_ILEGIBLE|LIBRERIA_DESACTUALIZADA|SINCRONIZACION_FALLIDA`. Los tres
primeros son estados de un **valor** y piden acciones distintas —capturar / un clic / actualizar el
ejercicio—; los otros tres son de la **maquinaria** (el catálogo de `satcfdi` no se puede leer, la versión
instalada lleva más de un año, el último intento de sincronizar con Banxico falló) y meterlos a la fuerza
en los primeros haría que la alerta mintiera. `detalle` es la frase lista para mostrar: `motivo` es una
etiqueta de máquina y las alertas de maquinaria no se explican solas. `vigencia_desde` y `fecha_esperada`
son nulas en las de maquinaria.

Se calculan en cada petición (dependen de la fecha de hoy: una alerta cacheada de anoche diría "al día" el
1 de febrero por la mañana) y **no hacen ninguna llamada de red**. Esa es la propiedad central del
mecanismo: la UMA cambia el 1 de febrero y el salario mínimo el 1 de enero, así que el sistema sabe que
está desactualizado sin leer el DOF, y eso no se rompe cuando una página cambia de estructura. `TIPO_CAMBIO_USD`
queda **fuera** de la alarma de calendario a propósito —cambia cada día hábil, no por decreto en fecha
fija, y meterlo la dejaría permanentemente en rojo—; su ausencia sigue siendo visible por `claves_sin_valor`.

### PUT /v1/configuracion/fiscal/{clave} — Captura o corrección manual *(admin)*
Body: `{ "valor": "117.31", "vigencia_desde": "2026-02-01", "vigencia_hasta": null, "fuente": "…", "ejercicio": null }`.
**200** con el parámetro resultante: `origen: MANUAL` y `confirmado: false` — capturar no confirma.
**409 `VIGENCIA_SOLAPADA`** si el tramo se pisa con otro de la misma clave (no se cierra el anterior por
cuenta propia: cerrarlo haría indistinguible el error de teclear mal el año). **422
`CONFIGURACION_INVALIDA`** si la clave no está en la lista blanca, el valor no es positivo, **no cabe en
`Numeric(18,6)`** (12 dígitos enteros), **trae más de 6 decimales**, la fuente va vacía o las vigencias
son incoherentes. Corregir la **cifra** de un tramo ya confirmado limpia su confirmación. Bitácora con el
valor anterior y el nuevo.

Los decimales de más **se rechazan, no se redondean**: guardar 6 donde llegaron 10 almacenaría una cifra
distinta de la que la persona revisó, y su siguiente `POST .../confirmar` chocaría con un `409
VALOR_CAMBIO` inexplicable — el que cambió fue el servidor. Ningún valor fiscal real pasa de 4 decimales.
El valor se devuelve siempre con la escala de la columna (`"117.310000"`), la misma en el `PUT` y en el
`GET`.

### POST /v1/configuracion/fiscal/{clave}/confirmar — Activar un valor propuesto *(admin)*
Body: `{ "vigencia_desde": "2026-02-01", "valor": "117.31" }`. El cliente manda **el valor que está
confirmando**. **200** con el parámetro confirmado (idempotente: reconfirmar no reescribe quién revisó).
**409 `VALOR_CAMBIO`** si no coincide con el almacenado — la propuesta cambió entre que la pantalla se
pintó y que se hizo clic, y confirmar a ciegas es lo que el invariante existe para evitar. **404** si no
hay tramo con esa `vigencia_desde`. Bitácora.

### GET·PUT /v1/configuracion/percepciones[/{tipo}] — Marcas del §3.1 *(admin)*
`GET` → `{ "marcas": [ {tipo_percepcion, descripcion_sat, es_ingreso_ordinario, base_exencion, factor_exencion, integra_sbc, es_provisionable, sujeto_a_tope_conjunto, multiplicador_no_derivable, nota_revision, nota_revision_hash, confirmado, confirmado_por, confirmado_en} ], "claves_sin_marcas": ["002", …] }`.

`claves_sin_marcas` son las claves de `c_TipoPercepcion` que **todavía no tienen ninguna marca
capturada**, y espeja `claves_sin_valor` de `/fiscal`. Existe para que el **denominador sea
autoritativo**: sin él, el cliente necesita su propia copia del catálogo del SAT para saber qué
tarjetas existen —y por tanto para el contador "0 de 44" y para el tercer estado, "sin marcas
capturadas"—. `descripcion_sat` no basta: solo etiqueta filas que **ya existen**, no puede hablar
de un tipo que no tiene fila. Con este campo la copia del cliente sobra y desaparece una clase
entera de deriva: al subir la versión de `satcfdi` la lista del servidor crece y la del cliente no.
Si el catálogo embebido no se puede leer llega **vacía** (misma lectura que `descripcion_sat`,
falla abierto); la señal autoritativa de esa avería es la alerta `CATALOGO_ILEGIBLE` de `/fiscal`.
`PUT /{tipo}` body: los **siete** campos de marca **más `nota_revision`**, todos obligatorios (la nota
admite `null`). `base_exencion: NINGUNA` exige `factor_exencion: null` y prohíbe tanto
`sujeto_a_tope_conjunto: true` como `multiplicador_no_derivable: true`; cualquier otra base exige el
factor presente y positivo (**422** si no).
Igual que los importes: **capturar no confirma**, y cambiar una marca limpia la confirmación.

`nota_revision` es **la duda declarada** de ese tipo: qué la genera y qué habría que verificar antes de
confirmarlo. 39 de las 44 marcas sembradas traen una. Viaja en el `GET` para que la pantalla la muestre
al lado del botón de confirmar — sin ella, confirmar sería a ciegas, que es lo que el invariante existe
para impedir. Es editable en el `PUT` porque resolver la duda es parte de revisarla, y **obligatoria
aunque admita `null`** para que borrar una duda cueste escribir `null` en vez de omitir un campo.
Nunca provoca `409` al confirmar (no viaja en ese cuerpo), pero **sí limpia la confirmación de la marca
cuando aparece o cambia** — y no cuando desaparece. La asimetría es deliberada: confirmar es "una persona
revisó esto y responde por ello", así que una duda que esa persona no tenía delante invalida esa
revisión, mientras que resolver una duda no invalida nada. Aquí **no** aplica el precedente de la
`fuente` de `param_fiscal` (que sí conserva la confirmación al cambiar): la fuente dice de dónde salió el
valor, esta nota dice que el valor podría estar mal.

`sujeto_a_tope_conjunto` **no lleva default**: es el mismo cuerpo con el que se confirma, y un default
dejaría que un cliente que ni lo menciona activara —o creara— una marca de previsión social sin el tope
del art. 93 a la vista, que es la condición que la migración `c7a1e0b4d92f` declaró inaceptable.

`multiplicador_no_derivable` (añadido 2026-08-07, migración `a1d93f27e5b8`) dice que al
`factor_exencion` le falta un multiplicador que **el CFDI no trae**: son nueve tipos cuyo número de la
ley viene "por" algo que el comprobante no incluye — "90 UMA por **año de servicio**" (022, 023, 025,
039, 053), "15 UMA **diarias**" (044, 051, 052) y "1 UMA por **domingo laborado**" (020). Con la bandera
en `true`, B-03 deja el tope de exención **vacío** y emite `MULTIPLICADOR_NO_DERIVABLE`; sin ella lo
calcularía suponiendo un multiplicador de 1, publicando un tope muy por debajo del legal que el informe
presentaría como un exceso del patrón que no existe.

Es una columna y no una lista en el programa por el §2.12, y es **la tercera vez** en la misma fase que
hizo falta —después de `sujeto_a_tope_conjunto` y `nota_revision`—, de donde sale la regla general: *si
el cálculo lo necesita, o si quien confirma tiene que verlo, tiene que ser una columna.* Reemplaza a la
aproximación anterior de B-03 (usar `nota_revision`), que era más conservadora de la cuenta —39 de las 44
marcas traen nota y solo nueve por este motivo— y **se desactivaba sin querer** al resolver una nota.

**Tampoco lleva default**, y por un motivo más directo que el del tope conjunto: este campo *sí* calcula,
así que omitirlo activaría el cálculo de un tope inventado sin que nadie lo hubiera mirado. Con
`base_exencion: NINGUNA` tiene que ir en `false`: no hay factor al que le falte un multiplicador.
Entra en la comparación que devuelve `409 MARCAS_CAMBIARON` y en la huella de `--marcas` de la
herramienta de línea de comandos.

`descripcion_sat` es la descripción de `c_TipoPercepcion` ("Becas para trabajadores y/o hijos"), resuelta
del **mismo** `satcfdi` que valida la escritura. Quien confirma necesita ver la clave y la descripción, y
sin este campo el cliente tenía que llevar su propia copia del catálogo: dos copias del mismo dato, y la
del cliente sin actualizarse cuando se actualiza la librería. `null` si la clave no está en la versión
instalada o si el catálogo no se pudo leer — **leer falla abierto, escribir no** (503, ver abajo): una
descripción ausente no impide revisar una marca, escribir sin poder validar sí es inaceptable.

`{tipo}` se valida contra `c_TipoPercepcion` del catálogo embebido de `satcfdi` (44 claves), no solo por
longitud: **422 `TIPO_PERCEPCION_INVALIDO`** si no existe. `150` en vez de `015` crearía una marca
huérfana confirmable mientras la `015` real sigue sin calcular — silencioso en las dos puntas. Si el
catálogo no se puede leer, **503 `CATALOGO_SAT_ILEGIBLE`**: no se escribe sin poder validar.

### POST /v1/configuracion/percepciones/{tipo}/confirmar — Activar las marcas de un tipo *(admin)*
Body: las **seis marcas que calculan** más **`nota_revision_hash`**, sin el texto de la nota — confirmar
no es editar; quien resuelve la duda la borra con un `PUT`, que es el otro acto. **409
`MARCAS_CAMBIARON`** si las marcas diferen de lo almacenado. Sin este método la puerta de confirmación de
esta tabla sería una puerta tapiada: la captura nunca confirma, así que ninguna marca podría llegar a
calcular. Bitácora.

**409 `DUDA_NO_VISTA`** si la marca tiene hoy una duda cuya huella no es la que mandó el cliente. Cierra
la forma **concurrente** de justo lo que la puerta existe para impedir: A abre `010` sin duda, B le agrega
una por `PUT` (u otra persona, o una recarga de semillas), A pulsa Confirmar — las seis marcas no
cambiaron, así que antes esto daba `200` y la marca quedaba confirmada **con una duda que nadie vio**.

Es **la huella y no el texto** porque la razón por la que `nota_revision` está fuera de la comparación de
marcas sigue siendo buena: obligar a reenviar verbatim 800 caracteres de prosa produciría un `409` por una
diferencia de espacios en blanco. Y es un **valor opaco que emite el servidor** (`nota_revision_hash` del
`GET`) y el cliente devuelve tal cual: si el cliente lo calculara tendría que reproducir la normalización
byte a byte, y cualquier discrepancia sería un `409` inexplicable — el mismo fallo que evitamos al
rechazar el redondeo silencioso de los importes. No hay que interpretarlo ni compararlo en el cliente.

La comprobación es **asimétrica, exactamente como la que limpia la confirmación en el `PUT`**: si la duda
**aparece o cambia**, `409`; si la duda **se resolvió** entre que se pintó la pantalla y el clic, pasa —
quien revisó lo hizo contra *más* información de la que hay hoy, y resolver una duda no invalida una
revisión. Sin esa asimetría, resolver una duda invalidaría las confirmaciones en vuelo y la pantalla
devolvería `409` a alguien que hizo exactamente lo correcto, que es como se le enseña a la gente a no
resolver dudas.

`nota_revision_hash` **no lleva default**, por la misma razón que `sujeto_a_tope_conjunto` y
`nota_revision`: este es el cuerpo que activa un valor fiscal, y con un default un cliente que ni menciona
el campo confirmaría sin decir qué duda tenía delante. `null` no es una omisión: afirma "la marca que
revisé no tenía duda declarada", y es lo que mandan las 5 de las 44 que no traen ninguna.

### GET·PUT /v1/empresas/{empresa_id}/configuracion — Política laboral *(GET consulta+ · PUT operador+)*
Body/respuesta: `{ "zona_salarial": "GENERAL"|"ZLFN"|null, "dias_aguinaldo": int|null, "factor_prima_vacacional": "0.2500"|null }`.
Los tres campos **viajan siempre, incluso nulos**: "no configurado" es un estado que degrada B-10 (sin
zona salarial no se evalúa el salario mínimo) y un campo omitido no lo comunica. El `PUT` reemplaza los
tres. `empresa_id` sale del path y lo valida `require_empresa`; el cuerpo no lo lleva. Bitácora.

### GET·PUT /v1/empresas/{empresa_id}/configuracion/mapeos — Centros de costo y provisiones *(GET consulta+ · PUT operador+)*
Body/respuesta: `{ "departamentos": [{departamento_texto, centro_costo}], "conceptos_provision": [{naturaleza, tipo, clave, categoria}] }`
(`categoria` ∈ `AGUINALDO|VACACIONES|PRIMA_VACACIONAL|NO_APLICA`). El `PUT` **reemplaza las dos listas
completas**: lo que no venga deja de existir. **422 `MAPEO_DUPLICADO`** si un cuerpo trae dos renglones
con la misma clave natural. Bitácora con las dos listas enteras, antes y después.

`NO_APLICA` es lo que permite que la clasificación esté **completa**. B-08 necesita saber cuánto
aguinaldo se pagó; con un solo concepto sin clasificar, "aguinaldo pagado = 0" es indistinguible de "sí
se pagó y no sé en cuál concepto viene". Sin esta categoría, marcar "este concepto no es provisión" solo
se podría hacer no capturándolo, que es exactamente lo que hace quien todavía no lo revisó.

### GET /v1/empresas/{empresa_id}/configuracion/conceptos-observados — Lo que la nómina emitió *(consulta+)*
**200:** `{ "conceptos": [{naturaleza, tipo, clave, concepto, descripcion_sat, comprobantes, importe, categoria}], "departamentos": [{departamento_texto, comprobantes, centro_costo}], "sin_clasificar": int, "sin_mapear": int }`.

Los conceptos y departamentos que **aparecen de verdad** en los CFDI de nómina de la empresa, con la
categoría o el centro de costo que ya tengan (o `null`). Existe porque pedirle al usuario que teclee
`P/002/047` era pedirle un dato que no tiene: esas claves las inventa el sistema de nómina del patrón.
Con esta lista la pantalla enumera lo que existe, la persona **reconoce la descripción** y elige
categoría; nunca teclea una clave.

`clave` puede venir nula (el complemento no la exige) y entonces el concepto no se puede clasificar —
`map_concepto_provision` la lleva en la PK—, así que tampoco cuenta en `sin_clasificar`. **Sin filtro de
fecha ni de estatus, a propósito:** no es un informe sino el inventario de lo que hay que configurar, y
un concepto que solo apareció hace dos años sigue necesitando categoría para que la clasificación quede
completa. Cuatro consultas agregadas en total, con `GROUP BY` en la base (regla 11).

### Quién mantiene los valores al día — y el interruptor que lo apaga

La tarea diaria del beat `revisar_vigencia_fiscal` hace dos cosas, en una sola transacción con su bitácora:
intenta sincronizar `TIPO_CAMBIO_USD` con la API SIE de Banxico (serie `SF43718`, token en `BANXICO_TOKEN`)
y después recalcula las alertas. **La sincronización propone, no confirma** —`origen: SINCRONIZADO`,
`confirmado_en` nulo—, exactamente igual que la semilla y la captura manual: ni la API más confiable activa
un valor por su cuenta. Un valor que se desvía más del **50%** del anterior se propone igual, pero con la
desviación calculada dentro de `fuente`, que es lo que la pantalla enseña al lado del botón de confirmar.

**No hay sincronización de la UMA ni del salario mínimo, y no la va a haber.** El INEGI publica la UMA como
boletín PDF y la CONASAMI publica en el DOF; raspar HTML no falla cuando el sitio cambia, devuelve otra cosa,
y el resultado es un valor fiscal viejo con cara de vigente. Lo que sí funciona es el calendario, y eso es
lo que hace la alarma. El razonamiento completo está en el docstring de `app/services/sincronizacion_fiscal.py`.

El interruptor vive en `GET·PUT /v1/config/automatizaciones` *(admin)*, junto a los otros cuatro:
`{ sync_diaria, lista_69b, re_verificar, limpieza, vigencia_fiscal }`, todos booleanos, default `true`,
bitácora en el `PUT`. **`vigencia_fiscal` es el único con default en el cuerpo del `PUT`**: los otros cuatro
son del contrato congelado y este llegó después, así que un cliente anterior no debe recibir `422`. La
pantalla hace `{...autos, [clave]: valor}` sobre lo que devolvió el `GET`, de modo que el valor viaja de ida
y vuelta y el default no llega a resetear un interruptor que el administrador apagó.

> **No existe un endpoint de "recargar semillas desde YAML"**, a propósito: `cargar_desde_yaml` hace
> `commit`/`rollback` sobre la sesión de quien la llama, y ese `rollback` descartaría la fila de bitácora
> que la regla 8 exige escribir en la misma transacción. El cargador es del script de línea de comandos.

---

## 9. Interfaz `ApiClient` (congelada — freeze de Fase 1, 2026-07-27)

Literal de `apps/web/src/lib/api.ts`. Dos campos y un módulo se añadieron respecto al borrador porque el
demo (Claude Design) los ejercita: `Job.id_solicitud` y `Comprobante.xml_path` (los muestran los drawers
P6/P7), y `listarUsuarios`/`listarConfiguracion`/`listarBitacora` (P10/P11, antes solo descritos como
endpoints REST en §2/§8 sin entrada en esta interfaz). Las mutaciones de usuarios de §2 (alta, permisos,
activar/desactivar) no se añaden aquí porque P10 es de solo lectura en el demo — se agregan cuando exista
una UI real que las use.

```typescript
// apps/web/src/lib/api.ts — contrato único; api.mock.ts hoy, api.http.ts cuando exista el backend real
export type Rol = 'admin' | 'operador' | 'consulta';
export type EstadoJob = 'NUEVO' | 'SOLICITADO' | 'EN_PROCESO' | 'TERMINADA' | 'DESCARGADO' | 'ERROR';
export type EstatusCfdi = 'vigente' | 'cancelado' | 'no_verificado';
export type TipoEvento = 'cancelacion_tardia' | 'efos' | 'efirma_por_vencer' | 'error_descarga' | 'resumen_sync';

export interface Page<T> { data: T[]; page: number; per_page: number; total: number }
export interface EmpresaResumen { empresa_id: number; nombre: string; rfc: string; rol: Rol;
                                  activo: boolean; efirma: { presente: boolean; not_after: string | null } | null }
export interface Job { job_id: number; tipo: 'emitido' | 'recibido'; solicitud: 'CFDI' | 'METADATA';
                       origen: 'manual' | 'sync'; desde: string; hasta: string; estado: EstadoJob;
                       intentos: number; paquetes: number; mensaje: string | null; updated_at: string;
                       id_solicitud: string | null }
export interface Comprobante { comprobante_id: number; uuid: string; folio: string | null;
                               rfc_emisor: string; rfc_receptor: string; razon_social_emisor: string | null;
                               total: number | null; fecha_emision: string | null; tipo_comprobante: string | null;
                               estatus: EstatusCfdi; estatus_verificado_at: string | null; xml_path: string | null }
export interface Evento { evento_id: number; tipo: TipoEvento; detalle: Record<string, unknown>; created_at: string }
export interface NotificacionDestino { correo: string; eventos: TipoEvento[] }
export interface UsuarioAdmin { usuario_id: number; correo: string; nombre: string; rol_global: Rol;
                                activo: boolean; permisos: { empresa_id: number; empresa_nombre: string; rol: Rol }[] }
export interface ConfiguracionItem { clave: string; ejercicio_fiscal: string; valor: string; descripcion: string }
export interface BitacoraEntrada { bitacora_id: number; actor: string; accion: string; entidad: string;
                                   detalle: Record<string, unknown>; created_at: string }

// Configuración fiscal — añadido post-freeze (2026-08-06, informes fase 3). Ver §8bis.
// Los importes van como CADENA en las dos direcciones (`valor`, `factor_prima_vacacional`,
// `importe`): un número JSON pasa por `float` y el backend lo rechaza con 422.
export type OrigenValor = 'SEMILLA' | 'MANUAL' | 'SINCRONIZADO';
export type ZonaSalarial = 'GENERAL' | 'ZLFN';
export type CategoriaProvision = 'AGUINALDO' | 'VACACIONES' | 'PRIMA_VACACIONAL' | 'NO_APLICA';
export interface ParametroFiscal { clave: string; ejercicio: number; valor: string; vigencia_desde: string;
                                   vigencia_hasta: string | null; origen: OrigenValor; fuente: string;
                                   sincronizado_en: string | null; confirmado: boolean;
                                   confirmado_por: string | null; confirmado_en: string | null }
// Alarma de vigencia (§8bis). Se recalcula en cada GET y no usa red. Los tres primeros motivos
// describen un VALOR (capturar / un clic / actualizar el ejercicio); los tres últimos, la
// MAQUINARIA. `detalle` es la frase lista para mostrar.
export type MotivoAlertaVigencia = 'AUSENTE' | 'SIN_CONFIRMAR' | 'CADUCADO'
                                 | 'CATALOGO_ILEGIBLE' | 'LIBRERIA_DESACTUALIZADA' | 'SINCRONIZACION_FALLIDA';
export interface AlertaVigencia { clave: string; motivo: MotivoAlertaVigencia;
                                  vigencia_desde: string | null; fecha_esperada: string | null; detalle: string }
export interface ConfiguracionFiscal { parametros: ParametroFiscal[]; claves_sin_valor: string[];
                                       alertas: AlertaVigencia[] }
export interface ParametroFiscalIn { valor: string; vigencia_desde: string; vigencia_hasta?: string | null;
                                     fuente: string; ejercicio?: number | null }
// Marcas de exención del art. 93 (§8bis). `factor_exencion` es CADENA o nula, como todos los
// importes, y su unidad la decide `base_exencion`; con `PORCENTAJE` está en **escala 0-100, no como
// fracción** ("100" = el cien por ciento). `sujeto_a_tope_conjunto`, `multiplicador_no_derivable` y
// `nota_revision` NO llevan
// default: omitirlos es 422 (§8bis explica por qué cada uno).
export type BaseExencion = 'UMA_DIAS' | 'SM_DIAS' | 'PORCENTAJE' | 'NINGUNA';
export interface MarcasPercepcion { es_ingreso_ordinario: boolean; base_exencion: BaseExencion;
                                    factor_exencion: string | null; integra_sbc: boolean;
                                    es_provisionable: boolean; sujeto_a_tope_conjunto: boolean;
                                    multiplicador_no_derivable: boolean }
export interface MarcaPercepcionIn extends MarcasPercepcion { nota_revision: string | null }
// Cuerpo del confirmar: las seis marcas MÁS la huella de la duda que se tenía delante. Opaca —
// se copia de `MarcaPercepcion.nota_revision_hash` y se devuelve tal cual, nunca se calcula ni
// se compara en el cliente. Sin default: `null` afirma "no había duda", omitirlo es 422.
export interface MarcaPercepcionConfirmarIn extends MarcasPercepcion { nota_revision_hash: string | null }
// `descripcion_sat` sale del mismo `c_TipoPercepcion` de `satcfdi` que valida la escritura.
// `nota_revision_hash` es la huella opaca que hay que devolver al confirmar (ver §8bis).
export interface MarcaPercepcion extends MarcasPercepcion { tipo_percepcion: string;
                                    descripcion_sat: string | null;
                                    nota_revision: string | null; nota_revision_hash: string | null;
                                    confirmado: boolean;
                                    confirmado_por: string | null; confirmado_en: string | null }
// El GET de percepciones devuelve un OBJETO, no una lista: `claves_sin_marcas` es el resto del
// catálogo del SAT y hace autoritativo el denominador del "0 de 44". Con él, la copia del
// catálogo que el cliente llevaba (`catalogoTipoPercepcion.ts`) se puede BORRAR.
export interface CatalogoPercepciones { marcas: MarcaPercepcion[]; claves_sin_marcas: string[] }
export interface ConfiguracionEmpresa { empresa_id: number; zona_salarial: ZonaSalarial | null;
                                        dias_aguinaldo: number | null; factor_prima_vacacional: string | null }
export type ConfiguracionEmpresaIn = Omit<ConfiguracionEmpresa, 'empresa_id'>;
export interface MapeoDepartamento { departamento_texto: string; centro_costo: string }
export interface MapeoConceptoProvision { naturaleza: string; tipo: string; clave: string; categoria: CategoriaProvision }
export interface MapeosEmpresa { departamentos: MapeoDepartamento[]; conceptos_provision: MapeoConceptoProvision[] }
export interface ConceptoObservado { naturaleza: string; tipo: string; clave: string | null; concepto: string | null;
                                     descripcion_sat: string | null; comprobantes: number; importe: string;
                                     categoria: CategoriaProvision | null }
export interface DepartamentoObservado { departamento_texto: string; comprobantes: number; centro_costo: string | null }
export interface ObservadosEmpresa { conceptos: ConceptoObservado[]; departamentos: DepartamentoObservado[];
                                     sin_clasificar: number; sin_mapear: number }

export interface ApiClient {
  // Sesión (prioridad 1)
  me(): Promise<{ usuario_id: number; correo: string; nombre: string; rol_global: Rol; empresas: EmpresaResumen[] }>;
  // Empresas
  listarEmpresas(): Promise<EmpresaResumen[]>;
  crearEmpresa(input: { nombre: string; rfc: string }): Promise<EmpresaResumen>;
  /** Añadido post-freeze (2026-07-28) — RF-EMP-02, PATCH /v1/empresas/{id}, solo admin. */
  actualizarEmpresa(empresaId: number, input: { activo: boolean }): Promise<EmpresaResumen>;
  /** Añadido post-freeze (2026-07-28) — DELETE /v1/empresas/{id}, solo admin. Borrado real
   * (a diferencia de actualizarEmpresa con activo=false); 409 EMPRESA_CON_HISTORIAL si la
   * empresa ya tiene e.firma/jobs/comprobantes (doc 04 §4.4: el historial fiscal no se borra). */
  eliminarEmpresa(empresaId: number): Promise<void>;
  // Bóveda (prioridad 1)
  subirEfirma(empresaId: number, files: { cer: File; key: File; password: string; escenarioDemo?: string }):
    Promise<{ num_serie: string; not_before: string; not_after: string; dias_para_vencer: number }>;
  obtenerEfirma(empresaId: number): Promise<{ num_serie: string; not_before: string; not_after: string } | null>;
  eliminarEfirma(empresaId: number): Promise<void>;
  // Descargas (prioridad 2)
  crearDescarga(empresaId: number, input: { tipo: 'emitido' | 'recibido'; solicitud: 'CFDI' | 'METADATA';
                desde: string; hasta: string; simVencidaDemo?: boolean }): Promise<{ job_ids: number[]; ventanas: number }>;
  listarJobs(empresaId: number, f?: { estado?: EstadoJob; origen?: 'manual' | 'sync'; page?: number }): Promise<Page<Job>>;
  reintentarJob(empresaId: number, jobId: number): Promise<void>;
  // Comprobantes (prioridades 2–3)
  listarComprobantes(empresaId: number, f?: { desde?: string; hasta?: string; estatus?: EstatusCfdi;
                     tipo_comprobante?: string; direccion?: 'emitido' | 'recibido'; q?: string; page?: number }): Promise<Page<Comprobante>>;
  validarLote(empresaId: number, alcance: 'no_verificados' | 'todos' | { uuids: string[] }): Promise<{ tarea_id: string }>;
  exportarExcel(empresaId: number, f?: Record<string, string>): Promise<{ tarea_id: string }>;
  estadoTarea(tareaId: string): Promise<{ estado: 'pendiente' | 'completada' | 'fallida'; descarga_url?: string }>;
  // Vigilancia y notificaciones (prioridad 3)
  listarEventos(empresaId: number, f?: { tipo?: TipoEvento; page?: number }): Promise<Page<Evento>>;
  obtenerNotificaciones(empresaId: number): Promise<{ destinos: NotificacionDestino[] }>;
  guardarNotificaciones(empresaId: number, destinos: NotificacionDestino[]): Promise<void>;
  // Administración (añadido en el freeze — doc 05 §2/§8, consumido por P10/P11; solo lectura)
  listarUsuarios(): Promise<UsuarioAdmin[]>;
  listarConfiguracion(): Promise<ConfiguracionItem[]>;
  listarBitacora(f?: { page?: number }): Promise<Page<BitacoraEntrada>>;
  // Configuración fiscal (§8bis) — añadido post-freeze (2026-08-06, informes fase 3), consumido por
  // la pestaña /admin/fiscal y por /e/:id/configuracion. Los tres primeros son solo admin; los de
  // empresa siguen el reparto de siempre (GET consulta+, PUT operador+).
  listarConfiguracionFiscal(): Promise<ConfiguracionFiscal>;
  capturarParametroFiscal(clave: string, input: ParametroFiscalIn): Promise<ParametroFiscal>;
  confirmarParametroFiscal(clave: string, input: { vigencia_desde: string; valor: string }): Promise<ParametroFiscal>;
  // Marcas del art. 93, solo admin. 422 TIPO_PERCEPCION_INVALIDO si `{tipo}` no está en
  // `c_TipoPercepcion`; 503 CATALOGO_SAT_ILEGIBLE —transitorio— si no se puede leer el catálogo.
  // El GET devuelve un OBJETO (marcas + claves_sin_marcas) y el confirmar pide la huella de la
  // duda: 409 DUDA_NO_VISTA si la marca tiene hoy una duda que no es la que el cliente vio.
  listarMarcasPercepcion(): Promise<CatalogoPercepciones>;
  guardarMarcaPercepcion(tipo: string, input: MarcaPercepcionIn): Promise<MarcaPercepcion>;
  confirmarMarcaPercepcion(tipo: string, input: MarcaPercepcionConfirmarIn): Promise<MarcaPercepcion>;
  obtenerConfiguracionEmpresa(empresaId: number): Promise<ConfiguracionEmpresa>;
  guardarConfiguracionEmpresa(empresaId: number, input: ConfiguracionEmpresaIn): Promise<ConfiguracionEmpresa>;
  obtenerMapeosEmpresa(empresaId: number): Promise<MapeosEmpresa>;
  guardarMapeosEmpresa(empresaId: number, input: MapeosEmpresa): Promise<MapeosEmpresa>;
  obtenerConceptosObservados(empresaId: number): Promise<ObservadosEmpresa>;
}
```

**Los métodos de `catalogo_percepcion_marca` se añadieron en una segunda vuelta (2026-08-06)**, no en la
primera, y la razón importa: las 44 marcas se sembraron con **39 dudas declaradas**
(`config/fiscal/README.md` §5.3) que hasta la ronda 2 de la tarea 4 vivían en comentarios del YAML y **no
viajaban en la respuesta**. Una pantalla que ofreciera "Confirmar" sobre esas filas habría dejado confirmar
a ciegas justo lo que el invariante existe para impedir. Hoy `nota_revision` es columna y viaja en el `GET`,
así que la duda puede estar donde tiene que estar —al lado del botón— y la pantalla ya se puede construir.

**La copia del catálogo del SAT que llevaba el cliente ya no existe.** Vivía en
`apps/web/src/features/admin/catalogoTipoPercepcion.ts` y hacía dos cosas: describir la clave (`015` →
"Becas para trabajadores y/o hijos", que quien confirma necesita ver) y **decidir qué tarjetas existen** —el
denominador del "0 de 44" y el tercer estado, "sin marcas capturadas"—. `descripcion_sat` resolvió lo
primero y `claves_sin_marcas` lo segundo, así que la copia se borró (2026-08-06) y con ella la deriva: al
subir la versión de `satcfdi` la lista del servidor crece y ya no hay ninguna del cliente que se quede
atrás. Efecto secundario conocido: un tipo **sin ninguna fila** se pinta solo con su clave, porque
`claves_sin_marcas` no lleva descripción.

Campos `escenarioDemo`/`simVencidaDemo` de `subirEfirma`/`crearDescarga` son exclusivos de
`VITE_DEMO_CONTROLS` (fuerzan la respuesta del backend simulado para la sesión de validación) — no
existen en `api.http.ts` cuando se construya el backend real.

> Cobertura: sesión/usuarios, empresas, bóveda, descargas/máquina de estados (crear/monitorear/reintentar), comprobantes (listar/validar/exportar), eventos, notificaciones, administración (usuarios/configuración/bitácora, solo lectura) — todos los módulos del SRS §3.
