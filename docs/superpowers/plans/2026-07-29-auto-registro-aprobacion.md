# Auto-registro con aprobación + recuperación de contraseña — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permitir auto-registro de usuarios (quedan pendientes de aprobación, con rol `consulta` y sin acceso hasta que un admin apruebe), avisar al admin por correo, y agregar recuperación de contraseña (Firebase nativo).

**Architecture:** Campo `aprobado` nuevo en `usuarios`; la puerta `_usuario_activo_por_token` exige `aprobado AND activo` con códigos de error precisos. Auto-registro = Firebase en el cliente (`createUserWithEmailAndPassword`) + `POST /v1/auth/registro` (autenticado, crea el local pendiente y avisa a admins por SMTP best-effort). Aprobación/rechazo desde `PATCH`/`DELETE /v1/usuarios/{id}` (admin). Reset de contraseña 100% Firebase cliente (`sendPasswordResetEmail`).

**Tech Stack:** FastAPI + SQLAlchemy async + Alembic + Firebase Admin SDK + pytest. React + react-router + Firebase Auth cliente + TypeScript. Sin test unitario frontend (verificación `tsc`/`eslint` + manual).

## Global Constraints

- **Regla de acceso:** un usuario opera solo si `aprobado=true` Y `activo=true`.
- **Códigos de error de la puerta** (403, envelope `{codigo,mensaje}`): `NO_REGISTRADO`, `CUENTA_PENDIENTE`, `CUENTA_INACTIVA`.
- **Solo el auto-registro** crea `aprobado=false`, `rol_global=consulta`. Bootstrap y `POST /v1/usuarios` (alta admin) crean `aprobado=true`.
- **Aprobar solo activa** (`aprobado=true`); NO otorga empresas.
- **Correo del auto-registro es autoritativo desde Firebase** (`firebase_auth.get_user(uid).email`), no del body.
- **Aviso a admins es best-effort:** si el SMTP no está o falla, se loguea y NO rompe el registro.
- **Reset de contraseña:** Firebase cliente (`sendPasswordResetEmail`), sin backend.
- **Envelope de error backend:** `HTTPException(status, detail={"codigo","mensaje"})` (lo envuelve `app/main.py` en `{"error":{...}}`).
- **Migración:** se corre desde el HOST con `.venv/bin/alembic` (lee `.env` → `localhost:3308`); el contenedor tiene migraciones stale, NO usar `docker compose exec api alembic`. Head actual real = `707ce82c3acb`.
- **Tests backend:** usan testcontainers con `create_all` desde el modelo (la migración NO es requisito para los tests; el modelo sí). Firebase Admin SDK y SMTP siempre mockeados; nunca red real. `asyncio_mode = "auto"` — no declarar `pytestmark` a nivel módulo.
- **Commits:** rama `feat/auto-registro-aprobacion`. Cada commit termina con:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`

---

## File Structure

**Nuevos:** `alembic/versions/<rev>_add_usuarios_aprobado.py`, `apps/web/src/features/auth/RegistroPage.tsx`, `apps/web/src/features/auth/RecuperarPage.tsx`, `tests/test_auth_registro.py`.

**Modificados:** `app/models/usuario.py`, `app/api/deps.py`, `app/repositories/usuarios.py`, `app/api/v1/schemas.py`, `app/api/v1/auth_bootstrap.py`, `app/api/v1/usuarios.py`, `app/services/notificaciones.py`, y frontend `api.ts`/`api.http.ts`/`api.mock.ts`/`AuthContext.tsx`/`App.tsx`/`LoginPage.tsx`/`features/admin/UsuariosPage.tsx`.

---

## Task 1: Backend foundation — campo `aprobado`, migración, puerta de acceso, repo, schemas

**Files:** Modify `app/models/usuario.py`, `app/api/deps.py`, `app/repositories/usuarios.py`, `app/api/v1/schemas.py`, `app/api/v1/auth_bootstrap.py`, `app/api/v1/usuarios.py`; Create `alembic/versions/<rev>_add_usuarios_aprobado.py`; Test `tests/test_auth_registro.py`.

**Interfaces:**
- Produces: `Usuario.aprobado: bool`; `usuarios_repo.crear(..., aprobado: bool = False)`, `usuarios_repo.actualizar(..., aprobado: bool | None = None)`, `usuarios_repo.eliminar(db, usuario)`, `usuarios_repo.contar_admins_activos(db) -> int`, `usuarios_repo.correos_admins(db) -> list[str]`; `deps.uid_del_token`; puerta con códigos; `UsuarioOut.aprobado`, `UsuarioPatchIn.aprobado`.

- [ ] **Step 1: Escribir los tests que fallan** (puerta de acceso + aprobado=True en bootstrap/alta-admin)

Crea `tests/test_auth_registro.py`:

```python
"""Auto-registro con aprobación (spec 2026-07-29). Firebase Admin SDK y SMTP mockeados; el fixture `db`
recrea tablas por test desde el modelo (incluye la columna `aprobado`)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import RolGlobal
from app.models.usuario import Usuario
from app.repositories import usuarios as usuarios_repo
from tests.factories import crear_usuario


async def _usuario(db: AsyncSession, *, uid: str, correo: str, rol=RolGlobal.CONSULTA, activo=True, aprobado=True) -> Usuario:
    u = await usuarios_repo.crear(db, firebase_uid=uid, correo=correo, nombre="N", rol_global=rol, aprobado=aprobado)
    u.activo = activo
    await db.commit()
    return u


async def test_puerta_pendiente_403_codigo(client: AsyncClient, db: AsyncSession) -> None:
    await _usuario(db, uid="uid-pend", correo="pend@example.com", aprobado=False)
    res = await client.get("/v1/me", headers={"Authorization": "Bearer uid-pend"})
    assert res.status_code == 403
    assert res.json()["error"]["codigo"] == "CUENTA_PENDIENTE"


async def test_puerta_inactiva_403_codigo(client: AsyncClient, db: AsyncSession) -> None:
    await _usuario(db, uid="uid-off", correo="off@example.com", aprobado=True, activo=False)
    res = await client.get("/v1/me", headers={"Authorization": "Bearer uid-off"})
    assert res.status_code == 403
    assert res.json()["error"]["codigo"] == "CUENTA_INACTIVA"


async def test_puerta_no_registrado_403_codigo(client: AsyncClient, db: AsyncSession) -> None:
    res = await client.get("/v1/me", headers={"Authorization": "Bearer uid-fantasma"})
    assert res.status_code == 403
    assert res.json()["error"]["codigo"] == "NO_REGISTRADO"


async def test_usuario_aprobado_activo_pasa(client: AsyncClient, db: AsyncSession) -> None:
    await _usuario(db, uid="uid-ok", correo="ok@example.com", aprobado=True, activo=True)
    res = await client.get("/v1/me", headers={"Authorization": "Bearer uid-ok"})
    assert res.status_code == 200


async def test_contar_admins_activos(db: AsyncSession) -> None:
    await _usuario(db, uid="a1", correo="a1@example.com", rol=RolGlobal.ADMIN)
    await _usuario(db, uid="a2", correo="a2@example.com", rol=RolGlobal.ADMIN, activo=False)  # no cuenta
    await _usuario(db, uid="c1", correo="c1@example.com", rol=RolGlobal.CONSULTA)              # no cuenta
    assert await usuarios_repo.contar_admins_activos(db) == 1
```

Nota: `crear_usuario` de `tests/factories.py` puede no aceptar `aprobado`; los tests de arriba usan `usuarios_repo.crear` directo. Si `factories.crear_usuario` se usa en otros tests y ahora el modelo exige `aprobado`, dale `default` en el modelo (Step 3) para no romperlos.

- [ ] **Step 2: Correr y ver que fallan**

Run: `.venv/bin/python -m pytest tests/test_auth_registro.py -v`
Expected: FAIL — la columna/gate/`crear(aprobado=)`/`contar_admins_activos` no existen.

- [ ] **Step 3: Modelo — columna `aprobado`**

En `app/models/usuario.py`, junto a `activo`:

```python
    aprobado: Mapped[bool] = mapped_column(TINYINT(1), nullable=False, default=False)
```

- [ ] **Step 4: Repositorio**

En `app/repositories/usuarios.py`:

```python
async def crear(db: AsyncSession, *, firebase_uid: str, correo: str, nombre: str, rol_global: RolGlobal, aprobado: bool = False) -> Usuario:
    usuario = Usuario(firebase_uid=firebase_uid, correo=correo, nombre=nombre, rol_global=rol_global, activo=True, aprobado=aprobado)
    db.add(usuario)
    await db.flush()
    return usuario


async def actualizar(db: AsyncSession, usuario: Usuario, *, activo: bool | None = None, rol_global: RolGlobal | None = None, aprobado: bool | None = None) -> Usuario:
    if activo is not None:
        usuario.activo = activo
    if rol_global is not None:
        usuario.rol_global = rol_global
    if aprobado is not None:
        usuario.aprobado = aprobado
    await db.flush()
    return usuario


async def eliminar(db: AsyncSession, usuario: Usuario) -> None:
    await db.delete(usuario)
    await db.flush()


async def contar_admins_activos(db: AsyncSession) -> int:
    total = await db.scalar(
        select(func.count()).select_from(Usuario).where(Usuario.rol_global == RolGlobal.ADMIN, Usuario.activo.is_(True), Usuario.aprobado.is_(True))
    )
    return int(total or 0)


async def correos_admins(db: AsyncSession) -> list[str]:
    filas = await db.scalars(
        select(Usuario.correo).where(Usuario.rol_global == RolGlobal.ADMIN, Usuario.activo.is_(True), Usuario.aprobado.is_(True))
    )
    return [c for c in filas.all() if c]
```

- [ ] **Step 5: Puerta de acceso + `uid_del_token` en `deps.py`**

Reemplaza `_usuario_activo_por_token` y agrega `uid_del_token`:

```python
async def _usuario_activo_por_token(authorization: str | None, db: AsyncSession) -> Usuario:
    uid = verificar_id_token(authorization)
    usuario = await db.scalar(select(Usuario).where(Usuario.firebase_uid == uid))
    if usuario is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail={"codigo": "NO_REGISTRADO", "mensaje": "No existe un usuario de Hub CFDI para esta cuenta."})
    if not usuario.aprobado:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail={"codigo": "CUENTA_PENDIENTE", "mensaje": "Tu cuenta está pendiente de aprobación por un administrador."})
    if not usuario.activo:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail={"codigo": "CUENTA_INACTIVA", "mensaje": "Tu cuenta está desactivada."})
    return usuario


async def uid_del_token(authorization: str | None = Header(default=None)) -> str:
    """Solo verifica el token de Firebase y devuelve el uid — para endpoints que operan ANTES de que
    exista/esté aprobado el usuario local (auto-registro)."""
    return verificar_id_token(authorization)
```

(`Header` ya está importado en `deps.py`.)

- [ ] **Step 6: Schemas — exponer/aceptar `aprobado`**

En `app/api/v1/schemas.py`:
- `UsuarioOut`: agrega `aprobado: bool`.
- `UsuarioPatchIn`: agrega `aprobado: bool | None = None`.
(`UsuarioAdminOut` hereda de `UsuarioOut`, así que ya lo expone.)

- [ ] **Step 7: Las construcciones de `UsuarioOut` deben pasar `aprobado`**

`UsuarioOut(...)` ahora exige `aprobado`. Actualiza cada construcción:
- `app/api/v1/auth_bootstrap.py` (`bootstrap_admin` return): agrega `aprobado=usuario.aprobado`. Además, en la llamada a `usuarios_repo.crear(...)` del bootstrap, agrega `aprobado=True`.
- `app/api/v1/usuarios.py` (`crear_usuario` y `actualizar_usuario` returns): agrega `aprobado=usuario.aprobado`. En `crear_usuario`, la llamada a `usuarios_repo.crear(...)` agrega `aprobado=True` (alta directa por admin ya queda aprobada). En `listar_usuarios`, `UsuarioAdminOut(...)` agrega `aprobado=u.aprobado`.

- [ ] **Step 8: Correr los tests de esta tarea + regresión + mypy**

Run: `.venv/bin/python -m pytest tests/test_auth_registro.py tests/test_auth.py tests/test_idor.py tests/test_metadata_export.py -v`
(el último incluye los tests del bootstrap — deben seguir verdes con `aprobado=True`.)
Expected: PASS. Luego `.venv/bin/python -m mypy app` → 0 errores.

- [ ] **Step 9: Crear y aplicar la migración**

Desde el HOST (no el contenedor):
```bash
.venv/bin/alembic heads          # confirma el head actual (esperado 707ce82c3acb)
.venv/bin/alembic revision -m "add usuarios aprobado"   # crea el archivo con revision id + down_revision correctos
```
Edita el archivo generado en `alembic/versions/`:
```python
from alembic import op
from sqlalchemy.dialects import mysql

def upgrade() -> None:
    op.add_column("usuarios", sa.Column("aprobado", mysql.TINYINT(1), nullable=False, server_default="0"))
    op.execute("UPDATE usuarios SET aprobado = 1")  # las filas existentes ya son legítimas

def downgrade() -> None:
    op.drop_column("usuarios", "aprobado")
```
(Asegúrate de que `import sqlalchemy as sa` esté en el archivo; el stub de alembic lo incluye.)

Aplica y verifica:
```bash
.venv/bin/alembic upgrade head
docker compose exec -T mysql mysql -uroot -phub_cfdi_root hub_cfdi -e "SHOW COLUMNS FROM usuarios LIKE 'aprobado';"
```
Expected: la columna `aprobado` existe.

- [ ] **Step 10: Commit**

```bash
git add app/models/usuario.py app/api/deps.py app/repositories/usuarios.py app/api/v1/schemas.py app/api/v1/auth_bootstrap.py app/api/v1/usuarios.py alembic/versions/ tests/test_auth_registro.py
git commit -m "feat: Campo aprobado + puerta de acceso con estados (pendiente/inactivo)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Backend — endpoint de auto-registro, aviso a admins, aprobación y rechazo

**Files:** Modify `app/api/v1/auth_bootstrap.py` (endpoint `/registro`), `app/api/v1/schemas.py` (`RegistroIn`/`RegistroOut`), `app/services/notificaciones.py` (`enviar_aviso_registro`), `app/api/v1/usuarios.py` (`PATCH` aprobado + `DELETE`); Test `tests/test_auth_registro.py`.

**Interfaces:**
- Consumes: `deps.uid_del_token`, `usuarios_repo.crear/eliminar/contar_admins_activos/correos_admins`, `notificaciones.resolver_credenciales/enviar_aviso_registro` (Task 1 + este).
- Produces: `POST /v1/auth/registro`; `PATCH /v1/usuarios/{id}` con `aprobado`; `DELETE /v1/usuarios/{id}`.

- [ ] **Step 1: Escribir los tests que fallan**

Agrega a `tests/test_auth_registro.py` (helpers de Task 1 disponibles). Firebase Admin SDK mockeado en el módulo del router:

```python
class _CuentaFake:
    def __init__(self, uid, email):
        self.uid = uid
        self.email = email


@pytest.fixture()
def firebase_reg(monkeypatch):
    import app.api.v1.auth_bootstrap as mod
    estado = {"emails": {"uid-nuevo": "nuevo@example.com"}, "borradas": []}
    monkeypatch.setattr(mod, "firebase_app", lambda: None)
    monkeypatch.setattr(mod.firebase_auth, "get_user", lambda uid, **k: _CuentaFake(uid, estado["emails"].get(uid, f"{uid}@example.com")))
    monkeypatch.setattr(mod.firebase_auth, "delete_user", lambda uid, **k: estado["borradas"].append(uid))
    return estado


@pytest.fixture()
def smtp_espia(monkeypatch):
    import app.api.v1.auth_bootstrap as mod
    envios = []
    monkeypatch.setattr(mod.notificaciones, "resolver_credenciales", _cred_fake := (lambda db: _Cred()))
    monkeypatch.setattr(mod.notificaciones, "enviar_aviso_registro", lambda destinos, correo, nombre, cred: envios.append((destinos, correo)))
    return envios


class _Cred:  # placeholder de SmtpCredenciales
    pass


async def test_registro_crea_pendiente_consulta(client, db, firebase_reg, smtp_espia) -> None:
    # un admin aprobado para que haya destinatario del aviso
    await _usuario(db, uid="admin1", correo="admin@example.com", rol=RolGlobal.ADMIN)
    res = await client.post("/v1/auth/registro", json={"nombre": "Nuevo"}, headers={"Authorization": "Bearer uid-nuevo"})
    assert res.status_code == 201, res.text
    u = await usuarios_repo.por_correo(db, "nuevo@example.com")
    assert u is not None and u.rol_global == RolGlobal.CONSULTA and u.aprobado is False
    assert smtp_espia and smtp_espia[0][0] == ["admin@example.com"]  # se avisó al admin


async def test_registro_correo_de_firebase_no_del_body(client, db, firebase_reg) -> None:
    res = await client.post("/v1/auth/registro", json={"nombre": "X", "correo": "otro@intruso.com"}, headers={"Authorization": "Bearer uid-nuevo"})
    assert res.status_code == 201
    assert await usuarios_repo.por_correo(db, "nuevo@example.com") is not None  # ganó el de Firebase
    assert await usuarios_repo.por_correo(db, "otro@intruso.com") is None


async def test_registro_ya_existe_409(client, db, firebase_reg) -> None:
    await _usuario(db, uid="uid-nuevo", correo="nuevo@example.com", aprobado=False)
    res = await client.post("/v1/auth/registro", json={"nombre": "X"}, headers={"Authorization": "Bearer uid-nuevo"})
    assert res.status_code == 409
    assert res.json()["error"]["codigo"] == "YA_REGISTRADO"


async def test_registro_sin_smtp_no_falla(client, db, firebase_reg, monkeypatch) -> None:
    import app.api.v1.auth_bootstrap as mod
    from app.services.notificaciones import SmtpNoConfiguradoError
    await _usuario(db, uid="admin1", correo="admin@example.com", rol=RolGlobal.ADMIN)
    monkeypatch.setattr(mod.notificaciones, "resolver_credenciales", lambda db: (_ for _ in ()).throw(SmtpNoConfiguradoError("no config")))
    res = await client.post("/v1/auth/registro", json={"nombre": "X"}, headers={"Authorization": "Bearer uid-nuevo"})
    assert res.status_code == 201  # el registro se completa aunque no haya SMTP


async def test_patch_aprobar_activa_acceso(client, db, firebase_reg) -> None:
    admin = await _usuario(db, uid="admin1", correo="admin@example.com", rol=RolGlobal.ADMIN)
    pend = await _usuario(db, uid="uid-p", correo="p@example.com", aprobado=False)
    res = await client.patch(f"/v1/usuarios/{pend.usuario_id}", json={"aprobado": True}, headers={"Authorization": "Bearer admin1"})
    assert res.status_code == 200
    await db.refresh(pend)
    assert pend.aprobado is True


async def test_delete_rechaza_y_borra_firebase(client, db, firebase_reg) -> None:
    await _usuario(db, uid="admin1", correo="admin@example.com", rol=RolGlobal.ADMIN)
    pend = await _usuario(db, uid="uid-p", correo="p@example.com", aprobado=False)
    res = await client.delete(f"/v1/usuarios/{pend.usuario_id}", headers={"Authorization": "Bearer admin1"})
    assert res.status_code == 204
    assert await usuarios_repo.por_id(db, pend.usuario_id) is None
    assert firebase_reg["borradas"] == ["uid-p"]


async def test_delete_ultimo_admin_409(client, db, firebase_reg) -> None:
    admin = await _usuario(db, uid="admin1", correo="admin@example.com", rol=RolGlobal.ADMIN)
    res = await client.delete(f"/v1/usuarios/{admin.usuario_id}", headers={"Authorization": "Bearer admin1"})
    assert res.status_code == 409  # no puede eliminarse a sí mismo / último admin
```

Nota: los tests de `smtp_espia` mockean `mod.notificaciones.resolver_credenciales`/`enviar_aviso_registro`, así que el endpoint debe llamar a esas funciones a través de `notificaciones.` (importar el módulo, no las funciones sueltas). Ajusta los mocks si construyes `SmtpCredenciales` real.

- [ ] **Step 2: Correr y ver que fallan**

Run: `.venv/bin/python -m pytest tests/test_auth_registro.py -k "registro or patch_aprobar or delete" -v`
Expected: FAIL (endpoints no existen / no aceptan aprobado).

- [ ] **Step 3: Schemas `RegistroIn`/`RegistroOut`**

En `app/api/v1/schemas.py`:
```python
class RegistroIn(BaseModel):
    nombre: str

class RegistroOut(BaseModel):
    estado: str
```

- [ ] **Step 4: Función de correo en `notificaciones.py`**

Agrega (usa el `_enviar`/`SmtpCredenciales`/`EmailMessage` existentes):
```python
def enviar_aviso_registro(destinos: list[str], solicitante_correo: str, solicitante_nombre: str, credenciales: SmtpCredenciales) -> None:
    mensaje = EmailMessage()
    mensaje["Subject"] = "Hub CFDI — nueva solicitud de acceso"
    mensaje["From"] = credenciales.remitente
    mensaje["To"] = ", ".join(destinos)
    mensaje.set_content(f"{solicitante_nombre} ({solicitante_correo}) solicitó acceso a Hub CFDI.\n\nRevísalo y apruébalo en la sección Usuarios.")
    _enviar(mensaje, credenciales)
```

- [ ] **Step 5: Endpoint `POST /auth/registro` en `auth_bootstrap.py`**

Agrega imports arriba: `from app.api.deps import get_db, uid_del_token`, `from app.api.v1.schemas import RegistroIn, RegistroOut`, `from app.services import notificaciones`, `from app.services.notificaciones import SmtpNoConfiguradoError`, y un `logger = logging.getLogger("app")` (con `import logging`). Luego:

```python
@router.post("/registro", status_code=status.HTTP_201_CREATED, response_model=RegistroOut)
async def registro(body: RegistroIn, uid: str = Depends(uid_del_token), db: AsyncSession = Depends(get_db)) -> RegistroOut:
    try:
        cuenta = firebase_auth.get_user(uid, app=firebase_app())
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail={"codigo": "FIREBASE_ERROR", "mensaje": "No se pudo verificar la cuenta de Firebase."}) from exc
    correo = cuenta.email
    if await usuarios_repo.por_firebase_uid(db, uid) or (correo and await usuarios_repo.por_correo(db, correo)):
        raise HTTPException(status.HTTP_409_CONFLICT, detail={"codigo": "YA_REGISTRADO", "mensaje": "Esta cuenta ya está registrada."})

    usuario = await usuarios_repo.crear(db, firebase_uid=uid, correo=correo or f"{uid}@sin-correo.local", nombre=body.nombre, rol_global=RolGlobal.CONSULTA, aprobado=False)
    await bitacora.registrar(db, actor=correo or uid, accion="auto_registro", entidad=f"usuario:{usuario.usuario_id}", detalle={"correo": correo})
    await db.commit()

    # Aviso a admins — best-effort: nunca rompe el registro.
    try:
        destinos = await usuarios_repo.correos_admins(db)
        if destinos:
            credenciales = await notificaciones.resolver_credenciales(db)
            notificaciones.enviar_aviso_registro(destinos, correo or "", body.nombre, credenciales)
    except SmtpNoConfiguradoError:
        logger.info("registro: SMTP no configurado; no se envió aviso a admins.")
    except Exception:  # noqa: BLE001
        logger.warning("registro: fallo enviando el aviso a admins.", exc_info=True)

    return RegistroOut(estado="pendiente")
```

- [ ] **Step 6: `PATCH` aprobado + `DELETE` en `usuarios.py`**

En `actualizar_usuario` (`PATCH`): pasa `aprobado=body.aprobado` a `usuarios_repo.actualizar(...)` y agrégalo al `detalle` de bitácora.

Agrega el endpoint de rechazo:
```python
@router.delete("/{usuario_id}", status_code=status.HTTP_204_NO_CONTENT)
async def eliminar_usuario(usuario_id: int, admin: Usuario = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> None:
    usuario = await usuarios_repo.por_id(db, usuario_id)
    if usuario is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No encontrado.")
    if usuario.usuario_id == admin.usuario_id:
        raise HTTPException(status.HTTP_409_CONFLICT, detail={"codigo": "NO_AUTO_ELIMINACION", "mensaje": "No puedes eliminar tu propia cuenta."})
    if usuario.rol_global == RolGlobal.ADMIN and await usuarios_repo.contar_admins_activos(db) <= 1:
        raise HTTPException(status.HTTP_409_CONFLICT, detail={"codigo": "ULTIMO_ADMIN", "mensaje": "No puedes eliminar al último administrador."})

    firebase_uid = usuario.firebase_uid
    await usuarios_repo.eliminar(db, usuario)
    await bitacora.registrar(db, actor=admin.correo, accion="eliminar_usuario", entidad=f"usuario:{usuario_id}", detalle={"correo": usuario.correo})
    await db.commit()
    # Borra la cuenta de Firebase best-effort (la eliminación local ya es efectiva).
    try:
        firebase_auth.delete_user(firebase_uid, app=firebase_app())
    except Exception:  # noqa: BLE001
        logger_usuarios.warning("eliminar_usuario: no se pudo borrar la cuenta Firebase %s.", firebase_uid, exc_info=True)
```
Agrega en `usuarios.py`: `import logging`, `logger_usuarios = logging.getLogger("app")`, y asegúrate de que `firebase_app` esté importado (`from app.core.security import firebase_app`).

- [ ] **Step 7: Tests verdes + regresión + mypy**

Run: `.venv/bin/python -m pytest tests/test_auth_registro.py tests/test_metadata_export.py -v` → PASS. `.venv/bin/python -m mypy app` → 0 errores.

- [ ] **Step 8: Commit**

```bash
git add app/api/v1/auth_bootstrap.py app/api/v1/usuarios.py app/api/v1/schemas.py app/services/notificaciones.py tests/test_auth_registro.py
git commit -m "feat: Auto-registro (POST /auth/registro) + aviso a admins + aprobar/rechazar usuarios

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Frontend — ApiClient (registro, aprobar, rechazar) + tipo aprobado

**Files:** Modify `apps/web/src/lib/api.ts`, `apps/web/src/lib/api.http.ts`, `apps/web/src/lib/api.mock.ts`.

**Interfaces:**
- Produces: `registrarUsuario(body: { nombre: string }): Promise<void>`, `actualizarUsuario(id: number, body: { activo?: boolean; rol_global?: Rol; aprobado?: boolean }): Promise<void>`, `eliminarUsuario(id: number): Promise<void>`; `UsuarioAdmin.aprobado: boolean`.

- [ ] **Step 1: `api.ts`**

- En `interface UsuarioAdmin`, agrega `aprobado: boolean;`.
- En la interfaz `ApiClient`, agrega:
```typescript
  registrarUsuario(body: { nombre: string }): Promise<void>;
  actualizarUsuario(id: number, body: { activo?: boolean; rol_global?: Rol; aprobado?: boolean }): Promise<void>;
  eliminarUsuario(id: number): Promise<void>;
```

- [ ] **Step 2: `api.http.ts`**

Agrega los tres nombres al `Pick<ApiClient, ...>` (`ApiClientHttpSubset`) e implementa:
```typescript
  registrarUsuario: (body) => request<void>(`/v1/auth/registro`, { method: 'POST', body: JSON.stringify(body) }),
  actualizarUsuario: (id, body) => request<void>(`/v1/usuarios/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  eliminarUsuario: (id) => request<void>(`/v1/usuarios/${id}`, { method: 'DELETE' }),
```

- [ ] **Step 3: `api.mock.ts`**

- Agrega `aprobado: 1` (o `0`) al `DbUsuario` interface y a las filas seed (los seed existentes → `aprobado: 1`).
- En `listarUsuarios`, incluye `aprobado: !!x.aprobado` en el objeto devuelto.
- Implementa `registrarUsuario` (agrega un usuario mock pendiente), `actualizarUsuario` (muta la fila), `eliminarUsuario` (quita la fila). Mantén el estilo async existente.

- [ ] **Step 4: typecheck + lint**

Run: `cd apps/web && npm run typecheck && npm run lint` → limpio.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/lib/api.ts apps/web/src/lib/api.http.ts apps/web/src/lib/api.mock.ts
git commit -m "feat(web): ApiClient para auto-registro y aprobar/rechazar usuarios

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Frontend — RegistroPage, RecuperarPage, enlaces del login, rutas y UX de pendiente

**Files:** Create `apps/web/src/features/auth/RegistroPage.tsx`, `apps/web/src/features/auth/RecuperarPage.tsx`; Modify `apps/web/src/App.tsx`, `apps/web/src/features/auth/LoginPage.tsx`, `apps/web/src/auth/AuthContext.tsx`.

**Interfaces:** Consumes `api.registrarUsuario` (Task 3), Firebase (`createUserWithEmailAndPassword`, `sendPasswordResetEmail`, `signOut`), `getFirebaseAuth`.

- [ ] **Step 1: `RegistroPage.tsx`**

Crea el componente (estilo de `LoginPage`/`SignupPage`). Flujo:
```tsx
import { createUserWithEmailAndPassword, signOut } from 'firebase/auth';
// ... useState nombre/correo/password/confirmar/error/ok/enviando
// onSubmit:
//   if (password !== confirmar) -> error
//   const auth = getFirebaseAuth(); if (!auth) return;
//   try {
//     await createUserWithEmailAndPassword(auth, correo, password);
//     await api.registrarUsuario({ nombre });
//     await signOut(auth);                       // no dejarlo "logueado" pero pendiente
//     setOk(true);                               // muestra "Cuenta creada, pendiente de aprobación"
//   } catch (e) { mapear auth/email-already-in-use, auth/weak-password, auth/invalid-email, y ApiError 409 YA_REGISTRADO }
```
Muestra, en `ok`, un panel "Cuenta creada. Un administrador debe aprobar tu acceso antes de que puedas entrar." con un enlace a `/login`. Reusa el `FIREBASE_ERROR_MENSAJE` (o define uno local).

- [ ] **Step 2: `RecuperarPage.tsx`**

```tsx
import { sendPasswordResetEmail } from 'firebase/auth';
// form con un input correo; onSubmit:
//   const auth = getFirebaseAuth(); if (!auth) return;
//   try { await sendPasswordResetEmail(auth, correo); setOk(true); }
//   catch { /* mensaje neutro igual */ }
// SIEMPRE muestra el mismo mensaje neutro "Si el correo existe, te enviamos un enlace para restablecer tu contraseña."
```

- [ ] **Step 3: Rutas en `App.tsx`**

Junto a `/login` y `/bootstrap`:
```tsx
              <Route path="/registro" element={<RegistroPage />} />
              <Route path="/recuperar" element={<RecuperarPage />} />
```
(importa ambos componentes.)

- [ ] **Step 4: Enlaces en `LoginPage.tsx`**

Debajo del botón "Entrar", agrega:
```tsx
              <div className="flex justify-between text-[13px]">
                <Link to="/registro" className="text-primary">Crear cuenta</Link>
                <Link to="/recuperar" className="text-primary">¿Olvidaste tu contraseña?</Link>
              </div>
```
(importa `Link` de `react-router`.)

- [ ] **Step 5: UX de pendiente en `AuthContext.tsx`**

En el `catch` de `onAuthStateChanged` (donde hoy setea `loginError` genérico), mapea el código:
```tsx
      } catch (e) {
        const codigo = e instanceof ApiError ? e.codigo : '';
        const msg =
          codigo === 'CUENTA_PENDIENTE' ? 'Tu cuenta está pendiente de aprobación por un administrador.'
          : codigo === 'CUENTA_INACTIVA' ? 'Tu cuenta está desactivada. Contacta al administrador.'
          : 'No existe un usuario de Hub CFDI para este correo en este entorno.';
        setLoginError(msg);
        await signOut(auth);
        setUsuario(null);
      }
```

- [ ] **Step 6: typecheck + lint**

Run: `cd apps/web && npm run typecheck && npm run lint` → limpio.

- [ ] **Step 7: Commit**

```bash
git add apps/web/src/features/auth/RegistroPage.tsx apps/web/src/features/auth/RecuperarPage.tsx apps/web/src/App.tsx apps/web/src/features/auth/LoginPage.tsx apps/web/src/auth/AuthContext.tsx
git commit -m "feat(web): Pantallas de registro y recuperar contraseña + UX de cuenta pendiente

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Frontend — UsuariosPage con aprobación (badges, Aprobar/Rechazar)

**Files:** Modify `apps/web/src/features/admin/UsuariosPage.tsx`.

**Interfaces:** Consumes `api.listarUsuarios` (con `aprobado`), `api.actualizarUsuario`, `api.eliminarUsuario` (Task 3).

- [ ] **Step 1: Estado + mutaciones**

Convierte `UsuariosPage` para usar `useMutation` + `useQueryClient`:
```tsx
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useToast } from '@/components/ui/ToastProvider';
import { Button } from '@/components/ui/Button';
// dentro del componente:
const qc = useQueryClient();
const { toast } = useToast();
const aprobar = useMutation({
  mutationFn: (id: number) => api.actualizarUsuario(id, { aprobado: true }),
  onSuccess: () => { qc.invalidateQueries({ queryKey: ['usuarios'] }); toast('Usuario aprobado', 'ok'); },
  onError: () => toast('No se pudo aprobar', 'error'),
});
const rechazar = useMutation({
  mutationFn: (id: number) => api.eliminarUsuario(id),
  onSuccess: () => { qc.invalidateQueries({ queryKey: ['usuarios'] }); toast('Solicitud rechazada', 'ok'); },
  onError: () => toast('No se pudo rechazar', 'error'),
});
```

- [ ] **Step 2: Badge de estado + columna de acciones**

Agrega una columna "Estado" con un badge derivado:
- `!u.aprobado` → "Pendiente" (naranja), `u.aprobado && !u.activo` → "Inactivo" (gris), else "Activo" (verde).
Y una columna "Acciones": si `!u.aprobado`, botones **Aprobar** (`aprobar.mutate(u.usuario_id)`) y **Rechazar** (con `confirm(...)` → `rechazar.mutate(u.usuario_id)`). Muestra un contador de pendientes arriba de la tabla: `usuarios.filter(u => !u.aprobado).length`.

- [ ] **Step 3: typecheck + lint**

Run: `cd apps/web && npm run typecheck && npm run lint` → limpio.

- [ ] **Step 4: Verificación manual (usuario, con backend + front arriba)**

1. Cerrar sesión / abrir en incógnito → `/login` → "Crear cuenta" → registrarse → mensaje "pendiente de aprobación"; al intentar entrar, "pendiente".
2. Como admin, ir a Usuarios → aparece el pendiente con badge y contador → **Aprobar** → el usuario ya puede iniciar sesión (sin ver empresas hasta darle permisos).
3. **Rechazar** otro registro → desaparece y se borra su cuenta de Firebase.
4. "¿Olvidaste tu contraseña?" → escribir correo → llega el correo de reset de Firebase.
(Crea cuentas reales en Firebase — usar el proyecto de prueba.)

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/features/admin/UsuariosPage.tsx
git commit -m "feat(web): Gestión de aprobación de usuarios en el panel de admin

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review (hecho al escribir el plan)

- **Cobertura del spec:** §3 modelo/puerta → Task 1; §4.1 registro → Task 2; §4.2 aprobar/rechazar → Task 2; §4.3 correo → Task 2; §5.1 ApiClient → Task 3; §5.2-5.6 rutas/registro/recuperar/login/pendiente → Task 4; §5.7 UsuariosPage → Task 5; §6 pruebas backend → Tasks 1-2, frontend → typecheck/lint/manual; §7 verificación en vivo → Task 5 Step 4.
- **Sin placeholders:** código completo salvo el detalle visual de RegistroPage/RecuperarPage (patrón claro, se sigue el estilo de LoginPage/SignupPage ya en el repo).
- **Consistencia de tipos:** `aprobado` fluye modelo→repo→schema→endpoints→ApiClient→UsuarioAdmin→UsuariosPage; códigos de error (`CUENTA_PENDIENTE`/`CUENTA_INACTIVA`/`NO_REGISTRADO`/`YA_REGISTRADO`/`ULTIMO_ADMIN`/`NO_AUTO_ELIMINACION`) definidos en backend (Tasks 1-2) y consumidos en el front (Task 4 AuthContext). `crear(aprobado=)` definido en Task 1 y usado por bootstrap/alta-admin/registro. `UsuarioOut.aprobado` obliga a actualizar sus construcciones (Task 1 Step 7).
- **Dependencias entre tareas:** Task 2 usa `uid_del_token`/`crear(aprobado=)`/`contar_admins_activos`/`correos_admins` de Task 1. Task 3 debe ir antes de 4/5 (métodos del ApiClient). Task 5 usa `UsuarioAdmin.aprobado` de Task 3.
