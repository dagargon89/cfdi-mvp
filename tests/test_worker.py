"""Worker: integración con SAT mockeado (doc 06 §2.5) — nunca importa `satcfdi` ni toca
la red; `SatFacade` se reemplaza por un doble en `app.worker.tasks`. La bóveda/Signer SÍ
son reales (e.firma de prueba cifrada de verdad) para ejercitar el descifrado completo.

El doble usa estado de CLASE (no de instancia): `_paso_polling`/`_paso_nuevo` construyen
un `SatFacade` nuevo en cada invocación de `paso_job` (nunca lo cachean, a propósito —
así nunca queda material descifrado vivo entre invocaciones), así que la progresión de
una prueba a través de varias llamadas debe sobrevivir ese "nuevo objeto cada vez".
"""

from __future__ import annotations

import asyncio
import base64
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.configuracion import Configuracion
from app.models.enums import EstadoJob, OrigenJob, SolicitudTipo, TipoJob
from app.models.job import Job
from app.repositories import efirmas as efirmas_repo
from app.sat_hub.errors import SatReintentableError
from app.sat_hub.sat_facade import ESTADO_ACEPTADA, ESTADO_EN_PROCESO, ESTADO_RECHAZADA, ESTADO_TERMINADA, ResultadoVerificacion
from app.services import boveda
from app.worker import tasks as worker_tasks
from tests._certs import generar_fiel_prueba
from tests.factories import crear_empresa

pytestmark = pytest.mark.asyncio


class FakeFacade:
    """Doble de `SatFacade` — nunca toca `satcfdi` ni el SAT real."""

    secuencia_verificar: list[ResultadoVerificacion] = []
    indice_verificar = 0
    llamadas_solicitar = 0

    def __init__(self, signer: object, rfc: str) -> None:
        self.rfc = rfc

    def solicitar(self, job: object) -> str:
        FakeFacade.llamadas_solicitar += 1
        return "ID-SOLICITUD-TEST"

    def verificar(self, id_solicitud: str) -> ResultadoVerificacion:
        idx = min(FakeFacade.indice_verificar, len(FakeFacade.secuencia_verificar) - 1)
        FakeFacade.indice_verificar += 1
        return FakeFacade.secuencia_verificar[idx]

    def descargar(self, id_paquete: str) -> tuple[dict[str, object], str]:
        return {}, base64.b64encode(f"contenido-{id_paquete}".encode()).decode()


@pytest.fixture()
def facade_fake(monkeypatch: pytest.MonkeyPatch) -> type[FakeFacade]:
    FakeFacade.secuencia_verificar = []
    FakeFacade.indice_verificar = 0
    FakeFacade.llamadas_solicitar = 0
    monkeypatch.setattr(worker_tasks, "SatFacade", FakeFacade)
    return FakeFacade


def _efirma_cifrada_sin_validar_vigencia(cer_bytes: bytes, key_bytes: bytes, password: str) -> boveda.EfirmaCifrada:
    """Igual que `boveda.preparar_efirma` pero SIN el chequeo de vigencia — para simular en
    la prueba una e.firma que era válida al darse de alta y venció después (nunca se llega
    a este estado vía la API real: `preparar_efirma` lo bloquea en el alta, RF-BOV-02)."""
    from app.services.fiel import cargar_signer

    signer = cargar_signer(cer_bytes, key_bytes, password)
    cert = signer.certificate
    if not hasattr(cert, "not_valid_after_utc") and hasattr(cert, "to_cryptography"):
        cert = cert.to_cryptography()
    not_before = getattr(cert, "not_valid_before_utc", None) or cert.not_valid_before.replace(tzinfo=timezone.utc)
    not_after = getattr(cert, "not_valid_after_utc", None) or cert.not_valid_after.replace(tzinfo=timezone.utc)
    dek = boveda.generar_dek()
    kek = boveda.cargar_kek()
    return boveda.EfirmaCifrada(
        num_serie=str(signer.serial_number),
        not_before=not_before,
        not_after=not_after,
        cer_pem=cer_bytes,
        key_cifrada=boveda.cifrar(dek, key_bytes),
        password_cifrada=boveda.cifrar(dek, password.encode()),
        dek_envuelta=boveda.envolver_dek(kek, dek),
    )


async def _crear_job_con_efirma(
    db: AsyncSession, *, estado: EstadoJob = EstadoJob.NUEVO, not_after: datetime | None = None, id_solicitud: str | None = None
) -> Job:
    empresa = await crear_empresa(db, rfc="EKU9003173C9")
    if not_after is not None:
        cer, key, password = generar_fiel_prueba(rfc="EKU9003173C9", not_before=datetime(2020, 1, 1), not_after=not_after)
        cifrada = _efirma_cifrada_sin_validar_vigencia(cer, key, password)
    else:
        cer, key, password = generar_fiel_prueba(rfc="EKU9003173C9")
        cifrada = boveda.preparar_efirma(cer, key, password, "EKU9003173C9")
    await efirmas_repo.upsert(db, empresa.empresa_id, cifrada)
    job = Job(
        empresa_id=empresa.empresa_id,
        tipo=TipoJob.RECIBIDO,
        solicitud=SolicitudTipo.CFDI,
        origen=OrigenJob.MANUAL,
        fecha_inicial=date(2026, 1, 1),
        fecha_final=date(2026, 1, 31),
        estado=estado,
        id_solicitud=id_solicitud,
        intentos=0,
        paquetes=1 if estado is not EstadoJob.NUEVO else 0,
    )
    db.add(job)
    await db.flush()
    await db.commit()
    return job


async def _set_config(db: AsyncSession, clave: str, valor: object) -> None:
    db.add(Configuracion(clave=clave, ejercicio_fiscal="vigente", valor=valor))
    await db.flush()
    await db.commit()


async def test_camino_feliz_completo(db: AsyncSession, facade_fake: type[FakeFacade]) -> None:
    job = await _crear_job_con_efirma(db)

    resultado_nuevo = await worker_tasks.paso_job(db, job.job_id)
    assert resultado_nuevo.siguiente == "reintentar"
    await db.refresh(job)
    assert job.estado is EstadoJob.SOLICITADO
    assert job.id_solicitud == "ID-SOLICITUD-TEST"

    facade_fake.secuencia_verificar = [
        ResultadoVerificacion(estado_solicitud=ESTADO_ACEPTADA),
        ResultadoVerificacion(estado_solicitud=ESTADO_EN_PROCESO),
        ResultadoVerificacion(estado_solicitud=ESTADO_TERMINADA, ids_paquetes=["PAQ-1"], num_cfdis=3),
    ]

    r1 = await worker_tasks.paso_job(db, job.job_id)
    assert r1.siguiente == "reintentar"
    await db.refresh(job)
    assert job.estado is EstadoJob.EN_PROCESO
    assert job.intentos == 1

    r2 = await worker_tasks.paso_job(db, job.job_id)
    assert r2.siguiente == "reintentar"
    await db.refresh(job)
    assert job.estado is EstadoJob.EN_PROCESO
    assert job.intentos == 2

    r3 = await worker_tasks.paso_job(db, job.job_id)
    assert r3.siguiente == "hecho"
    await db.refresh(job)
    assert job.estado is EstadoJob.DESCARGADO
    assert job.paquetes == 1
    assert facade_fake.llamadas_solicitar == 1  # nunca se re-solicita (RF-DESC-04)


async def test_reintentos_agotados_pasa_a_error(db: AsyncSession, facade_fake: type[FakeFacade]) -> None:
    await _set_config(db, "max_reintentos", 3)
    job = await _crear_job_con_efirma(db, estado=EstadoJob.SOLICITADO, id_solicitud="ID-YA-SOLICITADO")
    facade_fake.secuencia_verificar = [ResultadoVerificacion(estado_solicitud=ESTADO_EN_PROCESO)]

    resultado = None
    for _ in range(3):
        resultado = await worker_tasks.paso_job(db, job.job_id)

    await db.refresh(job)
    assert resultado is not None and resultado.siguiente == "hecho"
    assert job.estado is EstadoJob.ERROR
    assert "reintentos" in (job.mensaje or "")


async def test_rechazo_definitivo_pasa_a_error(db: AsyncSession, facade_fake: type[FakeFacade]) -> None:
    job = await _crear_job_con_efirma(db, estado=EstadoJob.SOLICITADO, id_solicitud="ID-X")
    facade_fake.secuencia_verificar = [ResultadoVerificacion(estado_solicitud=ESTADO_RECHAZADA, mensaje="Rechazado por el SAT")]

    resultado = await worker_tasks.paso_job(db, job.job_id)
    await db.refresh(job)
    assert resultado.siguiente == "hecho"
    assert job.estado is EstadoJob.ERROR
    assert job.mensaje == "Rechazado por el SAT"


async def test_sin_resultados_pasa_a_descargado_con_cero_paquetes(db: AsyncSession, facade_fake: type[FakeFacade]) -> None:
    """CodEstatus=5004 ("No se encontró la información") es un éxito documentado del SAT, no
    un error — visto en producción con una solicitud de METADATA para un mes sin comprobantes.
    EstadoSolicitud llega en 0 (fuera del catálogo 1-6), pero no debe tratarse como error ni
    como "en proceso"."""
    job = await _crear_job_con_efirma(db, estado=EstadoJob.SOLICITADO, id_solicitud="ID-X")
    facade_fake.secuencia_verificar = [ResultadoVerificacion(estado_solicitud=0, mensaje="No se encontro la informacion", cod_estatus="5004")]

    resultado = await worker_tasks.paso_job(db, job.job_id)
    await db.refresh(job)
    assert resultado.siguiente == "hecho"
    assert job.estado is EstadoJob.DESCARGADO
    assert job.paquetes == 0
    assert job.mensaje is None


async def test_paquete_vacio_pasa_a_error_con_detalle_del_sat(db: AsyncSession, facade_fake: type[FakeFacade]) -> None:
    """El SAT reporta la solicitud TERMINADA con un id de paquete, pero al descargarlo devuelve
    el <Paquete> vacío (base64 = None). El motivo real llega en el encabezado (CodEstatus/Mensaje);
    el job debe pasar a ERROR con ESE detalle, no reventar con el opaco 'not NoneType' de base64."""
    job = await _crear_job_con_efirma(db, estado=EstadoJob.SOLICITADO, id_solicitud="ID-X")

    class FacadePaqueteVacio(FakeFacade):
        def descargar(self, id_paquete: str) -> tuple[dict[str, object], str | None]:
            return {"CodEstatus": "5002", "Mensaje": "Se han agotado las solicitudes de por vida"}, None

    worker_tasks.SatFacade = FacadePaqueteVacio  # type: ignore[misc,assignment]
    FakeFacade.secuencia_verificar = [ResultadoVerificacion(estado_solicitud=ESTADO_TERMINADA, ids_paquetes=["PAQ-1"], num_cfdis=1)]

    resultado = await worker_tasks.paso_job(db, job.job_id)
    await db.refresh(job)
    assert resultado.siguiente == "hecho"
    assert job.estado is EstadoJob.ERROR
    assert "5002" in (job.mensaje or "")
    assert "Se han agotado las solicitudes de por vida" in (job.mensaje or "")
    assert "NoneType" not in (job.mensaje or "")  # el error opaco de base64 no debe filtrarse


async def test_estado_no_catalogado_con_mensaje_pasa_a_error(db: AsyncSession, facade_fake: type[FakeFacade]) -> None:
    """Visto en producción con una solicitud de METADATA: el SAT respondió
    EstadoSolicitud=0/CodEstatus=404/"Error no controlado" en cada sondeo durante más de una
    hora, sin variar nunca. Un código no catalogado CON mensaje no es "sigue en proceso" —
    debe pasar a ERROR de inmediato, no agotar los 60 reintentos con un mensaje genérico."""
    job = await _crear_job_con_efirma(db, estado=EstadoJob.SOLICITADO, id_solicitud="ID-X")
    facade_fake.secuencia_verificar = [ResultadoVerificacion(estado_solicitud=0, mensaje="Error no controlado.")]

    resultado = await worker_tasks.paso_job(db, job.job_id)
    await db.refresh(job)
    assert resultado.siguiente == "hecho"
    assert job.estado is EstadoJob.ERROR
    assert "Error no controlado" in (job.mensaje or "")


async def test_estado_no_catalogado_con_mensaje_se_recupera_en_el_margen_de_gracia(db: AsyncSession, facade_fake: type[FakeFacade]) -> None:
    """Visto también en producción: el mismo `id_solicitud` respondió error/éxito/error en
    menos de un minuto. El margen de gracia in-proceso debe absorber un "parpadeo" que se
    recupera solo, sin fallar el job de inmediato."""
    job = await _crear_job_con_efirma(db, estado=EstadoJob.SOLICITADO, id_solicitud="ID-X")
    facade_fake.secuencia_verificar = [
        ResultadoVerificacion(estado_solicitud=0, mensaje="Error no controlado."),
        ResultadoVerificacion(estado_solicitud=ESTADO_ACEPTADA),
    ]

    resultado = await worker_tasks.paso_job(db, job.job_id)
    await db.refresh(job)
    assert resultado.siguiente == "reintentar"
    assert job.estado is EstadoJob.EN_PROCESO


async def test_estado_no_catalogado_sin_mensaje_sigue_en_proceso(db: AsyncSession, facade_fake: type[FakeFacade]) -> None:
    """Un código no catalogado SIN mensaje (silencio, no un error explícito) sigue tratándose
    como transitorio — es el caso ya visto en producción que se auto-resolvió solo."""
    job = await _crear_job_con_efirma(db, estado=EstadoJob.SOLICITADO, id_solicitud="ID-X")
    facade_fake.secuencia_verificar = [ResultadoVerificacion(estado_solicitud=0, mensaje=None)]

    resultado = await worker_tasks.paso_job(db, job.job_id)
    await db.refresh(job)
    assert resultado.siguiente == "reintentar"
    assert job.estado is EstadoJob.EN_PROCESO


async def test_efirma_vencida_pasa_a_error_sin_solicitar(db: AsyncSession, facade_fake: type[FakeFacade]) -> None:
    vencida = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
    job = await _crear_job_con_efirma(db, not_after=vencida)

    resultado = await worker_tasks.paso_job(db, job.job_id)
    await db.refresh(job)
    assert resultado.siguiente == "hecho"
    assert job.estado is EstadoJob.ERROR
    assert facade_fake.llamadas_solicitar == 0  # nunca se llegó a construir el facade


async def test_intermitencia_transitoria_se_recupera_sin_error(db: AsyncSession, facade_fake: type[FakeFacade]) -> None:
    job = await _crear_job_con_efirma(db, estado=EstadoJob.SOLICITADO, id_solicitud="ID-X")

    class FacadeIntermitente(FakeFacade):
        fallos_restantes = 1

        def verificar(self, id_solicitud: str) -> ResultadoVerificacion:
            if FacadeIntermitente.fallos_restantes > 0:
                FacadeIntermitente.fallos_restantes -= 1
                raise SatReintentableError("Timeout del WS del SAT.")
            return super().verificar(id_solicitud)

    worker_tasks.SatFacade = FacadeIntermitente  # type: ignore[misc,assignment]
    FakeFacade.secuencia_verificar = [ResultadoVerificacion(estado_solicitud=ESTADO_EN_PROCESO)]

    with pytest.raises(SatReintentableError):
        await worker_tasks.paso_job(db, job.job_id)
    await db.refresh(job)
    assert job.estado is EstadoJob.SOLICITADO  # sin cambios: el job no se corrompe

    resultado = await worker_tasks.paso_job(db, job.job_id)
    await db.refresh(job)
    assert resultado.siguiente == "reintentar"
    assert job.estado is EstadoJob.EN_PROCESO


async def test_ejecutar_job_adaptador_celery(
    db: AsyncSession, facade_fake: type[FakeFacade], monkeypatch: pytest.MonkeyPatch, mysql_url: str
) -> None:
    """Smoke test del adaptador Celery real (`ejecutar_job`) — usa una e.firma vencida a
    propósito para que el paso termine en un solo `paso_job` sin pasar por `self.retry()`
    (la progresión NUEVO→...→DESCARGADO ya se prueba arriba llamando `paso_job` directamente).

    `ejecutar_job` hace `asyncio.run(...)` por diseño (así es como corre de verdad dentro
    de un worker de Celery, que no tiene loop propio) — por eso se invoca en un hilo aparte
    con un engine propio: llamarlo en el loop de la prueba (`asyncio.run` anidado) o
    reusando el engine/conexión del fixture `db` (loop distinto al del hilo) rompería.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    vencida = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
    job = await _crear_job_con_efirma(db, not_after=vencida)

    engine_aislado = create_async_engine(mysql_url)
    monkeypatch.setattr(worker_tasks, "SessionLocal", async_sessionmaker(engine_aislado, expire_on_commit=False))

    await asyncio.to_thread(lambda: worker_tasks.ejecutar_job.apply(args=[job.job_id]).get())

    await db.refresh(job)
    assert job.estado is EstadoJob.ERROR


async def test_reanudacion_no_duplica_solicitud(db: AsyncSession, facade_fake: type[FakeFacade]) -> None:
    """Simula un worker que muere tras NUEVO→SOLICITADO y otro que retoma el job:
    la segunda invocación nunca vuelve a llamar `solicitar()` (RF-DESC-04)."""
    job = await _crear_job_con_efirma(db)
    await worker_tasks.paso_job(db, job.job_id)
    await db.refresh(job)
    id_solicitud_original = job.id_solicitud
    assert facade_fake.llamadas_solicitar == 1

    facade_fake.secuencia_verificar = [ResultadoVerificacion(estado_solicitud=ESTADO_EN_PROCESO)]
    await worker_tasks.paso_job(db, job.job_id)  # "otro worker" retoma el mismo job_id
    await db.refresh(job)
    assert job.id_solicitud == id_solicitud_original
    assert facade_fake.llamadas_solicitar == 1  # sin segunda solicitud
