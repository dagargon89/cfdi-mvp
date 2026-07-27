"""Dependencia de autorización — regla no negociable 3 de CLAUDE.md: ningún endpoint
de datos existe sin pasar por aquí. Token → usuario local activo → permiso usuario↔empresa.

Distinción de códigos (doc 05 §1.3, doc 06 §2.2):
- 401: token ausente/inválido/expirado.
- 403: usuario sin registro local o inactivo (RF-AUTH-02/04); o SÍ tiene acceso a la
  empresa pero con rol insuficiente para la acción (no hay nada que enumerar: ya sabe
  que la empresa existe y que tiene algo de acceso).
- 404: la empresa no existe O no está entre las autorizadas del usuario — misma
  respuesta en ambos casos (anti-enumeración; un atacante no puede distinguir).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verificar_id_token
from app.db.session import get_db as _get_db
from app.models.enums import RolEmpresa, RolGlobal
from app.models.usuario import Usuario
from app.models.usuario_empresa import UsuarioEmpresa

_ORDEN_ROL: dict[RolEmpresa, int] = {RolEmpresa.CONSULTA: 0, RolEmpresa.OPERADOR: 1}


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async for session in _get_db():
        yield session


@dataclass(frozen=True, slots=True)
class ContextoEmpresa:
    usuario: Usuario
    empresa_id: int
    rol: RolEmpresa | RolGlobal  # RolGlobal.ADMIN cuando el acceso es implícito de administrador
    es_admin: bool


async def _usuario_activo_por_token(authorization: str | None, db: AsyncSession) -> Usuario:
    uid = verificar_id_token(authorization)
    usuario = await db.scalar(select(Usuario).where(Usuario.firebase_uid == uid))
    if usuario is None or not usuario.activo:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Usuario inactivo o no registrado en Hub CFDI.")
    return usuario


async def usuario_actual(
    authorization: str | None = Header(default=None), db: AsyncSession = Depends(get_db)
) -> Usuario:
    """Para endpoints que no cuelgan de una empresa (`GET /v1/me`, admin de usuarios/bitácora)."""
    return await _usuario_activo_por_token(authorization, db)


async def require_admin(usuario: Usuario = Depends(usuario_actual)) -> Usuario:
    if usuario.rol_global != RolGlobal.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Solo un administrador puede realizar esta acción.")
    return usuario


def require_empresa(rol_minimo: RolEmpresa = RolEmpresa.CONSULTA) -> Callable[..., Awaitable[ContextoEmpresa]]:
    """Dependencia parametrizada por rol mínimo requerido sobre `empresa_id` (path param)."""

    async def dep(
        empresa_id: int,
        authorization: str | None = Header(default=None),
        db: AsyncSession = Depends(get_db),
    ) -> ContextoEmpresa:
        usuario = await _usuario_activo_por_token(authorization, db)

        if usuario.rol_global == RolGlobal.ADMIN:
            return ContextoEmpresa(usuario=usuario, empresa_id=empresa_id, rol=RolGlobal.ADMIN, es_admin=True)

        permiso = await db.scalar(
            select(UsuarioEmpresa).where(
                UsuarioEmpresa.usuario_id == usuario.usuario_id,
                UsuarioEmpresa.empresa_id == empresa_id,
            )
        )
        if permiso is None:
            # Anti-enumeración (doc 05 §1.3): empresa inexistente y empresa ajena responden igual.
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No encontrado.")
        if _ORDEN_ROL[permiso.rol] < _ORDEN_ROL[rol_minimo]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Tu rol no permite esta acción sobre esta empresa.")
        return ContextoEmpresa(usuario=usuario, empresa_id=empresa_id, rol=permiso.rol, es_admin=False)

    return dep
