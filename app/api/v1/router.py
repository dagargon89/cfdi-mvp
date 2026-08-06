"""Agregador de routers /v1 — cada módulo de doc 05 se añade aquí conforme se construye."""

from fastapi import APIRouter

from app.api.v1 import automatizaciones, auth_bootstrap, bitacora, comprobantes, config_smtp, configuracion, descargas, efirma, empresas, eventos, informes, notificaciones, sesion, tareas, usuarios

router = APIRouter(prefix="/v1")
router.include_router(auth_bootstrap.router)
router.include_router(sesion.router)
router.include_router(empresas.router)
router.include_router(efirma.router)
router.include_router(descargas.router)
router.include_router(comprobantes.router)
router.include_router(informes.router_catalogo)
router.include_router(informes.router)
router.include_router(tareas.router)
router.include_router(usuarios.router)
router.include_router(bitacora.router)
router.include_router(eventos.router)
router.include_router(notificaciones.router)
router.include_router(config_smtp.router)
router.include_router(automatizaciones.router)
router.include_router(configuracion.router)
router.include_router(configuracion.router_empresa)
