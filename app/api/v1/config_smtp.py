"""GET/PUT /v1/config/smtp, POST /v1/config/smtp/probar (RF-NOT-01) — configuración global
de correo saliente, gestionada desde Configuración → Correo. Solo admin (mismo nivel que
Usuarios/Bitácora, las otras pestañas de esa pantalla)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_admin
from app.api.v1.schemas import ConfigSmtpIn, ConfigSmtpOut, ConfigSmtpProbarIn
from app.models.usuario import Usuario
from app.repositories import configuracion_smtp as config_smtp_repo
from app.services import bitacora as bitacora_service
from app.services import notificaciones as notificaciones_service

router = APIRouter(prefix="/config/smtp", tags=["config-smtp"])


@router.get("", response_model=ConfigSmtpOut)
async def obtener_config_smtp_endpoint(admin: Usuario = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> ConfigSmtpOut:
    config = await config_smtp_repo.obtener(db)
    if config is None:
        return ConfigSmtpOut(configurado=False, host=None, port=None, usuario=None, remitente=None, tls=None)
    # La contraseña NUNCA se regresa, ni cifrada — el formulario la deja vacía y solo la
    # sobreescribe si el usuario teclea una nueva (doc 04 §3.4, mismo principio que la e.firma).
    return ConfigSmtpOut(configurado=True, host=config.host, port=config.port, usuario=config.usuario, remitente=config.remitente, tls=config.tls)


@router.put("", response_model=None, status_code=status.HTTP_204_NO_CONTENT)
async def guardar_config_smtp_endpoint(
    body: ConfigSmtpIn, admin: Usuario = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> None:
    try:
        await notificaciones_service.guardar_config(
            db, host=body.host, port=body.port, usuario=body.usuario, remitente=body.remitente, tls=body.tls, password_plano=body.password
        )
    except notificaciones_service.SmtpNoConfiguradoError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail={"codigo": "SMTP_SIN_CONTRASENA", "mensaje": str(exc)}) from exc

    await bitacora_service.registrar(db, actor=admin.correo, accion="guardar_config_smtp", entidad="config_smtp:1", detalle={"host": body.host, "usuario": body.usuario})
    await db.commit()


@router.post("/probar", response_model=None, status_code=status.HTTP_200_OK)
async def probar_config_smtp_endpoint(
    body: ConfigSmtpProbarIn, admin: Usuario = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> dict[str, bool]:
    password = body.password
    if not password:
        existente = await config_smtp_repo.obtener(db)
        if existente is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"codigo": "SMTP_SIN_CONTRASENA", "mensaje": "Escribe la contraseña de aplicación para probar (todavía no hay ninguna guardada)."},
            )
        password = notificaciones_service.descifrar_password_guardada(existente)

    credenciales = notificaciones_service.SmtpCredenciales(
        host=body.host, port=body.port, usuario=body.usuario, password=password, remitente=body.remitente, tls=body.tls
    )
    try:
        notificaciones_service.enviar_correo_prueba(body.correo_destino, credenciales)
    except Exception as exc:  # noqa: BLE001 — cualquier fallo de smtplib se traduce al admin tal cual
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail={"codigo": "SMTP_ERROR", "mensaje": str(exc)}) from exc
    return {"enviado": True}
