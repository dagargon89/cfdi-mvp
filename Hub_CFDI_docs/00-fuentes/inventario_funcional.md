# Inventario Funcional — Hub CFDI Plataforma Web

| Campo | Valor |
|---|---|
| Documento | Inventario funcional y análisis de viabilidad (fuente del SRS v2.0) |
| Versión | 1.0 |
| Fecha | 2026-07-27 |
| Depende de | [`investigacion_ezaudita.md`](investigacion_ezaudita.md) · [`../../CFDI-app-Escritorio/`](../../CFDI-app-Escritorio/) (SRS v1.0 archivado) |
| Decisiones de contexto | Stack: **FastAPI end-to-end** + React 19 + MySQL 8 + Celery/Redis + Firebase Auth. Alcance objetivo: **paridad completa con ezaudita®**. Modelo: **multicliente/empresa** — una sola instancia administra múltiples empresas/RFC con permisos por usuario; **no** es multi-tenant SaaS (decisiones David 2026-07-27) |

Escala de viabilidad: ✅ Viable (base técnica confirmada) · ⚠️ Viable con riesgo/condición · 🔬 Requiere investigación antes de comprometer · ❌ No viable / se recomienda excluir.

---

## 1. Funciones ya contempladas (heredadas del proyecto de escritorio v1.0)

Todas provienen del SRS v1.0 archivado. Ninguna se pierde; cambia su carcasa y su modelo de operación (de app local mono-usuario a plataforma web multicliente/empresa con varios usuarios).

| # | Función (ID original) | Destino en la plataforma web | Viabilidad |
|---|---|---|---|
| E-01 | Gestión de clientes multi-RFC (RF-CLI-01/02/03) | **Se conserva y escala:** entidad `empresa` (cliente/RFC) en una sola instancia, con permisos de acceso por usuario y por empresa. El aislamiento por cliente del v1.0 se mantiene como principio | ✅ |
| E-02 | Carga de FIEL + validación de vigencia (RF-FIEL-01/02) | **Se conserva** (mismo `Signer` de satcfdi); la validación de vigencia gana valor: alerta proactiva de vencimiento por correo | ✅ |
| E-03 | No persistencia de contraseña de FIEL (RF-FIEL-03) | **Muere como estaba y se reescribe:** en web la e.firma se custodia en el servidor (como ezaudita en AWS). Pasa a: bóveda cifrada con envelope encryption, llaves fuera de la BD, acceso auditado. Requiere ADR propio | ⚠️ crítico |
| E-04 | Troceo de rangos ≤12 meses + tope ~5 años (RF-DESC-01) | **Se conserva tal cual** (`daterange`) | ✅ |
| E-05 | Solicitud emitidos/recibidos, CFDI/metadata (RF-DESC-02) | **Se conserva tal cual** (fachada satcfdi) | ✅ |
| E-06 | Ciclo asíncrono con estados persistidos (RF-DESC-03) | **Se conserva:** la máquina de estados del job pasa íntegra a workers Celery; el polling deja de depender de que la app esté abierta — mejora natural | ✅ |
| E-07 | Reanudabilidad tras cierre (RF-DESC-04) | **Se conserva y se simplifica:** el servidor no "se cierra"; la reanudación cubre reinicios de worker/deploy | ✅ |
| E-08 | Reintentos con backoff ante fallos del SAT (RF-DESC-05) | **Se conserva** (Celery retry policies) | ✅ |
| E-09 | Escritura de paquetes sin sobrescribir (RF-DESC-06) | **Se adapta:** de carpeta local a almacenamiento de objetos/directorio del servidor por empresa | ✅ |
| E-10 | Validación de estatus sin captcha (RF-VAL-01/02) | **Se conserva** (`SAT.status()`); en web se puede programar como job periódico | ✅ |
| E-11 | Re-verificación y frescura del estatus (RF-VAL-03) | **Se conserva y se potencia:** es la base de la alerta de cancelaciones tardías (N-09) | ✅ |
| E-12 | Parseo de paquetes e indexado (RF-RES-01) | **Se conserva** (tabla `comprobantes` → MySQL, con FK a `empresa`) | ✅ |
| E-13 | Nomenclatura configurable con tokens (RF-RES-02) | **Se conserva**; sigue pendiente D1 (Pedro): UUID vs folio interno | ⚠️ D1 |
| E-14 | Comprobante de validación (RF-RES-03) | **Se conserva**; sigue pendiente D2 (Pedro): registro vs PDF | ⚠️ D2 |
| E-15 | Búsqueda y filtrado local (RF-EXP-01) | **Se transforma:** de consulta local a listados web con filtros — converge con N-04 | ✅ |
| E-16 | Export a Excel (RF-EXP-02) | **Se conserva y amplía** a XML/PDF/Excel (converge con N-15) | ✅ |
| E-17 | Reglas del SAT como configuración versionada (RF-CFG-01) | **Se conserva tal cual** | ✅ |
| E-18 | CLI de validación (carcasa Fase 1) | **Se degrada a herramienta interna** de operación/debug; deja de ser entregable de usuario | ✅ |
| E-19 | GUI Flet + design system Flet (doc 08 v1.0) | **Muere.** Se reemplaza por React 19 + Tailwind 4; el doc 08 se rehace en formato web estándar | — |
| E-20 | SQLite WAL, un escritor (H-09) | **Muere.** Se reemplaza por MySQL 8 + transacciones + workers | — |

**Resumen:** 16 de 20 funciones se conservan o mejoran con el pivote; 2 requieren decisión pendiente de Pedro (D1/D2); 2 mueren por diseño (Flet, SQLite) y ya tienen reemplazo definido.

---

## 2. Funciones nuevas (paridad con ezaudita®)

| # | Función (ref. ezaudita) | Viabilidad | Esfuerzo | Base técnica / condición |
|---|---|---|---|---|
| N-01 | Sincronización diaria automática por empresa (A1) | ✅ | Bajo | Scheduler (Celery beat) sobre el Engine existente; jobs nocturnos por empresa |
| N-02 | Descarga manual bajo demanda del mes en curso (A2) | ✅ | Bajo | Ya existe (`crear_descarga` + `run`); solo se expone en UI |
| N-03 | Monitoreo de conexión SAT y avance de descargas (A3) | ✅ | Bajo | La tabla `jobs` ya lo registra; es una vista |
| N-04 | Listados configurables: columnas, filtros, búsqueda avanzada (B5–B7) | ✅ | Medio | Índice `comprobantes` + React (TanStack Table); moneda extranjera = columnas del XML ya parseado |
| N-05 | Historia del ejercicio actual + 5 anteriores (A1) | ✅ | Bajo | Ya cubierto por tope ~5 años del troceo (E-04) |
| N-06 | Cálculo de IVA 4.0: cobrado/pagado efectivo, PUE/PPD, retenciones (C8) | ⚠️ | **Alto** | Datos disponibles (satcfdi parsea CFDI 4.0 + Pagos 2.0); el algoritmo fiscal es lógica nueva y delicada. **Condición: Pedro como validador fiscal desde el diseño, con casos de prueba reales** |
| N-07 | Conciliación del precargado de IVA del SAT (C9) | 🔬 | Alto | **No existe WS oficial documentado del prellenado.** Investigar mecanismo (¿scraping del visor? ¿carga manual del precargado y diff?). No comprometer en SRS hasta resolver. Alternativa viable: conciliación contra archivo que el usuario descarga del visor |
| N-08 | ISR con base en flujo de efectivo (C10) | ⚠️ | **Alto** | Misma condición que N-06: motor fiscal propio validado por Pedro. Deducciones autorizadas requieren criterio contable, no solo CFDI |
| N-09 | Alerta de cancelaciones tardías (E14) | ✅ | Bajo-medio | Diff de `estatus` + `estatus_verificado_at` (E-11) contra periodo declarado; notificación |
| N-10 | Control EFOS 69-B con cruce diario histórico (E15) | ✅ | Medio | **Listado 69-B nativo en satcfdi** (confirmado 2026-07-27); job diario de cruce contra `comprobantes.rfc_emisor` |
| N-11 | Validación de errores de emisión vs guías de llenado CFDI 4.0 (E12) | ⚠️ | Medio-alto | satcfdi valida estructura/esquema; las reglas de guías de llenado (2.7.1.32 RMF) son un motor de reglas propio que crece con cada RMF. Fasear: empezar con las validaciones de satcfdi + top de errores comunes |
| N-12 | Notificaciones por correo configurables, destinatarios ilimitados (E16) | ✅ | Medio | Servicio de notificaciones (nuevo): plantillas, suscripciones por evento, SMTP/SES |
| N-13 | Conciliación REP: saldos PPD y pagos pendientes de emitir/recibir (D11) | ✅ | Medio | Relación UUID factura ↔ CFDI de pago (satcfdi parsea Pagos 2.0); lógica de saldos nueva pero determinista |
| N-14 | Reportes de nómina para retenciones (F17) | ✅ | Medio | satcfdi parsea complemento Nómina; reportes agregados + permiso de visualización por usuario |
| N-15 | Export XML/PDF/Excel desde listados (I22) | ✅ | Medio | Excel ya previsto; PDF = representación impresa del CFDI (satcfdi genera); ZIP de XML |
| N-16 | DIOT: generación del archivo batch (G18) | ✅ | Medio | **DIOT nativa en satcfdi** (confirmado); vigilar el formato vigente (DIOT 2025+) |
| N-17 | Descarga de CSF (H19) | ✅ | Medio | **Nativa en satcfdi** ("Descarga de Constancia de Situación Fiscal", confirmado) |
| N-18 | Descarga de Opinión de Cumplimiento (H19) | 🔬 | Medio | No confirmada en satcfdi; verificar soporte o servicio SAT accesible. No comprometer hasta probar |
| N-19 | Tablero de inicio: ingresos, gastos, IVA, errores (I20) | ✅ | Medio | Agregaciones sobre `comprobantes` + resultados de validaciones |
| N-20 | Dashboards estadísticos (I21) | ✅ | Medio | Ídem; gráficas en React |
| N-21 | Multiusuario/multiempresa con permisos granulares (K24) | ✅ | Medio-alto | Firebase Auth + RBAC (patrón de casa: Gates/Policies → dependencias de FastAPI); permisos por empresa y por módulo (nómina restringible) |
| N-22 | Gestión de suscripción/planes (K25) | ⚠️ | Medio | **Depende de D4: ¿plataforma interna o comercializable?** Si es interna, se reduce a gestión de cuentas de usuario. Si se comercializa, al ser multicliente (no multi-tenant), el modelo natural es instancia por despacho/licencia — no planes self-service |
| N-23 | Sincronizador ADD CONTPAQi® (J23) | ❌ | Alto | Integración propietaria + componente de escritorio instalable. Fuera de alcance recomendado; re-evaluar solo si un cliente lo exige |

---

## 3. Funciones nuevas requeridas por el modelo web (no vienen de ezaudita)

Estas no existen en el proyecto v1.0 ni en el inventario de ezaudita, pero el modelo plataforma las exige:

| # | Función | Viabilidad | Notas |
|---|---|---|---|
| P-01 | Autenticación web (Firebase Auth) + sesiones | ✅ | Patrón de casa (SICAV, Panel de Acuerdos) |
| P-02 | **Bóveda de e.firmas:** custodia cifrada de .cer/.key/contraseña por empresa | ⚠️ crítico | Envelope encryption, llaves fuera de la BD (KMS/archivo de llave del servidor), acceso auditado, cifrado en reposo. **El requisito de seguridad más serio del proyecto; ADR propio** |
| P-03 | Aislamiento por empresa: FK a `empresa` en todo el modelo + verificación de permiso usuario↔empresa en cada acceso | ✅ | Casos negativos IDOR obligatorios en doc 06 (usuario sin permiso no accede a datos de esa empresa) |
| P-04 | Bitácora inmutable de operaciones sensibles | ✅ | Patrón de casa (AuditService en transacción) |
| P-05 | Infraestructura: deploy, TLS, backups cifrados, monitoreo, workers | ✅ | Nuevo costo operativo permanente; VPS/cloud por decidir |
| P-06 | Cumplimiento LFPDPPP como encargado del tratamiento de datos fiscales de terceros | ⚠️ | Aviso de privacidad, contrato de resguardo de e.firma por cliente, derechos ARCO. Sube de exigencia si se comercializa (N-22) |

---

## 4. No viables o excluidas del alcance

| Función | Razón |
|---|---|
| Sincronizador ADD CONTPAQi® (N-23) | Componente de escritorio propietario ajeno al modelo; costo/beneficio no justifica el MVP |
| Conciliación del precargado vía WS oficial (N-07 en su forma "automática total") | No existe servicio oficial documentado; comprometerla sin investigación sería vender scraping frágil. Se ofrece la variante "conciliación contra archivo del visor" mientras se investiga |
| App móvil nativa | Ni ezaudita la tiene; la web responsive cubre el caso |
| API pública / webhooks / SSO | Ezaudita tampoco los ofrece; post-MVP si surge demanda |
| Timbrado/emisión, contabilidad electrónica completa, declaraciones (F2/F3 v1.0) | Siguen fuera, igual que en el proyecto original (satcfdi soporta contabilidad electrónica 1.3 — queda como opción futura documentada, no comprometida) |

---

## 5. Dependencias y decisiones que condicionan el SRS v2.0

| # | Decisión | Responsable | Bloquea |
|---|---|---|---|
| D1 | Nomenclatura: UUID vs folio interno | Pedro | Default de resguardo (E-13) |
| D2 | Comprobante: registro vs PDF | Pedro | E-14 |
| D4 (nueva) | **¿Plataforma interna o comercializable?** (si se comercializa: instancia por despacho/licencia, al no ser multi-tenant) | David | N-22, P-06, doc 04 |
| D5 (nueva) | **Pedro como validador fiscal del motor IVA/ISR** (algoritmos y casos de prueba) | David/Pedro | N-06, N-08 |
| D6 (nueva) | Mecanismo de conciliación del precargado | Investigación técnica | N-07 |
| D7 (nueva) | Infraestructura de despliegue (VPS propio vs cloud) y almacenamiento de paquetes | David | P-05, doc 02 §despliegue |

---

## 6. Propuesta de fases para el SRS v2.0 (paridad completa como visión)

La paridad completa es el alcance objetivo; se organiza en releases para que el riesgo fiscal (N-06/07/08) no bloquee el valor temprano:

| Release | Contenido | Funciones |
|---|---|---|
| **MVP (R1)** | Núcleo + monitoreo: lo que ya estaba diseñado, ahora web multicliente/empresa | E-01…E-18, N-01…N-05, N-09, N-10, N-12, P-01…P-06 |
| **R2 — Fiscal determinista** | Lo que satcfdi resuelve nativo + lógica determinista | N-13 (REP), N-14 (nómina), N-15 (export), N-16 (DIOT), N-17 (CSF), N-19/N-20 (dashboards), N-21 (permisos finos) |
| **R3 — Motor fiscal** | Lo que requiere validación fiscal de Pedro e investigación | N-06 (IVA), N-08 (ISR), N-07 (precargado, según D6), N-11 (guías de llenado completas), N-18 (Opinión), N-22 (según D4) |

**Veredicto:** de las 23 funciones nuevas de ezaudita, **17 son viables con base técnica confirmada**, 4 son viables con condición (motor fiscal validado por Pedro, decisión interna/comercial), 2 requieren investigación previa (precargado, Opinión de Cumplimiento) y 1 se excluye (CONTPAQi). Ninguna función del proyecto original se pierde: 16 se conservan o mejoran, 2 esperan a Pedro, 2 mueren por diseño con reemplazo definido.
