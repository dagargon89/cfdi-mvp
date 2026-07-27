# ADR-003 — Pivote de aplicación de escritorio a plataforma web multicliente

| Campo | Valor |
|---|---|
| Estado | **Aceptado** (David, 2026-07-27) |
| Fecha | 2026-07-27 |
| Reemplaza | [ADR-002 v1.0 (Flet)](../../../CFDI-app-Escritorio/02-arquitectura/ADR/ADR-002_framework_ui_escritorio.md) por completo; [ADR-001 v1.0](../../../CFDI-app-Escritorio/02-arquitectura/ADR/ADR-001_stack_satcfdi_nucleo_carcasa.md) parcialmente (SQLite y carcasa mueren; `satcfdi` y núcleo/carcasa sobreviven) |
| Depende de | [`00_auditoria_fuentes.md`](../../00-fuentes/00_auditoria_fuentes.md) · [`inventario_funcional.md`](../../00-fuentes/inventario_funcional.md) |

## 1. Contexto

El Hub CFDI v1.0 se diseñó como app de escritorio mono-usuario (Python/Flet/SQLite) con la premisa "la FIEL nunca sale del equipo". Al evaluar la plataforma ezaudita® como referencia de mercado, David decidió reestructurar el producto: la operación real es de despacho (varios usuarios, muchas empresas/RFC, sincronización diaria desatendida, alertas por correo), y ese caso lo sirve mejor una plataforma web siempre encendida que una app que depende de que alguien la abra. El alcance de largo plazo se amplía a paridad funcional con ezaudita®, faseada.

## 2. Decisión

Pivotar a **plataforma web multicliente/empresa** (una instancia, múltiples empresas, permisos por usuario; **no** multi-tenant SaaS), con prioridades de construcción: (1) seguridad/auth, (2) núcleo de escritorio, (3) complementos MVP, (4) resto a futuro.

| Capa | v1.0 (escritorio) | v2.0 (web) |
|---|---|---|
| Carcasa | Flet (GUI local) + CLI | React 19 + Vite + Tailwind 4 (`apps/web`) |
| Lógica de aplicación | En proceso local | **FastAPI** (REST `/v1`, OpenAPI) |
| Ejecución del ciclo SAT | Hilo local del Engine | **Workers Celery + Redis** (importan `sat_hub`) |
| Programación | Manual (Operador abre la app) | **Celery beat**: sync diaria, cruce EFOS |
| Persistencia | SQLite WAL | **MySQL 8** InnoDB utf8mb4 |
| Identidad | Sesión del SO | **Firebase Auth** (ID token) + RBAC usuario↔empresa en MySQL |
| Secretos FIEL | Llavero del SO; contraseña nunca persistida | **Bóveda cifrada en servidor** (envelope encryption) — ver §6 |
| Motor SAT | `satcfdi` | `satcfdi` (sin cambio; se amplía uso: 69-B, DIOT, CSF) |

**Por qué FastAPI y no CI4 (stack de casa):** el corazón del producto es el motor Python (`sat_hub`/`satcfdi`, sin equivalente PHP). Una API CI4 exigiría un segundo backend y un puente de serialización hacia un microservicio Python. FastAPI permite que API y workers compartan el mismo dominio en proceso, y genera OpenAPI automático que refuerza el contrato congelado (Gobernanza v3 mejora 4). React/Firebase/MySQL se conservan del estándar de casa.

## 3. Mapeo de conceptos (v1.0 → v2.0)

| Concepto v1.0 | Equivalente v2.0 |
|---|---|
| `Engine.run()` en hilo local | Tareas Celery (`solicitar_job`, `verificar_job`, `descargar_job`) que envuelven el mismo Engine |
| `Store` sobre SQLite | Repositories SQLAlchemy sobre MySQL (mismas entidades + nuevas) |
| Contrato del núcleo (doc 05 v1: interfaz Python) | Especificación de API REST (doc 05 v2) + `ApiClient` TS congelable |
| Operador único del SO | Usuarios Firebase con roles y permisos por empresa |
| Carpeta destino local por cliente | Almacenamiento por empresa en el servidor (fuera del webroot) |
| Llavero del SO | Bóveda cifrada con bitácora de acceso |
| Variante metodológica de escritorio | Proceso estándar completo (la Fase Demo regresa, doc 09 en MD) |

**Qué se conserva textualmente del v1.0:** la máquina de estados del job y sus invariantes (SRS §4), `daterange` (≤12 meses, ~5 años), la fachada `satcfdi` (mapeo tipo→método, H-04 original), la taxonomía de errores del núcleo, la validación de vigencia de FIEL y las reglas del SAT como configuración.

## 4. Consecuencias

**Positivas:** operación desatendida (sync nocturna sin abrir nada); multiusuario real con permisos; una sola instalación que sirve a todo el despacho; base para las funciones de paridad (EFOS, DIOT, CSF ya nativas en `satcfdi`); el gate de validación por CLI de v1.0 se sustituye por pruebas de integración de workers.

**Negativas / trade-offs aceptados:** custodia de e.firmas de terceros en el servidor (el mayor riesgo del proyecto — §6); aparece costo operativo permanente (servidor, TLS, backups, monitoreo); backend fuera del stack PHP de casa (curva para el equipo); el esfuerzo total crece ~4–6× respecto al proyecto de escritorio por el alcance de paridad.

**Neutrales:** el CLI de v1.0 se degrada a herramienta interna de operación/debug.

## 5. Impacto en documentos

Toda la documentación se regenera como v2.0 (versión mayor sincronizada). La v1.0 queda archivada íntegra en `CFDI-app-Escritorio/` con nota de superación. El doc 05 vuelve a ser especificación de API REST; el doc 08 se rehace para web; el doc 09 (demo) se reincorpora al proceso.

## 6. Implicaciones de seguridad (el corazón de este ADR)

El modelo de amenaza se **invierte**: de "disco local + credenciales del Operador" a "servidor público + custodia de identidades legales de terceros".

1. **Muere S3 v1.0** ("la FIEL nunca sale del equipo"). Nace la **bóveda**: `.key` y contraseña se cifran con AES-256-GCM bajo envelope encryption — una DEK por e.firma, envuelta por una KEK maestra que vive fuera de la BD (archivo de llave del servidor con permisos restrictivos; migrable a KMS). Descifrado únicamente en memoria del worker al construir el `Signer`; nunca en logs, API, Redis ni frontend. Todo acceso queda en bitácora.
2. **Aparece la superficie web completa:** OWASP Top 10 aplica sin adaptación (A01 IDOR entre empresas, A02, A03, CSRF/XSS en la SPA, rate limiting). El doc 04 v2.0 es el documento más profundo del proyecto (prioridad 1 de David).
3. **LFPDPPP sube de exigencia:** datos fiscales de terceros + e.firmas en custodia; bajo el supuesto de operación interna (H-05) se documenta aviso y medidas; si D4 cambia a comercial, ADR nuevo con contratos de resguardo.

## 7. Plan de migración

No hay datos que migrar (el escritorio no llegó a producción). La migración es de diseño: (1) archivar docs v1.0 ✅ (2026-07-27); (2) regenerar docs v2.0 (este paquete); (3) en Fase 2, portar `sat_hub` como paquete instalable consumido por los workers, reemplazando `Store` SQLite por repositories MySQL; (4) el CLI v1.0 se adapta como comando de administración (`manage.py`) para operación y debug.
