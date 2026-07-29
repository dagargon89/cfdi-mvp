"""Envío de correo de notificación (RF-NOT-01) — `smtplib` estándar, no un SDK propietario:
funciona igual con Gmail Workspace, Office 365, SES o SendGrid mientras expongan SMTP.

La configuración (host/puerto/usuario/contraseña de aplicación/remitente/TLS) vive en la
BD (`configuracion_smtp`, una sola fila), gestionada desde Configuración → Correo — nunca
por variable de entorno: cada instalación de Hub CFDI la captura desde la UI con el correo
y la contraseña de aplicación que el operador prefiera. La contraseña se cifra con el mismo
sobre AES-256-GCM que protege la e.firma en la bóveda (`app/services/boveda.py`).
"""

from __future__ import annotations

from dataclasses import dataclass
from email.message import EmailMessage
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import TipoEvento
from app.repositories import configuracion_smtp as config_smtp_repo
from app.sat_hub.errors import HubError
from app.services import boveda

if TYPE_CHECKING:
    from app.models.configuracion_smtp import ConfiguracionSmtp
    from app.models.evento import Evento
    from app.models.notificacion_destino import NotificacionDestino

_ASUNTOS: dict[TipoEvento, str] = {
    TipoEvento.CANCELACION_TARDIA: "Hub CFDI — cancelación tardía detectada",
    TipoEvento.EFOS: "Hub CFDI — RFC emisor en la lista 69-B (EFOS)",
    TipoEvento.EFIRMA_POR_VENCER: "Hub CFDI — e.firma por vencer",
    TipoEvento.ERROR_DESCARGA: "Hub CFDI — error en una descarga",
    TipoEvento.RESUMEN_SYNC: "Hub CFDI — resumen de sincronización diaria",
}


class SmtpNoConfiguradoError(HubError):
    """Nadie ha configurado el correo saliente todavía (Configuración → Correo) — o se pide
    guardar sin contraseña la primera vez, que no tiene ninguna previa que conservar.
    `enviar_notificacion` la captura y registra en `notificacion_log` como fallido, sin
    reintentar indefinidamente (reintentar no la va a arreglar sola)."""


@dataclass(frozen=True, slots=True)
class SmtpCredenciales:
    host: str
    port: int
    usuario: str
    password: str
    remitente: str
    tls: bool


def descifrar_password_guardada(config: "ConfiguracionSmtp") -> str:
    kek = boveda.cargar_kek()
    dek = boveda.desenvolver_dek(kek, config.dek_envuelta)
    return boveda.descifrar(dek, config.password_cifrada).decode()


async def resolver_credenciales(db: AsyncSession) -> SmtpCredenciales:
    """Lee la configuración guardada y descifra la contraseña. Se resuelve UNA vez por
    tarea de envío (no una vez por destinatario) — `enviar_notificacion` la pasa ya resuelta
    a cada llamada de `enviar_correo`."""
    config = await config_smtp_repo.obtener(db)
    if config is None:
        raise SmtpNoConfiguradoError("Nadie ha configurado el correo saliente todavía (Configuración → Correo).")
    return SmtpCredenciales(
        host=config.host, port=config.port, usuario=config.usuario, password=descifrar_password_guardada(config), remitente=config.remitente, tls=config.tls
    )


async def guardar_config(db: AsyncSession, *, host: str, port: int, usuario: str, remitente: str, tls: bool, password_plano: str | None) -> None:
    """`password_plano=None` (o vacío) conserva la contraseña ya guardada — para editar
    host/remitente/etc. desde el panel sin volver a teclear la contraseña de aplicación en
    cada guardado. Levanta `SmtpNoConfiguradoError` si no hay ninguna contraseña previa que
    conservar (primera configuración sin contraseña)."""
    existente = await config_smtp_repo.obtener(db)
    if password_plano:
        dek = boveda.generar_dek()
        kek = boveda.cargar_kek()
        password_cifrada = boveda.cifrar(dek, password_plano.encode())
        dek_envuelta = boveda.envolver_dek(kek, dek)
    elif existente is not None:
        password_cifrada, dek_envuelta = existente.password_cifrada, existente.dek_envuelta
    else:
        raise SmtpNoConfiguradoError("Se requiere una contraseña de aplicación la primera vez que se configura el correo.")

    await config_smtp_repo.guardar(
        db, host=host, port=port, usuario=usuario, remitente=remitente, tls=tls, password_cifrada=password_cifrada, dek_envuelta=dek_envuelta
    )


def _enviar(mensaje: EmailMessage, credenciales: SmtpCredenciales) -> None:
    import smtplib

    with smtplib.SMTP(credenciales.host, credenciales.port, timeout=15) as smtp:
        if credenciales.tls:
            smtp.starttls()
        smtp.login(credenciales.usuario, credenciales.password)
        smtp.send_message(mensaje)


def _cuerpo(evento: "Evento") -> str:
    lineas = [f"{clave}: {valor}" for clave, valor in evento.detalle.items()]
    return "Se generó una alerta en Hub CFDI:\n\n" + "\n".join(lineas)


def enviar_correo(destino: "NotificacionDestino", evento: "Evento", credenciales: SmtpCredenciales) -> None:
    """Deja propagar cualquier excepción de `smtplib` — el caller decide cómo traducir eso
    a un reintento de Celery."""
    mensaje = EmailMessage()
    mensaje["Subject"] = _ASUNTOS.get(evento.tipo, "Hub CFDI — nueva alerta")
    mensaje["From"] = credenciales.remitente
    mensaje["To"] = destino.correo
    mensaje.set_content(_cuerpo(evento))
    _enviar(mensaje, credenciales)


def enviar_aviso_registro(destinos: list[str], solicitante_correo: str, solicitante_nombre: str, credenciales: SmtpCredenciales) -> None:
    """Aviso a los admins tras un auto-registro (RF-AUTH-02, spec 2026-07-29) — best-effort,
    el caller decide qué hacer si falla o si no hay SMTP configurado."""
    mensaje = EmailMessage()
    mensaje["Subject"] = "Hub CFDI — nueva solicitud de acceso"
    mensaje["From"] = credenciales.remitente
    mensaje["To"] = ", ".join(destinos)
    mensaje.set_content(f"{solicitante_nombre} ({solicitante_correo}) solicitó acceso a Hub CFDI.\n\nRevísalo y apruébalo en la sección Usuarios.")
    _enviar(mensaje, credenciales)


def enviar_correo_prueba(correo_destino: str, credenciales: SmtpCredenciales) -> None:
    """Botón "Enviar correo de prueba" del panel — valida host/usuario/contraseña de
    aplicación en vivo, antes de depender de que dispare una alerta real."""
    mensaje = EmailMessage()
    mensaje["Subject"] = "Hub CFDI — correo de prueba"
    mensaje["From"] = credenciales.remitente
    mensaje["To"] = correo_destino
    mensaje.set_content("Este es un correo de prueba de la configuración de correo de Hub CFDI. Si lo recibiste, la configuración funciona correctamente.")
    _enviar(mensaje, credenciales)


def encolar_si_nuevo(evento: "Evento | None") -> None:
    """`eventos_repo.crear` devuelve `None` cuando el evento ya existía (no-op de
    idempotencia) — en ese caso no hay nada nuevo que notificar. Import perezoso de
    `app.worker.tasks` para no crear un ciclo services↔worker a nivel de módulo (el worker
    sí importa de `app.services.*` al cargar, pero nada en `services` importa `worker` al
    cargar — solo aquí, dentro de la función, en el momento en que de verdad hace falta)."""
    if evento is None:
        return
    from app.worker.tasks import enviar_notificacion

    enviar_notificacion.delay(evento.evento_id)
