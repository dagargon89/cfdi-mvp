"""Endpoints de informes (spec §7.2) y el pre-vuelo del ETL (disparador 3, spec §6.3)."""

from __future__ import annotations

import io
import os

import pytest
from openpyxl import load_workbook
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.models.enums import RolEmpresa, RolGlobal
from app.worker import tasks as worker_tasks
from tests import factories, fixtures_cfdi


@pytest.fixture(autouse=True)
def _sesion_de_prueba_en_worker(engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch) -> None:
    """`worker_tasks.SessionLocal` apunta a `DATABASE_URL` (placeholder en pruebas): la
    tarea de generación de informes se ejerce aquí llamando su lógica async directo (sin
    `asyncio.run`/Celery), así que basta apuntarlo al mismo engine que usa el fixture `db`
    (testcontainer real) — mismo patrón que `test_worker_comprobantes.py`."""
    monkeypatch.setattr(worker_tasks, "SessionLocal", async_sessionmaker(engine, expire_on_commit=False))


async def test_catalogo_expone_b02_con_su_json_schema(client, db: AsyncSession) -> None:  # type: ignore[no-untyped-def]
    await factories.crear_usuario(db, uid="op", correo="op@test.mx", rol_global=RolGlobal.OPERADOR)

    r = await client.get("/v1/informes", headers={"Authorization": "Bearer op"})
    assert r.status_code == 200, r.text
    claves = {i["clave"]: i for i in r.json()}
    assert "B-02" in claves
    b02 = claves["B-02"]
    assert b02["grupo"] == "B"
    # El frontend arma el formulario desde aquí: los parámetros deben venir descritos.
    propiedades = b02["parametros"]["properties"]
    assert "fecha_desde" in propiedades
    assert propiedades["enmascarar_datos_personales"]["default"] is True


async def test_generar_informe_encola_con_los_parametros(client, db: AsyncSession, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from app.worker import tasks

    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    usuario = await factories.crear_usuario(db, uid="con", correo="con@test.mx", rol_global=RolGlobal.CONSULTA)
    await factories.asignar_permiso(db, usuario, empresa, RolEmpresa.CONSULTA)

    encoladas: list[tuple[int, str, dict, str]] = []

    class _Tarea:
        id = "tarea-informe"

    monkeypatch.setattr(
        tasks.generar_informe,
        "delay",
        lambda empresa_id, clave, parametros, actor: (encoladas.append((empresa_id, clave, parametros, actor)), _Tarea())[1],
    )

    r = await client.post(
        f"/v1/empresas/{empresa.empresa_id}/informes/B-02",
        json={"fecha_desde": "2026-06-01", "fecha_hasta": "2026-07-31"},
        headers={"Authorization": "Bearer con"},
    )
    assert r.status_code == 202, r.text
    assert r.json()["tarea_id"] == "tarea-informe"
    assert encoladas[0][1] == "B-02"
    assert encoladas[0][2]["fecha_desde"] == "2026-06-01"
    assert encoladas[0][3] == "con@test.mx"


async def test_clave_desconocida_da_404(client, db: AsyncSession) -> None:
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    usuario = await factories.crear_usuario(db, uid="con", correo="con@test.mx", rol_global=RolGlobal.CONSULTA)
    await factories.asignar_permiso(db, usuario, empresa, RolEmpresa.CONSULTA)

    r = await client.post(
        f"/v1/empresas/{empresa.empresa_id}/informes/Z-99",
        json={"fecha_desde": "2026-06-01", "fecha_hasta": "2026-07-31"},
        headers={"Authorization": "Bearer con"},
    )
    assert r.status_code == 404


async def test_parametros_invalidos_dan_422(client, db: AsyncSession) -> None:
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    usuario = await factories.crear_usuario(db, uid="con", correo="con@test.mx", rol_global=RolGlobal.CONSULTA)
    await factories.asignar_permiso(db, usuario, empresa, RolEmpresa.CONSULTA)

    r = await client.post(
        f"/v1/empresas/{empresa.empresa_id}/informes/B-02",
        json={"fecha_desde": "no-es-fecha"},
        headers={"Authorization": "Bearer con"},
    )
    assert r.status_code == 422


async def test_sin_enmascarar_exige_operador_y_deja_bitacora(client, db: AsyncSession, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """spec §8."""
    from sqlalchemy import select

    from app.models.bitacora import Bitacora
    from app.worker import tasks

    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    consulta = await factories.crear_usuario(db, uid="con", correo="con@test.mx", rol_global=RolGlobal.CONSULTA)
    await factories.asignar_permiso(db, consulta, empresa, RolEmpresa.CONSULTA)
    operador = await factories.crear_usuario(db, uid="op", correo="op@test.mx", rol_global=RolGlobal.OPERADOR)
    await factories.asignar_permiso(db, operador, empresa, RolEmpresa.OPERADOR)

    class _Tarea:
        id = "t"

    monkeypatch.setattr(tasks.generar_informe, "delay", lambda *a, **k: _Tarea())

    cuerpo = {"fecha_desde": "2026-06-01", "fecha_hasta": "2026-07-31", "enmascarar_datos_personales": False}

    r = await client.post(f"/v1/empresas/{empresa.empresa_id}/informes/B-02", json=cuerpo, headers={"Authorization": "Bearer con"})
    assert r.status_code == 403

    r = await client.post(f"/v1/empresas/{empresa.empresa_id}/informes/B-02", json=cuerpo, headers={"Authorization": "Bearer op"})
    assert r.status_code == 202

    registros = list((await db.execute(select(Bitacora).where(Bitacora.accion == "generar_informe"))).scalars().all())
    assert registros, "la generación sin enmascarar debe quedar en bitácora"
    assert registros[-1].detalle["enmascarar_datos_personales"] is False


async def test_tarea_genera_libro_y_normaliza_lo_pendiente(db: AsyncSession) -> None:
    """Pre-vuelo: el comprobante existe en `comprobantes` pero nunca se normalizó. La
    tarea lo normaliza antes de consultar, así que el informe NO sale vacío."""
    from app.worker.tasks import _generar_informe_async

    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    carpeta = os.path.join(get_settings().storage_root, str(empresa.empresa_id), "comprobantes")
    os.makedirs(carpeta, exist_ok=True)
    with open(os.path.join(carpeta, "nomina.xml"), "wb") as f:
        f.write(fixtures_cfdi.cfdi_nomina())
    await factories.crear_comprobante(
        db,
        empresa_id=empresa.empresa_id,
        uuid="77777777-7777-7777-7777-777777777777",
        tipo_comprobante="N",
        xml_path=os.path.join(str(empresa.empresa_id), "comprobantes", "nomina.xml"),
    )

    resultado = await _generar_informe_async(
        empresa.empresa_id,
        "B-02",
        {"fecha_desde": "2026-06-01", "fecha_hasta": "2026-07-31"},
        "op@test.mx",
    )

    assert resultado["filas"] == 1
    ruta = os.path.join(get_settings().storage_root, resultado["ruta"])
    assert os.path.isfile(ruta)

    with open(ruta, "rb") as f:
        wb = load_workbook(io.BytesIO(f.read()))
    assert wb.sheetnames == ["Datos", "Parámetros", "Banderas", "Diccionario"]
    datos = wb["Datos"]
    encabezados = [c.value for c in datos[1]]
    assert "UUID" in encabezados
    assert any("Sueldo" in (t or "") for t in encabezados)
