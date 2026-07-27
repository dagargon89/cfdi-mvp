"""POST /v1/usuarios, PUT .../permisos, PATCH /v1/usuarios/{id} — doc 05 §2 (solo admin).

La alta (RF-AUTH-02, "sin auto-registro") crea la cuenta en Firebase Auth vía Admin SDK
para obtener un `firebase_uid` de inmediato — el usuario define su contraseña después
con el flujo estándar de "recuperar contraseña" de Firebase; este backend no envía ese
correo (fuera de alcance de Sprint 1, ver notificaciones en Sprint 4).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from firebase_admin import auth as firebase_auth
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_admin
from app.api.v1.schemas import PermisoEmpresaOut, PermisosIn, UsuarioAdminOut, UsuarioCrearIn, UsuarioOut, UsuarioPatchIn
from app.core.security import firebase_app
from app.models.usuario import Usuario
from app.repositories import permisos as permisos_repo
from app.repositories import usuarios as usuarios_repo
from app.services import bitacora

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

    usuario = await usuarios_repo.crear(db, firebase_uid=cuenta.uid, correo=body.correo, nombre=body.nombre, rol_global=body.rol_global)
    await bitacora.registrar(db, actor=admin.correo, accion="alta_usuario", entidad=f"usuario:{usuario.usuario_id}", detalle={"correo": body.correo, "rol_global": body.rol_global.value})
    await db.commit()
    return UsuarioOut(usuario_id=usuario.usuario_id, correo=usuario.correo, nombre=usuario.nombre, rol_global=usuario.rol_global.value, activo=usuario.activo)


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
    return UsuarioOut(usuario_id=usuario.usuario_id, correo=usuario.correo, nombre=usuario.nombre, rol_global=usuario.rol_global.value, activo=usuario.activo)


@router.patch("/{usuario_id}", response_model=UsuarioOut)
async def actualizar_usuario(
    usuario_id: int, body: UsuarioPatchIn, admin: Usuario = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> UsuarioOut:
    usuario = await usuarios_repo.por_id(db, usuario_id)
    if usuario is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No encontrado.")
    await usuarios_repo.actualizar(db, usuario, activo=body.activo, rol_global=body.rol_global)
    await bitacora.registrar(
        db, actor=admin.correo, accion="editar_usuario", entidad=f"usuario:{usuario_id}",
        detalle={"activo": body.activo, "rol_global": body.rol_global.value if body.rol_global else None},
    )
    await db.commit()
    return UsuarioOut(usuario_id=usuario.usuario_id, correo=usuario.correo, nombre=usuario.nombre, rol_global=usuario.rol_global.value, activo=usuario.activo)
