# 03 — Modelo de Datos

| Campo | Valor |
|---|---|
| Documento | 03 — Modelo de Datos |
| Versión | 2.0 |
| Fecha | 2026-07-27 |
| Motor | MySQL 8.x InnoDB · `utf8mb4_unicode_ci` |
| Normalización | 3NF con desnormalización controlada en `comprobantes` (índice de consulta) |
| Depende de | [`ADR-003`](../02-arquitectura/ADR/ADR-003_pivote_web.md) · [`01_SRS`](../01-vision/01_SRS_especificacion_requisitos.md) · [`02_arquitectura`](../02-arquitectura/02_arquitectura_sistema.md) |

> v2.0 reemplaza el modelo SQLite v1.0. `empresas`/`jobs`/`comprobantes` heredan el diseño v1.0 adaptado a MySQL; lo demás es capa de plataforma nueva (prioridad 1 y 3).

---

## 1. Diagrama Entidad-Relación

```mermaid
erDiagram
    usuarios ||--o{ usuario_empresa : "tiene permisos"
    empresas ||--o{ usuario_empresa : "autoriza a"
    empresas ||--o| efirmas : "custodia"
    empresas ||--o{ jobs : "genera"
    empresas ||--o{ comprobantes : "posee"
    jobs ||--o{ comprobantes : "produce"
    empresas ||--o{ notificacion_destinos : "configura"
    empresas ||--o{ eventos : "recibe"
    eventos ||--o{ notificacion_log : "dispara"
    lista_69b ||--o{ eventos : "origina (efos)"

    usuarios { bigint usuario_id PK
               varchar firebase_uid UK
               varchar correo UK
               varchar nombre
               enum rol_global
               tinyint activo }
    usuario_empresa { bigint usuario_id FK
                      bigint empresa_id FK
                      enum rol }
    empresas { bigint empresa_id PK
               varchar nombre
               varchar rfc UK
               varchar plantilla_nomenclatura
               tinyint genera_pdf_comprobante
               tinyint activo }
    efirmas { bigint efirma_id PK
              bigint empresa_id FK UK
              varchar num_serie
              datetime not_before
              datetime not_after
              blob cer_pem
              blob key_cifrada
              blob password_cifrada
              blob dek_envuelta }
    jobs { bigint job_id PK
           bigint empresa_id FK
           enum tipo
           enum solicitud
           enum origen
           date fecha_inicial
           date fecha_final
           varchar id_solicitud
           enum estado
           int intentos
           int paquetes
           text mensaje }
    comprobantes { bigint comprobante_id PK
                   bigint empresa_id FK
                   bigint job_id FK
                   char uuid
                   varchar folio
                   varchar rfc_emisor
                   varchar rfc_receptor
                   varchar razon_social_emisor
                   decimal total
                   datetime fecha_emision
                   char tipo_comprobante
                   enum estatus
                   datetime estatus_verificado_at
                   varchar xml_path
                   varchar comprobante_path }
    lista_69b { bigint registro_id PK
                varchar rfc
                enum situacion
                date fecha_publicacion
                date version_lista }
    eventos { bigint evento_id PK
              bigint empresa_id FK
              enum tipo
              json detalle
              datetime created_at }
    notificacion_destinos { bigint destino_id PK
                            bigint empresa_id FK
                            varchar correo
                            set eventos_suscritos
                            tinyint activo }
    notificacion_log { bigint envio_id PK
                       bigint evento_id FK
                       varchar correo
                       enum resultado }
    bitacora { bigint bitacora_id PK
               varchar actor
               varchar accion
               varchar entidad
               json detalle
               datetime created_at }
    configuracion { varchar clave PK
                    json valor
                    varchar ejercicio_fiscal }
```

---

## 2. Diccionario de datos (tablas núcleo)

### `usuarios`
Usuarios de la plataforma; la identidad la da Firebase, la autorización esta tabla (regla 4 CLAUDE.md).

| Columna | Tipo | Null | Default | Restricciones | Descripción |
|---|---|---|---|---|---|
| `usuario_id` | BIGINT UNSIGNED | No | AI | PK | — |
| `firebase_uid` | VARCHAR(128) | No | — | UNIQUE | uid verificado del ID token |
| `correo` | VARCHAR(190) | No | — | UNIQUE | Correo del usuario |
| `nombre` | VARCHAR(120) | No | — | — | — |
| `rol_global` | ENUM('admin','operador','consulta') | No | 'consulta' | — | Rol base; el efectivo por empresa está en `usuario_empresa` |
| `activo` | TINYINT(1) | No | 1 | — | Desactivación bloquea acceso (RF-AUTH-04) |

### `usuario_empresa`
Permiso explícito usuario↔empresa (RF-AUTH-03). PK compuesta `(usuario_id, empresa_id)`; `rol ENUM('operador','consulta')` — los admin tienen acceso implícito total, registrado en bitácora.

### `empresas`
Clientes/RFC administrados. `rfc VARCHAR(13) UNIQUE` (CHECK longitud 12–13, mayúsculas), `plantilla_nomenclatura VARCHAR(190)` (RF-RES-02, default pendiente D1), `genera_pdf_comprobante TINYINT(1) DEFAULT 0` (RF-RES-03, D2), `activo` (baja lógica RF-EMP-02).

### `efirmas`
Bóveda (RF-BOV). Una e.firma vigente por empresa (`empresa_id` UNIQUE; el reemplazo sobreescribe con bitácora).

| Columna | Tipo | Descripción |
|---|---|---|
| `cer_pem` | BLOB | Certificado (público, sin cifrar) |
| `key_cifrada` | BLOB | `.key` cifrada AES-256-GCM con la DEK (incluye nonce+tag) |
| `password_cifrada` | BLOB | Contraseña cifrada con la DEK |
| `dek_envuelta` | BLOB | DEK envuelta por la KEK maestra (fuera de la BD) |
| `num_serie`, `not_before`, `not_after` | VARCHAR/DATETIME | Metadatos del certificado (RF-BOV-02) |

> **Nunca** existen columnas de contraseña o llave en claro. El descifrado ocurre solo en workers (doc 04 §3.4).

### `jobs`
Idéntica en semántica a v1.0 + `origen ENUM('manual','sync')` (RF-SYNC) y FK a `empresas`. Estados `ENUM('NUEVO','SOLICITADO','EN_PROCESO','TERMINADA','DESCARGADO','ERROR')`; `id_solicitud` inmutable una vez asignado (regla de aplicación); `updated_at` en cada transición.

### `comprobantes`
Índice local de CFDI (heredado v1.0). `UNIQUE(empresa_id, uuid)`; `estatus ENUM('vigente','cancelado','no_verificado')` + `estatus_verificado_at` (base de cancelaciones tardías); desnormaliza `razon_social_emisor` y `total` para listar sin re-abrir XML. `uuid CHAR(36)`.

### `lista_69b`
Copia local de la lista EFOS con versión fechada: `rfc`, `situacion ENUM('presunto','definitivo','desvirtuado','sentencia_favorable')`, `fecha_publicacion`, `version_lista`. El cruce (RF-RIES-02) corre contra `comprobantes.rfc_emisor` de recibidos.

### `eventos`
Materialización de riesgos y avisos: `tipo ENUM('cancelacion_tardia','efos','efirma_por_vencer','error_descarga','resumen_sync')`, `detalle JSON` (UUIDs afectados, RFC, fechas). Fuente de las notificaciones; idempotencia por hash de detalle (regla de aplicación, evita alertar dos veces — RF-RIES-01).

### `notificacion_destinos` / `notificacion_log`
Destinatarios por empresa (correos libres) con `eventos_suscritos SET(...)` (RF-NOT-01), y registro de envíos con `resultado ENUM('enviado','fallido')`.

### `bitacora`
Append-only (RF-BIT-01): `actor` (usuario o `worker`), `accion`, `entidad` (`tipo:id`), `detalle JSON`, `created_at`. Sin UPDATE/DELETE (privilegios del usuario MySQL de la app lo impiden).

### `configuracion`
Clave-valor JSON versionada por `ejercicio_fiscal` (RF-CFG-01): `max_meses_ventana`, `max_anios_antiguedad`, `polling_espera_seg`, `max_reintentos`, `umbral_vigencia_dias`, `hora_sync`.

---

## 3. DDL (extracto ejecutable — tablas críticas)

```sql
CREATE DATABASE IF NOT EXISTS hub_cfdi
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE hub_cfdi;

CREATE TABLE usuarios (
  usuario_id    BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  firebase_uid  VARCHAR(128) NOT NULL UNIQUE,
  correo        VARCHAR(190) NOT NULL UNIQUE,
  nombre        VARCHAR(120) NOT NULL,
  rol_global    ENUM('admin','operador','consulta') NOT NULL DEFAULT 'consulta',
  activo        TINYINT(1) NOT NULL DEFAULT 1,
  created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE empresas (
  empresa_id    BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  nombre        VARCHAR(190) NOT NULL,
  rfc           VARCHAR(13)  NOT NULL UNIQUE,
  plantilla_nomenclatura VARCHAR(190) NOT NULL DEFAULT '{razon_social}_{folio}_V',
  genera_pdf_comprobante TINYINT(1) NOT NULL DEFAULT 0,
  activo        TINYINT(1) NOT NULL DEFAULT 1,
  created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT chk_rfc CHECK (CHAR_LENGTH(rfc) BETWEEN 12 AND 13)
) ENGINE=InnoDB;

CREATE TABLE usuario_empresa (
  usuario_id  BIGINT UNSIGNED NOT NULL,
  empresa_id  BIGINT UNSIGNED NOT NULL,
  rol         ENUM('operador','consulta') NOT NULL DEFAULT 'consulta',
  PRIMARY KEY (usuario_id, empresa_id),
  FOREIGN KEY (usuario_id) REFERENCES usuarios(usuario_id)  ON DELETE CASCADE,
  FOREIGN KEY (empresa_id) REFERENCES empresas(empresa_id)  ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE efirmas (
  efirma_id     BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  empresa_id    BIGINT UNSIGNED NOT NULL UNIQUE,
  num_serie     VARCHAR(40)  NOT NULL,
  not_before    DATETIME NOT NULL,
  not_after     DATETIME NOT NULL,
  cer_pem       BLOB NOT NULL,           -- público
  key_cifrada   BLOB NOT NULL,           -- AES-256-GCM(DEK)
  password_cifrada BLOB NOT NULL,        -- AES-256-GCM(DEK)
  dek_envuelta  BLOB NOT NULL,           -- DEK envuelta por KEK (fuera de la BD)
  created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (empresa_id) REFERENCES empresas(empresa_id) ON DELETE RESTRICT
) ENGINE=InnoDB;

CREATE TABLE jobs (
  job_id        BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  empresa_id    BIGINT UNSIGNED NOT NULL,
  tipo          ENUM('emitido','recibido') NOT NULL,
  solicitud     ENUM('CFDI','METADATA') NOT NULL DEFAULT 'CFDI',
  origen        ENUM('manual','sync') NOT NULL DEFAULT 'manual',
  fecha_inicial DATE NOT NULL,
  fecha_final   DATE NOT NULL,
  id_solicitud  VARCHAR(64) NULL,
  estado        ENUM('NUEVO','SOLICITADO','EN_PROCESO','TERMINADA','DESCARGADO','ERROR')
                NOT NULL DEFAULT 'NUEVO',
  intentos      INT UNSIGNED NOT NULL DEFAULT 0,
  paquetes      INT UNSIGNED NOT NULL DEFAULT 0,
  mensaje       TEXT NULL,
  created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  FOREIGN KEY (empresa_id) REFERENCES empresas(empresa_id) ON DELETE RESTRICT,
  CONSTRAINT chk_rango CHECK (fecha_final >= fecha_inicial),
  INDEX idx_jobs_empresa_estado (empresa_id, estado),
  INDEX idx_jobs_estado (estado)
) ENGINE=InnoDB;

CREATE TABLE comprobantes (
  comprobante_id BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  empresa_id    BIGINT UNSIGNED NOT NULL,
  job_id        BIGINT UNSIGNED NULL,
  uuid          CHAR(36) NOT NULL,
  folio         VARCHAR(40) NULL,
  rfc_emisor    VARCHAR(13) NOT NULL,
  rfc_receptor  VARCHAR(13) NOT NULL,
  razon_social_emisor VARCHAR(254) NULL,
  total         DECIMAL(18,2) NULL,
  fecha_emision DATETIME NULL,
  tipo_comprobante CHAR(1) NULL,     -- I/E/T/N/P
  estatus       ENUM('vigente','cancelado','no_verificado') NOT NULL DEFAULT 'no_verificado',
  estatus_verificado_at DATETIME NULL,
  xml_path      VARCHAR(500) NULL,
  comprobante_path VARCHAR(500) NULL,
  created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_empresa_uuid (empresa_id, uuid),
  FOREIGN KEY (empresa_id) REFERENCES empresas(empresa_id) ON DELETE RESTRICT,
  FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE SET NULL,
  INDEX idx_comp_emp_fecha   (empresa_id, fecha_emision),
  INDEX idx_comp_emp_estatus (empresa_id, estatus),
  INDEX idx_comp_emisor      (rfc_emisor),
  INDEX idx_comp_emp_verif   (empresa_id, estatus_verificado_at)
) ENGINE=InnoDB;

CREATE TABLE lista_69b (
  registro_id   BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  rfc           VARCHAR(13) NOT NULL,
  situacion     ENUM('presunto','definitivo','desvirtuado','sentencia_favorable') NOT NULL,
  fecha_publicacion DATE NULL,
  version_lista DATE NOT NULL,
  UNIQUE KEY uq_rfc_version (rfc, version_lista),
  INDEX idx_69b_rfc (rfc)
) ENGINE=InnoDB;

CREATE TABLE eventos (
  evento_id   BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  empresa_id  BIGINT UNSIGNED NOT NULL,
  tipo        ENUM('cancelacion_tardia','efos','efirma_por_vencer','error_descarga','resumen_sync') NOT NULL,
  detalle     JSON NOT NULL,
  hash_detalle CHAR(64) NOT NULL,          -- idempotencia de alertas
  created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_evento (empresa_id, tipo, hash_detalle),
  FOREIGN KEY (empresa_id) REFERENCES empresas(empresa_id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE notificacion_destinos (
  destino_id  BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  empresa_id  BIGINT UNSIGNED NOT NULL,
  correo      VARCHAR(190) NOT NULL,
  eventos_suscritos SET('cancelacion_tardia','efos','efirma_por_vencer','error_descarga','resumen_sync') NOT NULL,
  activo      TINYINT(1) NOT NULL DEFAULT 1,
  UNIQUE KEY uq_emp_correo (empresa_id, correo),
  FOREIGN KEY (empresa_id) REFERENCES empresas(empresa_id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE notificacion_log (
  envio_id   BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  evento_id  BIGINT UNSIGNED NOT NULL,
  correo     VARCHAR(190) NOT NULL,
  resultado  ENUM('enviado','fallido') NOT NULL,
  mensaje    VARCHAR(500) NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (evento_id) REFERENCES eventos(evento_id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE bitacora (
  bitacora_id BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  actor       VARCHAR(190) NOT NULL,     -- correo del usuario o 'worker'
  accion      VARCHAR(60)  NOT NULL,
  entidad     VARCHAR(120) NOT NULL,     -- 'tipo:id'
  detalle     JSON NULL,
  created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_bit_entidad (entidad),
  INDEX idx_bit_fecha (created_at)
) ENGINE=InnoDB;

CREATE TABLE configuracion (
  clave            VARCHAR(80) NOT NULL,
  ejercicio_fiscal VARCHAR(9)  NOT NULL DEFAULT 'vigente',
  valor            JSON NOT NULL,
  updated_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (clave, ejercicio_fiscal)
) ENGINE=InnoDB;
```

---

## 4. Reglas de integridad en capa de aplicación

1. **Transiciones legales del job:** el repository valida el par (estado_actual → nuevo) contra la máquina de estados (SRS §4); transición ilegal ⇒ excepción.
2. **`id_solicitud` inmutable** una vez asignado.
3. **Ventana ≤ 12 meses** garantizada por `daterange` antes del INSERT (el CHECK solo cubre orden de fechas).
4. **Bitácora INSERT-only:** el usuario MySQL de la aplicación no tiene UPDATE/DELETE sobre `bitacora`.
5. **Idempotencia de eventos:** `hash_detalle = SHA-256(canonical(detalle))` con UNIQUE evita alertas duplicadas.
6. **RFC normalizado** (mayúsculas, sin espacios) al persistir.
7. **Permiso usuario↔empresa** verificado en la dependencia de auth de todo endpoint (doc 02 §3.2), nunca en SQL condicional del frontend.

## 5. Justificaciones de diseño

- **`UNIQUE(empresa_id, uuid)` y no `UNIQUE(uuid)`:** el mismo CFDI puede aparecer legítimamente en dos empresas (una emisora, otra receptora).
- **Blobs cifrados en BD y no archivos:** mantiene la e.firma dentro del perímetro transaccional (alta+bitácora atómicas) y de los backups cifrados; la KEK fuera de la BD garantiza que un dump aislado no sirve para descifrar.
- **`origen` en `jobs`:** distingue sync automática de disparo manual — necesario para el monitoreo (RF-SYNC-03) y para métricas de la corrida diaria.
- **`lista_69b` versionada por fecha:** permite saber contra qué versión se cruzó y re-ejecutar diffs; el histórico de situaciones cambia (presunto→definitivo/desvirtuado).
- **`eventos` con hash de idempotencia:** las corridas diarias re-evalúan el mundo entero; sin idempotencia, cada corrida re-alertaría lo mismo.
- **DECIMAL(18,2) para totales:** los importes fiscales no se almacenan en flotante.
- **Desnormalización en `comprobantes`:** listar y exportar sin re-abrir XML (RNF-03: 1M filas por empresa).
