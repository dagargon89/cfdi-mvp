# Auditoría del nivel 3 — Ciclo de descarga del SAT

**Fecha:** 2026-08-20
**Sistema:** Hub CFDI · rama `main`
**Método:** pruebas adversariales automatizadas, barrido exhaustivo de la máquina de estados y una prueba de concurrencia real
**Batería:** [`tests/auditoria/test_nivel3_ciclo_descarga.py`](../../tests/auditoria/test_nivel3_ciclo_descarga.py)

## Veredicto

**18 de 19 pruebas en verde. La que falta no es un error: es un defecto conocido, ahora
reproducido con un número exacto.**

`N3-03` demuestra que dos ejecuciones concurrentes del mismo job envían **2 solicitudes al SAT**
donde debía haber una. Queda marcada `xfail(strict=True)` para que no se pierda de vista: cuando se
arregle, la prueba pasará y `strict` hará fallar la suite hasta que alguien quite la marca.

Todo lo demás resiste, incluidas las dos regresiones de fallos que ya ocurrieron en producción.

## 1. Por qué este nivel es el más delicado

Los niveles 1 y 2 protegen contra accesos indebidos. Este nivel no protege nada: **produce**. Un
fallo aquí no filtra información — pierde datos fiscales sin avisar, o le pide al SAT cosas que va a
rechazar. Y lo que se pierde no se nota: un día de CFDI que nunca se descargó no deja hueco visible
hasta que alguien cuadra contra la contabilidad.

## 2. Máquina de estados

| ID | Prueba | Cobertura | Resultado |
|---|---|---|---|
| N3-01 | Ninguna transición ilegal pasa | **36 combinaciones** (todas las posibles) | **PASA** |
| N3-02 | Las once transiciones legales sí pasan | 11 pares | **PASA** |

N3-01 no prueba una muestra: recorre **todos** los pares `estado × estado` y exige que cada uno
fuera de las once transiciones legales sea rechazado. Es el barrido que detecta que alguien "abra"
una transición al añadir un caso de uso.

El par más importante que cubre es `NUEVO → DESCARGADO`: un job que nunca habló con el SAT no puede
aparecer como descargado, porque los informes lo darían por bueno **sin tener un solo XML detrás**.

N3-02 es su control positivo. Sin él, una máquina de estados que rechazara *todo* dejaría N3-01 en
verde.

## 3. El defecto: la carrera de la doble solicitud

| ID | Prueba | Esperado | Obtenido |
|---|---|---|---|
| N3-03 | Dos ejecuciones concurrentes del mismo job | 1 solicitud al SAT | **2 solicitudes** |

**Cómo se reprodujo.** Dos invocaciones simultáneas de `paso_job` sobre el mismo job en `NUEVO`,
cada una con **su propia sesión de base de datos** —igual que dos workers de Celery— lanzadas con
`asyncio.gather`. Un doble del facade cuenta las llamadas a `solicitar()`. Contó 2.

**La causa.** `transicion()` valida la legalidad contra `job.estado` **ya cargado en memoria**
([`jobs.py:41`](../../app/repositories/jobs.py:41)), sin bloqueo de fila. Las dos ejecuciones leen
`NUEVO`, las dos pasan la validación, las dos llaman al SAT.

**Por qué importa más de lo que parece.** El daño no es gastar cuota de solicitudes: el SAT rechaza
la solicitud duplicada exacta con `CodEstatus=5005`, lo que produce `SatRechazoError` y manda a
`ERROR` **un job que estaba perfectamente bien**. La duplicación no desperdicia trabajo, lo destruye.

**Cuándo se dispara hoy.** No ocurre en la operación normal porque existe un solo mensaje de Celery
por job. Se alcanza con un **doble clic en "Reintentar"** desde la interfaz, y se alcanzaría de
forma sistemática al añadir cualquier recuperación que reencole jobs.

**El arreglo, ya diseñado y aprobado**: toma atómica con la columna `tomado_en` y un
compare-and-swap en una sola sentencia
([diseño del 2026-08-19](../superpowers/specs/2026-08-19-visibilidad-bloqueos-design.md), §4.2).
Esta prueba es exactamente la que debe pasar cuando se implemente.

## 4. Validación de rangos

| ID | Ataque | Esperado | Resultado |
|---|---|---|---|
| N3-04 | `hasta` anterior a `desde` | `RangoInvalidoError` | **PASA** |
| N3-05 | Rango de un solo día calendario | `RangoInvalidoError` | **PASA** |
| N3-06 | Un año completo | se **trocea**, no se rechaza | **PASA** |
| N3-07 | Empresa sin e.firma | `EfirmaAusenteError` y **cero jobs creados** | **PASA** |
| N3-08 | e.firma vencida | `FielVencidaError` | **PASA** |
| N3-09 | Empresa desactivada | `EmpresaInactivaError` | **PASA** |

**N3-05 es una regresión de un fallo real.** El 2026-07-28 cuatro jobs de la sincronización diaria
murieron con `CodEstatus=301` porque el SAT rechaza un rango cuyo inicio y fin caen en el mismo día
calendario. La guarda existe desde entonces; esta prueba la fija.

**N3-06 comprueba la decisión correcta, no la fácil.** Un año entero no se rechaza: se parte en
ventanas que el SAT sí acepta. La prueba verifica además que ninguna ventana resultante quede
invertida ni de un solo día — si el troceo produjera una así, el SAT la rechazaría igual y el
backfill histórico fallaría a la mitad.

N3-07 y N3-08 no se conforman con la excepción: confirman que **no quedó ningún job en la tabla**.
Crear el job y dejarlo fallar después daría al operador la impresión de que la descarga va en marcha.

## 5. Robustez del diálogo con el SAT

| ID | Ataque | Esperado | Resultado |
|---|---|---|---|
| N3-10 | `EstadoSolicitud` fuera del catálogo 1-6 | seguir sondeando, **no** ERROR | **PASA** |
| N3-11 | Rechazo definitivo del SAT | ERROR **con mensaje** | **PASA** |
| N3-12 | Job ya `DESCARGADO` reprocesado | no toca el SAT, no cambia de estado | **PASA** |
| N3-13 | Job borrado entre encolado y ejecución | termina limpio, sin excepción | **PASA** |

**N3-10 no es hipotético.** `EstadoSolicitud=0` con "Error no controlado" apareció en los logs del
2026-08-20. Tratarlo como error definitivo mataría jobs por una respuesta que el SAT corrige al
siguiente sondeo.

**N3-11 protege al operador, no al sistema.** Un job en `ERROR` sin mensaje es un job que nadie
puede diagnosticar. (Relacionado: el mensaje "Solicitud Aceptada" en un job en ERROR, señalado el
2026-08-20, es exactamente el caso en que el mensaje existe pero no explica nada.)

**N3-12 cubre la reentrega de mensajes**, algo que un broker puede hacer por su cuenta: un job
terminal no debe volver a pedir ni a reindexar. La prueba cuenta las construcciones del facade y
exige **cero**.

## 6. Enlaces de descarga

| ID | Ataque | Esperado | Resultado |
|---|---|---|---|
| N3-17 | Travesía de rutas (`../../../etc/passwd`) en un token firmado | la ruta queda fuera del área de datos | **PASA** |
| N3-18 | Firma alterada | `EnlaceInvalidoError` | **PASA** |
| N3-19 | Enlace vencido | `EnlaceInvalidoError` | **PASA** |

N3-18 y N3-19 comprueban que el token no es manipulable sin la llave y que **la caducidad se aplica
de verdad**, no solo viaja en el payload.

**Límite de N3-17, dicho claro:** comprueba la *propiedad* de la ruta resuelta, no ejecuta el
endpoint. Documenta por qué la comprobación de
[`tareas.py`](../../app/api/v1/tareas.py) es necesaria, pero no la prueba. Una prueba de integración
del endpoint con un token de ruta maliciosa sería más fuerte.

## 7. Contabilidad de la sincronización

Esta sección es la más valiosa del nivel, porque los fallos aquí **no se ven**.

| ID | Prueba | Resultado |
|---|---|---|
| N3-14 | Un job en `ERROR` **no** cuenta como ventana sincronizada | **PASA** |
| N3-15 | Un job `EN_PROCESO` **sí** cuenta | **PASA** |
| N3-16 | La ventana de ayer ya cubierta no se repite | **PASA** |

Las dos primeras son las dos mitades de la misma decisión, y ambas nacieron de fallos reales:

- **Si un `ERROR` contara** (N3-14), ese día quedaría **saltado para siempre**: el job falló, no bajó
  nada, y la siguiente corrida arrancaría después. Ocurrió el 2026-07-28.
- **Si un `EN_PROCESO` no contara** (N3-15), se pediría hoy la misma ventana que el SAT todavía está
  procesando: una solicitud duplicada exacta, que el SAT rechaza con `CodEstatus=5005`. Sería un
  duplicado **cada día**.

## 8. ¿Protegen algo estas pruebas?

Tres mutaciones dirigidas al código de producción.

| Mutación | Pruebas que deben caer | Resultado |
|---|---|---|
| **A** — se abre `NUEVO → DESCARGADO` en `_TRANSICIONES` | N3-01 | **1 de 1 falló** ✓ |
| **B** — se quita `Job.estado != EstadoJob.ERROR` de `ultima_ventana_sincronizada` | N3-14 | **1 de 1 falló** ✓ |
| **C** — se elimina la guarda `if desde == hasta` | N3-05 | **1 de 1 falló** ✓ |

La mutación B es la que más tranquiliza: reintroduce **exactamente** el fallo de producción del
2026-07-28 y la batería lo detecta.

## 9. Lo que NO se probó

| No cubierto | Por qué | Cómo se cubriría |
|---|---|---|
| Idempotencia del resguardo (`UNIQUE(empresa_id, uuid)`) | Requiere paquetes ZIP con CFDI reales | Sembrar un paquete de prueba e indexarlo dos veces |
| Escritura parcial de paquetes (se esperaban N, se escribieron M) | Necesita simular fallo de disco a media descarga | Doble del facade que falle en el paquete 2 de 3 |
| Cuota real de solicitudes del SAT | No se puede probar sin gastarla de verdad | Observación en producción |
| Interrupción del worker a media transición | Requiere matar el proceso en un punto exacto | Prueba con señal, o inyección de fallo |
| Concurrencia en estados **distintos** de `NUEVO` | N3-03 solo cubre la carrera en `NUEVO` | Extender la prueba a `SOLICITADO`/`EN_PROCESO` |
| El endpoint de descarga con ruta maliciosa | Ver el límite de N3-17 en §6 | Prueba de integración sobre el endpoint |

La última fila de la tabla merece atención: **la carrera puede existir también en el sondeo**, no
solo en la solicitud. La toma atómica diseñada cubre `NUEVO`; conviene revisar si `SOLICITADO` y
`EN_PROCESO` necesitan la misma protección antes de dar el tema por cerrado.

## 10. Cómo reproducir

```bash
.venv/bin/python -m pytest tests/auditoria/test_nivel3_ciclo_descarga.py -q
```

Para ver el defecto de N3-03 con su número en pantalla en lugar de como `xfail`:

```bash
.venv/bin/python -m pytest tests/auditoria/test_nivel3_ciclo_descarga.py -k n3_03 --runxfail -q
```
