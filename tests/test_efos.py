"""EFOS 69-B (RF-RIES-02) — `descargar_lista_69b` nunca toca la red real (se mockea
`requests.get`, doc 07 Sprint 4 "límite de seguridad"); `cruzar_efos` se prueba contra el
histórico de comprobantes ya indexado."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import TipoEvento
from app.repositories import eventos as eventos_repo
from app.repositories import lista_69b as lista_69b_repo
from app.sat_hub.sat_facade import descargar_lista_69b
from app.services import riesgo as riesgo_service
from tests.factories import crear_comprobante, crear_empresa


def _csv_69b_falso() -> bytes:
    contenido = (
        "encabezado 1\r\n"
        "encabezado 2\r\n"
        "encabezado 3\r\n"
        '1,"EKU9003173C9","EMISOR PRESUNTO","Presunto","01/01/2026"\r\n'
        '2,"AAA010101AAA","EMISOR DEFINITIVO","Definitivo","01/01/2026"\r\n'
        '3,"BBB020202BBB","SITUACION NO CATALOGADA","Otra cosa","01/01/2026"\r\n'
        # Mismo RFC dos veces (historial real del SAT): la fila posterior gana.
        '4,"CCC030303CCC","EMISOR CON HISTORIAL","Presunto","01/01/2026"\r\n'
        '5,"CCC030303CCC","EMISOR CON HISTORIAL","Definitivo","15/03/2026"\r\n'
    )
    return contenido.encode("windows-1250")


def test_descargar_lista_69b_parsea_y_normaliza_situacion(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeResponse:
        content = _csv_69b_falso()

        def raise_for_status(self) -> None:
            return None

    def _fake_get(url: str, headers: dict[str, str] | None = None, timeout: int | None = None) -> _FakeResponse:
        assert "69-B" in url
        return _FakeResponse()

    monkeypatch.setattr("requests.get", _fake_get)
    filas = descargar_lista_69b()

    assert ("EKU9003173C9", "presunto") in filas
    assert ("AAA010101AAA", "definitivo") in filas
    assert ("CCC030303CCC", "definitivo") in filas  # RFC repetido: gana la fila posterior (historial real del SAT)
    assert len(filas) == 3  # "Otra cosa" se ignora; CCC030303CCC deduplicado a una sola fila


async def test_cruzar_efos_genera_evento_solo_para_empresas_con_coincidencia(db: AsyncSession) -> None:
    empresa = await crear_empresa(db, rfc="XAXX010101000")
    await crear_comprobante(db, empresa_id=empresa.empresa_id, uuid="11111111-1111-1111-1111-111111111111", rfc_emisor="EKU9003173C9")
    await crear_comprobante(db, empresa_id=empresa.empresa_id, uuid="22222222-2222-2222-2222-222222222222", rfc_emisor="EKU9003173C9")
    await crear_comprobante(db, empresa_id=empresa.empresa_id, uuid="33333333-3333-3333-3333-333333333333", rfc_emisor="ZZZ000000ZZZ")  # no listado

    hoy = date(2026, 7, 28)
    await lista_69b_repo.crear_version(db, hoy, [("EKU9003173C9", "definitivo")])
    await db.commit()

    creados = await riesgo_service.cruzar_efos(db, hoy)
    await db.commit()
    assert creados == 1

    eventos, total = await eventos_repo.listar(db, empresa.empresa_id, tipo=TipoEvento.EFOS)
    assert total == 1
    detalle = eventos[0].detalle
    assert detalle["rfc"] == "EKU9003173C9"
    assert detalle["situacion"] == "definitivo"
    assert sorted(detalle["uuids"]) == ["11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"]


async def test_cruzar_efos_sin_coincidencias_no_genera_eventos(db: AsyncSession) -> None:
    empresa = await crear_empresa(db, rfc="XAXX010101000")
    await crear_comprobante(db, empresa_id=empresa.empresa_id, uuid="11111111-1111-1111-1111-111111111111", rfc_emisor="ZZZ000000ZZZ")

    hoy = date(2026, 7, 28)
    await lista_69b_repo.crear_version(db, hoy, [("EKU9003173C9", "definitivo")])
    await db.commit()

    assert await riesgo_service.cruzar_efos(db, hoy) == 0


async def test_cruzar_efos_no_duplica_al_re_correr(db: AsyncSession) -> None:
    """doc 06 §2.6: re-correr el cruce con el mismo detalle exacto no genera un segundo aviso."""
    empresa = await crear_empresa(db, rfc="XAXX010101000")
    await crear_comprobante(db, empresa_id=empresa.empresa_id, uuid="11111111-1111-1111-1111-111111111111", rfc_emisor="EKU9003173C9")

    hoy = date(2026, 7, 28)
    await lista_69b_repo.crear_version(db, hoy, [("EKU9003173C9", "definitivo")])
    await db.commit()

    primero = await riesgo_service.cruzar_efos(db, hoy)
    await db.commit()
    segundo = await riesgo_service.cruzar_efos(db, hoy)
    await db.commit()

    assert primero == 1
    assert segundo == 0
