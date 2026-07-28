# CLAUDE.md — Guía operativa Hub CFDI (v2.0 web)

Hub CFDI es una plataforma web **multicliente/empresa** (una instancia, múltiples empresas/RFC, usuarios con permisos por empresa — NO multi-tenant) que descarga masivamente CFDI del SAT, valida vigencia sin captcha, vigila riesgos (cancelaciones tardías, EFOS 69-B), resguarda e indexa comprobantes y notifica por correo. Sustituye al proyecto de escritorio v1.0 (archivado en `../CFDI-app-Escritorio/`). Visión post-MVP: paridad con ezaudita® (IVA/ISR, DIOT, CSF).

## Prioridades rectoras (orden de construcción, definidas por David)

1. Seguridad y autenticación (bóveda de e.firmas, Firebase Auth, RBAC usuario↔empresa, bitácora).
2. Núcleo heredado de escritorio funcionando en web (empresas, FIEL, descarga masiva asíncrona, validación, resguardo, índice).
3. Complementos del MVP (sync diaria, monitoreo, listados, cancelaciones tardías, EFOS, notificaciones, export).
4. Todo lo demás → futuro (R2/R3), no se construye en el MVP.

## Núcleo de dominio

Pipeline: **e.firma en bóveda → descarga masiva (WS SOAP, asíncrona) → validación de estatus → resguardo/índice → vigilancia (EFOS, cancelaciones) → consulta/export**. El corazón sigue siendo el **job asíncrono reanudable** heredado de v1.0: `NUEVO → SOLICITADO → EN_PROCESO → TERMINADA → DESCARGADO` con `ERROR` re-encolable; cada ventana ≤ 12 meses es un job. Los workers Celery ejecutan la máquina de estados; el estado vive en MySQL.

## Stack

| Capa | Tecnología |
|---|---|
| Frontend | React 19 + Vite 6 + TS + Tailwind 4 + TanStack Query 5 (`apps/web`) |
| API | FastAPI (Python 3.11+), REST JSON `/v1` |
| Workers | Celery 5 + Redis 7; beat para sync diaria y cruce EFOS |
| Motor SAT | `satcfdi` 26.x fijada (descarga, status, 69-B, DIOT, CSF) |
| Datos | MySQL 8 InnoDB utf8mb4 |
| Auth | Firebase Auth — ID token Bearer verificado server-side |
| Bóveda | AES-256-GCM envelope encryption; llave maestra fuera de la BD |

## Estado de fase (gate)

| Fase | Estado | DoD verificada |
|---|---|---|
| 0 — Documentación (00–09) | ✅ Completa (2026-07-27) | Sí |
| 1 — Demo (prototipo externo + validación + freeze) | ✅ Cerrada (2026-07-27) | Sí — ver README.md |
| 2 — Backend + apps/web (MVP) | 🟡 `apps/web` completo · backend Sprint 0-4 (cimientos, seguridad, descarga masiva, resguardo/validación/consulta, sync diaria/EFOS/cancelaciones tardías/notificaciones) cerrados 2026-07-28, verificados con datos reales · Sprint 5 pendiente | Parcial |

**Regla de gate:** no generes código ni entregables de la fase N+1 si la fase N tiene "DoD verificada: No". El demo se prototipó en Claude Design (`demo-ux/09_demo_ux_guia.md`) y, tras el cierre de Fase 1, se tradujo 1:1 a `apps/web` — el contrato `ApiClient` (doc 05 §9) quedó congelado en ese momento.

## Reglas no negociables

1. **Nunca confiar en el cliente.** Toda decisión de seguridad (permiso sobre empresa, rol, propiedad de un job) se verifica en el backend contra la BD; el frontend solo refleja. *Por qué:* OWASP A01; el `empresa_id` que manda el navegador es un dato hostil.
2. **La bóveda es sagrada.** Material de e.firma (.key, contraseña) solo existe: cifrado en la bóveda (AES-256-GCM, envelope encryption) o en memoria del worker mientras construye el `Signer`. Nunca en logs, respuestas de API, Redis ni frontend. Todo acceso a la bóveda escribe bitácora. *Por qué:* es la identidad legal de los clientes (H-02); su filtración es el peor incidente posible.
3. **Permiso usuario↔empresa en cada endpoint.** Ninguna consulta toca datos de una empresa sin verificar `usuario_empresa` en esa petición. *Por qué:* el aislamiento por empresa es el control de acceso central del modelo multicliente.
4. **MySQL es la fuente de verdad; Firebase solo autentica.** Roles y permisos viven en MySQL; Firebase provee identidad (uid verificado). *Por qué:* separación identidad/autorización, patrón de casa.
5. **El estado del job vive en la BD, no en el worker.** Cada transición se persiste antes de continuar; `id_solicitud` es inmutable; reanudar nunca recrea la solicitud ante el SAT. *Por qué:* el SAT tarda de minutos a días; deploys y reinicios de worker no deben perder ni duplicar trabajo.
6. **Asincronía obligatoria.** Todo lo que toca al SAT (solicitar, verificar, descargar, status, 69-B) corre en workers Celery, nunca en el request HTTP. *Por qué:* latencias de segundos a días; la API responde siempre.
7. **Transacciones ACID en escrituras multi-tabla.** Resguardo (comprobantes + job), bóveda (e.firma + bitácora), permisos (usuario + relaciones) van en transacción. *Por qué:* integridad; media descarga indexada es peor que ninguna.
8. **Bitácora dentro de la transacción.** Operaciones sensibles (bóveda, permisos, borrados, cambios de config) escriben `bitacora` append-only en la misma transacción; si la bitácora falla, la operación se revierte. *Por qué:* trazabilidad exigible ante clientes y LFPDPPP.
9. **Reglas del SAT como configuración versionada** (12 meses, ~5 años, 200k/1M, polling). *Por qué:* cambian por ejercicio fiscal; sin deploy.
10. **Contrato de API congelado = fuente única.** Tras el freeze (fin de Fase 1), la interfaz `ApiClient` del doc 05 es literal; cualquier cambio la actualiza en la misma sesión. *Por qué:* Gobernanza v3 mejora 4.
11. **Cero N+1.** Listados de comprobantes/jobs usan joins/eager loading explícitos; auditado con echo de queries. *Por qué:* el índice apunta a cientos de miles de filas por empresa.
12. **Nada sensible real en docs ni fixtures.** RFC de prueba del SAT (`EKU9003173C9`, `XAXX010101000`), UUID ficticios, dominios `@demo.test`.

## Arquitectura en capas

```
React SPA (apps/web, TanStack Query)
   ↓ HTTPS/JSON  (Firebase ID token Bearer)
FastAPI: middlewares (CORS, rate limit) → deps de auth (verify token + permiso empresa)
   → Routers (validación Pydantic)
   → Services (dominio: DescargaService, ValidacionService, ResguardoService,
               EfosService, NotificacionService, BovedaService)
   → Repositories (SQLAlchemy 2, transacciones) → MySQL 8
   → encola tareas → Redis → Workers Celery (importan sat_hub + satcfdi) → SAT WS
Celery beat: sync diaria por empresa · cruce EFOS · re-verificación de estatus
BovedaService: AES-256-GCM (envelope); AuditService transversal → bitacora (append-only)
Almacenamiento de paquetes/XML por empresa (disco/objeto, fuera del webroot)
```

## Comandos de arranque (Fase 2)

```bash
# Todo junto (mysql, redis, api, worker, beat)
docker compose up -d --build               # http://localhost:8000 (OpenAPI en /docs)

# Backend, fuera de Docker (equivalente, para desarrollo local)
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m app.scripts.generar_kek_dev      # KEK de desarrollo (una sola vez)
alembic upgrade head                       # migraciones (DDL doc 03)
uvicorn app.main:app --reload              # http://localhost:8000 (OpenAPI en /docs)
celery -A app.worker.celery_app worker -l info   # workers SAT (`ejecutar_job` desde Sprint 2)
celery -A app.worker.celery_app beat -l info     # scheduler (Sprint 4: sync diaria/EFOS/re-verificación)

# Frontend
cd apps/web && npm install && npm run dev  # http://localhost:5173

# Calidad
pytest --cov=app && mypy app && pip-audit --strict -r requirements.txt --ignore-vuln PYSEC-2026-286
cd apps/web && npm run typecheck && npm run lint
```

> Nota (2026-07-27): `requirements.txt` todavía no usa `--require-hashes` (pendiente para el
> endurecimiento de Sprint 5, doc 04 §4.2 A06) — hoy es un `pip freeze` simple del entorno
> resuelto por `pyproject.toml`. `PYSEC-2026-286` (asyncmy) se ignora explícitamente en
> `pip-audit`: es una inyección SQL vía "claves de dict manipuladas" sin fix upstream a la
> fecha; no aplica a nuestro uso porque SQLAlchemy siempre parametriza con claves definidas
> por nuestros modelos, nunca con claves derivadas de entrada de usuario.

## Identidad visual (resumen operativo — detalle en doc 08)

- **Tono:** herramienta profesional densa en información; el color comunica **estado**, nunca es el único indicador (siempre chip con texto + ícono).
- **Base:** fondo `#F4F6F9`, superficies blancas, texto `#1E2733` / secundario `#556070`.
- **Primario:** `#1F5FA6` (AA sobre blanco). Semánticos por estado: éxito/vigente `#1E7A46`, proceso `#0B6E99`, atención `#9A5B00`, error/cancelado `#B4283A`.
- **Identificadores fiscales (RFC, UUID, folios) siempre en monoespaciada.**
- **Contraste:** todo par texto/fondo ≥ 4.5:1 (WCAG 2.1 AA); sidebar colapsable; tablas densas con filas alternas.

## Orden de lectura

1. `00-fuentes/00_auditoria_fuentes.md` · 2. `ADR-003` · 3. doc 01 SRS · 4. doc 02 arquitectura · 5. doc 03 datos · 6. doc 04 seguridad · 7. doc 05 API · 8. doc 06 pruebas · 9. doc 07 roadmap · 10. doc 08 design system · 11. `demo-ux/09_demo_ux_guia.md`.
