"""GET /v1/tareas/{tarea_id} y GET /v1/descargas-archivo/{token} — doc 05 §6.

`tareas` no tiene tabla propia: `tarea_id` ES el id de la tarea de Celery, y su estado se lee
del result backend (Redis, ya configurado en `app/worker/celery_app.py`) vía `AsyncResult`.
Limitación aceptada: un `tarea_id` inventado es indistinguible de "pendiente" para Celery — el
contrato congelado (`estadoTarea`, doc 05 §9) no recibe `empresaId` para acotar esta consulta.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse

from app.api.v1.schemas import TareaEstadoOut
from app.core.config import get_settings
from app.services import enlaces
from app.worker.celery_app import celery_app

router = APIRouter(tags=["tareas"])


@router.get("/tareas/{tarea_id}", response_model=TareaEstadoOut)
async def estado_tarea_endpoint(tarea_id: str) -> TareaEstadoOut:
    from celery.result import AsyncResult

    resultado = AsyncResult(tarea_id, app=celery_app)
    if resultado.state in ("PENDING", "STARTED", "RETRY"):
        return TareaEstadoOut(estado="pendiente")
    if resultado.state == "FAILURE":
        return TareaEstadoOut(estado="fallida")

    valor = resultado.result if isinstance(resultado.result, dict) else {}
    descarga_url = enlaces.url_descarga(valor["ruta"]) if "ruta" in valor else None
    return TareaEstadoOut(estado="completada", descarga_url=descarga_url)


@router.get("/descargas-archivo/{token}")
async def descargar_archivo_endpoint(token: str) -> FileResponse:
    try:
        payload = enlaces.verificar(token)
    except enlaces.EnlaceInvalidoError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Enlace inválido o vencido.") from exc

    storage_root = os.path.abspath(get_settings().storage_root)
    ruta_absoluta = os.path.abspath(os.path.join(storage_root, payload["ruta"]))
    # El token ya viene firmado por el servidor con una ruta que él mismo generó — esta
    # comprobación es una segunda capa (defensa en profundidad), no la única barrera.
    if not ruta_absoluta.startswith(storage_root + os.sep) or not os.path.isfile(ruta_absoluta):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No encontrado.")

    return FileResponse(ruta_absoluta, filename=os.path.basename(ruta_absoluta))
