"""PDF, "Detalle del CFDI" y `.zip` por comprobante (RF-RES-03/D2) — sin red, 100% local
(satcfdi.render + weasyprint)."""

from __future__ import annotations

import zipfile
from datetime import datetime, timezone
from io import BytesIO

from app.models.comprobante import Comprobante
from app.models.enums import EstatusCfdi
from app.services.representaciones import generar_detalle, generar_paquete_zip, generar_pdf
from tests.test_resguardo import _xml


def test_generar_pdf_produce_un_pdf_valido() -> None:
    pdf = generar_pdf(_xml("dcac7a17-4932-0d4b-88ec-a88704d354f0"))
    assert pdf.startswith(b"%PDF-")
    assert len(pdf) > 500


def test_generar_detalle_produce_un_pdf_valido() -> None:
    detalle = generar_detalle(_xml("dcac7a17-4932-0d4b-88ec-a88704d354f0"), EstatusCfdi.VIGENTE)
    assert detalle.startswith(b"%PDF-")
    assert len(detalle) > 200


def test_generar_detalle_no_truena_sin_impuestos() -> None:
    """El XML sintético de prueba no trae `Impuestos` a nivel comprobante — el Detalle debe
    generarse igual (campos en blanco), sin excepción."""
    detalle = generar_detalle(_xml("11111111-1111-1111-1111-111111111111"), EstatusCfdi.NO_VERIFICADO)
    assert detalle.startswith(b"%PDF-")


def test_generar_paquete_zip_contiene_los_3_archivos() -> None:
    xml_bytes = _xml("22222222-2222-2222-2222-222222222222", folio="42")
    comprobante = Comprobante(
        comprobante_id=1,
        empresa_id=1,
        uuid="22222222-2222-2222-2222-222222222222",
        folio="42",
        rfc_emisor="EKU9003173C9",
        rfc_receptor="XAXX010101000",
        razon_social_emisor="EMISOR DE PRUEBA SA DE CV",
        total=1160.0,
        fecha_emision=datetime(2026, 1, 15, 12, 0),
        tipo_comprobante="I",
        estatus=EstatusCfdi.VIGENTE,
        estatus_verificado_at=datetime(2026, 7, 28, tzinfo=timezone.utc).replace(tzinfo=None),
        xml_path="1/comprobantes/prueba.xml",
    )

    paquete = generar_paquete_zip(comprobante, xml_bytes)
    with zipfile.ZipFile(BytesIO(paquete)) as zf:
        nombres = set(zf.namelist())
        assert nombres == {
            "22222222-2222-2222-2222-222222222222.xml",
            "22222222-2222-2222-2222-222222222222.pdf",
            "22222222-2222-2222-2222-222222222222_detalle.pdf",
        }
        assert zf.read("22222222-2222-2222-2222-222222222222.xml") == xml_bytes
        assert zf.read("22222222-2222-2222-2222-222222222222.pdf").startswith(b"%PDF-")
        assert zf.read("22222222-2222-2222-2222-222222222222_detalle.pdf").startswith(b"%PDF-")
