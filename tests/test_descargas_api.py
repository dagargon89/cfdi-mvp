"""API de descargas/jobs (doc 05 §5) — 202/422/409/404, RBAC y anti-enumeración (IDOR).

El worker real (Celery/Redis) se reemplaza por un espía: esta capa solo prueba que la
API valida y persiste correctamente y encola — el procesamiento real ya se cubre a fondo
en `tests/test_worker.py`.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1 import descargas as descargas_router
from app.models.empresa import Empresa
from app.models.enums import EstadoJob, RolEmpresa, RolGlobal
from app.models.job import Job
from app.repositories import efirmas as efirmas_repo
from app.services import boveda
from tests._certs import generar_fiel_prueba
from tests.factories import asignar_permiso, crear_empresa, crear_usuario

pytestmark = pytest.mark.asyncio

_BODY = {"tipo": "recibido", "solicitud": "CFDI", "desde": "2026-01-01", "hasta": "2026-01-31"}


@pytest.fixture(autouse=True)
def _sin_worker_real(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(descargas_router, "ejecutar_job", SimpleNamespace(delay=lambda job_id: None))


async def _empresa_con_efirma(db: AsyncSession, rfc: str = "EKU9003173C9") -> Empresa:
    empresa = await crear_empresa(db, rfc=rfc)
    cer, key, password = generar_fiel_prueba(rfc=rfc)
    cifrada = boveda.preparar_efirma(cer, key, password, rfc)
    await efirmas_repo.upsert(db, empresa.empresa_id, cifrada)
    await db.commit()
    return empresa


async def test_crear_descarga_202(client: AsyncClient, db: AsyncSession) -> None:
    usuario = await crear_usuario(db, uid="uid-op", correo="op@demo.test", rol_global=RolGlobal.OPERADOR)
    empresa = await _empresa_con_efirma(db)
    await asignar_permiso(db, usuario, empresa, RolEmpresa.OPERADOR)

    r = await client.post(f"/v1/empresas/{empresa.empresa_id}/descargas", headers={"Authorization": "Bearer uid-op"}, json=_BODY)
    assert r.status_code == 202
    body = r.json()
    assert body["ventanas"] == 1
    assert len(body["job_ids"]) == 1


async def test_crear_descarga_sin_efirma_422(client: AsyncClient, db: AsyncSession) -> None:
    usuario = await crear_usuario(db, uid="uid-op2", correo="op2@demo.test", rol_global=RolGlobal.OPERADOR)
    empresa = await crear_empresa(db, rfc="EKU9003173C9")
    await asignar_permiso(db, usuario, empresa, RolEmpresa.OPERADOR)

    r = await client.post(f"/v1/empresas/{empresa.empresa_id}/descargas", headers={"Authorization": "Bearer uid-op2"}, json=_BODY)
    assert r.status_code == 422
    assert r.json()["error"]["codigo"] == "EFIRMA_AUSENTE"


async def test_consulta_no_puede_crear_descarga_403(client: AsyncClient, db: AsyncSession) -> None:
    usuario = await crear_usuario(db, uid="uid-con", correo="con@demo.test", rol_global=RolGlobal.CONSULTA)
    empresa = await _empresa_con_efirma(db)
    await asignar_permiso(db, usuario, empresa, RolEmpresa.CONSULTA)

    r = await client.post(f"/v1/empresas/{empresa.empresa_id}/descargas", headers={"Authorization": "Bearer uid-con"}, json=_BODY)
    assert r.status_code == 403


async def test_empresa_ajena_404_idor(client: AsyncClient, db: AsyncSession) -> None:
    await crear_usuario(db, uid="uid-ajeno", correo="ajeno@demo.test", rol_global=RolGlobal.OPERADOR)
    otra_empresa = await _empresa_con_efirma(db, rfc="XAXX010101000")  # sin permiso para uid-ajeno

    r = await client.post(f"/v1/empresas/{otra_empresa.empresa_id}/descargas", headers={"Authorization": "Bearer uid-ajeno"}, json=_BODY)
    assert r.status_code == 404


async def test_listar_jobs(client: AsyncClient, db: AsyncSession) -> None:
    usuario = await crear_usuario(db, uid="uid-op3", correo="op3@demo.test", rol_global=RolGlobal.OPERADOR)
    empresa = await _empresa_con_efirma(db)
    await asignar_permiso(db, usuario, empresa, RolEmpresa.OPERADOR)
    await client.post(f"/v1/empresas/{empresa.empresa_id}/descargas", headers={"Authorization": "Bearer uid-op3"}, json=_BODY)

    r = await client.get(f"/v1/empresas/{empresa.empresa_id}/jobs", headers={"Authorization": "Bearer uid-op3"})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["data"][0]["estado"] == "NUEVO"
    assert body["data"][0]["desde"] == "2026-01-01"


async def test_reintentar_job_no_error_409(client: AsyncClient, db: AsyncSession) -> None:
    """I8 (doc 06 §2.4): reintentar un job que no está en ERROR → 409."""
    usuario = await crear_usuario(db, uid="uid-op4", correo="op4@demo.test", rol_global=RolGlobal.OPERADOR)
    empresa = await _empresa_con_efirma(db)
    await asignar_permiso(db, usuario, empresa, RolEmpresa.OPERADOR)
    r_crear = await client.post(f"/v1/empresas/{empresa.empresa_id}/descargas", headers={"Authorization": "Bearer uid-op4"}, json=_BODY)
    job_id = r_crear.json()["job_ids"][0]  # queda en NUEVO — el worker está espiado, no corre

    r = await client.post(f"/v1/empresas/{empresa.empresa_id}/jobs/{job_id}/reintentar", headers={"Authorization": "Bearer uid-op4"})
    assert r.status_code == 409
    assert r.json()["error"]["codigo"] == "TRANSICION_ILEGAL"


async def test_reintentar_job_en_error_202(client: AsyncClient, db: AsyncSession) -> None:
    usuario = await crear_usuario(db, uid="uid-op5", correo="op5@demo.test", rol_global=RolGlobal.OPERADOR)
    empresa = await _empresa_con_efirma(db)
    await asignar_permiso(db, usuario, empresa, RolEmpresa.OPERADOR)
    r_crear = await client.post(f"/v1/empresas/{empresa.empresa_id}/descargas", headers={"Authorization": "Bearer uid-op5"}, json=_BODY)
    job_id = r_crear.json()["job_ids"][0]

    job = await db.get(Job, job_id)
    assert job is not None
    job.estado = EstadoJob.ERROR
    job.intentos = 60  # simula un job que ya agotó los reintentos antes de fallar
    await db.commit()

    r = await client.post(f"/v1/empresas/{empresa.empresa_id}/jobs/{job_id}/reintentar", headers={"Authorization": "Bearer uid-op5"})
    assert r.status_code == 202
    await db.refresh(job)
    assert job.estado is EstadoJob.NUEVO
    # una solicitud nueva merece un presupuesto de sondeo fresco — bug real visto en
    # producción: sin esto, un job reintentado casi de inmediato volvía a fallar por
    # "reintentos agotados" arrastrando el contador del intento anterior.
    assert job.intentos == 0
    assert job.id_solicitud is None


async def test_job_de_otra_empresa_404(client: AsyncClient, db: AsyncSession) -> None:
    usuario = await crear_usuario(db, uid="uid-op6", correo="op6@demo.test", rol_global=RolGlobal.OPERADOR)
    empresa_a = await _empresa_con_efirma(db, rfc="EKU9003173C9")
    empresa_b = await _empresa_con_efirma(db, rfc="XAXX010101000")
    await asignar_permiso(db, usuario, empresa_a, RolEmpresa.OPERADOR)
    await asignar_permiso(db, usuario, empresa_b, RolEmpresa.OPERADOR)

    r_crear = await client.post(f"/v1/empresas/{empresa_a.empresa_id}/descargas", headers={"Authorization": "Bearer uid-op6"}, json=_BODY)
    job_id = r_crear.json()["job_ids"][0]

    r = await client.get(f"/v1/empresas/{empresa_b.empresa_id}/jobs/{job_id}", headers={"Authorization": "Bearer uid-op6"})
    assert r.status_code == 404
