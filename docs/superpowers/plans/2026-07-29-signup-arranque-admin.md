# Signup de arranque del administrador (bootstrap) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Un signup de arranque que, solo mientras `usuarios` esté vacía, crea el primer administrador (cuenta en Firebase con contraseña + registro local `rol_global=admin`) protegido por un token de servidor, y luego desaparece dejando la app en el login habitual.

**Architecture:** Dos endpoints PÚBLICOS nuevos (`GET /v1/auth/bootstrap-status`, `POST /v1/auth/bootstrap`) sin `Depends` de auth, gateados por `COUNT(usuarios)==0` y un `BOOTSTRAP_ADMIN_TOKEN` del servidor. El frontend consulta el estado al cargar y enruta a una `SignupPage` nueva o al `LoginPage` existente. Reutiliza el patrón de `POST /v1/usuarios` (crear cuenta Firebase vía Admin SDK + registro local), agregando la contraseña.

**Tech Stack:** Backend FastAPI + SQLAlchemy async + Firebase Admin SDK + pytest (asyncio, testcontainers). Frontend React + react-router + Firebase Auth (cliente) + TypeScript. Sin framework de test unitario en el front (verificación por `tsc`/`eslint` + manual).

## Global Constraints

- **Endpoints públicos:** `bootstrap-status` y `bootstrap` NO llevan `Depends(require_admin)` ni `usuario_actual` — aún no puede existir un token. Montados en `app/api/v1/router.py`.
- **Gate:** el bootstrap solo opera si `await usuarios_repo.contar(db) == 0`.
- **Token:** comparación en tiempo constante `secrets.compare_digest(body.token, settings.bootstrap_admin_token)`.
- **Fail-closed:** si `settings.bootstrap_admin_token` es `""` → 503 `BOOTSTRAP_DESHABILITADO` (no se puede hacer bootstrap sin token puesto a propósito).
- **Orden de validación exacto:** (1) token vacío→503, (2) token no coincide→403 `TOKEN_INVALIDO`, (3) `contar()!=0`→409 `BOOTSTRAP_YA_REALIZADO`, (4) correo ya en BD→409 `CORREO_DUPLICADO`, (5) crear Firebase (`EmailAlreadyExistsError`→409 `CORREO_DUPLICADO`), (6) crear local `rol_global=ADMIN`, (7) bitácora `alta_admin_bootstrap`, (8) commit; si el registro local falla tras crear Firebase → `delete_user` + 500.
- **Envelope de error:** `HTTPException(status, detail={"codigo": ..., "mensaje": ...})` (el sobre `{"error": {...}}` lo arma `app/main.py`).
- **Tras el signup (frontend):** redirige a `/login` (no auto-login).
- **`request` del frontend ya omite `Authorization` cuando `getIdToken()` es null** (`api.http.ts:19`) — las llamadas públicas funcionan sin sesión.
- **`asyncio_mode = "auto"`** (pyproject): tests `async def` se autodetectan; NO declarar `pytestmark` a nivel módulo.
- **Aislamiento de tests:** el fixture `db` recrea las tablas por test → cada test arranca con `usuarios` vacía.
- **Limitación aceptada (documentar, no resolver):** dos bootstraps concurrentes con correos DISTINTOS podrían crear dos admins (ambos ven `contar()==0`); el gate del token (solo el operador lo tiene) y la ventana sub-segundo lo hacen irreal, y el resultado sería benigno (dos cuentas del propio operador). Los `UNIQUE(correo)`/`UNIQUE(firebase_uid)` sí cierran el caso de mismo correo.
- **Commits:** en la rama `feat/signup-bootstrap-admin`. Cada commit termina con:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`

---

## File Structure

**Nuevos:**
- `app/api/v1/auth_bootstrap.py` — router público con los 2 endpoints.
- `tests/test_auth_bootstrap.py` — pruebas (Firebase mockeado).
- `apps/web/src/features/auth/SignupPage.tsx` — pantalla de alta del admin.

**Modificados:**
- `app/core/config.py` — `bootstrap_admin_token`.
- `.env.example` — documentar `BOOTSTRAP_ADMIN_TOKEN`.
- `app/repositories/usuarios.py` — `contar()`.
- `app/api/v1/schemas.py` — `BootstrapStatusOut`, `BootstrapAdminIn`.
- `app/api/v1/router.py` — montar el router nuevo.
- `apps/web/src/lib/api.ts`, `api.http.ts`, `api.mock.ts` — `estadoBootstrap`, `crearAdminBootstrap`.
- `apps/web/src/auth/AuthContext.tsx` — `needsBootstrap` + fetch al montar.
- `apps/web/src/App.tsx` — ruta `/bootstrap` + import de `SignupPage`.
- `apps/web/src/features/auth/LoginPage.tsx` — redirigir a `/bootstrap` si `needsBootstrap`.

---

## Task 1: Backend — API de bootstrap (config, repo, schemas, endpoints, router)

**Files:**
- Create: `app/api/v1/auth_bootstrap.py`
- Modify: `app/core/config.py`, `.env.example`, `app/repositories/usuarios.py`, `app/api/v1/schemas.py`, `app/api/v1/router.py`
- Test: `tests/test_auth_bootstrap.py`

**Interfaces:**
- Produces:
  - `GET /v1/auth/bootstrap-status` → `{ needs_bootstrap: bool }`
  - `POST /v1/auth/bootstrap` (body `{correo, nombre, password, token}`) → 201 `UsuarioOut`
  - `usuarios_repo.contar(db) -> int`
  - `settings.bootstrap_admin_token: str` (default `""`)

- [ ] **Step 1: Escribir los tests que fallan**

Crea `tests/test_auth_bootstrap.py`:

```python
"""Signup de arranque del primer admin (bootstrap) — spec 2026-07-29. Firebase Admin SDK mockeado
(sin red real); el fixture `db` recrea tablas por test, así que cada caso arranca con `usuarios` vacía."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.enums import RolGlobal
from app.repositories import usuarios as usuarios_repo
from tests.factories import crear_usuario

_BODY = {"correo": "admin@demo.test", "nombre": "Admin", "password": "contrasena8", "token": "tok-test"}


class _CuentaFake:
    def __init__(self, uid: str) -> None:
        self.uid = uid


@pytest.fixture()
def firebase_fake(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Mockea el Admin SDK en el módulo del router: create_user devuelve un uid, delete_user se registra."""
    import app.api.v1.auth_bootstrap as mod

    estado: dict = {"creadas": [], "borradas": [], "fallar_create": None}

    def fake_create_user(**kwargs):
        if estado["fallar_create"] is not None:
            raise estado["fallar_create"]
        estado["creadas"].append(kwargs)
        return _CuentaFake("uid-fake-1")

    def fake_delete_user(uid, **kwargs):
        estado["borradas"].append(uid)

    monkeypatch.setattr(mod, "firebase_app", lambda: None)
    monkeypatch.setattr(mod.firebase_auth, "create_user", fake_create_user)
    monkeypatch.setattr(mod.firebase_auth, "delete_user", fake_delete_user)
    return estado


@pytest.fixture()
def con_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "bootstrap_admin_token", "tok-test")


async def test_status_bd_vacia(client: AsyncClient) -> None:
    res = await client.get("/v1/auth/bootstrap-status")
    assert res.status_code == 200
    assert res.json()["needs_bootstrap"] is True


async def test_status_con_usuario(client: AsyncClient, db: AsyncSession) -> None:
    await crear_usuario(db, uid="u1", correo="ya@demo.test")
    await db.commit()
    res = await client.get("/v1/auth/bootstrap-status")
    assert res.json()["needs_bootstrap"] is False


async def test_bootstrap_ok(client: AsyncClient, db: AsyncSession, firebase_fake: dict, con_token: None) -> None:
    res = await client.post("/v1/auth/bootstrap", json=_BODY)
    assert res.status_code == 201, res.text
    usuario = await usuarios_repo.por_correo(db, "admin@demo.test")
    assert usuario is not None
    assert usuario.rol_global == RolGlobal.ADMIN
    assert usuario.firebase_uid == "uid-fake-1"
    # se creó en Firebase CON contraseña
    assert firebase_fake["creadas"][0]["password"] == "contrasena8"


async def test_bootstrap_token_deshabilitado_503(client: AsyncClient, firebase_fake: dict, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "bootstrap_admin_token", "")
    res = await client.post("/v1/auth/bootstrap", json=_BODY)
    assert res.status_code == 503
    assert res.json()["error"]["codigo"] == "BOOTSTRAP_DESHABILITADO"


async def test_bootstrap_token_invalido_403(client: AsyncClient, firebase_fake: dict, con_token: None) -> None:
    res = await client.post("/v1/auth/bootstrap", json={**_BODY, "token": "otro"})
    assert res.status_code == 403
    assert res.json()["error"]["codigo"] == "TOKEN_INVALIDO"


async def test_bootstrap_ya_realizado_409(client: AsyncClient, db: AsyncSession, firebase_fake: dict, con_token: None) -> None:
    await crear_usuario(db, uid="u1", correo="ya@demo.test")
    await db.commit()
    res = await client.post("/v1/auth/bootstrap", json=_BODY)
    assert res.status_code == 409
    assert res.json()["error"]["codigo"] == "BOOTSTRAP_YA_REALIZADO"


async def test_bootstrap_correo_ya_en_firebase_409(client: AsyncClient, firebase_fake: dict, con_token: None) -> None:
    from firebase_admin import auth as firebase_auth

    firebase_fake["fallar_create"] = firebase_auth.EmailAlreadyExistsError("existe", None)
    res = await client.post("/v1/auth/bootstrap", json=_BODY)
    assert res.status_code == 409
    assert res.json()["error"]["codigo"] == "CORREO_DUPLICADO"


async def test_bootstrap_limpia_huerfano_si_falla_local(client: AsyncClient, firebase_fake: dict, con_token: None, monkeypatch) -> None:
    # Forzar fallo del registro local DESPUÉS de crear la cuenta en Firebase.
    import app.api.v1.auth_bootstrap as mod

    async def crear_explota(*a, **k):
        raise RuntimeError("fallo BD simulado")

    monkeypatch.setattr(mod.usuarios_repo, "crear", crear_explota)
    res = await client.post("/v1/auth/bootstrap", json=_BODY)
    assert res.status_code == 500
    assert firebase_fake["borradas"] == ["uid-fake-1"]  # se limpió el huérfano
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

Run: `.venv/bin/python -m pytest tests/test_auth_bootstrap.py -v`
Expected: FAIL — las rutas no existen (404) / `ImportError` de `bootstrap_admin_token`.

- [ ] **Step 3: Agregar `bootstrap_admin_token` a Settings**

En `app/core/config.py`, dentro de `class Settings`, junto a las otras variables (p. ej. tras `cors_origins`):

```python
    # Token de un solo uso para el signup de arranque del primer admin (spec 2026-07-29).
    # Vacío = bootstrap deshabilitado (fail-closed). Poner un valor largo y aleatorio solo
    # durante el alta inicial; una vez creado el admin, puede quitarse del entorno.
    bootstrap_admin_token: str = ""
```

En `.env.example` agrega una línea documentada:

```
# Alta del primer administrador (una sola vez tras desplegar con BD vacía). Deja vacío para
# deshabilitar. Genera uno con: python -c "import secrets; print(secrets.token_urlsafe(32))"
BOOTSTRAP_ADMIN_TOKEN=
```

- [ ] **Step 4: Agregar `contar()` al repositorio de usuarios**

En `app/repositories/usuarios.py`: cambia el import de sqlalchemy a `from sqlalchemy import func, select` y agrega:

```python
async def contar(db: AsyncSession) -> int:
    total = await db.scalar(select(func.count()).select_from(Usuario))
    return int(total or 0)
```

- [ ] **Step 5: Agregar los schemas**

En `app/api/v1/schemas.py` (asegúrate de que `EmailStr` y `Field` estén importados de pydantic; `EmailStr` ya se usa en `UsuarioCrearIn`):

```python
class BootstrapStatusOut(BaseModel):
    needs_bootstrap: bool


class BootstrapAdminIn(BaseModel):
    correo: EmailStr
    nombre: str
    password: str = Field(min_length=8)
    token: str
```

- [ ] **Step 6: Crear el router**

Crea `app/api/v1/auth_bootstrap.py`:

```python
"""Signup de arranque del primer administrador (bootstrap) — spec 2026-07-29.

Excepción explícita a RF-AUTH-02 ("sin auto-registro"), acotada al primer admin: estos endpoints son
PÚBLICOS (sin Depends de auth, porque aún no puede existir un token) y solo operan mientras `usuarios`
esté vacía. Protegidos por un token de arranque del servidor (BOOTSTRAP_ADMIN_TOKEN).
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from firebase_admin import auth as firebase_auth
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.v1.schemas import BootstrapAdminIn, BootstrapStatusOut, UsuarioOut
from app.core.config import get_settings
from app.core.security import firebase_app
from app.models.enums import RolGlobal
from app.repositories import usuarios as usuarios_repo
from app.services import bitacora

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/bootstrap-status", response_model=BootstrapStatusOut)
async def bootstrap_status(db: AsyncSession = Depends(get_db)) -> BootstrapStatusOut:
    return BootstrapStatusOut(needs_bootstrap=(await usuarios_repo.contar(db)) == 0)


@router.post("/bootstrap", status_code=status.HTTP_201_CREATED, response_model=UsuarioOut)
async def bootstrap_admin(body: BootstrapAdminIn, db: AsyncSession = Depends(get_db)) -> UsuarioOut:
    token_servidor = get_settings().bootstrap_admin_token
    if not token_servidor:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail={"codigo": "BOOTSTRAP_DESHABILITADO", "mensaje": "El alta de arranque no está habilitada en este servidor."})
    if not secrets.compare_digest(body.token, token_servidor):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail={"codigo": "TOKEN_INVALIDO", "mensaje": "Token de arranque inválido."})
    if await usuarios_repo.contar(db) != 0:
        raise HTTPException(status.HTTP_409_CONFLICT, detail={"codigo": "BOOTSTRAP_YA_REALIZADO", "mensaje": "Ya existe al menos un usuario; el alta de arranque no está disponible."})
    if await usuarios_repo.por_correo(db, body.correo):
        raise HTTPException(status.HTTP_409_CONFLICT, detail={"codigo": "CORREO_DUPLICADO", "mensaje": "Ya existe un usuario con ese correo."})

    try:
        cuenta = firebase_auth.create_user(email=body.correo, password=body.password, email_verified=False, app=firebase_app())
    except firebase_auth.EmailAlreadyExistsError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail={"codigo": "CORREO_DUPLICADO", "mensaje": "Ya existe una cuenta con ese correo en Firebase."}) from exc

    try:
        usuario = await usuarios_repo.crear(db, firebase_uid=cuenta.uid, correo=body.correo, nombre=body.nombre, rol_global=RolGlobal.ADMIN)
        await bitacora.registrar(db, actor=body.correo, accion="alta_admin_bootstrap", entidad=f"usuario:{usuario.usuario_id}", detalle={"correo": body.correo})
        await db.commit()
    except Exception as exc:  # noqa: BLE001 — no dejar cuenta huérfana en Firebase si el registro local falla
        await db.rollback()
        firebase_auth.delete_user(cuenta.uid, app=firebase_app())
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail={"codigo": "BOOTSTRAP_FALLIDO", "mensaje": "No se pudo completar el alta de arranque."}) from exc

    return UsuarioOut(usuario_id=usuario.usuario_id, correo=usuario.correo, nombre=usuario.nombre, rol_global=usuario.rol_global.value, activo=usuario.activo)
```

- [ ] **Step 7: Montar el router**

En `app/api/v1/router.py`: agrega `auth_bootstrap` al import `from app.api.v1 import ...` y añade (arriba de los demás, para que quede visible):

```python
router.include_router(auth_bootstrap.router)
```

- [ ] **Step 8: Correr los tests para verificar que pasan**

Run: `.venv/bin/python -m pytest tests/test_auth_bootstrap.py -v`
Expected: PASS (8 tests).

Nota: si `firebase_auth.EmailAlreadyExistsError("existe", None)` no acepta esos argumentos en la versión instalada de `firebase-admin`, ajusta la construcción en el test (p. ej. solo el mensaje) — el objetivo es que el `except` del router la capture.

- [ ] **Step 9: Regresión + mypy**

Run: `.venv/bin/python -m pytest tests/test_usuarios* tests/test_auth.py -v` (no romper auth existente) y `.venv/bin/python -m mypy app`
Expected: verde; mypy 0 errores.

- [ ] **Step 10: Commit**

```bash
git add app/api/v1/auth_bootstrap.py tests/test_auth_bootstrap.py app/core/config.py .env.example app/repositories/usuarios.py app/api/v1/schemas.py app/api/v1/router.py
git commit -m "feat: Endpoints de signup de arranque del primer admin (bootstrap)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Frontend — ApiClient (estadoBootstrap, crearAdminBootstrap)

**Files:**
- Modify: `apps/web/src/lib/api.ts`, `apps/web/src/lib/api.http.ts`, `apps/web/src/lib/api.mock.ts`

**Interfaces:**
- Produces (en `ApiClient`):
  - `estadoBootstrap(): Promise<{ needs_bootstrap: boolean }>`
  - `crearAdminBootstrap(body: { correo: string; nombre: string; password: string; token: string }): Promise<void>`

- [ ] **Step 1: Firmas en `api.ts`**

En `apps/web/src/lib/api.ts`, agrega a la interfaz `ApiClient` (cerca de `me()`):

```typescript
  estadoBootstrap(): Promise<{ needs_bootstrap: boolean }>;
  crearAdminBootstrap(body: { correo: string; nombre: string; password: string; token: string }): Promise<void>;
```

- [ ] **Step 2: Implementación HTTP en `api.http.ts`**

En `apps/web/src/lib/api.http.ts`:

1. Agrega `'estadoBootstrap'` y `'crearAdminBootstrap'` al `Pick<ApiClient, ...>` (`ApiClientHttpSubset`).
2. Agrega las implementaciones (usan `request`; sin token, y como `getIdToken()` devuelve null sin sesión, `request` omite el header):

```typescript
  estadoBootstrap: () => request<{ needs_bootstrap: boolean }>(`/v1/auth/bootstrap-status`),
  crearAdminBootstrap: (body) => request<void>(`/v1/auth/bootstrap`, { method: 'POST', body: JSON.stringify(body) }),
```

- [ ] **Step 3: Implementación mock en `api.mock.ts`**

En `apps/web/src/lib/api.mock.ts`, agrega al objeto `apiMock` (el mock ya trae un admin `dgarcia@planjuarez.org`, así que el sistema ya está "bootstrapeado"):

```typescript
  estadoBootstrap: async () => ({ needs_bootstrap: false }),
  crearAdminBootstrap: async () => { throw new ApiError(409, 'BOOTSTRAP_YA_REALIZADO', 'El mock ya tiene un administrador.'); },
```

(Asegúrate de que `ApiError` esté importado en `api.mock.ts`; si no, impórtalo de `./api`.)

- [ ] **Step 4: Verificar tipos y lint**

Run: `cd apps/web && npm run typecheck && npm run lint`
Expected: sin errores nuevos.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/lib/api.ts apps/web/src/lib/api.http.ts apps/web/src/lib/api.mock.ts
git commit -m "feat(web): ApiClient para el signup de arranque (estado + alta admin)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Frontend — SignupPage

**Files:**
- Create: `apps/web/src/features/auth/SignupPage.tsx`

**Interfaces:**
- Consumes: `api.crearAdminBootstrap` (Task 2), `useAuth` (para `needsBootstrap`, agregado en Task 4 — ver nota), `ApiError` (`@/lib/api`), `useNavigate` (`react-router`), `Button`, `useToast`.

**Nota de orden:** `useAuth().needsBootstrap` lo agrega la Task 4. Para que esta tarea compile por sí sola, la guarda que usa `needsBootstrap` se puede omitir aquí y añadir en Task 4, O implementar Task 3 y 4 juntas. Si se hacen por separado, en esta tarea NO referencies `needsBootstrap` todavía (solo el formulario + submit + redirect); la guarda se añade en Task 4.

- [ ] **Step 1: Crear `SignupPage.tsx`**

Crea `apps/web/src/features/auth/SignupPage.tsx` (mismo estilo visual que `LoginPage.tsx`):

```tsx
// Signup de arranque del primer administrador (spec 2026-07-29). Solo se muestra cuando la BD no tiene
// usuarios; crea la cuenta Firebase (con contraseña) + el registro local admin vía POST /v1/auth/bootstrap.
import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router';
import { Button } from '@/components/ui/Button';
import { useToast } from '@/components/ui/ToastProvider';
import { ApiError } from '@/lib/api';
import { api } from '@/lib/client';

const ERROR_MENSAJE: Record<string, string> = {
  TOKEN_INVALIDO: 'El token de arranque es incorrecto.',
  CORREO_DUPLICADO: 'Ya existe una cuenta con ese correo.',
  BOOTSTRAP_YA_REALIZADO: 'El administrador ya fue creado. Inicia sesión.',
  BOOTSTRAP_DESHABILITADO: 'El alta de arranque no está habilitada en el servidor.',
};

export function SignupPage() {
  const navigate = useNavigate();
  const { toast } = useToast();
  const [correo, setCorreo] = useState('');
  const [nombre, setNombre] = useState('');
  const [password, setPassword] = useState('');
  const [confirmar, setConfirmar] = useState('');
  const [token, setToken] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (password !== confirmar) {
      setError('Las contraseñas no coinciden.');
      return;
    }
    setEnviando(true);
    try {
      await api.crearAdminBootstrap({ correo, nombre, password, token });
      toast('Administrador creado. Inicia sesión con tus credenciales.', 'ok');
      navigate('/login', { replace: true });
    } catch (err) {
      if (err instanceof ApiError) setError(ERROR_MENSAJE[err.codigo] ?? err.mensaje);
      else setError('No se pudo completar el alta.');
    } finally {
      setEnviando(false);
    }
  }

  return (
    <div className="min-h-screen grid place-items-center bg-bg p-8">
      <div className="w-full max-w-[420px] flex flex-col gap-6">
        <div className="flex items-center gap-3">
          <div className="size-10 rounded-lg bg-primary text-white grid place-items-center font-bold text-[15px] tracking-tight">HC</div>
          <div>
            <div className="text-[22px] font-bold leading-tight">Hub CFDI</div>
            <div className="text-xs text-text-muted">Configuración inicial</div>
          </div>
        </div>

        <div className="bg-surface border border-border rounded-lg p-6 flex flex-col gap-4">
          <div className="text-lg font-semibold">Crear administrador</div>
          <p className="m-0 text-[13px] text-text-muted text-pretty">
            No hay usuarios en el sistema. Crea la cuenta del administrador inicial. Necesitas el
            <span className="font-mono"> BOOTSTRAP_ADMIN_TOKEN</span> definido en el servidor.
          </p>
          <form onSubmit={onSubmit} className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <label htmlFor="su-nombre" className="text-xs font-semibold text-text-muted">Nombre</label>
              <input id="su-nombre" required value={nombre} onChange={(e) => setNombre(e.target.value)} className="h-9 border border-border rounded px-2.5" />
            </div>
            <div className="flex flex-col gap-1.5">
              <label htmlFor="su-mail" className="text-xs font-semibold text-text-muted">Correo</label>
              <input id="su-mail" type="email" required value={correo} onChange={(e) => setCorreo(e.target.value)} className="h-9 border border-border rounded px-2.5" />
            </div>
            <div className="flex flex-col gap-1.5">
              <label htmlFor="su-pass" className="text-xs font-semibold text-text-muted">Contraseña (mín. 8)</label>
              <input id="su-pass" type="password" required minLength={8} autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} className="h-9 border border-border rounded px-2.5" />
            </div>
            <div className="flex flex-col gap-1.5">
              <label htmlFor="su-pass2" className="text-xs font-semibold text-text-muted">Confirmar contraseña</label>
              <input id="su-pass2" type="password" required autoComplete="new-password" value={confirmar} onChange={(e) => setConfirmar(e.target.value)} className="h-9 border border-border rounded px-2.5" />
            </div>
            <div className="flex flex-col gap-1.5">
              <label htmlFor="su-token" className="text-xs font-semibold text-text-muted">Token de arranque</label>
              <input id="su-token" required value={token} onChange={(e) => setToken(e.target.value)} className="h-9 border border-border rounded px-2.5 font-mono" />
            </div>
            {error && (
              <div role="alert" className="bg-danger-soft text-danger rounded-md px-2.5 py-2 text-[13px] font-medium">{error}</div>
            )}
            <Button type="submit" loading={enviando} className="justify-center">Crear administrador</Button>
          </form>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verificar tipos y lint**

Run: `cd apps/web && npm run typecheck && npm run lint`
Expected: sin errores nuevos. (Confirma que `ApiError` expone `.codigo` y `.mensaje` — lo usa `LoginPage`/otros; si el campo se llama distinto, ajústalo.)

- [ ] **Step 3: Commit**

```bash
git add apps/web/src/features/auth/SignupPage.tsx
git commit -m "feat(web): Pantalla de signup de arranque del administrador

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Frontend — AuthContext + enrutado del bootstrap

**Files:**
- Modify: `apps/web/src/auth/AuthContext.tsx`, `apps/web/src/App.tsx`, `apps/web/src/features/auth/LoginPage.tsx`, `apps/web/src/features/auth/SignupPage.tsx`

**Interfaces:**
- Consumes: `api.estadoBootstrap` (Task 2), `SignupPage` (Task 3).
- Produces: `useAuth().needsBootstrap: boolean | null`.

- [ ] **Step 1: `needsBootstrap` en AuthContext**

En `apps/web/src/auth/AuthContext.tsx`:

1. En la interfaz `AuthApi`, agrega: `needsBootstrap: boolean | null;`
2. En `AuthProvider`, agrega el estado y el fetch al montar:

```typescript
  const [needsBootstrap, setNeedsBootstrap] = useState<boolean | null>(null);

  useEffect(() => {
    api.estadoBootstrap()
      .then((r) => setNeedsBootstrap(r.needs_bootstrap))
      .catch(() => setNeedsBootstrap(false)); // ante fallo, no bloquear el login
  }, []);
```

3. En el `value` del provider, agrega `needsBootstrap`.

- [ ] **Step 2: Ruta `/bootstrap` en `App.tsx`**

En `apps/web/src/App.tsx`:
1. Importa: `import { SignupPage } from '@/features/auth/SignupPage';`
2. Agrega la ruta pública junto a `/login`:

```tsx
              <Route path="/login" element={<LoginPage />} />
              <Route path="/bootstrap" element={<SignupPage />} />
```

- [ ] **Step 3: Redirección en `LoginPage`**

En `apps/web/src/features/auth/LoginPage.tsx`, al inicio del componente (antes del `if (usuario)`):

```tsx
  const { firebaseConfigured, usuario, loginError, login, needsBootstrap } = useAuth();
  // ... (los useState existentes)
  if (needsBootstrap === null) return null;                    // aún cargando el estado de bootstrap
  if (needsBootstrap) return <Navigate to="/bootstrap" replace />;
  if (usuario) return <Navigate to="/empresas" replace />;
```

(`Navigate` ya está importado en `LoginPage`.)

- [ ] **Step 4: Guarda en `SignupPage`**

En `apps/web/src/features/auth/SignupPage.tsx`, añade la guarda usando `useAuth` (ahora sí existe `needsBootstrap`):
1. Importa: `import { Navigate } from 'react-router';` y `import { useAuth } from '@/auth/AuthContext';`
2. Al inicio del componente:

```tsx
  const { needsBootstrap } = useAuth();
  if (needsBootstrap === false) return <Navigate to="/login" replace />;
```

- [ ] **Step 5: Verificar tipos y lint**

Run: `cd apps/web && npm run typecheck && npm run lint`
Expected: sin errores nuevos.

- [ ] **Step 6: Verificación manual (con backend + front arriba)**

Con la BD real vacía de usuarios y `BOOTSTRAP_ADMIN_TOKEN` puesto en el `.env` del backend:
1. Abrir la app → debe redirigir a `/bootstrap` (SignupPage), no a `/login`.
2. Enviar el formulario con el token correcto → toast de éxito → redirige a `/login`.
3. Iniciar sesión con el correo/contraseña recién creados → entra como admin.
4. Recargar / abrir `/bootstrap` de nuevo → como ya hay un usuario, redirige a `/login`.
5. (negativo) Token incorrecto → mensaje de error, no crea nada.

(Nota: la verificación 2-3 crea una cuenta real en Firebase; hazla contra el proyecto Firebase de prueba, no el de producción, salvo que sea el alta real de producción.)

- [ ] **Step 7: Commit**

```bash
git add apps/web/src/auth/AuthContext.tsx apps/web/src/App.tsx apps/web/src/features/auth/LoginPage.tsx apps/web/src/features/auth/SignupPage.tsx
git commit -m "feat(web): Enrutado del signup de arranque (needsBootstrap + guardas)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review (hecho al escribir el plan)

- **Cobertura del spec:** §4.1 config → Task 1 Step 3; §4.2 repo.contar → Task 1 Step 4; §4.3 endpoints + orden de validación + huérfano → Task 1 Step 6; §4.4 schemas → Task 1 Step 5; §4.5 montaje → Task 1 Step 7; §5.1 ApiClient → Task 2; §5.2 AuthContext+enrutado → Task 4; §5.3 SignupPage → Task 3; §6 pruebas backend → Task 1 Step 1 (8 tests), front → typecheck/lint/manual (Tasks 2-4); §7 verificación en vivo → Task 4 Step 6.
- **Sin placeholders:** todo el código está escrito.
- **Consistencia de tipos:** `bootstrap_admin_token` (config) usado en el router; `contar()` definido en Task 1 Step 4 y usado en el router y los tests; `BootstrapStatusOut`/`BootstrapAdminIn` definidos en Step 5 y usados en Step 6; `estadoBootstrap`/`crearAdminBootstrap` declarados en Task 2 y consumidos en Tasks 3-4; `needsBootstrap` producido en Task 4 Step 1 y consumido en LoginPage/SignupPage; códigos de error (`TOKEN_INVALIDO`, `CORREO_DUPLICADO`, `BOOTSTRAP_YA_REALIZADO`, `BOOTSTRAP_DESHABILITADO`) idénticos entre el router (Task 1) y el mapeo del front (Task 3).
- **Dependencia entre Task 3 y 4:** anotada — `SignupPage` se crea en Task 3 sin la guarda de `needsBootstrap`, que se añade en Task 4 Step 4 (cuando el campo ya existe en el contexto).
