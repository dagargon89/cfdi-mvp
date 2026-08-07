"""GET/PUT /v1/config/automatizaciones — interruptores de las tareas automáticas (beat):
descarga diaria del SAT, actualización de la lista 69-B (EFOS), re-verificación de vigencia,
limpieza de almacenamiento y alarma de vigencia fiscal.
Solo admin (mismo nivel que las otras pestañas de Configuración). Default = todas activas."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_admin
from app.api.v1.schemas import AutomatizacionesConfig
from app.models.usuario import Usuario
from app.repositories import configuracion as config_repo
from app.services import bitacora as bitacora_service
from app.services import sincronizacion_fiscal as sincronizacion

router = APIRouter(prefix="/config", tags=["config"])

# clave de configuración por interruptor (default True = comportamiento actual).
_CLAVES = {
    "sync_diaria": "auto_sync_diaria",
    "lista_69b": "auto_lista_69b",
    "re_verificar": "auto_re_verificar",
    "limpieza": "auto_limpieza",
    # La clave la define el propio servicio, para que la tarea del beat y este interruptor no
    # puedan divergir en una letra (un `auto_vigencia_fical` aquí apagaría un interruptor que
    # nadie lee, y la tarea seguiría corriendo sin que nada lo delatara).
    "vigencia_fiscal": sincronizacion.CLAVE_AUTOMATIZACION,
}


@router.get("/automatizaciones", response_model=AutomatizacionesConfig)
async def obtener_automatizaciones(
    admin: Usuario = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> AutomatizacionesConfig:
    return AutomatizacionesConfig(
        sync_diaria=bool(await config_repo.valor(db, _CLAVES["sync_diaria"], True)),
        lista_69b=bool(await config_repo.valor(db, _CLAVES["lista_69b"], True)),
        re_verificar=bool(await config_repo.valor(db, _CLAVES["re_verificar"], True)),
        limpieza=bool(await config_repo.valor(db, _CLAVES["limpieza"], True)),
        vigencia_fiscal=bool(await config_repo.valor(db, _CLAVES["vigencia_fiscal"], True)),
    )


@router.put("/automatizaciones", response_model=AutomatizacionesConfig)
async def guardar_automatizaciones(
    body: AutomatizacionesConfig, admin: Usuario = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> AutomatizacionesConfig:
    await config_repo.establecer(db, _CLAVES["sync_diaria"], body.sync_diaria)
    await config_repo.establecer(db, _CLAVES["lista_69b"], body.lista_69b)
    await config_repo.establecer(db, _CLAVES["re_verificar"], body.re_verificar)
    await config_repo.establecer(db, _CLAVES["limpieza"], body.limpieza)
    await config_repo.establecer(db, _CLAVES["vigencia_fiscal"], body.vigencia_fiscal)
    await bitacora_service.registrar(
        db,
        actor=admin.correo,
        accion="editar_automatizaciones",
        entidad="config",
        detalle={
            "sync_diaria": body.sync_diaria,
            "lista_69b": body.lista_69b,
            "re_verificar": body.re_verificar,
            "limpieza": body.limpieza,
            "vigencia_fiscal": body.vigencia_fiscal,
        },
    )
    await db.commit()
    return body
