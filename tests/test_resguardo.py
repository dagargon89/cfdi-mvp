"""Resguardo e índice (RF-RES-01/02/03, doc 06 §2.5 "resguardo encadenado")."""

from __future__ import annotations

import os
import shutil
import zipfile
from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.comprobante import Comprobante
from app.models.enums import EstatusCfdi, OrigenJob, SolicitudTipo, TipoJob
from app.models.job import Job
from app.sat_hub.sat_facade import parse_cfdi
from app.services.resguardo import indexar_job, render_nombre, sanear_nombre_archivo
from tests.factories import crear_empresa

@pytest.fixture(autouse=True)
def _storage_limpio() -> None:
    """`STORAGE_ROOT` es un directorio real que sobrevive entre pruebas, pero `empresa_id`/
    `job_id` se reinician en cada `db` (AUTO_INCREMENT desde 1 tras drop_all/create_all) — sin
    esto, una prueba podría "encontrar" el zip que dejó otra bajo la misma ruta numérica."""
    root = get_settings().storage_root
    shutil.rmtree(root, ignore_errors=True)
    os.makedirs(root, exist_ok=True)

_XML_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4" xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
  Version="4.0" Fecha="2026-01-15T12:00:00" Folio="{folio}" Total="1160.00" SubTotal="1000.00"
  TipoDeComprobante="I" Moneda="MXN" LugarExpedicion="64000" Sello="X" NoCertificado="12345" Certificado="X"
  MetodoPago="PUE" FormaPago="01" Exportacion="01">
  <cfdi:Emisor Rfc="EKU9003173C9" Nombre="{razon_social}" RegimenFiscal="601"/>
  <cfdi:Receptor Rfc="XAXX010101000" Nombre="PUBLICO EN GENERAL" DomicilioFiscalReceptor="64000" RegimenFiscalReceptor="616" UsoCFDI="G03"/>
  <cfdi:Conceptos>
    <cfdi:Concepto ClaveProdServ="01010101" Cantidad="1" ClaveUnidad="H87" Descripcion="Prueba" ValorUnitario="1000.00" Importe="1000.00" ObjetoImp="02"/>
  </cfdi:Conceptos>
  <cfdi:Complemento>
    <tfd:TimbreFiscalDigital Version="1.1" UUID="{uuid}" FechaTimbrado="2026-01-15T12:00:01"
      RfcProvCertif="SAT970701NN3" SelloCFD="X" NoCertificadoSAT="30001000000400002495" SelloSAT="X"/>
  </cfdi:Complemento>
</cfdi:Comprobante>
"""


def _xml(uuid: str, *, folio: str = "1", razon_social: str = "EMISOR DE PRUEBA SA DE CV") -> bytes:
    return _XML_TEMPLATE.format(uuid=uuid, folio=folio, razon_social=razon_social).encode()


def test_parse_cfdi_fixture_sanity() -> None:
    """El propio XML sintético de prueba debe ser parseable — si esto falla, las pruebas de
    abajo fallarían por una razón ajena al resguardo (fixture rota, no bug real)."""
    campos = parse_cfdi(_xml("dcac7a17-4932-0d4b-88ec-a88704d354f0"))
    assert campos.uuid == "DCAC7A17-4932-0D4B-88EC-A88704D354F0"
    assert campos.rfc_emisor == "EKU9003173C9"


@pytest.mark.parametrize(
    "valor,no_debe_contener",
    [
        ("../../etc/passwd", "/"),
        ("nombre\\con\\barras", "\\"),
        ('nombre:con*caracteres?"invalidos<>|', ":"),
    ],
)
def test_sanear_nombre_archivo_quita_separadores(valor: str, no_debe_contener: str) -> None:
    limpio = sanear_nombre_archivo(valor)
    assert no_debe_contener not in limpio
    assert "/" not in limpio and "\\" not in limpio


def test_render_nombre_con_tokens_conocidos() -> None:
    campos = parse_cfdi(_xml("dcac7a17-4932-0d4b-88ec-a88704d354f0", folio="99", razon_social="ACME SA"))
    nombre = render_nombre("{razon_social}_{folio}_V", campos, EstatusCfdi.NO_VERIFICADO)
    assert nombre == "ACME SA_99_V.xml"


def test_render_nombre_con_traversal_no_escapa_directorio() -> None:
    campos = parse_cfdi(_xml("dcac7a17-4932-0d4b-88ec-a88704d354f0"))
    nombre = render_nombre("../../../{razon_social}", campos, EstatusCfdi.NO_VERIFICADO)
    assert "/" not in nombre and "\\" not in nombre
    assert not nombre.startswith("..")


def test_render_nombre_con_token_desconocido_no_truena() -> None:
    campos = parse_cfdi(_xml("dcac7a17-4932-0d4b-88ec-a88704d354f0", razon_social="ACME"))
    nombre = render_nombre("{token_inexistente}", campos, EstatusCfdi.NO_VERIFICADO)
    assert nombre.endswith(".xml")
    assert "ACME" in nombre  # cae al fallback razon_social_uuid_last4


async def _crear_job(db: AsyncSession, empresa_id: int) -> Job:
    job = Job(
        empresa_id=empresa_id,
        tipo=TipoJob.RECIBIDO,
        solicitud=SolicitudTipo.CFDI,
        origen=OrigenJob.MANUAL,
        fecha_inicial=date(2026, 1, 1),
        fecha_final=date(2026, 1, 31),
        paquetes=1,
    )
    db.add(job)
    await db.flush()
    await db.commit()
    return job


def _escribir_paquete_con_xmls(empresa_id: int, job_id: int, xmls: dict[str, bytes]) -> None:
    carpeta = os.path.join(get_settings().storage_root, str(empresa_id), str(job_id))
    os.makedirs(carpeta, exist_ok=True)
    with zipfile.ZipFile(os.path.join(carpeta, "paquete_1.zip"), "w") as zf:
        for nombre, contenido in xmls.items():
            zf.writestr(nombre, contenido)


async def test_indexar_job_es_idempotente(db: AsyncSession) -> None:
    empresa = await crear_empresa(db, rfc="EKU9003173C9")
    job = await _crear_job(db, empresa.empresa_id)
    _escribir_paquete_con_xmls(
        empresa.empresa_id,
        job.job_id,
        {
            "a.xml": _xml("11111111-1111-1111-1111-111111111111", folio="1"),
            "b.xml": _xml("22222222-2222-2222-2222-222222222222", folio="2"),
        },
    )

    nuevos_1 = await indexar_job(db, job, empresa)
    assert nuevos_1 == 2

    nuevos_2 = await indexar_job(db, job, empresa)
    assert nuevos_2 == 0  # re-ejecutar no duplica

    filas = (await db.scalars(select(Comprobante).where(Comprobante.empresa_id == empresa.empresa_id))).all()
    assert len(filas) == 2
    for fila in filas:
        assert fila.xml_path is not None
        ruta_absoluta = os.path.join(get_settings().storage_root, fila.xml_path)
        assert os.path.isfile(ruta_absoluta)


async def test_indexar_job_xml_corrupto_no_aborta_el_lote(db: AsyncSession) -> None:
    empresa = await crear_empresa(db, rfc="EKU9003173C9")
    job = await _crear_job(db, empresa.empresa_id)
    _escribir_paquete_con_xmls(
        empresa.empresa_id,
        job.job_id,
        {
            "valido.xml": _xml("33333333-3333-3333-3333-333333333333"),
            "corrupto.xml": b"<esto no es un cfdi valido",
        },
    )

    nuevos = await indexar_job(db, job, empresa)
    assert nuevos == 1

    filas = (await db.scalars(select(Comprobante).where(Comprobante.empresa_id == empresa.empresa_id))).all()
    assert len(filas) == 1
    assert filas[0].uuid == "33333333-3333-3333-3333-333333333333"


async def test_indexar_job_sin_paquetes_en_disco_no_truena(db: AsyncSession) -> None:
    empresa = await crear_empresa(db, rfc="EKU9003173C9")
    job = await _crear_job(db, empresa.empresa_id)
    nuevos = await indexar_job(db, job, empresa)
    assert nuevos == 0
