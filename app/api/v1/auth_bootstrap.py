"""Signup de arranque del primer administrador (bootstrap) — spec 2026-07-29.

Excepción explícita a RF-AUTH-02 ("sin auto-registro"), acotada al primer admin: estos endpoints son
PÚBLICOS (sin Depends de auth, porque aún no puede existir un token) y solo operan mientras `usuarios`
esté vacía. Protegidos por un token de arranque del servidor (BOOTSTRAP_ADMIN_TOKEN).
"""

from __future__ import annotations

import logging
import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from firebase_admin import auth as firebase_auth
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, uid_del_token
from app.api.v1.schemas import BootstrapAdminIn, BootstrapStatusOut, RegistroIn, RegistroOut, UsuarioOut
from app.core.config import get_settings
from app.core.security import firebase_app
from app.models.enums import RolGlobal
from app.repositories import usuarios as usuarios_repo
from app.services import bitacora, notificaciones
from app.services.notificaciones import SmtpNoConfiguradoError

logger = logging.getLogger("app")

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
        usuario = await usuarios_repo.crear(db, firebase_uid=cuenta.uid, correo=body.correo, nombre=body.nombre, rol_global=RolGlobal.ADMIN, aprobado=True)
        await bitacora.registrar(db, actor=body.correo, accion="alta_admin_bootstrap", entidad=f"usuario:{usuario.usuario_id}", detalle={"correo": body.correo})
        await db.commit()
    except Exception as exc:  # noqa: BLE001 — no dejar cuenta huérfana en Firebase si el registro local falla
        await db.rollback()
        try:
            firebase_auth.delete_user(cuenta.uid, app=firebase_app())
        except Exception:  # noqa: BLE001 — no enmascarar el 500 BOOTSTRAP_FALLIDO si la limpieza falla
            logger.warning("No se pudo eliminar la cuenta huérfana de Firebase uid=%s tras fallo de bootstrap", cuenta.uid, exc_info=True)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail={"codigo": "BOOTSTRAP_FALLIDO", "mensaje": "No se pudo completar el alta de arranque."}) from exc

    return UsuarioOut(usuario_id=usuario.usuario_id, correo=usuario.correo, nombre=usuario.nombre, rol_global=usuario.rol_global.value, activo=usuario.activo, aprobado=usuario.aprobado)


@router.post("/registro", status_code=status.HTTP_201_CREATED, response_model=RegistroOut)
async def registro(body: RegistroIn, uid: str = Depends(uid_del_token), db: AsyncSession = Depends(get_db)) -> RegistroOut:
    """Auto-registro (excepción explícita a RF-AUTH-02): el correo SIEMPRE viene de Firebase
    (nunca del body, para que nadie pueda declarar un correo ajeno) y el usuario local se
    crea `aprobado=False` — sin acceso hasta que un admin lo apruebe (`PATCH /usuarios/{id}`)."""
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
