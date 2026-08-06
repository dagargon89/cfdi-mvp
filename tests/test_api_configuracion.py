"""Endpoints de configuración fiscal (§12 del diseño, doc 05 §8).

Lo que estas pruebas fijan, en una frase: **un valor sin confirmar no calcula, y confirmar es
un acto aparte que exige mirar el valor.** De ahí las tres aserciones que sostienen todo lo
demás:

- capturar por `PUT` deja el valor con `origen: MANUAL` y **sin confirmar** (dos actos, no uno);
- `POST .../confirmar` es lo que hace que `valor_vigente` empiece a devolverlo;
- confirmar mandando un valor que ya no coincide con el almacenado se rechaza con `409`, que
  es el escenario "la propuesta cambió entre que se pintó la pantalla y que se hizo clic".

Y dos que protegen la implementación, no el contrato: el `PUT` pasa por
`guardar_param_fiscal` (se comprueba ejerciendo dos reglas que **solo** viven ahí dentro:
el rechazo de solapamiento y el limpiado de la confirmación cuando la cifra cambia), y un
importe que viaje como número JSON se rechaza en vez de aceptarse ya redondeado por `float`.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bitacora import Bitacora
from app.models.configuracion_fiscal import CatalogoPercepcionMarca, ConfiguracionEmpresa, ParamFiscal
from app.models.enums import BaseExencion, OrigenValor, RolEmpresa, RolGlobal
from app.services import configuracion_fiscal as cfg
from tests import factories

ADMIN = {"Authorization": "Bearer uid-admin"}


async def _admin(db: AsyncSession) -> None:
    await factories.crear_usuario(db, uid="uid-admin", correo="admin@demo.test", rol_global=RolGlobal.ADMIN)


def _param(
    clave: str,
    valor: str,
    desde: date,
    *,
    confirmado: bool = False,
    hasta: date | None = None,
    origen: OrigenValor = OrigenValor.SEMILLA,
) -> ParamFiscal:
    return ParamFiscal(
        clave=clave,
        vigencia_desde=desde,
        ejercicio=desde.year,
        valor=Decimal(valor),
        vigencia_hasta=hasta,
        origen=origen,
        fuente="INEGI, boletín UMA 2026",
        confirmado_por="otro@demo.test" if confirmado else None,
        confirmado_en=datetime(2026, 8, 1, 9, 0, 0) if confirmado else None,
    )


async def _contar_bitacora(db: AsyncSession, accion: str) -> int:
    return (await db.scalar(select(func.count()).select_from(Bitacora).where(Bitacora.accion == accion))) or 0


# --------------------------------------------------------------------------------------
# 1-2: quién puede ver la configuración fiscal, y qué ve
# --------------------------------------------------------------------------------------


async def test_get_fiscal_con_usuario_no_admin_da_403(client, db: AsyncSession) -> None:  # type: ignore[no-untyped-def]
    """La configuración fiscal es política federal: aplica a todas las empresas, así que no
    hay rol por empresa que la habilite. Solo administrador (regla 3)."""
    await factories.crear_usuario(db, uid="uid-op", correo="op@demo.test", rol_global=RolGlobal.OPERADOR)

    r = await client.get("/v1/configuracion/fiscal", headers={"Authorization": "Bearer uid-op"})
    assert r.status_code == 403, r.text


async def test_get_fiscal_lista_valor_procedencia_y_confirmacion(client, db: AsyncSession) -> None:  # type: ignore[no-untyped-def]
    await _admin(db)
    db.add(_param("UMA_DIARIA", "117.310000", date(2026, 2, 1)))
    db.add(_param("SALARIO_MINIMO_ZLFN", "440.870000", date(2026, 1, 1), confirmado=True))
    await db.commit()

    r = await client.get("/v1/configuracion/fiscal", headers=ADMIN)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    por_clave = {p["clave"]: p for p in cuerpo["parametros"]}

    uma = por_clave["UMA_DIARIA"]
    assert uma["valor"] == "117.310000"  # cadena, no número: ver el test de precisión de abajo
    assert uma["vigencia_desde"] == "2026-02-01"
    assert uma["vigencia_hasta"] is None
    assert uma["origen"] == "SEMILLA"
    assert uma["fuente"] == "INEGI, boletín UMA 2026"
    assert uma["confirmado"] is False
    assert uma["confirmado_por"] is None

    assert por_clave["SALARIO_MINIMO_ZLFN"]["confirmado"] is True
    assert por_clave["SALARIO_MINIMO_ZLFN"]["confirmado_por"] == "otro@demo.test"

    # El tercer estado del cuadro de degradación: claves conocidas de las que no hay ni
    # propuesta. Sin esto la pantalla no puede decir "falta capturar la UMA mensual".
    assert "UMA_MENSUAL" in cuerpo["claves_sin_valor"]
    assert "UMA_DIARIA" not in cuerpo["claves_sin_valor"]


# --------------------------------------------------------------------------------------
# 3-4: confirmar es lo que activa el valor, y exige mirar el valor
# --------------------------------------------------------------------------------------


async def test_confirmar_activa_el_valor_para_valor_vigente(client, db: AsyncSession) -> None:  # type: ignore[no-untyped-def]
    """El invariante completo, de punta a punta: antes de confirmar, `valor_vigente` —lo que
    usan los informes— devuelve `None` aunque el valor esté capturado."""
    await _admin(db)
    db.add(_param("UMA_DIARIA", "117.310000", date(2026, 2, 1)))
    await db.commit()
    assert await cfg.valor_vigente(db, "UMA_DIARIA", date(2026, 6, 30)) is None

    r = await client.post(
        "/v1/configuracion/fiscal/UMA_DIARIA/confirmar",
        json={"vigencia_desde": "2026-02-01", "valor": "117.31"},
        headers=ADMIN,
    )
    assert r.status_code == 200, r.text
    assert r.json()["confirmado"] is True
    assert r.json()["confirmado_por"] == "admin@demo.test"

    db.expire_all()
    assert await cfg.valor_vigente(db, "UMA_DIARIA", date(2026, 6, 30)) == Decimal("117.310000")


async def test_confirmar_un_valor_que_no_coincide_da_409_y_no_confirma(client, db: AsyncSession) -> None:  # type: ignore[no-untyped-def]
    """El caso real: la pantalla se pintó con 117.31, una recarga de semillas lo cambió a
    118.00, y el clic llega tarde. Confirmar a ciegas activaría una cifra que nadie revisó."""
    await _admin(db)
    db.add(_param("UMA_DIARIA", "118.000000", date(2026, 2, 1)))
    await db.commit()

    r = await client.post(
        "/v1/configuracion/fiscal/UMA_DIARIA/confirmar",
        json={"vigencia_desde": "2026-02-01", "valor": "117.31"},
        headers=ADMIN,
    )
    assert r.status_code == 409, r.text
    assert r.json()["error"]["codigo"] == "VALOR_CAMBIO"

    db.expire_all()
    fila = await db.scalar(select(ParamFiscal).where(ParamFiscal.clave == "UMA_DIARIA"))
    assert fila is not None
    assert fila.confirmado_en is None, "un 409 no puede dejar el valor confirmado a medias"
    assert await cfg.valor_vigente(db, "UMA_DIARIA", date(2026, 6, 30)) is None
    assert await _contar_bitacora(db, "confirmar_param_fiscal") == 0


async def test_confirmar_acepta_el_valor_con_otra_escala(client, db: AsyncSession) -> None:  # type: ignore[no-untyped-def]
    """La columna es `Numeric(18,6)` y devuelve '117.310000'; el cliente reenvía lo que le
    dieron. Si la comparación fuera textual, confirmar sería imposible sin adivinar ceros."""
    await _admin(db)
    db.add(_param("UMA_DIARIA", "117.310000", date(2026, 2, 1)))
    await db.commit()

    r = await client.post(
        "/v1/configuracion/fiscal/UMA_DIARIA/confirmar",
        json={"vigencia_desde": "2026-02-01", "valor": "117.310000"},
        headers=ADMIN,
    )
    assert r.status_code == 200, r.text


async def test_confirmar_un_tramo_inexistente_da_404(client, db: AsyncSession) -> None:  # type: ignore[no-untyped-def]
    await _admin(db)
    db.add(_param("UMA_DIARIA", "117.310000", date(2026, 2, 1)))
    await db.commit()

    r = await client.post(
        "/v1/configuracion/fiscal/UMA_DIARIA/confirmar",
        json={"vigencia_desde": "2025-02-01", "valor": "117.31"},
        headers=ADMIN,
    )
    assert r.status_code == 404, r.text


# --------------------------------------------------------------------------------------
# 5-6: capturar no confirma, y la validación es la del servicio
# --------------------------------------------------------------------------------------


async def test_put_manual_guarda_origen_manual_y_sin_confirmar(client, db: AsyncSession) -> None:  # type: ignore[no-untyped-def]
    """Capturar y confirmar son dos actos. Si el `PUT` confirmara "por comodidad", un valor
    fiscal entraría a los cálculos sin que nadie distinto de quien lo tecleó lo mirara."""
    await _admin(db)

    r = await client.put(
        "/v1/configuracion/fiscal/UMA_DIARIA",
        json={
            "valor": "117.31",
            "vigencia_desde": "2026-02-01",
            "fuente": "INEGI, boletín UMA 2026 (capturado a mano tras la fe de erratas)",
        },
        headers=ADMIN,
    )
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["origen"] == "MANUAL"
    assert cuerpo["fuente"].startswith("INEGI, boletín UMA 2026 (capturado a mano")
    assert cuerpo["confirmado"] is False
    assert cuerpo["ejercicio"] == 2026

    db.expire_all()
    assert await cfg.valor_vigente(db, "UMA_DIARIA", date(2026, 6, 30)) is None, "capturar no activa el valor"
    propuesto = await cfg.valor_propuesto(db, "UMA_DIARIA", date(2026, 6, 30))
    assert propuesto is not None
    assert propuesto.valor == Decimal("117.310000")
    assert propuesto.origen is OrigenValor.MANUAL


async def test_put_con_valor_negativo_da_422_y_no_escribe_nada(client, db: AsyncSession) -> None:  # type: ignore[no-untyped-def]
    await _admin(db)

    r = await client.put(
        "/v1/configuracion/fiscal/UMA_DIARIA",
        json={"valor": "-1", "vigencia_desde": "2026-02-01", "fuente": "dedazo"},
        headers=ADMIN,
    )
    assert r.status_code == 422, r.text

    assert (await db.scalar(select(func.count()).select_from(ParamFiscal))) == 0
    assert await _contar_bitacora(db, "capturar_param_fiscal") == 0


async def test_put_con_clave_desconocida_da_422(client, db: AsyncSession) -> None:  # type: ignore[no-untyped-def]
    """`UMA_DIARA` se capturaría y se confirmaría sin ruido, y después no la leería nadie
    nunca. La lista blanca vive en el servicio; el endpoint solo traduce el error."""
    await _admin(db)

    r = await client.put(
        "/v1/configuracion/fiscal/UMA_DIARA",
        json={"valor": "117.31", "vigencia_desde": "2026-02-01", "fuente": "INEGI"},
        headers=ADMIN,
    )
    assert r.status_code == 422, r.text
    assert (await db.scalar(select(func.count()).select_from(ParamFiscal))) == 0


async def test_put_con_importe_como_numero_json_se_rechaza(client, db: AsyncSession) -> None:  # type: ignore[no-untyped-def]
    """`Decimal` de punta a punta. Un número JSON se convierte pasando por `float`: verificado,
    `12345678901.123456` llega ya redondeado a `...455` y el error es irrecuperable. Se rechaza
    en la entrada, igual que hace el cargador con el YAML, en vez de guardarlo corrompido."""
    await _admin(db)

    r = await client.put(
        "/v1/configuracion/fiscal/UMA_DIARIA",
        content=b'{"valor": 117.31, "vigencia_desde": "2026-02-01", "fuente": "INEGI"}',
        headers={**ADMIN, "Content-Type": "application/json"},
    )
    assert r.status_code == 422, r.text
    assert (await db.scalar(select(func.count()).select_from(ParamFiscal))) == 0


async def test_el_importe_viaja_sin_perder_un_solo_decimal(client, db: AsyncSession) -> None:  # type: ignore[no-untyped-def]
    """Ida y vuelta completa con los seis decimales de la columna: entra como cadena, se guarda
    como `Decimal` y sale como cadena. En ningún punto hay un `float`."""
    await _admin(db)

    r = await client.put(
        "/v1/configuracion/fiscal/TIPO_CAMBIO_USD",
        json={"valor": "18.123456", "vigencia_desde": "2026-08-06", "fuente": "DOF 06-08-2026"},
        headers=ADMIN,
    )
    assert r.status_code == 200, r.text
    assert r.json()["valor"] == "18.123456"

    db.expire_all()
    fila = await db.scalar(select(ParamFiscal).where(ParamFiscal.clave == "TIPO_CAMBIO_USD"))
    assert fila is not None
    assert fila.valor == Decimal("18.123456")


# --------------------------------------------------------------------------------------
# El `PUT` pasa por `guardar_param_fiscal` — dos reglas que solo existen ahí dentro
# --------------------------------------------------------------------------------------


async def test_put_que_se_solapa_con_otro_tramo_da_409(client, db: AsyncSession) -> None:  # type: ignore[no-untyped-def]
    """El error de captura que motiva toda la puerta: se teclea 2026 donde iba 2027 y quedan
    dos tramos "vigentes hasta nuevo aviso" para la misma clave. Esta regla vive **solo** en
    `guardar_param_fiscal`; si el endpoint hiciera `db.add(...)` por su cuenta, este caso
    pasaría con un 200 y la nómina de medio año tomaría el valor equivocado en silencio."""
    await _admin(db)
    db.add(_param("SALARIO_MINIMO_GENERAL", "315.040000", date(2026, 1, 1)))
    await db.commit()

    r = await client.put(
        "/v1/configuracion/fiscal/SALARIO_MINIMO_GENERAL",
        json={"valor": "355.00", "vigencia_desde": "2026-06-15", "fuente": "DOF (con el año mal tecleado)"},
        headers=ADMIN,
    )
    assert r.status_code == 409, r.text
    assert r.json()["error"]["codigo"] == "VIGENCIA_SOLAPADA"

    assert (await db.scalar(select(func.count()).select_from(ParamFiscal))) == 1


async def test_corregir_la_cifra_de_un_valor_confirmado_lo_devuelve_a_la_cola(client, db: AsyncSession) -> None:  # type: ignore[no-untyped-def]
    """La segunda regla que solo vive en `guardar_param_fiscal`: una cifra distinta es un valor
    nuevo y necesita confirmación nueva. Corregirla no puede dejarla activa por herencia."""
    await _admin(db)
    db.add(_param("UMA_DIARIA", "117.310000", date(2026, 2, 1), confirmado=True))
    await db.commit()
    assert await cfg.valor_vigente(db, "UMA_DIARIA", date(2026, 6, 30)) == Decimal("117.310000")

    r = await client.put(
        "/v1/configuracion/fiscal/UMA_DIARIA",
        json={"valor": "118.00", "vigencia_desde": "2026-02-01", "fuente": "INEGI, fe de erratas"},
        headers=ADMIN,
    )
    assert r.status_code == 200, r.text
    assert r.json()["confirmado"] is False

    db.expire_all()
    assert await cfg.valor_vigente(db, "UMA_DIARIA", date(2026, 6, 30)) is None


# --------------------------------------------------------------------------------------
# 7: cada cambio deja bitácora, con el valor anterior y el nuevo
# --------------------------------------------------------------------------------------


async def test_capturar_y_confirmar_dejan_bitacora_con_anterior_y_nuevo(client, db: AsyncSession) -> None:  # type: ignore[no-untyped-def]
    """El `detalle` sustituye al diff de git: sin el valor anterior no se puede reconstruir
    qué cambió cuando la configuración se administra desde una pantalla."""
    await _admin(db)
    db.add(_param("UMA_DIARIA", "117.310000", date(2026, 2, 1)))
    await db.commit()

    r = await client.put(
        "/v1/configuracion/fiscal/UMA_DIARIA",
        json={"valor": "118.00", "vigencia_desde": "2026-02-01", "fuente": "INEGI, fe de erratas"},
        headers=ADMIN,
    )
    assert r.status_code == 200, r.text

    captura = await db.scalar(select(Bitacora).where(Bitacora.accion == "capturar_param_fiscal"))
    assert captura is not None
    assert captura.actor == "admin@demo.test"
    assert captura.entidad == "param_fiscal:UMA_DIARIA@2026-02-01"
    assert captura.detalle is not None
    assert captura.detalle["anterior"]["valor"] == "117.310000"
    assert captura.detalle["anterior"]["origen"] == "SEMILLA"
    assert captura.detalle["nuevo"]["valor"] == "118.000000"
    assert captura.detalle["nuevo"]["origen"] == "MANUAL"
    assert captura.detalle["nuevo"]["confirmado"] is False

    r = await client.post(
        "/v1/configuracion/fiscal/UMA_DIARIA/confirmar",
        json={"vigencia_desde": "2026-02-01", "valor": "118.00"},
        headers=ADMIN,
    )
    assert r.status_code == 200, r.text

    confirmacion = await db.scalar(select(Bitacora).where(Bitacora.accion == "confirmar_param_fiscal"))
    assert confirmacion is not None
    assert confirmacion.detalle is not None
    assert confirmacion.detalle["anterior"]["confirmado"] is False
    assert confirmacion.detalle["nuevo"]["confirmado"] is True
    assert confirmacion.detalle["nuevo"]["valor"] == "118.000000"


async def test_reconfirmar_no_reescribe_quien_confirmo_ni_duplica_bitacora(client, db: AsyncSession) -> None:  # type: ignore[no-untyped-def]
    """Reconfirmar lo ya confirmado no es un cambio: no puede borrar el rastro de quién lo
    revisó de verdad ni inventar una fila de auditoría de algo que no pasó."""
    await _admin(db)
    db.add(_param("UMA_DIARIA", "117.310000", date(2026, 2, 1), confirmado=True))
    await db.commit()

    r = await client.post(
        "/v1/configuracion/fiscal/UMA_DIARIA/confirmar",
        json={"vigencia_desde": "2026-02-01", "valor": "117.31"},
        headers=ADMIN,
    )
    assert r.status_code == 200, r.text
    assert r.json()["confirmado_por"] == "otro@demo.test"
    assert await _contar_bitacora(db, "confirmar_param_fiscal") == 0


# --------------------------------------------------------------------------------------
# Marcas de percepción (§3.1) — misma puerta que los importes
# --------------------------------------------------------------------------------------


async def test_percepciones_capturar_no_confirma_y_confirmar_las_activa(client, db: AsyncSession) -> None:  # type: ignore[no-untyped-def]
    """`factor_exencion` alimenta el cálculo de exenciones igual que la UMA, y es el dato más
    propenso a error de la fase (~46 derivaciones del art. 93 hechas a mano). Misma puerta."""
    await _admin(db)

    r = await client.put(
        "/v1/configuracion/percepciones/002",
        json={
            "es_ingreso_ordinario": False,
            "base_exencion": "UMA_DIAS",
            "factor_exencion": "30.0000",
            "integra_sbc": True,
            "es_provisionable": True,
        },
        headers=ADMIN,
    )
    assert r.status_code == 200, r.text
    assert r.json()["confirmado"] is False
    assert r.json()["tipo_percepcion"] == "002", "la clave del SAT es texto: '002' no puede volverse 2"

    db.expire_all()
    assert await cfg.marcas_de_percepcion(db) == {}, "sin confirmar, la marca no calcula"
    assert set(await cfg.marcas_propuestas(db)) == {"002"}

    r = await client.post(
        "/v1/configuracion/percepciones/002/confirmar",
        json={
            "es_ingreso_ordinario": False,
            "base_exencion": "UMA_DIAS",
            "factor_exencion": "30.0000",
            "integra_sbc": True,
            "es_provisionable": True,
        },
        headers=ADMIN,
    )
    assert r.status_code == 200, r.text
    assert r.json()["confirmado"] is True

    db.expire_all()
    confirmadas = await cfg.marcas_de_percepcion(db)
    assert set(confirmadas) == {"002"}
    assert confirmadas["002"].factor_exencion == Decimal("30.0000")


async def test_confirmar_una_marca_que_cambio_da_409(client, db: AsyncSession) -> None:  # type: ignore[no-untyped-def]
    await _admin(db)
    db.add(
        CatalogoPercepcionMarca(
            tipo_percepcion="022",
            es_ingreso_ordinario=False,
            base_exencion=BaseExencion.UMA_DIAS,
            factor_exencion=Decimal("90.0000"),
            integra_sbc=False,
            es_provisionable=False,
        )
    )
    await db.commit()

    r = await client.post(
        "/v1/configuracion/percepciones/022/confirmar",
        json={
            "es_ingreso_ordinario": False,
            "base_exencion": "UMA_DIAS",
            "factor_exencion": "30.0000",  # el revisor vio 30, la tabla dice 90
            "integra_sbc": False,
            "es_provisionable": False,
        },
        headers=ADMIN,
    )
    assert r.status_code == 409, r.text
    assert r.json()["error"]["codigo"] == "MARCAS_CAMBIARON"

    db.expire_all()
    assert await cfg.marcas_de_percepcion(db) == {}


async def test_corregir_una_marca_confirmada_la_devuelve_a_la_cola(client, db: AsyncSession) -> None:  # type: ignore[no-untyped-def]
    await _admin(db)
    db.add(
        CatalogoPercepcionMarca(
            tipo_percepcion="022",
            es_ingreso_ordinario=False,
            base_exencion=BaseExencion.UMA_DIAS,
            factor_exencion=Decimal("90.0000"),
            integra_sbc=False,
            es_provisionable=False,
            confirmado_por="otro@demo.test",
            confirmado_en=datetime(2026, 8, 1, 9, 0, 0),
        )
    )
    await db.commit()

    r = await client.put(
        "/v1/configuracion/percepciones/022",
        json={
            "es_ingreso_ordinario": False,
            "base_exencion": "UMA_DIAS",
            "factor_exencion": "91.0000",
            "integra_sbc": False,
            "es_provisionable": False,
        },
        headers=ADMIN,
    )
    assert r.status_code == 200, r.text
    assert r.json()["confirmado"] is False

    db.expire_all()
    assert await cfg.marcas_de_percepcion(db) == {}

    marca = await db.scalar(select(Bitacora).where(Bitacora.accion == "capturar_marca_percepcion"))
    assert marca is not None
    assert marca.detalle is not None
    assert marca.detalle["anterior"]["factor_exencion"] == "90.0000"
    assert marca.detalle["nuevo"]["factor_exencion"] == "91.0000"


async def test_percepcion_con_base_ninguna_y_factor_da_422(client, db: AsyncSession) -> None:  # type: ignore[no-untyped-def]
    """Misma coherencia que exige el cargador de semillas: sin base de exención no hay factor
    que aplicar, y aceptarlo dejaría un dato que ningún cálculo puede interpretar."""
    await _admin(db)

    r = await client.put(
        "/v1/configuracion/percepciones/001",
        json={
            "es_ingreso_ordinario": True,
            "base_exencion": "NINGUNA",
            "factor_exencion": "30.0000",
            "integra_sbc": True,
            "es_provisionable": True,
        },
        headers=ADMIN,
    )
    assert r.status_code == 422, r.text
    assert (await db.scalar(select(func.count()).select_from(CatalogoPercepcionMarca))) == 0


async def test_percepciones_con_usuario_no_admin_da_403(client, db: AsyncSession) -> None:  # type: ignore[no-untyped-def]
    await factories.crear_usuario(db, uid="uid-op", correo="op@demo.test", rol_global=RolGlobal.OPERADOR)

    r = await client.get("/v1/configuracion/percepciones", headers={"Authorization": "Bearer uid-op"})
    assert r.status_code == 403, r.text


# --------------------------------------------------------------------------------------
# 8-11: la configuración de una empresa
# --------------------------------------------------------------------------------------


async def test_configuracion_de_empresa_exige_operador(client, db: AsyncSession) -> None:  # type: ignore[no-untyped-def]
    """Consultar no basta: la zona salarial decide el resultado de una validación de
    cumplimiento (B-10), así que cambiarla es una operación de operador."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    consulta = await factories.crear_usuario(db, uid="uid-con", correo="con@demo.test", rol_global=RolGlobal.CONSULTA)
    await factories.asignar_permiso(db, consulta, empresa, RolEmpresa.CONSULTA)
    operador = await factories.crear_usuario(db, uid="uid-op", correo="op@demo.test", rol_global=RolGlobal.OPERADOR)
    await factories.asignar_permiso(db, operador, empresa, RolEmpresa.OPERADOR)

    cuerpo = {"zona_salarial": "ZLFN", "dias_aguinaldo": 30, "factor_prima_vacacional": "0.25"}

    r = await client.put(
        f"/v1/empresas/{empresa.empresa_id}/configuracion", json=cuerpo, headers={"Authorization": "Bearer uid-con"}
    )
    assert r.status_code == 403, r.text

    r = await client.put(
        f"/v1/empresas/{empresa.empresa_id}/configuracion", json=cuerpo, headers={"Authorization": "Bearer uid-op"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["zona_salarial"] == "ZLFN"
    assert r.json()["factor_prima_vacacional"] == "0.2500"


async def test_configuracion_de_empresa_ajena_responde_como_si_no_existiera(client, db: AsyncSession) -> None:  # type: ignore[no-untyped-def]
    """El brief pedía `403` "sin filtrar si existe", pero en este proyecto la respuesta que **no**
    filtra es `404`: `require_empresa` (doc 05 §1.3, `deps.py:95`) devuelve lo mismo para una
    empresa ajena que para una inexistente, y `403` solo cuando el usuario sí tiene acceso pero
    con rol insuficiente. Un `403` aquí delataría que la empresa existe — exactamente lo que la
    regla anti-enumeración evita, y lo que `tests/test_idor.py` fija para el resto de la API.
    Se comprueba que ambas respuestas son indistinguibles."""
    propia = await factories.crear_empresa(db, nombre="Propia", rfc="CHL960913IX9")
    ajena = await factories.crear_empresa(db, nombre="Ajena", rfc="EKU9003173C9")
    usuario = await factories.crear_usuario(db, uid="uid-op", correo="op@demo.test", rol_global=RolGlobal.OPERADOR)
    await factories.asignar_permiso(db, usuario, propia, RolEmpresa.OPERADOR)

    cuerpo = {"zona_salarial": "ZLFN", "dias_aguinaldo": 15, "factor_prima_vacacional": "0.25"}
    headers = {"Authorization": "Bearer uid-op"}

    r_ajena = await client.put(f"/v1/empresas/{ajena.empresa_id}/configuracion", json=cuerpo, headers=headers)
    r_inexistente = await client.put("/v1/empresas/424242/configuracion", json=cuerpo, headers=headers)

    assert r_ajena.status_code == 404
    assert r_inexistente.status_code == 404
    assert r_ajena.json()["error"]["mensaje"] == r_inexistente.json()["error"]["mensaje"]

    # Y nada se escribió en la empresa ajena.
    assert (await db.scalar(select(func.count()).select_from(ConfiguracionEmpresa))) == 0


async def test_zona_salarial_zlfn_hace_que_el_minimo_sea_el_de_frontera(client, db: AsyncSession) -> None:  # type: ignore[no-untyped-def]
    """Ciudad Juárez está en la Zona Libre de la Frontera Norte: 440.87 contra 315.04 del
    régimen general. Sin la zona configurada, B-10 no evalúa el salario mínimo; con ella mal
    configurada, daría falsos negativos silenciosos."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    operador = await factories.crear_usuario(db, uid="uid-op", correo="op@demo.test", rol_global=RolGlobal.OPERADOR)
    await factories.asignar_permiso(db, operador, empresa, RolEmpresa.OPERADOR)
    # El id se guarda aparte: `db.expire_all()` de más abajo dejaría la entidad `empresa` con
    # sus atributos por recargar, y leerlos desde una prueba async dispara `MissingGreenlet`.
    empresa_id = empresa.empresa_id
    db.add(_param("SALARIO_MINIMO_GENERAL", "315.040000", date(2026, 1, 1), confirmado=True))
    db.add(_param("SALARIO_MINIMO_ZLFN", "440.870000", date(2026, 1, 1), confirmado=True))
    await db.commit()

    assert await cfg.salario_minimo_de_empresa(db, empresa_id, date(2026, 6, 30)) is None

    r = await client.put(
        f"/v1/empresas/{empresa_id}/configuracion",
        json={"zona_salarial": "ZLFN", "dias_aguinaldo": 30, "factor_prima_vacacional": "0.25"},
        headers={"Authorization": "Bearer uid-op"},
    )
    assert r.status_code == 200, r.text

    db.expire_all()
    assert await cfg.salario_minimo_de_empresa(db, empresa_id, date(2026, 6, 30)) == Decimal("440.870000")


async def test_configuracion_de_empresa_recien_creada_trae_los_tres_campos_nulos(client, db: AsyncSession) -> None:  # type: ignore[no-untyped-def]
    """Los tres campos viajan en `null`, no se omiten: "no configurado" es un estado que la
    pantalla tiene que mostrar (degrada B-10), y un campo ausente del JSON no lo comunica."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    operador = await factories.crear_usuario(db, uid="uid-op", correo="op@demo.test", rol_global=RolGlobal.OPERADOR)
    await factories.asignar_permiso(db, operador, empresa, RolEmpresa.OPERADOR)

    r = await client.get(
        f"/v1/empresas/{empresa.empresa_id}/configuracion", headers={"Authorization": "Bearer uid-op"}
    )
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert set(cuerpo) == {"empresa_id", "zona_salarial", "dias_aguinaldo", "factor_prima_vacacional"}
    assert cuerpo["zona_salarial"] is None
    assert cuerpo["dias_aguinaldo"] is None
    assert cuerpo["factor_prima_vacacional"] is None


async def test_guardar_configuracion_de_empresa_deja_bitacora(client, db: AsyncSession) -> None:  # type: ignore[no-untyped-def]
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    operador = await factories.crear_usuario(db, uid="uid-op", correo="op@demo.test", rol_global=RolGlobal.OPERADOR)
    await factories.asignar_permiso(db, operador, empresa, RolEmpresa.OPERADOR)
    headers = {"Authorization": "Bearer uid-op"}

    await client.put(
        f"/v1/empresas/{empresa.empresa_id}/configuracion",
        json={"zona_salarial": "GENERAL", "dias_aguinaldo": 15, "factor_prima_vacacional": "0.25"},
        headers=headers,
    )
    r = await client.put(
        f"/v1/empresas/{empresa.empresa_id}/configuracion",
        json={"zona_salarial": "ZLFN", "dias_aguinaldo": 30, "factor_prima_vacacional": "0.30"},
        headers=headers,
    )
    assert r.status_code == 200, r.text

    filas = list(
        (
            await db.scalars(
                select(Bitacora)
                .where(Bitacora.accion == "guardar_configuracion_empresa")
                .order_by(Bitacora.bitacora_id)
            )
        ).all()
    )
    assert len(filas) == 2
    assert filas[0].detalle is not None and filas[0].detalle["anterior"] is None
    assert filas[1].detalle is not None
    assert filas[1].detalle["anterior"]["zona_salarial"] == "GENERAL"
    assert filas[1].detalle["nuevo"]["zona_salarial"] == "ZLFN"
    assert filas[1].detalle["nuevo"]["factor_prima_vacacional"] == "0.3000"


async def test_factor_de_prima_negativo_da_422(client, db: AsyncSession) -> None:  # type: ignore[no-untyped-def]
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    operador = await factories.crear_usuario(db, uid="uid-op", correo="op@demo.test", rol_global=RolGlobal.OPERADOR)
    await factories.asignar_permiso(db, operador, empresa, RolEmpresa.OPERADOR)

    r = await client.put(
        f"/v1/empresas/{empresa.empresa_id}/configuracion",
        json={"zona_salarial": "ZLFN", "dias_aguinaldo": 30, "factor_prima_vacacional": "-0.25"},
        headers={"Authorization": "Bearer uid-op"},
    )
    assert r.status_code == 422, r.text
    assert (await db.scalar(select(func.count()).select_from(ConfiguracionEmpresa))) == 0


# --------------------------------------------------------------------------------------
# Mapeos por empresa
# --------------------------------------------------------------------------------------


async def test_mapeos_se_reemplazan_completos_y_dejan_bitacora(client, db: AsyncSession) -> None:  # type: ignore[no-untyped-def]
    """B-06 agrupa por centro de costo y B-08 no se genera sin `map_concepto_provision`: lo que
    aquí se borra tiene efecto directo en los informes, así que la bitácora lleva las listas
    enteras, no un conteo."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    operador = await factories.crear_usuario(db, uid="uid-op", correo="op@demo.test", rol_global=RolGlobal.OPERADOR)
    await factories.asignar_permiso(db, operador, empresa, RolEmpresa.OPERADOR)
    empresa_id = empresa.empresa_id  # ver la nota de `db.expire_all()` más arriba
    headers = {"Authorization": "Bearer uid-op"}

    r = await client.put(
        f"/v1/empresas/{empresa_id}/configuracion/mapeos",
        json={
            "departamentos": [
                {"departamento_texto": "VENTAS", "centro_costo": "CC-100"},
                {"departamento_texto": "ADMON", "centro_costo": "CC-200"},
            ],
            "conceptos_provision": [
                {"naturaleza": "P", "tipo": "002", "clave": "AGUI", "categoria": "AGUINALDO"}
            ],
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert [d["departamento_texto"] for d in r.json()["departamentos"]] == ["ADMON", "VENTAS"]

    db.expire_all()
    assert await cfg.centro_de_costo(db, empresa_id) == {"VENTAS": "CC-100", "ADMON": "CC-200"}
    assert set(await cfg.categorias_de_provision(db, empresa_id)) == {("P", "002", "AGUI")}

    # Segundo PUT: reemplazo completo, lo que no viene deja de existir.
    r = await client.put(
        f"/v1/empresas/{empresa_id}/configuracion/mapeos",
        json={
            "departamentos": [{"departamento_texto": "VENTAS", "centro_costo": "CC-101"}],
            "conceptos_provision": [],
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text

    db.expire_all()
    assert await cfg.centro_de_costo(db, empresa_id) == {"VENTAS": "CC-101"}
    assert await cfg.categorias_de_provision(db, empresa_id) == {}

    ultima = list(
        (
            await db.scalars(
                select(Bitacora).where(Bitacora.accion == "guardar_mapeos_empresa").order_by(Bitacora.bitacora_id)
            )
        ).all()
    )[-1]
    assert ultima.detalle is not None
    assert len(ultima.detalle["anterior"]["departamentos"]) == 2
    assert ultima.detalle["nuevo"]["departamentos"] == [
        {"departamento_texto": "VENTAS", "centro_costo": "CC-101"}
    ]
    assert ultima.detalle["nuevo"]["conceptos_provision"] == []


async def test_mapeos_con_departamento_repetido_da_422(client, db: AsyncSession) -> None:  # type: ignore[no-untyped-def]
    """Dos renglones con la misma clave natural se pisan: el usuario vería guardado algo
    distinto de lo que mandó."""
    empresa = await factories.crear_empresa(db, rfc="CHL960913IX9")
    operador = await factories.crear_usuario(db, uid="uid-op", correo="op@demo.test", rol_global=RolGlobal.OPERADOR)
    await factories.asignar_permiso(db, operador, empresa, RolEmpresa.OPERADOR)
    empresa_id = empresa.empresa_id  # ver la nota de `db.expire_all()` más arriba

    r = await client.put(
        f"/v1/empresas/{empresa_id}/configuracion/mapeos",
        json={
            "departamentos": [
                {"departamento_texto": "VENTAS", "centro_costo": "CC-100"},
                {"departamento_texto": "VENTAS", "centro_costo": "CC-999"},
            ],
            "conceptos_provision": [],
        },
        headers={"Authorization": "Bearer uid-op"},
    )
    assert r.status_code == 422, r.text
    assert r.json()["error"]["codigo"] == "MAPEO_DUPLICADO"

    db.expire_all()
    assert await cfg.centro_de_costo(db, empresa_id) == {}
