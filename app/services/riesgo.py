"""Cruces de riesgo (RF-RIES-01/02): EFOS 69-B contra el histórico de comprobantes recibidos,
y cancelaciones tardías detectadas durante la re-verificación de vigencia."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.comprobante import Comprobante
from app.models.enums import TipoEvento
from app.models.evento import Evento
from app.repositories import eventos as eventos_repo
from app.repositories import lista_69b as lista_69b_repo
from app.services import notificaciones as notificaciones_service


async def cruzar_efos(db: AsyncSession, version_lista: date) -> int:
    """Cruza `lista_69b.rfc` (de esa versión) contra `comprobantes.rfc_emisor`, agrupado por
    empresa — histórico completo de recibidos, no solo lo nuevo (RF-RIES-02). Un `Evento`
    por combinación (empresa, RFC listado) con coincidencias; `hash_detalle` incluye
    `situacion` y la lista de UUIDs, así que un cambio real (nueva factura de ese emisor, o
    el SAT actualizando su situación) genera un aviso nuevo en vez de quedar silenciado por
    el hash de un evento anterior con un detalle distinto (doc 06 §2.6).

    Devuelve cuántos eventos NUEVOS se crearon (0 si todo ya se había notificado antes).
    """
    filas = await lista_69b_repo.rfcs_de_version(db, version_lista)
    if not filas:
        return 0
    situacion_por_rfc = {f.rfc: f.situacion.value for f in filas}

    result = await db.execute(
        select(Comprobante.empresa_id, Comprobante.rfc_emisor, Comprobante.uuid).where(
            Comprobante.rfc_emisor.in_(situacion_por_rfc.keys())
        )
    )
    agrupado: dict[tuple[int, str], list[str]] = defaultdict(list)
    for empresa_id, rfc_emisor, uuid_ in result.all():
        agrupado[(empresa_id, rfc_emisor)].append(uuid_)

    creados = 0
    for (empresa_id, rfc), uuids in agrupado.items():
        detalle = {"rfc": rfc, "situacion": situacion_por_rfc[rfc], "uuids": sorted(uuids)}
        evento = await eventos_repo.crear(db, empresa_id, TipoEvento.EFOS, detalle)
        notificaciones_service.encolar_si_nuevo(evento)
        if evento is not None:
            creados += 1
    return creados


def _mes_anterior(fecha_emision: datetime, hoy: date) -> bool:
    return (fecha_emision.year, fecha_emision.month) < (hoy.year, hoy.month)


async def registrar_cancelacion_tardia(db: AsyncSession, comprobante: Comprobante, *, hoy: date | None = None) -> Evento | None:
    """Se llama SOLO cuando el caller ya detectó una transición vigente→cancelado (doc 06
    §2.6) — este servicio no vuelve a comparar contra el estatus anterior, solo decide si la
    fecha de emisión cae en un mes ya cerrado (RF-RIES-01) y arma el evento."""
    hoy = hoy or date.today()
    if comprobante.fecha_emision is None or not _mes_anterior(comprobante.fecha_emision, hoy):
        return None
    detalle = {
        "uuid": comprobante.uuid,
        "rfc_emisor": comprobante.rfc_emisor,
        "fecha_emision": comprobante.fecha_emision.date().isoformat(),
    }
    evento = await eventos_repo.crear(db, comprobante.empresa_id, TipoEvento.CANCELACION_TARDIA, detalle)
    notificaciones_service.encolar_si_nuevo(evento)
    return evento
