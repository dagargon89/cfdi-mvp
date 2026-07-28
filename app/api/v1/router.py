"""Agregador de routers /v1 — cada módulo de doc 05 se añade aquí conforme se construye."""

from fastapi import APIRouter

from app.api.v1 import bitacora, comprobantes, descargas, efirma, empresas, sesion, tareas, usuarios

router = APIRouter(prefix="/v1")
router.include_router(sesion.router)
router.include_router(empresas.router)
router.include_router(efirma.router)
router.include_router(descargas.router)
router.include_router(comprobantes.router)
router.include_router(tareas.router)
router.include_router(usuarios.router)
router.include_router(bitacora.router)
