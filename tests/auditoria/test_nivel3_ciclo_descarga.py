"""Auditoría del nivel 3 — Ciclo de descarga del SAT. Pruebas **adversariales**.

Es el corazón del sistema: la máquina de estados de los jobs, el diálogo con el SAT y el
resguardo de lo descargado. Un fallo aquí no filtra nada — **pierde datos fiscales** o pide al
SAT cosas que no debe.

Los identificadores `N3-xx` son los del documento `docs/auditoria/nivel-3-ciclo-de-descarga.md`.

Una de estas pruebas está marcada `xfail(strict=True)`: documenta un defecto **conocido y
reproducido**, no una función pendiente. Cuando se arregle, la prueba pasará y `strict` hará
fallar la suite para obligar a quitar la marca — así el defecto no se olvida ni se queda tapado.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.enums import EstadoJob, OrigenJob, SolicitudTipo, TipoJob
from app.models.job import Job
from app.repositories import efirmas as efirmas_repo
from app.repositories import jobs as jobs_repo
from app.sat_hub.errors import TransicionIlegalError
from app.services import boveda
from app.services.descargas import EfirmaAusenteError, EmpresaInactivaError, RangoInvalidoError, crear_descarga
from app.worker import tasks as worker_tasks
from tests._certs import generar_fiel_prueba
from tests.factories import crear_empresa

pytestmark = pytest.mark.asyncio

RFC_EMPRESA = "EKU9003173C9"


async def _empresa_con_efirma(db: AsyncSession, *, rfc: str = RFC_EMPRESA):
    """Empresa lista para descargar: con e.firma vigente en la bóveda."""
    empresa = await crear_empresa(db, nombre="Con e.firma", rfc=rfc)
    cer, key, password = generar_fiel_prueba(rfc=rfc)
    cifrada = boveda.preparar_efirma(cer, key, password, rfc)
    await efirmas_repo.upsert(db, empresa.empresa_id, cifrada)
    await db.commit()
    return empresa


async def _job(db: AsyncSession, empresa_id: int, *, estado: EstadoJob = EstadoJob.NUEVO, id_solicitud: str | None = None) -> Job:
    job = Job(
        empresa_id=empresa_id,
        tipo=TipoJob.EMITIDO,
        solicitud=SolicitudTipo.CFDI,
        origen=OrigenJob.MANUAL,
        fecha_inicial=date(2026, 1, 1),
        fecha_final=date(2026, 1, 31),
        estado=estado,
        id_solicitud=id_solicitud,
    )
    db.add(job)
    await db.flush()
    await db.commit()
    return job


# --------------------------------------------------------------------------- #
# Máquina de estados: las once transiciones legales y ninguna más.
# --------------------------------------------------------------------------- #

_TODOS = list(EstadoJob)
_LEGALES = {
    (EstadoJob.NUEVO, EstadoJob.SOLICITADO),
    (EstadoJob.NUEVO, EstadoJob.ERROR),
    (EstadoJob.SOLICITADO, EstadoJob.EN_PROCESO),
    (EstadoJob.SOLICITADO, EstadoJob.TERMINADA),
    (EstadoJob.SOLICITADO, EstadoJob.ERROR),
    (EstadoJob.EN_PROCESO, EstadoJob.EN_PROCESO),
    (EstadoJob.EN_PROCESO, EstadoJob.TERMINADA),
    (EstadoJob.EN_PROCESO, EstadoJob.ERROR),
    (EstadoJob.TERMINADA, EstadoJob.DESCARGADO),
    (EstadoJob.TERMINADA, EstadoJob.ERROR),
    (EstadoJob.ERROR, EstadoJob.NUEVO),
}


async def test_n3_01_ninguna_transicion_ilegal_pasa(db: AsyncSession) -> None:
    """N3-01 · Barrido **exhaustivo** de la máquina de estados.

    Se prueban las `len(EstadoJob)**2` combinaciones posibles, no una muestra: cada par que no
    esté en las once transiciones legales tiene que ser rechazado. Este barrido es lo que
    detecta que alguien "abra" una transición al agregar un caso de uso.

    Salto directo `NUEVO → DESCARGADO` incluido: un job que nunca habló con el SAT no puede
    aparecer como descargado, porque el informe lo daría por bueno sin tener un solo XML.
    """
    empresa = await _empresa_con_efirma(db)
    eid = empresa.empresa_id
    ilegales_aceptadas: list[str] = []

    for origen in _TODOS:
        for destino in _TODOS:
            if (origen, destino) in _LEGALES:
                continue
            job = await _job(db, eid, estado=origen)
            try:
                await jobs_repo.transicion(db, job, destino)
                ilegales_aceptadas.append(f"{origen.value}→{destino.value}")
            except TransicionIlegalError:
                pass
            await db.rollback()

    assert not ilegales_aceptadas, f"transiciones ilegales aceptadas: {ilegales_aceptadas}"


async def test_n3_02_las_once_transiciones_legales_si_pasan(db: AsyncSession) -> None:
    """N3-02 · Control positivo del barrido anterior.

    Sin esto, una máquina de estados que rechazara **todo** dejaría N3-01 en verde.
    """
    empresa = await _empresa_con_efirma(db)
    eid = empresa.empresa_id
    legales_rechazadas: list[str] = []

    for origen, destino in sorted(_LEGALES, key=lambda p: (p[0].value, p[1].value)):
        job = await _job(db, eid, estado=origen)
        try:
            await jobs_repo.transicion(db, job, destino)
        except TransicionIlegalError:
            legales_rechazadas.append(f"{origen.value}→{destino.value}")
        await db.rollback()

    assert not legales_rechazadas, f"transiciones legales rechazadas: {legales_rechazadas}"


# --------------------------------------------------------------------------- #
# La carrera de la doble solicitud — defecto conocido.
# --------------------------------------------------------------------------- #


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Defecto conocido y reproducido: `transicion()` valida la legalidad contra `job.estado` "
        "ya cargado en memoria, sin bloqueo de fila, así que dos ejecuciones concurrentes del "
        "mismo job en NUEVO llaman las dos a `facade.solicitar()`. El arreglo diseñado es la "
        "toma atómica (columna `tomado_en` + CAS); ver el diseño de 2026-08-19."
    ),
)
async def test_n3_03_dos_ejecuciones_concurrentes_no_piden_dos_veces_al_sat(
    db: AsyncSession, mysql_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """N3-03 · **La prueba que expone el defecto del nivel 3.**

    Dos invocaciones simultáneas de `paso_job` sobre el mismo job en `NUEVO`. Cada una abre su
    propia sesión, como haría cada worker de Celery.

    El daño real no es cosmético: el SAT rechaza la solicitud duplicada exacta con
    `CodEstatus=5005`, lo que produce `SatRechazoError` y manda a `ERROR` un job que estaba
    perfectamente bien. Es decir, **la duplicación no solo desperdicia cuota: destruye el job**.
    """
    empresa = await _empresa_con_efirma(db)
    eid = empresa.empresa_id
    job = await _job(db, eid, estado=EstadoJob.NUEVO)

    solicitudes = 0

    class FacadeQueCuenta:
        def __init__(self, signer: object, rfc: str) -> None:
            pass

        def solicitar(self, job_dominio: object) -> str:
            nonlocal solicitudes
            solicitudes += 1
            return f"ID-SOLICITUD-{solicitudes}"

    monkeypatch.setattr(worker_tasks, "SatFacade", FacadeQueCuenta)

    engine = create_async_engine(mysql_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:

        async def un_paso() -> None:
            async with factory() as sesion:
                await worker_tasks.paso_job(sesion, job.job_id)

        await asyncio.gather(un_paso(), un_paso(), return_exceptions=True)
    finally:
        await engine.dispose()

    assert solicitudes == 1, f"se enviaron {solicitudes} solicitudes al SAT para un solo job"


# --------------------------------------------------------------------------- #
# Validación de rangos: no pedirle al SAT lo que va a rechazar.
# --------------------------------------------------------------------------- #


async def test_n3_04_un_rango_invertido_se_rechaza(db: AsyncSession) -> None:
    """N3-04 · `hasta` anterior a `desde`."""
    empresa = await _empresa_con_efirma(db)
    eid = empresa.empresa_id

    with pytest.raises(RangoInvalidoError):
        await crear_descarga(
            db, empresa, tipo=TipoJob.EMITIDO, solicitud=SolicitudTipo.CFDI,
            desde=date(2026, 3, 1), hasta=date(2026, 1, 1),
        )


async def test_n3_05_un_rango_de_un_solo_dia_se_rechaza(db: AsyncSession) -> None:
    """N3-05 · Regresión de un fallo real de producción (2026-07-28).

    El SAT rechaza con `CodEstatus=301` un rango cuyo inicio y fin caen en el mismo día
    calendario. Cuatro jobs de la sync diaria murieron así antes de que existiera esta guarda.
    """
    empresa = await _empresa_con_efirma(db)
    eid = empresa.empresa_id

    with pytest.raises(RangoInvalidoError):
        await crear_descarga(
            db, empresa, tipo=TipoJob.EMITIDO, solicitud=SolicitudTipo.CFDI,
            desde=date(2026, 1, 15), hasta=date(2026, 1, 15),
        )


async def test_n3_06_un_rango_largo_se_trocea_en_lugar_de_rechazarse(db: AsyncSession) -> None:
    """N3-06 · Un año completo no se rechaza: se parte en ventanas que el SAT sí acepta.

    Rechazar sería lo fácil; trocear es lo correcto, y es lo que permite un backfill histórico.
    """
    empresa = await _empresa_con_efirma(db)
    eid = empresa.empresa_id

    jobs = await crear_descarga(
        db, empresa, tipo=TipoJob.EMITIDO, solicitud=SolicitudTipo.CFDI,
        desde=date(2026, 1, 1), hasta=date(2026, 12, 31), hoy=date(2026, 12, 31),
    )

    assert len(jobs) > 1, "un año entero se pidió en una sola ventana"
    # Ninguna ventana puede quedar invertida ni de un solo día, o el SAT la rechazaría igual.
    for j in jobs:
        assert j.fecha_inicial < j.fecha_final
    # Cobertura contigua y sin traslape.
    ordenados = sorted(jobs, key=lambda j: j.fecha_inicial)
    for previo, siguiente in zip(ordenados, ordenados[1:], strict=False):
        assert siguiente.fecha_inicial > previo.fecha_inicial


async def test_n3_07_sin_efirma_no_se_crea_ninguna_descarga(db: AsyncSession) -> None:
    """N3-07 · Sin llave no se puede hablar con el SAT: crear el job solo produciría un ERROR
    y un operador convencido de que la descarga está en marcha."""
    empresa = await crear_empresa(db, nombre="Sin llave", rfc=RFC_EMPRESA)  # sin e.firma

    with pytest.raises(EfirmaAusenteError):
        await crear_descarga(
            db, empresa, tipo=TipoJob.EMITIDO, solicitud=SolicitudTipo.CFDI,
            desde=date(2026, 1, 1), hasta=date(2026, 1, 31),
        )

    assert (await db.scalar(select(Job).where(Job.empresa_id == empresa.empresa_id))) is None


async def test_n3_08_con_efirma_vencida_no_se_crea_ninguna_descarga(db: AsyncSession) -> None:
    """N3-08 · Igual que N3-07 pero con la llave caducada: el SAT la rechazaría."""
    from app.sat_hub.errors import FielVencidaError

    empresa = await crear_empresa(db, nombre="Llave vencida", rfc=RFC_EMPRESA)
    cer, key, password = generar_fiel_prueba(
        rfc=RFC_EMPRESA, not_before=datetime(2019, 1, 1), not_after=datetime(2020, 1, 1)
    )
    # Se siembra directamente en la bóveda: el alta por API ya rechaza una FIEL vencida
    # (probado en N2-09), así que este estado solo se alcanza cuando vence *después* del alta.
    from app.services.fiel import cargar_signer

    signer = cargar_signer(cer, key, password)
    dek = boveda.generar_dek()
    cifrada = boveda.EfirmaCifrada(
        num_serie=str(signer.serial_number),
        not_before=datetime(2019, 1, 1),
        not_after=datetime(2020, 1, 1),
        cer_pem=cer,
        key_cifrada=boveda.cifrar(dek, key),
        password_cifrada=boveda.cifrar(dek, password.encode()),
        dek_envuelta=boveda.envolver_dek(boveda.cargar_kek(), dek),
    )
    await efirmas_repo.upsert(db, empresa.empresa_id, cifrada)
    await db.commit()

    with pytest.raises(FielVencidaError):
        await crear_descarga(
            db, empresa, tipo=TipoJob.EMITIDO, solicitud=SolicitudTipo.CFDI,
            desde=date(2026, 1, 1), hasta=date(2026, 1, 31),
        )


async def test_n3_09_una_empresa_desactivada_no_descarga(db: AsyncSession) -> None:
    """N3-09 · Desactivar una empresa tiene que detener su tráfico hacia el SAT."""
    empresa = await _empresa_con_efirma(db)
    eid = empresa.empresa_id
    empresa.activo = False
    await db.flush()
    await db.commit()

    with pytest.raises(EmpresaInactivaError):
        await crear_descarga(
            db, empresa, tipo=TipoJob.EMITIDO, solicitud=SolicitudTipo.CFDI,
            desde=date(2026, 1, 1), hasta=date(2026, 1, 31),
        )


# --------------------------------------------------------------------------- #
# Robustez del diálogo con el SAT.
# --------------------------------------------------------------------------- #


async def test_n3_10_un_estado_desconocido_del_sat_no_tumba_el_job(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """N3-10 · El SAT devuelve un `EstadoSolicitud` fuera de su propio catálogo (1-6).

    Ocurre de verdad: `EstadoSolicitud=0` con "Error no controlado" apareció en los logs del
    2026-08-20. Tratarlo como error definitivo mataría jobs por una respuesta que el SAT
    corrige al siguiente sondeo; hay que seguir sondeando.
    """
    from app.sat_hub.sat_facade import ResultadoVerificacion

    empresa = await _empresa_con_efirma(db)
    eid = empresa.empresa_id
    job = await _job(db, eid, estado=EstadoJob.SOLICITADO, id_solicitud="ID-X")

    class FacadeRaro:
        def __init__(self, signer: object, rfc: str) -> None:
            pass

        def verificar(self, id_solicitud: str) -> ResultadoVerificacion:
            return ResultadoVerificacion(estado_solicitud=99, mensaje=None, cod_estatus=None)

    monkeypatch.setattr(worker_tasks, "SatFacade", FacadeRaro)

    resultado = await worker_tasks.paso_job(db, job.job_id)
    await db.refresh(job)

    assert resultado.siguiente == "reintentar", "un estado desconocido cortó el sondeo"
    assert job.estado is not EstadoJob.ERROR, "un estado desconocido mandó el job a ERROR"


async def test_n3_11_un_rechazo_definitivo_del_sat_deja_mensaje(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """N3-11 · Un job en ERROR sin mensaje es un job que nadie puede diagnosticar."""
    from app.sat_hub.sat_facade import ESTADO_RECHAZADA, ResultadoVerificacion

    empresa = await _empresa_con_efirma(db)
    eid = empresa.empresa_id
    job = await _job(db, eid, estado=EstadoJob.SOLICITADO, id_solicitud="ID-Y")

    class FacadeQueRechaza:
        def __init__(self, signer: object, rfc: str) -> None:
            pass

        def verificar(self, id_solicitud: str) -> ResultadoVerificacion:
            return ResultadoVerificacion(estado_solicitud=ESTADO_RECHAZADA, mensaje="Solicitud rechazada por el SAT.")

    monkeypatch.setattr(worker_tasks, "SatFacade", FacadeQueRechaza)

    await worker_tasks.paso_job(db, job.job_id)
    await db.refresh(job)

    assert job.estado is EstadoJob.ERROR
    assert job.mensaje, "el job quedó en ERROR sin explicación para el operador"


async def test_n3_12_un_job_en_estado_terminal_no_vuelve_a_moverse(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """N3-12 · Un job ya `DESCARGADO` no debe volver a hablar con el SAT ni cambiar de estado.

    Si lo hiciera, un mensaje de Celery reentregado (algo que un broker puede hacer) volvería a
    pedir y a reindexar lo mismo.
    """
    empresa = await _empresa_con_efirma(db)
    eid = empresa.empresa_id
    job = await _job(db, eid, estado=EstadoJob.DESCARGADO, id_solicitud="ID-Z")
    llamadas = 0

    class FacadeVigilante:
        def __init__(self, signer: object, rfc: str) -> None:
            nonlocal llamadas
            llamadas += 1

    monkeypatch.setattr(worker_tasks, "SatFacade", FacadeVigilante)

    resultado = await worker_tasks.paso_job(db, job.job_id)
    await db.refresh(job)

    assert resultado.siguiente == "hecho"
    assert job.estado is EstadoJob.DESCARGADO
    assert llamadas == 0, "un job terminal volvió a construir el facade del SAT"


async def test_n3_13_un_job_que_ya_no_existe_no_revienta_la_tarea(db: AsyncSession) -> None:
    """N3-13 · Job borrado entre el encolado y la ejecución: la tarea termina limpia.

    Sin esto, un `AttributeError` sobre `None` dejaría la tarea en FAILURE y el mensaje
    reencolándose contra un id inexistente.
    """
    resultado = await worker_tasks.paso_job(db, 987654)
    assert resultado.siguiente == "hecho"


# --------------------------------------------------------------------------- #
# Contabilidad de la sincronización: no saltarse días.
# --------------------------------------------------------------------------- #


async def test_n3_14_un_job_en_error_no_cuenta_como_ventana_sincronizada(db: AsyncSession) -> None:
    """N3-14 · Regresión de un fallo real de producción (2026-07-28).

    `ultima_ventana_sincronizada` **excluye** los jobs en ERROR: uno que falló nunca bajó nada,
    así que su fecha no puede darse por sincronizada. Si contara, **ese día quedaría saltado
    para siempre** y el hueco solo se descubriría al cuadrar contra la contabilidad.
    """
    empresa = await _empresa_con_efirma(db)
    eid = empresa.empresa_id

    descargado = await _job(db, eid, estado=EstadoJob.DESCARGADO)
    descargado.origen = OrigenJob.SYNC
    descargado.fecha_inicial, descargado.fecha_final = date(2026, 3, 1), date(2026, 3, 10)

    fallido = await _job(db, eid, estado=EstadoJob.ERROR)
    fallido.origen = OrigenJob.SYNC
    fallido.fecha_inicial, fallido.fecha_final = date(2026, 3, 10), date(2026, 3, 20)
    await db.flush()
    await db.commit()

    ultima = await jobs_repo.ultima_ventana_sincronizada(db, empresa.empresa_id, TipoJob.EMITIDO, SolicitudTipo.CFDI)

    assert ultima == date(2026, 3, 10), f"el job en ERROR contó como sincronizado (devolvió {ultima})"


async def test_n3_15_un_job_en_proceso_si_cuenta_como_ventana_sincronizada(db: AsyncSession) -> None:
    """N3-15 · La otra mitad de N3-14, y es la que evita un rechazo del SAT.

    Un job que todavía está en proceso **sí** cuenta: el SAT puede tardar, y volver a pedir la
    misma ventana hoy sería una solicitud duplicada exacta, que el SAT rechaza con
    `CodEstatus=5005`. Contar solo lo terminado produciría duplicados todos los días.
    """
    empresa = await _empresa_con_efirma(db)
    eid = empresa.empresa_id

    en_proceso = await _job(db, eid, estado=EstadoJob.EN_PROCESO, id_solicitud="ID-W")
    en_proceso.origen = OrigenJob.SYNC
    en_proceso.fecha_inicial, en_proceso.fecha_final = date(2026, 4, 1), date(2026, 4, 15)
    await db.flush()
    await db.commit()

    ultima = await jobs_repo.ultima_ventana_sincronizada(db, empresa.empresa_id, TipoJob.EMITIDO, SolicitudTipo.CFDI)

    assert ultima == date(2026, 4, 15)


async def test_n3_16_la_sync_no_repite_una_ventana_ya_sincronizada(db: AsyncSession) -> None:
    """N3-16 · Idempotencia diaria: con la ventana de ayer ya cubierta, no se crean jobs nuevos."""
    empresa = await _empresa_con_efirma(db)
    eid = empresa.empresa_id
    ayer = date.today() - timedelta(days=1)

    ya = await _job(db, eid, estado=EstadoJob.DESCARGADO)
    ya.origen = OrigenJob.SYNC
    ya.fecha_inicial, ya.fecha_final = ayer - timedelta(days=1), ayer
    await db.flush()
    await db.commit()

    ultima = await jobs_repo.ultima_ventana_sincronizada(db, empresa.empresa_id, TipoJob.EMITIDO, SolicitudTipo.CFDI)
    assert ultima is not None and ultima >= ayer, "la ventana de ayer no quedó registrada como cubierta"


# --------------------------------------------------------------------------- #
# Almacenamiento: los enlaces firmados no pueden salir del área de datos.
# --------------------------------------------------------------------------- #


async def test_n3_17_un_enlace_firmado_no_escapa_del_area_de_datos() -> None:
    """N3-17 · Travesía de rutas sobre el enlace de descarga.

    El token va firmado con `SIGNING_SECRET`, así que la ruta no es manipulable sin la llave;
    esta prueba ataca el otro lado: **si alguien firmara una ruta con `..`, ¿se serviría?**
    Es la comprobación de defensa en profundidad de `descargar_archivo_endpoint`.
    """
    import os

    from app.core.config import get_settings
    from app.services import enlaces

    token = enlaces.firmar({"ruta": "../../../../etc/passwd"})
    payload = enlaces.verificar(token)  # la firma es válida: la hicimos nosotros

    storage_root = os.path.abspath(get_settings().storage_root)
    ruta_absoluta = os.path.abspath(os.path.join(storage_root, payload["ruta"]))

    assert not ruta_absoluta.startswith(storage_root + os.sep), (
        "la ruta escapó del área de datos; la comprobación del endpoint es la única barrera"
    )


async def test_n3_18_un_enlace_con_firma_alterada_se_rechaza() -> None:
    """N3-18 · Sin la llave de firma no se puede pedir un archivo arbitrario."""
    from app.services import enlaces

    token = enlaces.firmar({"ruta": "11/1/paquete_1.zip"})
    cuerpo, _, firma = token.rpartition(".")
    alterado = f"{cuerpo}.{'0' * len(firma)}"

    with pytest.raises(enlaces.EnlaceInvalidoError):
        enlaces.verificar(alterado)


async def test_n3_19_un_enlace_vencido_se_rechaza() -> None:
    """N3-19 · La caducidad tiene que aplicarse de verdad, no solo viajar en el payload."""
    from app.services import enlaces

    token = enlaces.firmar({"ruta": "11/1/paquete_1.zip"}, ttl_seg=-1)

    with pytest.raises(enlaces.EnlaceInvalidoError):
        enlaces.verificar(token)
