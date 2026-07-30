"""POST /v1/usuarios, PUT .../permisos, PATCH /v1/usuarios/{id} — doc 05 §2 (solo admin).

La alta (RF-AUTH-02, "sin auto-registro") crea la cuenta en Firebase Auth vía Admin SDK
para obtener un `firebase_uid` de inmediato — el usuario define su contraseña después
con el flujo estándar de "recuperar contraseña" de Firebase; este backend no envía ese
correo (fuera de alcance de Sprint 1, ver notificaciones en Sprint 4).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from firebase_admin import auth as firebase_auth
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_admin
from app.api.v1.schemas import PermisoEmpresaOut, PermisosIn, UsuarioAdminOut, UsuarioCrearIn, UsuarioOut, UsuarioPatchIn
from app.core.security import firebase_app
from app.models.enums import RolGlobal
from app.models.usuario import Usuario
from app.repositories import permisos as permisos_repo
from app.repositories import usuarios as usuarios_repo
from app.services import bitacora

logger_usuarios = logging.getLogger("app")

router = APIRouter(prefix="/usuarios", tags=["usuarios"])


@router.get("", response_model=list[UsuarioAdminOut])
async def listar_usuarios(admin: Usuario = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> list[UsuarioAdminOut]:
    usuarios = await usuarios_repo.listar_con_permisos(db)
    return [
        UsuarioAdminOut(
            usuario_id=u.usuario_id,
            correo=u.correo,
            nombre=u.nombre,
            rol_global=u.rol_global.value,
            activo=u.activo,
            aprobado=u.aprobado,
            permisos=[PermisoEmpresaOut(empresa_id=p.empresa_id, empresa_nombre=p.empresa.nombre, rol=p.rol.value) for p in u.permisos],
        )
        for u in usuarios
    ]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=UsuarioOut)
async def crear_usuario(body: UsuarioCrearIn, admin: Usuario = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> UsuarioOut:
    if await usuarios_repo.por_correo(db, body.correo):
        raise HTTPException(status.HTTP_409_CONFLICT, detail={"codigo": "CORREO_DUPLICADO", "mensaje": "Ya existe un usuario con ese correo."})

    try:
        cuenta = firebase_auth.create_user(email=body.correo, email_verified=False, app=firebase_app())
    except firebase_auth.EmailAlreadyExistsError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail={"codigo": "CORREO_DUPLICADO", "mensaje": "Ya existe una cuenta con ese correo en Firebase."}) from exc

    usuario = await usuarios_repo.crear(db, firebase_uid=cuenta.uid, correo=body.correo, nombre=body.nombre, rol_global=body.rol_global, aprobado=True)
    await bitacora.registrar(db, actor=admin.correo, accion="alta_usuario", entidad=f"usuario:{usuario.usuario_id}", detalle={"correo": body.correo, "rol_global": body.rol_global.value})
    await db.commit()
    return UsuarioOut(usuario_id=usuario.usuario_id, correo=usuario.correo, nombre=usuario.nombre, rol_global=usuario.rol_global.value, activo=usuario.activo, aprobado=usuario.aprobado)


@router.put("/{usuario_id}/permisos", response_model=UsuarioOut)
async def asignar_permisos(
    usuario_id: int, body: PermisosIn, admin: Usuario = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> UsuarioOut:
    usuario = await usuarios_repo.por_id(db, usuario_id)
    if usuario is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No encontrado.")
    await permisos_repo.reemplazar(db, usuario_id, [(p.empresa_id, p.rol) for p in body.permisos])
    await bitacora.registrar(
        db, actor=admin.correo, accion="asignar_permisos", entidad=f"usuario:{usuario_id}",
        detalle={"permisos": [{"empresa_id": p.empresa_id, "rol": p.rol.value} for p in body.permisos]},
    )
    await db.commit()
    return UsuarioOut(usuario_id=usuario.usuario_id, correo=usuario.correo, nombre=usuario.nombre, rol_global=usuario.rol_global.value, activo=usuario.activo, aprobado=usuario.aprobado)


@router.patch("/{usuario_id}", response_model=UsuarioOut)
async def actualizar_usuario(
    usuario_id: int, body: UsuarioPatchIn, admin: Usuario = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> UsuarioOut:
    usuario = await usuarios_repo.por_id(db, usuario_id)
    if usuario is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No encontrado.")
    # No dejar el sistema sin ningún administrador: si el objetivo es el último admin activo/aprobado,
    # bloquear degradarlo (rol distinto de admin), desactivarlo o desaprobarlo.
    quita_admin = (
        (body.rol_global is not None and body.rol_global is not RolGlobal.ADMIN)
        or body.activo is False
        or body.aprobado is False
    )
    if usuario.rol_global is RolGlobal.ADMIN and quita_admin and await usuarios_repo.contar_admins_activos(db) <= 1:
        raise HTTPException(status.HTTP_409_CONFLICT, detail={"codigo": "ULTIMO_ADMIN", "mensaje": "No puedes quitar el rol de administrador al último administrador."})
    await usuarios_repo.actualizar(db, usuario, activo=body.activo, rol_global=body.rol_global, aprobado=body.aprobado)
    await bitacora.registrar(
        db, actor=admin.correo, accion="editar_usuario", entidad=f"usuario:{usuario_id}",
        detalle={"activo": body.activo, "rol_global": body.rol_global.value if body.rol_global else None, "aprobado": body.aprobado},
    )
    await db.commit()
    return UsuarioOut(usuario_id=usuario.usuario_id, correo=usuario.correo, nombre=usuario.nombre, rol_global=usuario.rol_global.value, activo=usuario.activo, aprobado=usuario.aprobado)


@router.delete("/{usuario_id}", status_code=status.HTTP_204_NO_CONTENT)
async def eliminar_usuario(usuario_id: int, admin: Usuario = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> None:
    usuario = await usuarios_repo.por_id(db, usuario_id)
    if usuario is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No encontrado.")
    if usuario.usuario_id == admin.usuario_id:
        raise HTTPException(status.HTTP_409_CONFLICT, detail={"codigo": "NO_AUTO_ELIMINACION", "mensaje": "No puedes eliminar tu propia cuenta."})
    # Defensa en profundidad: como `admin` (el actor) siempre es un ADMIN activo+aprobado (lo exige
    # `require_admin`), si el objetivo también es un ADMIN activo+aprobado, `contar_admins_activos()`
    # ya cuenta a ambos (>=2) y este branch no se alcanza para ese caso — el único camino real hoy es
    # que el objetivo sea un ADMIN inactivo o no aprobado (no cuenta en `contar_admins_activos`)
    # mientras el actor es el único admin activo; ver test_delete_ultimo_admin_admin_inactivo_409.
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
