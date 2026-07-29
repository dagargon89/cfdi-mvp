# Diseño — Signup de arranque del administrador (bootstrap)

**Fecha:** 2026-07-29
**Estado:** Aprobado, listo para plan de implementación

## 1. Problema

Al desplegar Hub CFDI en un entorno nuevo, la base de datos no tiene usuarios. Toda la creación de
usuarios pasa hoy por `POST /v1/usuarios`, que exige `require_admin` — pero no hay ningún admin todavía.
Hoy el primer admin se crea a mano en dos pasos (cuenta en la consola de Firebase + `INSERT` manual en
`usuarios`). Es el clásico problema del huevo y la gallina.

**Objetivo:** un **signup de arranque** que solo existe mientras la tabla `usuarios` esté vacía, crea el
primer usuario administrador (cuenta en Firebase + registro local) y luego desaparece para siempre,
dejando la app en el login habitual. Es la excepción explícita a RF-AUTH-02 ("sin auto-registro"),
acotada al primer admin.

## 2. Contexto de autenticación (estado actual)

- **Firebase Auth** hace la autenticación: el frontend hace `signInWithEmailAndPassword` y envía el ID
  token como `Authorization: Bearer`. El backend lo verifica con el Admin SDK (`app/core/security.py`
  `verificar_id_token`) y mapea token → usuario local por `firebase_uid` (`app/api/deps.py`
  `_usuario_activo_por_token`).
- **`POST /v1/usuarios`** (`app/api/v1/usuarios.py:42-55`, solo admin) ya crea la cuenta en Firebase vía
  Admin SDK (`firebase_auth.create_user(email=..., email_verified=False)`, **sin** contraseña) y el
  registro local (`usuarios_repo.crear`). Es el patrón a reutilizar, agregando la contraseña.
- **Modelo `Usuario`** (`app/models/usuario.py`): `firebase_uid` (unique), `correo` (unique), `nombre`,
  `rol_global` (enum `RolGlobal` = admin/operador/consulta, `app/models/enums.py:18-22`), `activo`.
- **Frontend** (`apps/web`): `AuthContext` solo tiene `login`/`logout`; `LoginPage` es la única pantalla de
  auth; `onAuthStateChanged` hace `signOut` si no hay usuario local. No hay signup.
- **Config** (`app/core/config.py`): `Settings` (pydantic-settings), variables Firebase obligatorias.

## 3. Decisiones tomadas (brainstorming)

| Decisión | Elección |
|---|---|
| Qué crea el signup | **Cuenta en Firebase (con contraseña) + registro local** con `rol_global=admin`, en una operación |
| Cuándo existe el signup | **Solo mientras `usuarios` esté vacía** (cero usuarios) |
| Protección de la ventana abierta | **Token de arranque** desde el servidor (`BOOTSTRAP_ADMIN_TOKEN` en el env) |
| Endpoint sin token configurado | **Falla cerrado** (503): no se puede hacer bootstrap sin un token puesto a propósito |
| Tras el signup | **Redirige al login habitual** (no auto-login); el admin entra con lo que creó |

**Fuera de alcance (YAGNI):** UI para que el admin cree usuarios adicionales después (el endpoint
`POST /v1/usuarios` ya existe pero `UsuariosPage` es solo lectura — feature aparte); recuperación de
contraseña; multi-admin en el bootstrap.

## 4. Backend

### 4.1 Config
- Nueva variable en `app/core/config.py`: `bootstrap_admin_token: str = ""` (default vacío = deshabilitado).
- Documentar en `.env.example` (backend): `BOOTSTRAP_ADMIN_TOKEN=` con nota de que es un secreto largo y
  aleatorio, usado una sola vez para el alta del primer admin.

### 4.2 Repositorio
- `app/repositories/usuarios.py`: agregar `async def contar(db) -> int` (`SELECT COUNT(*) FROM usuarios`).

### 4.3 Router nuevo `app/api/v1/auth_bootstrap.py` (público, sin dependencias de auth)
Prefijo `/auth`, montado bajo `/v1`.

**`GET /v1/auth/bootstrap-status`** → `BootstrapStatusOut { needs_bootstrap: bool }`
- `needs_bootstrap = (await usuarios_repo.contar(db)) == 0`. Sin token, sin auth. Solo el booleano.

**`POST /v1/auth/bootstrap`** → 201 `UsuarioOut`
- Body `BootstrapAdminIn { correo: EmailStr, nombre: str, password: str (min_length=8), token: str }`.
- Orden de validación (errores con envelope `{codigo, mensaje}` como el resto de la API):
  1. `settings.bootstrap_admin_token` vacío → **503** `BOOTSTRAP_DESHABILITADO`.
  2. `secrets.compare_digest(token, settings.bootstrap_admin_token)` falla → **403** `TOKEN_INVALIDO`.
  3. `await usuarios_repo.contar(db) != 0` → **409** `BOOTSTRAP_YA_REALIZADO`.
  4. `await usuarios_repo.por_correo(db, correo)` existe → **409** `CORREO_DUPLICADO`.
- Creación (reutiliza el patrón de `usuarios.py:48-52`, con contraseña):
  - `cuenta = firebase_auth.create_user(email=correo, password=password, email_verified=False, app=firebase_app())`;
    `EmailAlreadyExistsError` → **409** `CORREO_DUPLICADO`.
  - `usuario = await usuarios_repo.crear(db, firebase_uid=cuenta.uid, correo=correo, nombre=nombre, rol_global=RolGlobal.ADMIN)`.
  - Bitácora `alta_admin_bootstrap` (actor = `correo`, no hay sesión) → `commit`.
- **Manejo de huérfano/carrera:** el chequeo `contar()==0` y el `INSERT` van en la misma transacción; el
  `UNIQUE(correo)`/`UNIQUE(firebase_uid)` hace fallar un segundo request concurrente (→ se traduce a 409).
  Si el `flush()`/`commit` local falla **después** de crear la cuenta en Firebase, se ejecuta
  `firebase_auth.delete_user(cuenta.uid)` para no dejar la cuenta huérfana, y se propaga el error como 500.

### 4.4 Schemas (`app/api/v1/schemas.py`)
```
class BootstrapStatusOut(BaseModel):
    needs_bootstrap: bool

class BootstrapAdminIn(BaseModel):
    correo: EmailStr
    nombre: str
    password: str = Field(min_length=8)
    token: str
```
Reutiliza el `UsuarioOut` existente para la respuesta.

### 4.5 Montaje del router
Registrar `auth_bootstrap.router` en `app/api/v1/router.py` (agregar el import al `from app.api.v1 import ...`
y una línea `router.include_router(auth_bootstrap.router)`), **sin** el `Depends` de auth que llevan los demás.

## 5. Frontend (`apps/web`)

### 5.1 ApiClient
- `api.ts` + `api.http.ts` (+ `api.mock.ts`): `estadoBootstrap(): Promise<{ needs_bootstrap: boolean }>` y
  `crearAdminBootstrap(body: { correo; nombre; password; token }): Promise<UsuarioOut>`. Ambos **sin**
  `Authorization` (usan `request` sin token; `request` ya omite el header cuando `getIdToken()` es null).

### 5.2 AuthContext + enrutado
- `AuthContext` gana estado `needsBootstrap: boolean | null` (null = aún cargando). Al montar, llama
  `api.estadoBootstrap()` una vez.
- Router (`App.tsx`):
  - `needsBootstrap === true` → toda ruta no autenticada redirige a **`/bootstrap`** (SignupPage).
  - `needsBootstrap === false` → comportamiento actual (LoginPage).
  - Guarda: si se entra a `/bootstrap` con `needsBootstrap === false` → redirige a `/login`.

### 5.3 `SignupPage` (nueva, `features/auth/SignupPage.tsx`)
- Formulario: correo, nombre, contraseña + confirmación, y **token de arranque** (con copy que explique que
  es el `BOOTSTRAP_ADMIN_TOKEN` del `.env` del servidor).
- Al enviar → `api.crearAdminBootstrap(...)`. Éxito → toast + **redirige a `/login`**. Errores mapeados:
  `TOKEN_INVALIDO`, `CORREO_DUPLICADO`, `BOOTSTRAP_YA_REALIZADO`, `BOOTSTRAP_DESHABILITADO`.
- Mismo estilo visual y primitivos que `LoginPage.tsx`.

## 6. Pruebas

**Backend** (`tests/test_auth_bootstrap.py`, con dobles; Firebase Admin SDK mockeado como en los tests de
auth existentes; nunca red real):
- `bootstrap-status`: BD vacía → `needs_bootstrap=true`; con ≥1 usuario → `false`.
- `POST /bootstrap` feliz: token correcto + BD vacía → 201, `rol_global=admin`, bitácora `alta_admin_bootstrap`,
  y `create_user` llamado con `password`.
- Token ausente en el body / incorrecto → 403 `TOKEN_INVALIDO`.
- `bootstrap_admin_token` vacío en settings → 503 `BOOTSTRAP_DESHABILITADO`.
- BD con usuarios → 409 `BOOTSTRAP_YA_REALIZADO`.
- `EmailAlreadyExistsError` de Firebase → 409 `CORREO_DUPLICADO`.
- Fallo del `INSERT` local tras `create_user` → se llama `delete_user(uid)` (limpieza del huérfano).

**Frontend:** `tsc`/`eslint` limpios + verificación manual (BD vacía muestra `/bootstrap`; alta redirige a
`/login`; con admin ya creado, `/bootstrap` redirige a `/login`).

## 7. Verificación en vivo (post-implementación)
Contra el entorno real: con `usuarios` vacía y `BOOTSTRAP_ADMIN_TOKEN` puesto, abrir la app → aparece el
signup → crear el admin → confirmar que se creó la cuenta en Firebase y el registro local `admin`, que el
signup desaparece (`needs_bootstrap=false`) y que el admin puede iniciar sesión en el login normal.

## 8. Archivos afectados

**Nuevos:**
- `app/api/v1/auth_bootstrap.py`
- `tests/test_auth_bootstrap.py`
- `apps/web/src/features/auth/SignupPage.tsx`

**Modificados:**
- `app/core/config.py` — `bootstrap_admin_token`.
- `.env.example` (backend) — documentar la variable.
- `app/repositories/usuarios.py` — `contar()`.
- `app/api/v1/schemas.py` — `BootstrapStatusOut`, `BootstrapAdminIn`.
- `app/api/v1/router.py` — registrar el router nuevo.
- `apps/web/src/lib/api.ts`, `api.http.ts`, `api.mock.ts` — métodos nuevos.
- `apps/web/src/auth/AuthContext.tsx` — `needsBootstrap` + fetch.
- `apps/web/src/App.tsx` — ruta `/bootstrap` + enrutado condicional.
