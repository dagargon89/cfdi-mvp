"""Catálogo, generación de informes y reproceso del ETL (spec §7.2)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ContextoEmpresa, get_db, require_empresa, usuario_actual
from app.api.v1.schemas import InformeCatalogoOut, NormalizarIn, TareaCrearOut
from app.informes import registro
from app.models.enums import RolEmpresa
from app.models.usuario import Usuario
from app.services import bitacora as bitacora_service
from app.worker.tasks import generar_informe, normalizar_comprobantes

router_catalogo = APIRouter(tags=["informes"])
router = APIRouter(prefix="/empresas/{empresa_id}/informes", tags=["informes"])


@router_catalogo.get("/informes", response_model=list[InformeCatalogoOut])
async def catalogo_endpoint(usuario: Usuario = Depends(usuario_actual)) -> list[InformeCatalogoOut]:
    """Catálogo de informes disponibles con el JSON Schema de sus parámetros. No depende de
    la empresa: es la misma lista para todas."""
    return [InformeCatalogoOut(**entrada) for entrada in registro.catalogo()]


@router.post("/normalizar", status_code=status.HTTP_202_ACCEPTED, response_model=TareaCrearOut)
async def normalizar_endpoint(
    empresa_id: int,
    body: NormalizarIn,
    ctx: ContextoEmpresa = Depends(require_empresa(RolEmpresa.OPERADOR)),
    db: AsyncSession = Depends(get_db),
) -> TareaCrearOut:
    """Reprocesa los XML ya resguardados hacia la capa normalizada. Pide OPERADOR: es una
    escritura masiva, aunque idempotente."""
    await bitacora_service.registrar(
        db, actor=ctx.usuario.correo, accion="normalizar_comprobantes", entidad=f"empresa:{empresa_id}", detalle={"alcance": body.alcance}
    )
    await db.commit()

    tarea = normalizar_comprobantes.delay(empresa_id, body.alcance)
    return TareaCrearOut(tarea_id=tarea.id)


@router.post("/{clave}", status_code=status.HTTP_202_ACCEPTED, response_model=TareaCrearOut)
async def generar_endpoint(
    empresa_id: int,
    clave: str,
    parametros: dict[str, Any] = Body(default_factory=dict),
    ctx: ContextoEmpresa = Depends(require_empresa(RolEmpresa.CONSULTA)),
    db: AsyncSession = Depends(get_db),
) -> TareaCrearOut:
    """Encola la generación de un informe. Los parámetros se validan aquí contra la clase
    `Parametros` del informe, no en la tarea: un `422` es mucho más útil que una tarea que
    falla en segundo plano."""
    try:
        definicion = registro.obtener(clave)
    except registro.InformeDesconocidoError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Informe no encontrado.") from exc

    try:
        validados = definicion.Parametros(**parametros)
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.errors()) from exc

    # spec §8: generar sin enmascarar exige OPERADOR o superior y queda en bitácora.
    # `ctx.rol` es `RolEmpresa | RolGlobal` (deps.py:40): a un administrador global se le
    # asigna `RolGlobal.ADMIN`, no un `RolEmpresa`. Por eso la comprobación es
    # `ctx.rol == RolEmpresa.CONSULTA` y nunca `ctx.rol != RolEmpresa.OPERADOR`: con esa
    # segunda forma un administrador quedaría bloqueado de una acción que sí le corresponde.
    sin_enmascarar = getattr(validados, "enmascarar_datos_personales", True) is False
    if sin_enmascarar:
        if ctx.rol == RolEmpresa.CONSULTA:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail="Generar el informe sin enmascarar datos personales requiere rol de operador o superior.",
            )
        await bitacora_service.registrar(
            db,
            actor=ctx.usuario.correo,
            accion="generar_informe",
            entidad=f"empresa:{empresa_id}",
            # Los parámetros **validados**, no el dict crudo: la bitácora de un desenmascarado
            # tiene que decir con qué filtros efectivos se generó el libro que llevó datos
            # personales en claro, incluidos los que el cliente no escribió y tomaron su
            # default. Es la misma razón por la que la tarea pasa `p.model_dump()` al
            # `ContextoInforme`.
            detalle={"clave": clave, "enmascarar_datos_personales": False, "parametros": validados.model_dump(mode="json")},
        )
        await db.commit()

    tarea = generar_informe.delay(empresa_id, clave, validados.model_dump(mode="json"), ctx.usuario.correo)
    return TareaCrearOut(tarea_id=tarea.id)
