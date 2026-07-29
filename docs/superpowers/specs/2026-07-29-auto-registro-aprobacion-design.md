# Diseño — Auto-registro con aprobación del admin + recuperación de contraseña

**Fecha:** 2026-07-29
**Estado:** Aprobado, listo para plan de implementación

## 1. Problema y cambio de política

El SRS (RF-AUTH-02) decía "sin auto-registro": solo un admin daba de alta usuarios. David cambia esa
política a propósito: ahora cualquiera puede **auto-registrarse**, pero queda **pendiente de aprobación**
y sin acceso hasta que un admin lo apruebe; entra con el **rol de menos privilegios** (`consulta`) y sin
acceso a ninguna empresa. Además, se agrega **recuperación de contraseña**.

Contexto de auth (ver también el spec del bootstrap): Firebase Auth (cliente `signInWithEmailAndPassword`
+ backend `verificar_id_token` con Admin SDK); usuarios mapeados por `firebase_uid`; `_usuario_activo_por_token`
(`app/api/deps.py:44-49`) bloquea si el usuario local no existe o `not activo`. SMTP ya configurado
(`app/services/notificaciones.py`). `UsuariosPage` (admin) hoy es solo lectura.

## 2. Decisiones tomadas (brainstorming)

| Decisión | Elección |
|---|---|
| Estado "pendiente" | Campo nuevo `aprobado: bool` (default false) en `usuarios` |
| Creación de cuenta en el auto-registro | **Firebase en el cliente** (`createUserWithEmailAndPassword`) + `POST /v1/auth/registro` al backend |
| Rol del auto-registrado | `rol_global=consulta`, sin permisos por-empresa |
| Aprobar | Solo activa el acceso (`aprobado=true`); el admin otorga empresas aparte |
| Recuperación de contraseña | **Firebase nativo** (`sendPasswordResetEmail`) — cero backend |
| Aviso al admin | **Sí**, correo a los admins vía el SMTP configurado (best-effort) |

**Fuera de alcance (YAGNI):** auto-aprobación por dominio de correo; verificación de correo obligatoria;
asignación de empresa durante la aprobación (el admin usa el `PUT /permisos` existente); branding propio
del correo de reset (lo maneja Firebase).

## 3. Modelo y puerta de acceso

- **Migración:** agregar `aprobado` (TINYINT(1), not null, default 0) a `usuarios`; `UPDATE usuarios SET
  aprobado=1` para las filas existentes (ya legítimas).
- **Regla de acceso:** un usuario puede usar el sistema solo si `aprobado=true` **Y** `activo=true`.
- **`_usuario_activo_por_token`** (`app/api/deps.py`) se refuerza y distingue el motivo con envelope
  `{codigo, mensaje}` (hoy lanza un 403 de texto plano; cambia a detalle estructurado):
  - no existe local → 403 `NO_REGISTRADO`
  - `aprobado=false` → 403 `CUENTA_PENDIENTE`
  - `activo=false` → 403 `CUENTA_INACTIVA`
- Como esta dependencia la usan TODOS los endpoints autenticados, un pendiente queda bloqueado en todo el
  sistema; `GET /v1/me` es quien le comunica al frontend el motivo (`CUENTA_PENDIENTE`).
- **Quién crea con `aprobado=true`:** el bootstrap del primer admin (ya existe) y `POST /v1/usuarios`
  (alta directa por admin) deben fijar `aprobado=true`. Solo `POST /v1/auth/registro` crea `aprobado=false`.

## 4. Backend

### 4.1 `POST /v1/auth/registro` (autenticado con el token del recién creado; NO exige aprobación)
Se agrega al router público `/auth` existente (`app/api/v1/auth_bootstrap.py`), sin crear un router nuevo.
- Dependencia ligera: solo `verificar_id_token(authorization) -> uid` (no `usuario_actual`, que exigiría
  aprobado+activo). Se agrega un helper/dep `uid_del_token`.
- Correo autoritativo desde Firebase: `firebase_auth.get_user(uid).email` (Admin SDK) — no se confía en el
  body para el correo. `nombre` viene del body (`RegistroIn { nombre: str }`).
- Si ya existe local por `firebase_uid` o `correo` → 409 `YA_REGISTRADO`.
- Crea: `rol_global=consulta`, `aprobado=false`, `activo=true`. Bitácora `auto_registro`.
- **Aviso a admins (best-effort):** tras crear, envía correo a todos los `rol_global=admin` activos y
  aprobados (con correo) usando el SMTP configurado. Si el SMTP no está o falla → se loguea y NO rompe el
  registro (mismo patrón tolerante de las notificaciones actuales). Devuelve 201 `{ estado: "pendiente" }`.

### 4.2 Aprobación / rechazo (admin, `require_admin`)
- **Aprobar:** `UsuarioPatchIn` gana `aprobado: bool | None`; `PATCH /v1/usuarios/{id}` lo aplica junto a
  `activo`/`rol_global`. Bitácora incluye `aprobado`.
- **Rechazar:** `DELETE /v1/usuarios/{id}` — borra el registro local **y** la cuenta de Firebase
  (`firebase_auth.delete_user`). Guardas: 404 si no existe; 409 si el objetivo es el propio admin
  (`no puedes eliminarte`) o si es el **último admin** aprobado/activo. Bitácora `eliminar_usuario`.
- **Exponer `aprobado`** en `UsuarioAdminOut` (y por tanto en `GET /v1/usuarios`).

### 4.3 Servicio de correo
- Nueva función en `app/services/notificaciones.py`: `enviar_aviso_registro(destinos: list[str],
  solicitante_correo: str, solicitante_nombre: str, credenciales)` que arma un `EmailMessage` (asunto
  "Nueva solicitud de acceso a Hub CFDI", cuerpo con quién solicitó y que revise Usuarios) y usa el
  `_enviar` existente. Se orquesta desde el endpoint de registro resolviendo credenciales con
  `resolver_credenciales(db)`; si no hay config SMTP, se omite sin fallar.

## 5. Frontend (`apps/web`)

### 5.1 ApiClient
- `registrarUsuario(body: { nombre: string }): Promise<void>` → `POST /v1/auth/registro` (autenticado).
- Admin: `actualizarUsuario(id, body: { activo?: boolean; rol_global?: Rol; aprobado?: boolean }): Promise<void>`
  (`PATCH`), `eliminarUsuario(id): Promise<void>` (`DELETE`).
- Tipo `UsuarioAdmin` gana `aprobado: boolean`.
- El reset de contraseña NO usa el ApiClient (es Firebase cliente).

### 5.2 Rutas públicas nuevas (junto a `/login`, `/bootstrap`)
- `/registro` → `RegistroPage`; `/recuperar` → `RecuperarPage`.

### 5.3 `RegistroPage`
- Form: nombre, correo, contraseña + confirmación.
- `createUserWithEmailAndPassword(auth, correo, password)` → token → `api.registrarUsuario({ nombre })` →
  éxito: mensaje "Cuenta creada. Un administrador debe aprobar tu acceso." + `signOut`. Mapea errores de
  Firebase (`auth/email-already-in-use`, `auth/weak-password`, `auth/invalid-email`) y backend 409.

### 5.4 `RecuperarPage`
- Un campo (correo) → `sendPasswordResetEmail(auth, correo)` → mensaje neutro "Si el correo existe, te
  enviamos un enlace." (no revela si el correo está registrado). Maneja `auth/invalid-email`.

### 5.5 `LoginPage`
- Dos enlaces: "¿No tienes cuenta? Regístrate" (→ `/registro`) y "¿Olvidaste tu contraseña?" (→ `/recuperar`).

### 5.6 UX de cuenta pendiente (`AuthContext`)
- En `onAuthStateChanged`, cuando `api.me()` falle con `ApiError.codigo === 'CUENTA_PENDIENTE'` (o
  `CUENTA_INACTIVA`), mostrar el mensaje amable correspondiente en vez del genérico, y `signOut`.

### 5.7 `UsuariosPage` (admin) — gestión de aprobación
- Badge de estado por usuario: **Pendiente** (`!aprobado`), **Inactivo** (`aprobado && !activo`), **Activo**.
  Contador de pendientes visible.
- Acciones **Aprobar** (`actualizarUsuario(id, { aprobado: true })`) y **Rechazar**
  (`eliminarUsuario(id)`, con confirmación). `useMutation` + invalidar `['usuarios']`.

## 6. Pruebas

**Backend** (Firebase Admin SDK mockeado — `get_user`/`delete_user`; SMTP mockeado; sin red):
- `POST /registro`: crea `consulta`/`aprobado=false`; correo tomado de Firebase, no del body; 409 si ya
  existe; dispara el aviso a admins (verifica el envío mockeado); no falla si no hay SMTP.
- Puerta de acceso: token de `aprobado=false` → 403 `CUENTA_PENDIENTE`; `activo=false` → `CUENTA_INACTIVA`;
  usuario aprobado+activo → pasa.
- `PATCH {aprobado: true}` activa el acceso; `POST /v1/usuarios` y bootstrap crean `aprobado=true`.
- `DELETE`: borra local + Firebase; 409 al intentar borrar al último admin o a sí mismo.
- Migración: `aprobado` existe; filas previas quedan en `true`.

**Frontend:** `tsc`/`eslint` + verificación manual (registro → pendiente; admin aprueba → el usuario entra;
reset envía correo; enlaces del login).

## 7. Verificación en vivo (post-implementación)
Contra el entorno real: registrar un usuario nuevo → confirmar que queda pendiente y no entra (mensaje
"pendiente"), que llega el correo al admin, que tras Aprobar el usuario ya inicia sesión (con acceso a nada
hasta darle permisos de empresa), que Rechazar borra la cuenta, y que el enlace de "recuperar contraseña"
llega y funciona.

## 8. Archivos afectados

**Nuevos:**
- `alembic/versions/<rev>_add_usuarios_aprobado.py`
- `apps/web/src/features/auth/RegistroPage.tsx`, `apps/web/src/features/auth/RecuperarPage.tsx`
- `tests/test_auth_registro.py`

**Modificados:**
- `app/models/usuario.py` — `aprobado`.
- `app/api/deps.py` — puerta `aprobado`/códigos; dep `uid_del_token`.
- `app/api/v1/auth_bootstrap.py` — endpoint `POST /auth/registro`; el bootstrap fija `aprobado=True`.
- `app/api/v1/usuarios.py` — `aprobado=True` en alta admin; `PATCH` aprobado; `DELETE` (rechazo) con guardas.
- `app/api/v1/schemas.py` — `RegistroIn`, `UsuarioPatchIn.aprobado`, `UsuarioAdminOut.aprobado`, `UsuarioOut.aprobado`.
- `app/repositories/usuarios.py` — `crear(..., aprobado=...)`, `actualizar(..., aprobado=...)`, `eliminar`, `contar_admins`.
- `app/services/notificaciones.py` — `enviar_aviso_registro`.
- Frontend: `api.ts`, `api.http.ts`, `api.mock.ts`, `AuthContext.tsx`, `App.tsx`, `LoginPage.tsx`,
  `features/admin/UsuariosPage.tsx`.
