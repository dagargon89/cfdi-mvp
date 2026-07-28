import logging
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import router as v1_router
from app.core.config import get_settings

logger = logging.getLogger("app")
settings = get_settings()

app = FastAPI(
    title="Hub CFDI API",
    version="0.1.0",
    docs_url="/docs" if settings.environment != "production" else None,
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(v1_router)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Formato de error estándar (doc 05 §1.4) — `detail` puede ser un str simple o un
    dict {codigo, mensaje, detalle} para errores de negocio (422 de bóveda/descargas)."""
    detail = exc.detail
    if isinstance(detail, dict) and "mensaje" in detail:
        error = {"codigo": detail.get("codigo", "ERROR"), "mensaje": detail["mensaje"], "trace_id": str(uuid4())}
        if "detalle" in detail:
            error["detalle"] = detail["detalle"]
    else:
        error = {"codigo": "ERROR", "mensaje": str(detail), "trace_id": str(uuid4())}
    return JSONResponse(status_code=exc.status_code, content={"error": error})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Red de seguridad para excepciones no controladas (doc 05 §1.3, 500).

    Sin esto, un error no capturado escapa a `ServerErrorMiddleware` de Starlette, que queda
    POR FUERA de `CORSMiddleware` — la respuesta sale sin cabeceras CORS y el navegador lo
    reporta como "bloqueado por política de CORS", ocultando el error 500 real (así se
    descubrió el bug de `num_serie` demasiado angosto para una e.firma real). El detalle
    completo solo va a los logs del servidor, nunca al cliente.
    """
    logger.exception("Error no controlado en %s %s", request.method, request.url.path)
    error = {"codigo": "ERROR", "mensaje": "Error interno del servidor.", "trace_id": str(uuid4())}
    return JSONResponse(status_code=500, content={"error": error})


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
