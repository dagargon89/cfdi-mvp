# Auditoría del nivel 1 — Acceso e identidad

**Fecha:** 2026-08-20
**Sistema:** Hub CFDI · rama `main` · base real de la empresa 11
**Método:** pruebas adversariales automatizadas + verificación en vivo contra la API corriendo
**Batería:** [`tests/auditoria/test_nivel1_acceso.py`](../../tests/auditoria/test_nivel1_acceso.py)

## Veredicto

**El nivel 1 resiste.** 21 de 21 pruebas adversariales en verde, 7 de 7 comprobaciones en vivo
de autenticación correctas, y las defensas están **demostradamente activas** (no solo presentes):
tres mutaciones dirigidas al código de autorización hacen fallar las pruebas que les corresponden.

**Un hallazgo**: `GET /v1/tareas/{id}` responde sin exigir token. Severidad baja-media, arreglo de
una línea. Detalle en §6.

Lo que no se probó, y por qué, está en §7 — importa tanto como lo que sí.

## 1. Qué se atacó

No se comprobó que entrar funcione (eso ya lo cubre la suite ordinaria de 988 pruebas). Se intentó
**entrar donde no se debe**, en cinco frentes:

| Frente | Pregunta que responde |
|---|---|
| Autenticación | ¿Se pasa sin un token que el servidor haya verificado? |
| Autorización local | ¿Basta una cuenta de Firebase para ser usuario del Hub? |
| Aislamiento multi-empresa | ¿Se alcanzan los datos de una empresa ajena? |
| Escalada de privilegios | ¿Puede alguien hacerse administrador o darse permisos? |
| Integridad administrativa | ¿Se puede dejar el sistema sin dueño, o reabrir el alta de arranque? |

## 2. Pruebas automatizadas

21 pruebas, todas **PASA**. La columna "defensa" nombra el mecanismo que las detiene.

### Autenticación

| ID | Ataque | Esperado | Defensa | Resultado |
|---|---|---|---|---|
| N1-01 | Petición sin encabezado `Authorization` | 401 | `_extraer_token` | **PASA** |
| N1-02 | Esquema `Basic` en lugar de `Bearer` | 401 | `_extraer_token` | **PASA** |
| N1-03 | Token que el verificador rechaza | 401 | `verificar_id_token` | **PASA** |
| N1-04 | `Bearer` sin token ni espacio | 401 | `_extraer_token` | **PASA** |

### Autorización local — un token válido no basta

| ID | Ataque | Esperado | Defensa | Resultado |
|---|---|---|---|---|
| N1-05 | Cuenta de Firebase legítima sin usuario local | 403 `NO_REGISTRADO` | `_usuario_activo_por_token` | **PASA** |
| N1-06 | Cuenta pendiente de aprobación | 403 `CUENTA_PENDIENTE` | idem | **PASA** |
| N1-07 | Cuenta desactivada | 403 `CUENTA_INACTIVA` | idem | **PASA** |

N1-05 es el ataque clásico contra un backend que confía en su proveedor de identidad: cualquiera
puede crearse una cuenta de Firebase, y eso no debe abrir ninguna puerta.

### Aislamiento entre empresas

| ID | Ataque | Esperado | Defensa | Resultado |
|---|---|---|---|---|
| N1-08 | Usuario de la empresa A pide datos de la empresa B | 404 | `require_empresa` | **PASA** |
| N1-09 | **Enumeración**: ¿la respuesta delata que la empresa existe? | respuestas idénticas | anti-enumeración | **PASA** |
| N1-10 | Rol `consulta` lanza una descarga (gasta cuota del SAT y usa la e.firma) | 403 | `_ORDEN_ROL` | **PASA** |
| N1-11 | *Control positivo*: el admin global sí alcanza cualquier empresa | 200 | intencional | **PASA** |

N1-09 es la prueba fina del diseño: empresa ajena y empresa inexistente devuelven **el mismo código
y el mismo cuerpo**. Si difirieran, un atacante barrería el rango de `empresa_id` y sabría cuántas
empresas hay y con qué ids sin ver un solo dato. Las respuestas solo se distinguen por el
`trace_id`, que es único por petición a propósito y no es información sobre la empresa.

N1-11 existe para que las demás signifiquen algo: sin un control positivo, un cambio que rompiera
*todo* acceso dejaría las pruebas de arriba en verde.

### Escalada de privilegios

| ID | Ataque | Esperado | Defensa | Resultado |
|---|---|---|---|---|
| N1-12 | Usuario normal lista el padrón de usuarios | 403 | `require_admin` | **PASA** |
| N1-13 | Autoascenso: `PATCH` de su propio `rol_global` a `admin` | 403 y rol sin cambio | `require_admin` | **PASA** |
| N1-14 | Autoservicio: asignarse permisos sobre una empresa ajena | 403 y sin acceso efectivo | `require_admin` | **PASA** |
| N1-15 | Cuenta pendiente que se aprueba a sí misma | 403 y `aprobado` sin cambio | doble (ver §5) | **PASA** |

N1-13 y N1-14 no se conforman con el 403: releen el estado para confirmar que **el efecto tampoco
ocurrió**. Un 403 con el cambio aplicado sería el peor de los mundos.

### Integridad administrativa

| ID | Ataque | Esperado | Defensa | Resultado |
|---|---|---|---|---|
| N1-16 | Reabrir el alta de arranque con usuarios ya existentes | 403/409/503 | `BOOTSTRAP_YA_REALIZADO` | **PASA** |
| N1-17 | Un administrador se elimina a sí mismo | 409 `NO_AUTO_ELIMINACION` | guarda explícita | **PASA** |
| N1-18 | Quitar el rol al **último** administrador | 409 `ULTIMO_ADMIN` | `contar_admins_activos` | **PASA** |
| N1-19 | Primer usuario del sistema por auto-registro | 403 `REGISTRO_NO_DISPONIBLE` | guarda de BD vacía | **PASA** |
| N1-20 | Auto-registro que nace con acceso | 201 pero 403 al usarlo | `aprobado=False` | **PASA** |
| N1-21 | Registrar un correo ya ocupado | 409 `YA_REGISTRADO` | dedup + `IntegrityError` | **PASA** |

N1-16 es el más grave si fallara: un `POST /auth/bootstrap` que siguiera abierto convertiría en
administrador a cualquiera con la URL.

N1-19 documenta una defensa que no esperaba encontrar y que está bien pensada: con la base vacía el
auto-registro se **niega**, porque el primer usuario sería un `consulta` pendiente y *no habría
nadie con permiso para aprobarlo* — el sistema quedaría cerrado sobre sí mismo.

## 3. Verificación en vivo — autenticación real de Firebase

Contra `http://localhost:8000/v1/me` con el servidor real y Firebase real. Cubre exactamente lo que
las pruebas automatizadas **no** pueden: firma, expiración y audiencia del token.

| ID | Encabezado enviado | Esperado | Obtenido |
|---|---|---|---|
| V-01 | *(ninguno)* | 401 | **401** |
| V-02 | `Basic YWRtaW46YWRtaW4=` | 401 | **401** |
| V-03 | `Bearer` | 401 | **401** |
| V-04 | `Bearer ` (cadena vacía) | 401 | **401** |
| V-05 | `Bearer esto-no-es-un-jwt` | 401 | **401** |
| V-06 | JWT bien formado con **firma falsa** | 401 | **401** |
| V-07 | `bearer` en minúsculas | 401 | **401** |

**Sin fuga de motivo.** Todas responden el mismo cuerpo genérico —
`{"codigo":"ERROR","mensaje":"Token inválido o expirado."}` — sin distinguir ausente de expirado, de
revocado, de firma inválida. El detalle solo va al log del servidor.

V-04 merece una nota: con el doble de pruebas un `Bearer ` vacío se convertiría en un uid vacío y
daría 403; **contra el Firebase real da 401**, que es lo correcto. Es justo la clase de diferencia
que solo aparece probando en vivo.

## 4. Barrido de endpoints sin token

Se llamaron 21 endpoints de datos sin credencial alguna. La regla no negociable 3 del proyecto dice
que ningún endpoint de datos existe sin pasar por `deps.py`.

| Resultado | Endpoints |
|---|---|
| **401 (correcto)** | `/me`, `/empresas`, `/usuarios`, `/bitacora`, `/configuracion/fiscal`, `/configuracion/percepciones`, `/configuracion/tarifa-isr`, `/config/automatizaciones`, `/config/smtp`, `/informes`, `/efos/estado`, `/empresas/11/comprobantes`, `/empresas/11/jobs`, `/empresas/11/efirma`, `/empresas/11/eventos`, `/empresas/11/configuracion`, `/empresas/11/comprobantes/export`, `/empresas/11/jobs/23/metadata` |
| 404 (ruta inexistente, no evaluable) | `/configuracion`, `/notificaciones` |
| **200 — sin autenticación** | **`/tareas/1`** ← ver §6 |
| Público por diseño | `/health`, `/v1/auth/bootstrap-status` |

**18 de 19 endpoints evaluables exigen credencial. Uno no.**

## 5. ¿Protegen algo estas pruebas?

Una prueba en verde puede no estar comprobando nada. Se rompió el código de autorización a
propósito, tres veces, para confirmar que la batería lo nota.

| Mutación aplicada a `app/api/deps.py` | Pruebas que deben caer | Resultado |
|---|---|---|
| **A** — se elimina la comprobación `if not usuario.aprobado` | N1-06, N1-20 | **2 de 2 fallaron** ✓ |
| **B** — `permiso is None` concede acceso de operador en vez de 404 | N1-08, N1-09, N1-14 | **3 de 3 fallaron** ✓ |
| **C** — `require_admin` deja de exigir el rol | N1-12, N1-13, N1-14, N1-15 | **3 de 4 fallaron** |

En las tres, el conteo de selección de `-k` fue distinto de cero (2, 3 y 4 pruebas), así que ningún
"fallo" es el falso positivo de un filtro que no selecciona nada.

**La excepción de la mutación C es un hallazgo positivo.** N1-15 (cuenta pendiente que se aprueba a
sí misma) **sobrevive** a que `require_admin` deje de funcionar, porque la detiene antes la
comprobación de aprobación: dos capas independientes cubren el mismo ataque. Defensa en profundidad
real, no redundancia declarada.

## 6. Hallazgo — `GET /v1/tareas/{id}` no exige autenticación

**Severidad: baja-media. Arreglo: una línea.**

Es el único endpoint de datos sin dependencia de autorización
([`tareas.py`](../../app/api/v1/tareas.py)).

**Lo que no permite.** Con un `tarea_id` desconocido no se obtiene nada: responde
`{"estado":"pendiente","descarga_url":null}`, igual que para un id inventado. No hay enumeración
útil ni oráculo de existencia aprovechable.

**Lo que sí permite.** Quien conozca un `tarea_id` real y completado obtiene su `descarga_url` — un
enlace a un archivo con datos fiscales (el Excel de un informe, el ZIP de comprobantes) **sin
presentar credencial**. Dos atenuantes reales: el `tarea_id` es un UUID v4 de Celery (122 bits, no
adivinable por fuerza bruta) y el enlace firmado caduca en **600 segundos**
([`enlaces.py:38`](../../app/services/enlaces.py:38)). El riesgo práctico es un `tarea_id` filtrado
por un log, una captura de pantalla o el historial del navegador.

**El matiz que importa.** El docstring del módulo declara una limitación conocida: el contrato
congelado de `estadoTarea` no recibe `empresaId`, así que el endpoint no puede **autorizar** por
empresa. Es cierto — y no justifica no **autenticar**. Son cosas distintas: exigir un usuario válido
no necesita `empresaId` y no toca el contrato.

**Por qué el arreglo es seguro.** El frontend ya llama a este endpoint con el token puesto
([`api.http.ts:217`](../../apps/web/src/lib/api.http.ts:217), vía el `request()` común que autentica
todas las llamadas). Añadir `usuario: Usuario = Depends(usuario_actual)` no rompe ningún cliente
existente. Quedaría pendiente, aparte, la autorización por empresa, que sí exige cambiar el
contrato.

## 7. Lo que NO se probó

Declarado explícitamente, porque una auditoría que no dice sus límites se lee como más completa de
lo que es.

| No cubierto | Por qué | Cómo se cubriría |
|---|---|---|
| Token de **otro proyecto** de Firebase (audiencia cruzada) | No hay un segundo proyecto a mano | Crear un proyecto de prueba y emitir un token real |
| Token **expirado** y token **revocado** reales | Requieren un token real y esperar, o revocar en la consola | Prueba manual con la consola de Firebase |
| Aislamiento multi-empresa **en vivo** | Necesita dos tokens reales de dos usuarios distintos | Sesión real en el navegador por cada usuario |
| Fuerza bruta / límite de intentos | El backend **no** implementa límite de tasa; lo delega en Firebase | Decisión de diseño a revisar antes de exponer a internet |
| Fijación y caducidad de sesión en el cliente | Vive en Firebase, no en este backend | Auditoría del SDK del navegador |
| CORS y cabeceras de seguridad | Fuera del nivel 1; se verá en el nivel de despliegue | Sprint 5 (endurecimiento) |

La ausencia de **límite de intentos propio** no es un defecto del nivel 1 —Firebase lo aporta en el
lado de la autenticación— pero conviene tenerlo escrito antes de que el sistema quede expuesto a
internet.

## 8. Cómo reproducir

```bash
.venv/bin/python -m pytest tests/auditoria/ -q
```

Las comprobaciones en vivo de §3 y §4 requieren la API corriendo en `localhost:8000` y son llamadas
`curl` sin credencial; están descritas una por una en las tablas.
