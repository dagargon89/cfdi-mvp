# Hub CFDI — Plataforma Web de Descarga Masiva y Cumplimiento CFDI

| Campo | Valor |
|---|---|
| Proyecto | Hub CFDI (v2.0 — plataforma web) |
| Modelo | **Multicliente/empresa**: una instancia administra múltiples empresas/RFC con permisos por usuario. No es multi-tenant SaaS |
| Operación | Interna (supuesto H-05; si se comercializa → ADR nuevo) |
| Versión de documentación | 2.0 |
| Fecha | 2026-07-27 |
| Metodología | Estándar v1 + Demo-First v2.1 (Docs-First) + Gobernanza v3.0 |
| Reemplaza a | Documentación v1.0 de escritorio, archivada en [`../CFDI-app-Escritorio/`](../CFDI-app-Escritorio/) |

Plataforma web que descarga masivamente los CFDI de múltiples empresas/RFC desde el Web Service del SAT (sincronización diaria automática y bajo demanda), valida su vigencia sin captcha, vigila riesgos (cancelaciones tardías, lista EFOS 69-B), resguarda e indexa los comprobantes y notifica por correo. Visión de largo plazo: paridad funcional con ezaudita® (motor fiscal IVA/ISR, DIOT, CSF), faseada post-MVP.

> ⚠️ **Cambio de stack y modelo (v1.0 → v2.0):** el proyecto fue app de escritorio (Python/Flet/SQLite). Se reestructuró a plataforma web por decisión de David (2026-07-27) — ver [ADR-003](02-arquitectura/ADR/ADR-003_pivote_web.md). El diseño del dominio (máquina de estados, troceo, fachada `satcfdi`) se conserva; la carcasa y el modelo de seguridad cambian por completo.

---

## Prioridades rectoras del MVP (definidas por David, 2026-07-27)

1. **Seguridad y autenticación primero.** Bóveda de e.firmas, Firebase Auth, RBAC usuario↔empresa y bitácora se diseñan y construyen antes que cualquier función de negocio.
2. **El núcleo de escritorio funciona aquí.** Las funciones ya diseñadas en v1.0 (gestión de empresas, FIEL, descarga masiva asíncrona, validación de estatus, resguardo e índice) son el corazón del MVP.
3. **Complementos que completan el MVP:** sincronización diaria automática, monitoreo de descargas, listados con filtros, alerta de cancelaciones tardías, control EFOS 69-B, notificaciones por correo, export a Excel.
4. **Todo lo demás se proyecta a futuro** (R2/R3): REP, nómina, DIOT, CSF, dashboards estadísticos, motor IVA/ISR, precargado, Opinión de Cumplimiento, comercialización.

## Estado de fase (gate de avance — Gobernanza v3)

| Fase | Estado | DoD verificada |
|---|---|---|
| 0 — Documentación (00–09) | ✅ Completa (2026-07-27) | Sí — checklist v1/v3 + validación programática JSON espejo ↔ DDL (0 errores) |
| 1 — Demo (prototipo externo desde doc 09 + validación + freeze del contrato) | ✅ Cerrada (2026-07-27) | Sí — ver justificación abajo |
| 2 — Backend + apps/web (MVP) | 🟡 En progreso — frontend (`apps/web`) completo; backend: Sprint 0 (cimientos) y Sprint 1 (seguridad: auth, bóveda, bitácora) cerrados 2026-07-27; Sprints 2-5 (descarga masiva vía Celery, resguardo, EFOS, notificaciones, endurecimiento) pendientes | Parcial (frontend + Sprint 0-1 backend) |
| 3 — Releases futuros (R2/R3) | ⬜ Proyectados | No |

> **Regla de gate:** ningún agente o desarrollador genera entregables de la Fase N+1 si la Fase N tiene "DoD verificada: No", salvo excepción justificada por escrito en esta tabla.

> **Justificación del cierre de Fase 1 (2026-07-27):** David construyó el prototipo real en Claude Design (`Hub CFDI - Demo UX.dc.html`, 11 pantallas + 403 + drawers + modal + toasts) y, en la misma sesión de implementación, lo validó línea por línea contra los docs 01/03/05/08/09 antes de trasladarlo a `apps/web`. No se registraron hallazgos que requirieran cambiar el contrato (ver `demo-ux/09_demo_ux_guia.md` §10). El contrato `ApiClient` queda congelado en `05_especificacion_api.md` §9, con las adiciones que el propio demo exigió (usuarios/config/bitácora de administración, `id_solicitud` en `Job`, `xml_path` en `Comprobante`).

## Stack

| Capa | Tecnología | Versión objetivo |
|---|---|---|
| Frontend | React + Vite + TypeScript + Tailwind CSS + TanStack Query | React 19 · Vite 6 · TW 4 |
| API | FastAPI (Python) | 3.11+ / FastAPI 0.11x |
| Workers / cola | Celery + Redis (importan `sat_hub` directo) | Celery 5 · Redis 7 |
| Scheduler | Celery beat (sincronización diaria) | — |
| Motor SAT | `satcfdi` (descarga masiva, estatus, 69-B, DIOT, CSF) | 26.x fijada |
| Base de datos | MySQL InnoDB `utf8mb4_unicode_ci` | 8.x |
| Autenticación | Firebase Authentication (ID tokens) | — |
| Bóveda de e.firmas | Envelope encryption (AES-256-GCM; llave maestra fuera de la BD) | — |
| Correo | SMTP/SES para notificaciones | — |

## Arquitectura en un párrafo

SPA React consume una API REST FastAPI organizada en capas (routers → services → repositories → MySQL), con Celery/Redis para el trabajo pesado: los workers importan el núcleo `sat_hub` (heredado de v1.0: máquina de estados del job, troceo ≤12 meses, fachada `satcfdi`) y ejecutan el ciclo asíncrono solicitar→verificar→descargar con estado persistido en MySQL. Celery beat programa la sincronización diaria por empresa y el cruce EFOS. La e.firma de cada empresa vive en una bóveda cifrada (envelope encryption); se descifra solo en memoria del worker para construir el `Signer`. Todo acceso pasa por verificación de Firebase ID token + permiso usuario↔empresa, y toda operación sensible escribe bitácora dentro de la misma transacción.

**Código fuente y arranque:** el backend y `apps/web` se construyen en Fase 2. Ver [`CLAUDE.md`](CLAUDE.md).

---

## Índice de documentos

| # | Documento | Ruta |
|---|---|---|
| — | Fuente: investigación ezaudita® | [`00-fuentes/investigacion_ezaudita.md`](00-fuentes/investigacion_ezaudita.md) |
| — | Fuente: inventario funcional y viabilidad | [`00-fuentes/inventario_funcional.md`](00-fuentes/inventario_funcional.md) |
| 00 | Auditoría de fuentes | [`00-fuentes/00_auditoria_fuentes.md`](00-fuentes/00_auditoria_fuentes.md) |
| — | Guía operativa para agentes IA | [`CLAUDE.md`](CLAUDE.md) |
| ADR-003 | Pivote a plataforma web (stack y modelo) | [`02-arquitectura/ADR/ADR-003_pivote_web.md`](02-arquitectura/ADR/ADR-003_pivote_web.md) |
| 01 | SRS — Especificación de requisitos | [`01-vision/01_SRS_especificacion_requisitos.md`](01-vision/01_SRS_especificacion_requisitos.md) |
| 02 | Arquitectura del sistema | [`02-arquitectura/02_arquitectura_sistema.md`](02-arquitectura/02_arquitectura_sistema.md) |
| 03 | Modelo de datos (MySQL) | [`03-datos/03_modelo_de_datos.md`](03-datos/03_modelo_de_datos.md) |
| 04 | Plan de seguridad (prioridad 1) | [`04-seguridad/04_plan_de_seguridad.md`](04-seguridad/04_plan_de_seguridad.md) |
| 05 | Especificación de API (borrador pre-freeze) | [`05-api/05_especificacion_api.md`](05-api/05_especificacion_api.md) |
| 06 | Plan de pruebas | [`06-pruebas/06_plan_de_pruebas.md`](06-pruebas/06_plan_de_pruebas.md) |
| 07 | Roadmap por sprints | [`07-roadmap/07_roadmap_sprints.md`](07-roadmap/07_roadmap_sprints.md) |
| 08 | Identidad visual y design system | [`01-vision/08_identidad_visual_design_system.md`](01-vision/08_identidad_visual_design_system.md) |
| 09 | Guía del demo UX (spec MD para prototipo externo) | [`demo-ux/09_demo_ux_guia.md`](demo-ux/09_demo_ux_guia.md) |
| — | ADRs v1.0 (histórico) | [`../CFDI-app-Escritorio/02-arquitectura/ADR/`](../CFDI-app-Escritorio/02-arquitectura/ADR/) |

---

## Decisiones clave del MVP

| Decisión | Valor | Referencia |
|---|---|---|
| Modelo de producto | Web multicliente/empresa, instancia única, operación interna | ADR-003 · H-05 |
| Stack backend | FastAPI end-to-end; workers Celery importan `sat_hub` sin puente | ADR-003 |
| Custodia de e.firma | Bóveda cifrada (envelope encryption), acceso auditado, descifrado solo en worker | Doc 04 · H-02 |
| Autenticación | Firebase Auth (ID token Bearer); permiso usuario↔empresa en cada endpoint | Doc 04 §3.2 |
| Núcleo de dominio | `sat_hub` v1.0 se conserva (máquina de estados, troceo, fachada satcfdi) | ADR-003 §3 |
| Alcance MVP | Prioridades 1–3; paridad ezaudita completa faseada a R2/R3 | Doc 01 §1.2 · Doc 07 |
| Nomenclatura / comprobante | Configurables; defaults pendientes de Pedro (D1/D2) | Doc 01 RF-RES |
| Demo | Especificado en MD (doc 09), prototipado en Claude Design y trasladado 1:1 a `apps/web` (Fase 2) | Metodología v2.1 · cerrado 2026-07-27 |

---

## Cómo leer esta documentación

1. **Contexto y decisiones:** `00_auditoria_fuentes.md` → `ADR-003` — por qué se pivotó y qué se decidió.
2. **Qué hace el sistema:** doc 01 (SRS) — prioridades, requisitos, máquina de estados, criterios del MVP.
3. **Cómo se construye:** docs 02 (arquitectura) → 03 (datos) → 04 (seguridad) → 05 (API).
4. **Cómo se valida y entrega:** docs 06 (pruebas) → 07 (roadmap).
5. **Cómo se ve y se prototipa:** doc 08 (design system) → doc 09 (spec del demo).
