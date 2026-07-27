"""Agregador de routers /v1 — cada módulo de doc 05 se añade aquí conforme se construye."""

from fastapi import APIRouter

from app.api.v1 import bitacora, efirma, empresas, sesion, usuarios

router = APIRouter(prefix="/v1")
router.include_router(sesion.router)
router.include_router(empresas.router)
router.include_router(efirma.router)
router.include_router(usuarios.router)
router.include_router(bitacora.router)
