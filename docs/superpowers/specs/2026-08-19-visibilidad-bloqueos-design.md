# Visibilidad de bloqueos: banner de configuración fiscal y recuperación de jobs huérfanos

**Fecha:** 2026-08-19
**Estado:** diseño aprobado, pendiente de plan de implementación

## 1. El problema

Dos huecos de visibilidad detectados el 2026-08-19 revisando la aplicación en vivo contra la base
real de la empresa 11.

**Hueco 1 — un bloqueo invisible.** `tarifa_isr` está vacía, así que B-09 no puede generar ni una
fila. El sistema lo sabe: `revisar_vigencia_fiscal` levantó la alerta `TARIFA_ISR / AUSENTE` y la
pantalla de configuración fiscal la muestra. Pero la pantalla que se llama **Alertas** no la
muestra, y el tablero tampoco: su tarjeta "Alertas 3" son los tres eventos `resumen_sync` de julio.
Para enterarse del bloqueo más grave del sistema hay que saber ir a Configuración → Fiscal.

La causa es estructural, no un olvido: las alertas de vigencia son **globales** y viven en
`GET /configuracion/fiscal` bajo `require_admin`, mientras la pantalla Alertas lista `eventos`
**de una empresa** y la ven también los operadores. Dos ámbitos y dos permisos que nunca se
cruzaron.

**Hueco 2 — cuatro jobs muertos que nadie reporta.** Los jobs 16-19 (empresa 11, ventana
2026-07-28→29) quedaron en `NUEVO` con `intentos=0` e `id_solicitud=NULL` desde el 2026-07-30:
`ejecutar_job.delay()` se llamó, pero el mensaje se perdió al detener los servicios y **nada
reencola un job en `NUEVO`**. La cola de Celery está vacía (`LLEN celery` = 0). El tablero dice
"Jobs activos 0 · en proceso ahora", que es literalmente cierto —ninguno está corriendo— pero un
operador no tiene por qué notar que hay cuatro inertes.

## 2. Decisiones de alcance

Tomadas con David el 2026-08-19:

1. **Visibilidad, no notificación.** Enterarse al entrar a la aplicación. No se persisten las
   alertas fiscales como eventos ni se manda correo: no se toca `eventos` ni `notificacion_log`.
2. **Banner en el tablero**, reusando el patrón del banner de e.firma que ya existe.
3. **Solo lo que bloquea.** El banner aparece únicamente cuando algo impide que un informe se
   genere. Lo que solo degrada no pone banner.
4. **Los jobs huérfanos se recuperan, no se muestran.** Se elimina la causa en lugar de exponer el
   síntoma; el tablero no cambia.

## 3. Parte 1 — Banner de configuración fiscal

### 3.1 Qué ve el operador

Una franja arriba del tablero, con la forma del banner de e.firma
(`TableroPage.tsx:29-34`):

> ⚠️ **No se puede recalcular el ISR: falta la tarifa quincenal de 2026.** → *Ir a configuración fiscal*

**El texto no se redacta aquí.** Sale literal de `configuracion_isr.faltantes`, que ya produce una
frase por causa (`AVISO_SIN_TARIFA`, `AVISO_SIN_MARCAS`). Es la misma frase que B-09 emite como
aviso al negarse a generar. Que el banner y el informe digan lo mismo palabra por palabra no es
estética: si divergen, uno de los dos miente.

### 3.2 Qué cuenta como bloqueo

Ponen banner las dos causas que dejan a B-09 sin producir ninguna fila:

1. **Tarifa del ISR** ausente o sin confirmar para una periodicidad que la empresa usa.
2. **Marcas de percepción** sin confirmar de los tipos que la empresa de verdad timbró.

**No** ponen banner, a propósito:

- El **subsidio al empleo** sin confirmar: B-09 sí genera, con las columnas de comparación vacías y
  su propia nota. Degradar no es bloquear.
- El **fallo de sincronización de Banxico** y el **tipo de cambio** sin capturar: no bloquean ningún
  informe de nómina. Con el token ausente esa alerta es permanente, y un banner permanente se
  vuelve mobiliario — la fatiga de alertas ya está en el registro de riesgos del roadmap.

**Condición de silencio:** si la empresa no tiene CFDI de nómina, no hay banner. Un bloqueo sobre un
informe sin datos que procesar no es un bloqueo; sin esta condición todas las empresas nuevas
nacerían con el banner encendido.

### 3.3 Implementación

`GET /empresas/{empresa_id}/informes/isr/diagnostico` → `{ bloqueado: bool, faltantes: [str] }`.

Tres pasos: dos consultas ligeras para las periodicidades y los tipos de percepción presentes en la
nómina de la empresa en el ejercicio, y una llamada a `configuracion_isr.resolver()` —que ya existe
y hace seis consultas fijas. No se invoca el motor de informes.

El tablero lo consume con `useQuery`, igual que los demás datos.

**Qué ejercicio se diagnostica: el del último CFDI de nómina de la empresa**, no el año en curso.
Con datos que acaban en julio de 2026, en enero de 2027 el año en curso haría aparecer "falta la
tarifa de 2027" —un bloqueo falso, porque no hay ningún recibo de 2027 que recalcular—. Y se
diagnostica **solo ese ejercicio**, no todos los que tengan datos: avisar de la tarifa de 2023
porque quedan recibos viejos en el acervo es ruido sobre un informe que nadie va a generar. Es la
misma razón de la condición de silencio de §3.2: el banner habla de los datos que hay, no del
calendario.

**Permisos.** El endpoint vive bajo la empresa y lo lee cualquier rol con acceso a ella, incluido
consulta: es un diagnóstico de los datos de esa empresa, no la configuración fiscal. El enlace del
banner apunta a `/admin/fiscal`, que sigue siendo admin-only. Un operador ve *que* está bloqueado y
a quién pedírselo; no puede confirmar valores fiscales.

### 3.4 Riesgo: dos caminos al mismo hecho

B-09 deriva `tipos_presentes` y `periodicidades_presentes` de los datos que ya cargó en memoria
(`b09_recalculo_isr.py:540`), no con consultas —es su regla de cero N+1. El endpoint los va a sacar
por SQL. **Son dos caminos al mismo hecho: si divergen, el banner dirá "todo bien" mientras B-09 se
niega a generar.** Es la clase de defecto que ya costó una ronda en la fase 2 (dos informes del
mismo periodo con totales distintos, resuelto extrayendo `universo_nomina`).

No se unifican porque hacerlo metería consultas nuevas dentro del informe y rompería su regla 11.
Se atan con una **prueba de consistencia**: sobre los mismos datos sembrados, el diagnóstico y B-09
deben coincidir en si está bloqueado y en el texto de los faltantes. Si alguien cambia un camino y
no el otro, la prueba falla.

## 4. Parte 2 — Recuperación de jobs huérfanos

### 4.1 El hallazgo que ordena el trabajo

`paso_job` documenta que es "re-entrante y sin estado en memoria: relee todo de la BD, así que si un
worker muere a medias, la siguiente invocación retoma sin duplicar `id_solicitud`"
(`tasks.py:261`). Es cierto **en secuencia**.

No en **concurrencia**: `transicion()` valida la legalidad contra `job.estado` ya cargado en memoria
(`jobs.py:41`), sin bloqueo de fila. Dos invocaciones simultáneas del mismo job leen `NUEVO` las
dos, las dos pasan la validación, y las dos llaman a `facade.solicitar()`.

Hoy no ocurre porque existe **un solo mensaje por job**. Una recuperación que reencola crea la
posibilidad: mensaje viejo en la cola más mensaje nuevo. Y el daño es concreto —el SAT rechaza la
solicitud duplicada exacta con `CodEstatus=5005`, lo que produce `SatRechazoError` y manda el job a
`ERROR`. **Una recuperación ingenua puede matar un job que estaba bien.** De ahí el orden: primero
la toma atómica, después la recuperación.

### 4.2 Pieza 1 — Toma atómica del job

Columna nueva `jobs.tomado_en DATETIME NULL` con migración de Alembic, y
`jobs_repo.tomar_para_solicitar(db, job_id)` que hace un compare-and-swap en una sentencia:

```sql
UPDATE jobs SET tomado_en = NOW()
WHERE job_id = ? AND estado = 'NUEVO'
  AND (tomado_en IS NULL OR tomado_en < NOW() - INTERVAL 30 MINUTE)
```

`rowcount = 0` → alguien más lo tomó; `_paso_nuevo` sale sin tocar el SAT. `rowcount = 1` → el job
es suyo.

**Por qué una columna y no un lock en Redis:** en este diseño la máquina de estados vive en la BD
—`transicion()` es "el único punto por el que un job cambia de estado"—. Un lock en Redis pondría
parte de ese estado fuera de la fuente de verdad y no sería auditable. Con la columna se puede ver
cuándo se tomó cada job.

**Por qué no `SELECT ... FOR UPDATE`:** exigiría mantener la transacción abierta durante la llamada
de red al SAT. Bloquear una fila de MySQL mientras se espera al SAT invita a un timeout de lock.

Esta pieza **vale por sí sola**: hoy un doble clic en "Reintentar" desde la UI puede producir dos
solicitudes al SAT.

### 4.3 Pieza 2 — La recuperación

`recuperar_jobs_encolados`: busca jobs en `NUEVO`, con `id_solicitud IS NULL` y `updated_at` de hace
más de 30 minutos, y les hace `ejecutar_job.delay()`. Se dispara desde la señal `worker_ready` de
Celery. El hook son tres líneas que llaman a la tarea; la lógica vive en una función normal que se
prueba sin señales.

**El umbral de 30 minutos.** Un job en `NUEVO` que reintenta legítimamente porque el SAT anda
saturado se ve *idéntico* a un huérfano: `SatReintentableError` se propaga sin tocar el job, así que
ni `estado` ni `updated_at` cambian. Con `retry_backoff_max=300` y `max_retries=8` el peor caso de
reintentos legítimos suma unos 9 minutos; 30 da margen.

Y por la pieza 1, **equivocarse en el umbral no hace daño**: el CAS impide la segunda solicitud. La
toma atómica es lo que vuelve seguro el margen de error.

### 4.4 Lo que no cambia

El tablero. Su etiqueta "Jobs activos · en proceso ahora" ya es honesta y excluye `NUEVO` a
propósito. Con la recuperación no hay jobs muertos que reportar.

### 4.5 Los cuatro jobs de hoy

**Decisión de David: marcarlos `ERROR` antes de desplegar**, para que la recuperación arranque con
la casa limpia y no dispare cuatro solicitudes al SAT por una ventana de julio.

**Consecuencia no obvia, y su mitigación.** `ultima_ventana_sincronizada` **excluye** los jobs en
`ERROR` (`jobs.py:75-95`). Al marcarlos:

- `emitido/CFDI`, `recibido/CFDI`, `recibido/METADATA` conservan jobs `DESCARGADO` con
  `fecha_final = 2026-07-28`, así que la sync siguiente arranca ahí y cubre el hueco.
- `emitido/METADATA` se queda **sin ningún job no-`ERROR`** (los jobs 9 y 13 ya están en `ERROR`).
  `ultima` pasa a `None` y la sync arrancaría en `ayer - 1 día`, **dejando sin pedir la metadata de
  emitidos del 2026-07-28 en adelante**.

Mitigación: al reactivar la sync diaria, lanzar **una descarga manual** de `emitido/METADATA` para
la ventana 2026-07-28 → ayer. Es una acción de la UI, no código.

## 5. Pruebas

Lo que de verdad protege este trabajo:

- **La carrera**, con dos ejecuciones concurrentes del mismo job: solo una llega al SAT. Sin esta
  prueba la pieza 1 no demuestra nada.
- **Mutación sobre el CAS**: quitar `estado = 'NUEVO'` del `WHERE` debe hacer **fallar** la prueba de
  la carrera. Hay que exigir el fallo y mirar el conteo de selección de `-k` —un `-k` que no
  selecciona nada sale con código 5 y se ve igual que una mutación muerta.
- Un huérfano de hace 40 minutos se reencola; uno de hace 5 minutos no se toca; uno en `SOLICITADO`
  nunca.
- **Consistencia** entre el diagnóstico del ISR y B-09 (§3.4).
- Una empresa sin CFDI de nómina no produce banner.
- Con tarifa y marcas confirmadas, `bloqueado = false` y `faltantes` vacío.

## 6. Verificación en vivo (criterio de cierre)

Ninguna parte se da por terminada con las pruebas contra dobles en verde:

- Con la base como está hoy (sin tarifa), el tablero de la empresa 11 muestra el banner con el texto
  de la tarifa faltante, y el enlace lleva a la pantalla que lo resuelve.
- Tras confirmar tarifa y marcas, el banner desaparece **y** B-09 genera sus 8 filas. El mismo
  cambio de estado apaga el banner y desbloquea el informe.
- Un job sembrado en `NUEVO` con `updated_at` viejo se recupera al reiniciar el worker, y el
  reinicio no toca ningún job legítimo.

## 7. Fuera de alcance

- **Persistir las alertas fiscales como eventos** y notificarlas por correo (decisión 1 de §2).
- **Listar las alertas fiscales en la pantalla Alertas.** Cruzaría el ámbito global con el de
  empresa y le mostraría a un operador no-admin una alerta que no puede resolver.
- **Cambiar los KPI del tablero.** Con la recuperación funcionando no hay nada nuevo que contar.
- **Un tick periódico de recuperación en `beat`** además de la señal `worker_ready`. Cubriría el
  caso de un mensaje perdido con el worker vivo; es una línea en `beat_schedule` si algún día se
  quiere, y la pieza 1 ya lo hace seguro.
- **Reactivar `auto_sync_diaria`** (hoy en `false` por decisión del 2026-07-30) y **el
  `BANXICO_TOKEN`**: operación, no código.
