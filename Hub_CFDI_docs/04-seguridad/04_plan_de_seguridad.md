# 04 — Plan de Seguridad

| Campo | Valor |
|---|---|
| Documento | 04 — Plan de Seguridad (**prioridad 1 del MVP**) |
| Versión | 2.0 |
| Fecha | 2026-07-27 |
| Marco | OWASP Top 10 (2021) · OWASP ASVS · LFPDPPP |
| Depende de | [`ADR-003`](../02-arquitectura/ADR/ADR-003_pivote_web.md) · [`01_SRS`](../01-vision/01_SRS_especificacion_requisitos.md) · [`03_modelo_de_datos`](../03-datos/03_modelo_de_datos.md) |

> **Inversión del modelo de amenaza vs v1.0.** El escritorio protegía un disco local; la plataforma protege un **servidor público que custodia e.firmas de terceros** — identidades legales de los clientes del despacho. Este documento gobierna el diseño: por decisión de David, la seguridad se construye antes que cualquier función de negocio, y ningún módulo del MVP se acepta sin sus controles verificados.

---

## 1. Postura de seguridad

### 1.1 Activos a proteger

| Activo | Criticidad | Justificación |
|---|---|---|
| E.firmas en bóveda (.key + contraseña, por empresa) | **Crítica** | Permiten firmar como el contribuyente ante el SAT. Filtración = suplantación legal de clientes; incidente terminal para la confianza del despacho |
| KEK maestra | **Crítica** | Descifra todas las DEK de la bóveda |
| CFDI e índice (`comprobantes`) | **Alta** | Datos fiscales de terceros; PII y secreto comercial (LFPDPPP) |
| Credenciales de usuarios / sesiones | Alta | Puerta a todo lo anterior |
| BD completa y backups | Alta | Contienen los blobs cifrados y todos los datos |
| Bitácora | Media | Integridad de la trazabilidad (no confidencialidad) |
| Configuración | Media | Parámetros operativos; sin secretos |

### 1.2 Actores de amenaza

Atacante externo contra la superficie web (auth, IDOR, inyección, fuerza bruta); **usuario autenticado malicioso o curioso** intentando acceder a empresas no asignadas o escalar rol; atacante con acceso al servidor o a un backup (busca la bóveda); dependencia comprometida (pip/npm) ejecutando código con acceso a la KEK; interno negligente (secretos en logs, KEK en repositorio); MITM hacia el SAT o hacia el navegador.

---

## 2. OWASP Top 10 — Controles aplicados

### A01 — Broken Access Control (el riesgo #1 de este sistema)
- **Riesgo específico:** un usuario autenticado lee/opera empresas que no le fueron asignadas (IDOR sobre `empresa_id`, `job_id`, `comprobante_id`), o un rol consulta ejecuta acciones de operador.
- **Controles:**
  - Dependencia `require_empresa(rol_minimo)` en **todo** endpoint de datos: token verificado → usuario activo → permiso `usuario_empresa` → contexto autorizado (snippet en doc 02 §5; vive en `app/api/deps.py`).
  - Los recursos anidados se resuelven **siempre** filtrando por la empresa del contexto, nunca por el id suelto:

    ```python
    # app/repositories/jobs.py — el job se busca DENTRO de la empresa autorizada
    async def get_de_empresa(db: AsyncSession, empresa_id: int, job_id: int) -> Job:
        row = await db.scalar(select(Job).where(Job.job_id == job_id,
                                                Job.empresa_id == empresa_id))
        if row is None:
            raise HTTPException(404)   # no existe O no es de tu empresa: misma respuesta
        return row
    ```
  - Pruebas negativas obligatorias por recurso (doc 06 §2.7): usuario sin permiso ⇒ 403/404, rol consulta en endpoint mutante ⇒ 403.

### A02 — Cryptographic Failures → la bóveda
- **Riesgo específico:** exposición de `.key`/contraseñas por BD comprometida, backup filtrado o logs.
- **Controles — diseño de la bóveda (envelope encryption):**
  1. Por e.firma: DEK aleatoria de 256 bits; `AES-256-GCM(DEK)` cifra `.key` y contraseña (nonce único por operación, tag autenticado).
  2. La DEK se guarda **envuelta** por la KEK maestra; la KEK vive en archivo del servidor (permisos 600, montado solo en `api`/`worker`), **fuera de la BD y de sus backups**. Un dump de BD robado no se descifra sin la KEK.
  3. Descifrado exclusivamente en workers, en memoria, para construir el `Signer`; el material nunca viaja a la API, Redis, logs ni frontend (regla 2 CLAUDE.md).
  4. Todo descifrado escribe bitácora (`uso_boveda`, con job asociado) — RF-BOV-03.

    ```python
    # app/services/boveda.py — cifrado envelope (cryptography)
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    import os

    def cifrar(dek: bytes, dato: bytes) -> bytes:
        nonce = os.urandom(12)
        return nonce + AESGCM(dek).encrypt(nonce, dato, None)   # nonce ∥ ciphertext+tag

    def descifrar(dek: bytes, blob: bytes) -> bytes:
        return AESGCM(dek).decrypt(blob[:12], blob[12:], None)  # tag inválido ⇒ excepción

    def envolver_dek(kek: bytes, dek: bytes) -> bytes:  return cifrar(kek, dek)
    def desenvolver_dek(kek: bytes, blob: bytes) -> bytes: return descifrar(kek, blob)
    ```
  - **Rotación:** de KEK (re-envolver todas las DEK — operación offline documentada, sin re-cifrar blobs); de e.firma (reemplazo RF-BOV-04). Migración a KMS gestionado como endurecimiento cuando D7 se resuelva a cloud.
- TLS 1.2+ obligatorio en toda la plataforma (nginx) y verificado hacia el SAT (`verify` nunca desactivado en satcfdi).

### A03 — Injection
- **Riesgo:** SQLi en filtros de listados (texto libre, RFC); inyección en plantilla de nomenclatura.
- **Controles:** SQLAlchemy 2 con parámetros ligados en el 100% de las consultas (prohibido `text()` con interpolación); validación Pydantic de entrada (RFC con regex, enums estrictos); la plantilla de nomenclatura solo admite tokens de lista blanca y el resultado se sanea como nombre de archivo (sin `../`, separadores ni caracteres de control).

### A04 — Insecure Design
- **Controles de diseño ya adoptados:** máquina de estados con persistencia previa (no hay estados fantasma); idempotencia de eventos (no hay fatiga de alertas que lleve a ignorarlas); `id_solicitud` inmutable (no hay solicitudes duplicadas ante el SAT); reglas normativas como configuración auditada; asincronía obligatoria (la API no puede ser rehén del SAT).

### A05 — Security Misconfiguration
- **Controles:** CORS restringido al origen de la SPA; headers de seguridad (HSTS, X-Content-Type-Options, CSP para la SPA); OpenAPI `/docs` deshabilitado o protegido en producción; MySQL/Redis sin exposición pública (red interna de Compose); contenedores non-root; usuario MySQL de la app con privilegios mínimos (sin DDL en runtime; sin UPDATE/DELETE sobre `bitacora`); configuración por entorno sin defaults inseguros.

### A06 — Vulnerable and Outdated Components
- **Controles:** `satcfdi` y todas las dependencias Python fijadas con hashes (`pip install --require-hashes`); `pip-audit` y `npm audit` como gate de CI; imagen base slim actualizada; frontend sin dependencias de runtime innecesarias.

### A07 — Identification and Authentication Failures
- **Riesgo:** tokens falsificados/expirados; usuarios dados de baja que siguen entrando; e.firma vencida operando.
- **Controles:** verificación server-side del ID token (firma, `exp`, `aud`, revocación) vía Admin SDK; usuario local `activo` como interruptor inmediato (RF-AUTH-04); sin auto-registro (RF-AUTH-02); rate limiting sobre endpoints de mayor sensibilidad; vigencia de e.firma verificada antes de encolar (RF-BOV-02, hereda v1.0):

    ```python
    # app/services/fiel.py — heredado de sat_hub v1.0
    def validar_vigencia(signer: Signer, umbral_dias: int) -> None:
        cert = signer.certificate
        ahora = datetime.now(cert.not_valid_after_utc.tzinfo)
        if ahora > cert.not_valid_after_utc:
            raise FielVencidaError("e.firma vencida; el job no se encola")
        if ahora + timedelta(days=umbral_dias) > cert.not_valid_after_utc:
            eventos.emitir(EventoTipo.EFIRMA_POR_VENCER, ...)   # una vez, idempotente
    ```

### A08 — Software and Data Integrity Failures
- **Controles:** conteo de paquetes escritos vs reportados antes de `DESCARGADO`; parseo de XML con `satcfdi` (no regex); `UNIQUE(empresa_id, uuid)` impide duplicar índice; CI verifica lockfiles; sin ejecución de código desde datos (plantillas de correo estáticas con placeholders).

### A09 — Security Logging and Monitoring Failures
- **Controles:** bitácora append-only en transacción (RF-BIT-01); filtro de redacción de secretos en logging (heredado v1.0); log de notificaciones; alerta operativa si la corrida diaria no corre o si la tasa de `ERROR` excede umbral; los 403 repetidos por usuario quedan registrados (detección de sondeo IDOR).

### A10 — SSRF
- **Riesgo bajo:** el sistema no acepta URLs del usuario. Los únicos destinos salientes son el SAT (fijo, vía satcfdi), Firebase y el SMTP configurado por el Admin. Se documenta para trazabilidad.

---

## 3. Seguridad específica por capa

### 3.1 Filtros / middlewares
| Control | Propósito | Aplica a |
|---|---|---|
| Verificación de ID token | Identidad | Todos los endpoints salvo health |
| `require_empresa(rol)` | Autorización por empresa | Todos los endpoints de datos |
| Rate limit | Fuerza bruta / abuso | Grupos por sensibilidad (doc 05 §1.5) |
| CORS + headers seguridad | Superficie navegador | Global |

### 3.2 Autenticación y sesión (flujo completo)

```mermaid
sequenceDiagram
    participant U as SPA
    participant FB as Firebase Auth
    participant API as FastAPI
    participant DB as MySQL
    U->>FB: login
    FB-->>U: ID token (exp ~1h, refresh automático del SDK)
    U->>API: petición + Bearer token
    API->>API: verificar firma/exp/aud (Admin SDK, claves cacheadas)
    API->>DB: usuario activo por uid  →  permiso empresa
    alt cualquier verificación falla
        API-->>U: 401/403 (sin detalle de cuál capa falló)
    else
        API-->>U: 200
    end
    Note over U: token en memoria de la SPA; nunca en localStorage
```

### 3.3 Autorización (RBAC)

| Recurso / acción | Admin | Operador (empresa asignada) | Consulta (asignada) |
|---|---|---|---|
| Usuarios y permisos | ✅ | ❌ | ❌ |
| Empresas: alta/edición/baja | ✅ | ❌ | ❌ |
| Bóveda: alta/reemplazo/borrado e.firma | ✅ | ✅ | ❌ |
| Descargas: crear/reintentar | ✅ | ✅ | ❌ |
| Monitoreo, listados, export | ✅ | ✅ | ✅ |
| Notificaciones: configurar destinos | ✅ | ✅ | ❌ |
| Configuración global | ✅ | ❌ | ❌ |
| Bitácora | ✅ | ❌ | ❌ |

### 3.4 Datos en tránsito y en reposo

| Dato | Tránsito | Reposo |
|---|---|---|
| e.firma (.key, contraseña) | TLS al subir; nunca sale después | AES-256-GCM envelope (bóveda) |
| KEK | No viaja | Archivo 600 fuera de BD/backups; solo procesos api/worker |
| CFDI/XML/paquetes | TLS | Volumen dedicado fuera del webroot; backup cifrado |
| BD | Red interna | Backups cifrados; restore ensayado |
| ID tokens | TLS | Memoria de la SPA (no localStorage) |

### 3.5 Seguridad del cliente (SPA)
Escape por defecto de React (sin `dangerouslySetInnerHTML`); CSP restrictiva; el frontend jamás recibe material de bóveda ni rutas absolutas del servidor; los formularios de e.firma envían y olvidan (sin estado persistente de contraseña); errores genéricos al usuario, detalle solo en logs del servidor.

### 3.6 Workers
Los workers son el único perímetro con acceso a la KEK y al SAT: no exponen puertos; el material descifrado vive el mínimo necesario (scope de la tarea); las excepciones de satcfdi se traducen a la taxonomía propia antes de loguear (evita volcar payloads sensibles); resultados en Redis solo contienen ids y estados, nunca contenido.

---

## 4. Procedimientos operativos

### 4.1 Gestión de secretos
KEK generada offline (32 bytes CSPRNG), entregada al servidor por canal seguro, respaldada en gestor de secretos del despacho (nunca en el repo ni en backups de BD). Credenciales de servicio (Firebase Admin, SMTP, MySQL) por variables de entorno del host. Rotación de KEK: generar nueva → re-envolver DEKs en mantenimiento → invalidar anterior; registrada en bitácora.

### 4.2 Checklist de hardening (gate del sprint de lanzamiento)
- [ ] TLS activo con renovación automática; HSTS.
- [ ] Firewall: solo 443/22; MySQL/Redis internos.
- [ ] KEK con permisos 600, fuera de imagen, repo y backups de BD.
- [ ] Usuario MySQL de la app con mínimos privilegios; `bitacora` INSERT-only.
- [ ] `pip-audit`/`npm audit` limpios; lockfiles con hashes.
- [ ] `/docs` OpenAPI cerrado en producción.
- [ ] Backups cifrados + restore ensayado (incluye volumen de XML).
- [ ] Filtro de redacción de secretos activo en logging.
- [ ] Pruebas negativas de A01/A02/A07 verdes contra el código final (Gobernanza v3 mejora 3).

### 4.3 Respuesta a incidentes
1. **Compromiso del servidor o de la KEK:** aislar el servidor; asumir bóveda comprometida; notificar a cada empresa afectada para **revocar y renovar su e.firma ante el SAT** (es la única remediación real); rotar KEK y credenciales; restaurar desde backup limpio; post-mortem en bitácora.
2. **Filtración de BD/backup sin KEK:** los blobs no son descifrables; evaluar exposición del resto (índice de CFDI = datos fiscales) y notificar conforme LFPDPPP.
3. **Cuenta de usuario comprometida:** desactivar usuario (efecto inmediato, RF-AUTH-04), revisar bitácora de sus acciones, rotar su acceso.

### 4.4 Privacidad y cumplimiento (LFPDPPP)
Bajo el supuesto de operación interna (H-05), el despacho trata datos fiscales y e.firmas de sus clientes como **encargado**: finalidad limitada (descarga, validación, resguardo, vigilancia), consentimiento documentado por empresa para la custodia de la e.firma, aislamiento por empresa, derechos ARCO operables (localizar por listados, exportar, eliminar empresa con su bóveda y archivos mediante procedimiento auditado), y política de retención documentada por empresa. Si D4 cambia a comercialización: ADR nuevo con aviso de privacidad público y contratos de resguardo formales.
