"""Endpoints de la configuración fiscal (§12 del diseño, §2.12 y §3.1 del documento fuente):
consultar el estado de cada valor, capturarlo a mano, y **confirmarlo**.

El invariante que estos endpoints materializan: **un valor sin confirmar no calcula.**
Sembrar, cargar o sincronizar *proponen*; solo una persona confirma. De ahí que capturar y
confirmar sean dos llamadas distintas y no una sola "por comodidad": un `PUT` guarda con
`origen: MANUAL` y **sin** confirmación, y activar el valor exige un segundo acto deliberado.
Fusionarlos dejaría que un valor fiscal entrara a un cálculo sin que nadie lo mirara.

Y la regla que protege la confirmación de sí misma: **confirmar exige que el cliente mande el
valor que está confirmando**, y el servidor responde `409` si no coincide con el almacenado.
Sin eso, una propuesta que cambió entre que la pantalla se pintó y que se hizo clic —una
recarga de semillas, otro administrador, la sincronización de Banxico— se confirmaría a
ciegas, que es justo el escenario contra el que existe el invariante.

Por qué toda escritura de `param_fiscal` pasa por `guardar_param_fiscal`
------------------------------------------------------------------------
Ahí viven el rechazo de solapamiento de vigencias, el `with_for_update` que serializa a dos
escritores de la misma clave, y el limpiado de la confirmación cuando la cifra cambia.
Construir un `ParamFiscal` a mano con `db.add(...)` compilaría, pasaría las pruebas y
evaporaría las tres garantías en silencio. **No lo hagas**: la puerta es una sola.

Qué NO se expone aquí
---------------------
No hay endpoint de "recargar semillas desde YAML". `cargar_desde_yaml` hace `commit`/
`rollback` sobre la sesión de quien lo llama, y ese `rollback` descartaría la fila de bitácora
que la regla 8 exige escribir en la misma transacción. El cargador es para el script de línea
de comandos, que no escribe bitácora a propósito (y por eso `guardar_param_fiscal` protege las
correcciones manuales de que una recarga las pise sin dejar rastro).

Permisos, sin margen (regla 3)
------------------------------
La configuración fiscal es política federal y aplica a todas las empresas ⇒ `require_admin`.
La configuración de una empresa es política laboral suya ⇒ `require_empresa(OPERADOR)`, con el
`empresa_id` del **path**, nunca del cuerpo: el que manda el navegador es un dato hostil.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ContextoEmpresa, get_db, require_admin, require_empresa
from app.api.v1.schemas import (
    ConfiguracionEmpresaIn,
    ConfiguracionEmpresaOut,
    ConfiguracionFiscalOut,
    MapConceptoProvisionOut,
    MapDepartamentoOut,
    MapeosEmpresaIn,
    MapeosEmpresaOut,
    MarcaPercepcionIn,
    MarcaPercepcionOut,
    ParamFiscalConfirmarIn,
    ParamFiscalGuardarIn,
    ParamFiscalOut,
)
from app.models.configuracion_fiscal import (
    CatalogoPercepcionMarca,
    ConfiguracionEmpresa,
    MapConceptoProvision,
    MapDepartamento,
    ParamFiscal,
)
from app.models.empresa import Empresa
from app.models.enums import OrigenValor, RolEmpresa
from app.models.usuario import Usuario
from app.services import bitacora as bitacora_service
from app.services import configuracion_fiscal as cfg

router = APIRouter(prefix="/configuracion", tags=["configuracion-fiscal"])
router_empresa = APIRouter(prefix="/empresas/{empresa_id}/configuracion", tags=["configuracion-fiscal"])

# `param_fiscal.confirmado_por` y `catalogo_percepcion_marca.confirmado_por` son VARCHAR(128)
# y `usuarios.correo` es VARCHAR(190). El recorte evita un DataError 1406 de MySQL a media
# escritura y no pierde nada auditable: la fila de bitácora de la misma transacción guarda el
# `actor` completo (VARCHAR(190)).
_LARGO_CONFIRMADO_POR = 128


def _ahora() -> datetime:
    """`datetime` sin zona, como todas las columnas `DateTime` del proyecto (que son naive en
    UTC). Mismo patrón que `app/worker/tasks.py`."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _actor(correo: str) -> str:
    return correo[:_LARGO_CONFIRMADO_POR]


def _param_a_salida(fila: ParamFiscal) -> ParamFiscalOut:
    return ParamFiscalOut(
        clave=fila.clave,
        ejercicio=fila.ejercicio,
        valor=fila.valor,
        vigencia_desde=fila.vigencia_desde,
        vigencia_hasta=fila.vigencia_hasta,
        origen=fila.origen.value,
        fuente=fila.fuente,
        sincronizado_en=fila.sincronizado_en.isoformat() if fila.sincronizado_en else None,
        confirmado=fila.confirmado_en is not None,
        confirmado_por=fila.confirmado_por,
        confirmado_en=fila.confirmado_en.isoformat() if fila.confirmado_en else None,
    )


def _marca_a_salida(fila: CatalogoPercepcionMarca) -> MarcaPercepcionOut:
    return MarcaPercepcionOut(
        tipo_percepcion=fila.tipo_percepcion,
        es_ingreso_ordinario=fila.es_ingreso_ordinario,
        base_exencion=fila.base_exencion.value,
        factor_exencion=fila.factor_exencion,
        integra_sbc=fila.integra_sbc,
        es_provisionable=fila.es_provisionable,
        confirmado=fila.confirmado_en is not None,
        confirmado_por=fila.confirmado_por,
        confirmado_en=fila.confirmado_en.isoformat() if fila.confirmado_en else None,
    )


def _marca_a_detalle(fila: CatalogoPercepcionMarca) -> dict[str, Any]:
    """Las marcas de una fila, en tipos que el `JSON` de `bitacora` sabe guardar (el `Decimal`
    va como texto: serializarlo a `float` en el rastro de auditoría perdería precisión justo
    en el dato que se está auditando)."""
    return {
        "es_ingreso_ordinario": fila.es_ingreso_ordinario,
        "base_exencion": fila.base_exencion.value,
        "factor_exencion": str(fila.factor_exencion) if fila.factor_exencion is not None else None,
        "integra_sbc": fila.integra_sbc,
        "es_provisionable": fila.es_provisionable,
        "confirmado": fila.confirmado_en is not None,
    }


def _marca_in_a_detalle(body: MarcaPercepcionIn) -> dict[str, Any]:
    return {
        "es_ingreso_ordinario": body.es_ingreso_ordinario,
        "base_exencion": body.base_exencion.value,
        "factor_exencion": str(body.factor_exencion) if body.factor_exencion is not None else None,
        "integra_sbc": body.integra_sbc,
        "es_provisionable": body.es_provisionable,
    }


def _difieren(fila: CatalogoPercepcionMarca, body: MarcaPercepcionIn) -> bool:
    return (
        fila.es_ingreso_ordinario != body.es_ingreso_ordinario
        or fila.base_exencion is not body.base_exencion
        or fila.factor_exencion != body.factor_exencion
        or fila.integra_sbc != body.integra_sbc
        or fila.es_provisionable != body.es_provisionable
    )


# --------------------------------------------------------------------------------------
# param_fiscal
# --------------------------------------------------------------------------------------


@router.get("/fiscal", response_model=ConfiguracionFiscalOut)
async def listar_fiscal(
    admin: Usuario = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> ConfiguracionFiscalOut:
    """Todos los tramos capturados, confirmados o no, con su procedencia — más las claves
    conocidas de las que no hay ni propuesta, que es el tercer estado del cuadro de
    degradación y el único que exige ir a capturar algo."""
    filas = list(
        (await db.scalars(select(ParamFiscal).order_by(ParamFiscal.clave, ParamFiscal.vigencia_desde))).all()
    )
    con_valor = {fila.clave for fila in filas}
    return ConfiguracionFiscalOut(
        parametros=[_param_a_salida(fila) for fila in filas],
        claves_sin_valor=sorted(cfg.CLAVES_PARAM_FISCAL - con_valor),
    )


async def _snapshot_del_tramo(db: AsyncSession, clave: str, vigencia_desde: date) -> dict[str, Any] | None:
    """El contenido del tramo **antes** de escribirlo, para el `detalle` de la bitácora.

    Dos decisiones que parecen detalle y no lo son:

    1. **Selecciona columnas, no la entidad.** Cargar el `ParamFiscal` por el ORM lo metería
       en el mapa de identidad, y la lectura `FOR UPDATE` de `guardar_param_fiscal` devolvería
       *ese mismo objeto* sin refrescar sus atributos (SQLAlchemy no pisa lo ya cargado salvo
       con `populate_existing()`): el candado seguiría tomándose, pero la comprobación de
       solapamiento razonaría sobre el snapshot viejo. Una fila de columnas no toca el mapa de
       identidad.
    2. **Toma el candado sobre el mismo rango** que `guardar_param_fiscal` (`clave = ...`), no
       sobre la fila exacta. Un rango más angosto aquí y uno más ancho después abriría un ciclo
       de espera entre dos peticiones de la misma clave con `vigencia_desde` distintos; con el
       mismo rango, la segunda petición simplemente espera a la primera.
    """
    fila = (
        await db.execute(
            select(
                ParamFiscal.vigencia_desde,
                ParamFiscal.ejercicio,
                ParamFiscal.valor,
                ParamFiscal.vigencia_hasta,
                ParamFiscal.origen,
                ParamFiscal.fuente,
                ParamFiscal.confirmado_en,
            )
            .where(ParamFiscal.clave == clave)
            .with_for_update()
        )
    ).all()
    previa = next((f for f in fila if f.vigencia_desde == vigencia_desde), None)
    if previa is None:
        return None
    return {
        "valor": str(previa.valor),
        "ejercicio": previa.ejercicio,
        "vigencia_hasta": previa.vigencia_hasta.isoformat() if previa.vigencia_hasta else None,
        "origen": previa.origen.value,
        "fuente": previa.fuente,
        "confirmado": previa.confirmado_en is not None,
    }


@router.put("/fiscal/{clave}", response_model=ParamFiscalOut)
async def guardar_fiscal(
    clave: str,
    body: ParamFiscalGuardarIn,
    admin: Usuario = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ParamFiscalOut:
    """Captura o corrige un tramo a mano. Queda con `origen: MANUAL` y **sin confirmar**:
    capturar no confirma, ni siquiera cuando quien captura es la misma persona que confirmaría.

    Toda la validación (clave conocida, valor positivo, fuente no vacía, vigencias coherentes,
    sin solapamiento) vive en `guardar_param_fiscal` y no se duplica aquí — duplicarla haría
    que las dos copias se separaran y que la del endpoint pareciera la autoridad.
    """
    anterior = await _snapshot_del_tramo(db, clave, body.vigencia_desde)
    try:
        fila = await cfg.guardar_param_fiscal(
            db,
            clave=clave,
            valor=body.valor,
            vigencia_desde=body.vigencia_desde,
            vigencia_hasta=body.vigencia_hasta,
            origen=OrigenValor.MANUAL,
            fuente=body.fuente,
            ejercicio=body.ejercicio,
        )
    except cfg.SolapamientoDeVigencia as exc:
        # 409 y no 422: el dato que llegó es válido, lo que choca es el estado de la tabla.
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail={"codigo": "VIGENCIA_SOLAPADA", "mensaje": str(exc)}
        ) from exc
    except cfg.ErrorDeConfiguracion as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"codigo": "CONFIGURACION_INVALIDA", "mensaje": str(exc)}
        ) from exc

    # La columna es `Numeric(18,6)`: releerla hace que la respuesta y la bitácora digan la
    # cifra **con la escala que quedó almacenada** ("118.000000"), no la que tecleó el cliente
    # ("118.00"). Numéricamente son la misma, pero un `GET` posterior devolvería la primera y
    # la pantalla mostraría dos textos distintos para el mismo valor.
    await db.refresh(fila)

    await bitacora_service.registrar(
        db,
        actor=admin.correo,
        accion="capturar_param_fiscal",
        entidad=f"param_fiscal:{clave}@{body.vigencia_desde.isoformat()}",
        # El anterior y el nuevo, que es lo que sustituye al diff de git en una configuración
        # que se administra desde una pantalla.
        detalle={"clave": clave, "anterior": anterior, "nuevo": _param_a_detalle(fila)},
    )
    await db.commit()
    return _param_a_salida(fila)


def _param_a_detalle(fila: ParamFiscal) -> dict[str, Any]:
    return {
        "valor": str(fila.valor),
        "ejercicio": fila.ejercicio,
        "vigencia_hasta": fila.vigencia_hasta.isoformat() if fila.vigencia_hasta else None,
        "origen": fila.origen.value,
        "fuente": fila.fuente,
        "confirmado": fila.confirmado_en is not None,
    }


@router.post("/fiscal/{clave}/confirmar", response_model=ParamFiscalOut)
async def confirmar_fiscal(
    clave: str,
    body: ParamFiscalConfirmarIn,
    admin: Usuario = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ParamFiscalOut:
    """Confirma un tramo propuesto: a partir de aquí `valor_vigente` lo devuelve y los informes
    calculan con él.

    El `FOR UPDATE` toma el mismo rango por clave que `guardar_param_fiscal`, así que una
    captura simultánea de la misma clave espera en vez de colarse entre la comparación del
    valor y la escritura de la confirmación.
    """
    tramos = list((await db.scalars(select(ParamFiscal).where(ParamFiscal.clave == clave).with_for_update())).all())
    fila = next((t for t in tramos if t.vigencia_desde == body.vigencia_desde), None)
    if fila is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No encontrado.")

    if fila.valor != body.valor:
        # `Decimal("117.31") == Decimal("117.310000")` es verdadero: la comparación es por
        # valor numérico, no por escala, así que el cliente no tiene que adivinar los decimales
        # con los que la columna `Numeric(18,6)` devolvió la cifra.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "codigo": "VALOR_CAMBIO",
                "mensaje": (
                    f"El valor de `{clave}` cambió mientras revisabas: está en {fila.valor} y confirmaste "
                    f"{body.valor}. Vuelve a cargar la pantalla y revísalo otra vez antes de confirmar."
                ),
            },
        )

    if fila.confirmado_en is not None:
        # Idempotente: reconfirmar lo ya confirmado no cambia nada, así que tampoco reescribe
        # quién lo confirmó (sería borrar el rastro del que sí lo revisó) ni deja bitácora de
        # un cambio que no ocurrió.
        return _param_a_salida(fila)

    fila.confirmado_por = _actor(admin.correo)
    fila.confirmado_en = _ahora()
    await db.flush()
    await bitacora_service.registrar(
        db,
        actor=admin.correo,
        accion="confirmar_param_fiscal",
        entidad=f"param_fiscal:{clave}@{body.vigencia_desde.isoformat()}",
        detalle={
            "clave": clave,
            "anterior": {"valor": str(fila.valor), "confirmado": False},
            "nuevo": {"valor": str(fila.valor), "confirmado": True},
        },
    )
    await db.commit()
    return _param_a_salida(fila)


# --------------------------------------------------------------------------------------
# catalogo_percepcion_marca (§3.1)
# --------------------------------------------------------------------------------------


@router.get("/percepciones", response_model=list[MarcaPercepcionOut])
async def listar_percepciones(
    admin: Usuario = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> list[MarcaPercepcionOut]:
    filas = await db.scalars(
        select(CatalogoPercepcionMarca).order_by(CatalogoPercepcionMarca.tipo_percepcion)
    )
    return [_marca_a_salida(fila) for fila in filas]


@router.put("/percepciones/{tipo}", response_model=MarcaPercepcionOut)
async def guardar_percepcion(
    tipo: str,
    body: MarcaPercepcionIn,
    admin: Usuario = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> MarcaPercepcionOut:
    """Captura o corrige las marcas de un tipo de percepción. Igual que los importes: **capturar
    no confirma**, y si algo cambia, la confirmación anterior se limpia — un `factor_exencion`
    distinto es una exención distinta y vuelve a la cola de revisión."""
    if len(tipo) != 3:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "codigo": "TIPO_PERCEPCION_INVALIDO",
                "mensaje": (
                    f"`tipo_percepcion` debe tener 3 posiciones y llegó {tipo!r}. Las claves del catálogo "
                    "del SAT llevan sus ceros a la izquierda: '001' no es '1'."
                ),
            },
        )

    fila = await db.get(CatalogoPercepcionMarca, tipo, with_for_update=True)
    anterior = _marca_a_detalle(fila) if fila is not None else None
    if fila is None:
        fila = CatalogoPercepcionMarca(
            tipo_percepcion=tipo,
            es_ingreso_ordinario=body.es_ingreso_ordinario,
            base_exencion=body.base_exencion,
            factor_exencion=body.factor_exencion,
            integra_sbc=body.integra_sbc,
            es_provisionable=body.es_provisionable,
        )
        db.add(fila)
    else:
        if _difieren(fila, body):
            fila.confirmado_por = None
            fila.confirmado_en = None
        fila.es_ingreso_ordinario = body.es_ingreso_ordinario
        fila.base_exencion = body.base_exencion
        fila.factor_exencion = body.factor_exencion
        fila.integra_sbc = body.integra_sbc
        fila.es_provisionable = body.es_provisionable
    await db.flush()
    await db.refresh(fila)  # escala real de `Numeric(9,4)`; ver el mismo comentario en `guardar_fiscal`

    await bitacora_service.registrar(
        db,
        actor=admin.correo,
        accion="capturar_marca_percepcion",
        entidad=f"catalogo_percepcion_marca:{tipo}",
        detalle={"tipo_percepcion": tipo, "anterior": anterior, "nuevo": _marca_a_detalle(fila)},
    )
    await db.commit()
    return _marca_a_salida(fila)


@router.post("/percepciones/{tipo}/confirmar", response_model=MarcaPercepcionOut)
async def confirmar_percepcion(
    tipo: str,
    body: MarcaPercepcionIn,
    admin: Usuario = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> MarcaPercepcionOut:
    """Confirma las marcas de un tipo de percepción: a partir de aquí `marcas_de_percepcion`
    las devuelve y los informes calculan exenciones con ellas.

    Existe porque sin él la puerta de confirmación de esta tabla sería una puerta tapiada: la
    captura nunca confirma, así que ninguna marca podría llegar jamás a calcular. Y pide el
    juego completo de marcas —no solo el tipo— por la misma razón que los importes: lo que se
    confirma es *lo que se revisó*, y si cambió entre la pantalla y el clic, se rechaza con 409.
    """
    fila = await db.get(CatalogoPercepcionMarca, tipo, with_for_update=True)
    if fila is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No encontrado.")
    if _difieren(fila, body):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "codigo": "MARCAS_CAMBIARON",
                "mensaje": (
                    f"Las marcas del tipo {tipo} cambiaron mientras las revisabas. Vuelve a cargar la "
                    "pantalla y revísalas otra vez antes de confirmarlas."
                ),
            },
        )
    if fila.confirmado_en is not None:
        return _marca_a_salida(fila)

    fila.confirmado_por = _actor(admin.correo)
    fila.confirmado_en = _ahora()
    await db.flush()
    await bitacora_service.registrar(
        db,
        actor=admin.correo,
        accion="confirmar_marca_percepcion",
        entidad=f"catalogo_percepcion_marca:{tipo}",
        detalle={
            "tipo_percepcion": tipo,
            "anterior": {**_marca_in_a_detalle(body), "confirmado": False},
            "nuevo": {**_marca_in_a_detalle(body), "confirmado": True},
        },
    )
    await db.commit()
    return _marca_a_salida(fila)


# --------------------------------------------------------------------------------------
# Configuración por empresa
# --------------------------------------------------------------------------------------


async def _exige_empresa(db: AsyncSession, empresa_id: int) -> None:
    """Un administrador global pasa `require_empresa` para *cualquier* `empresa_id`, exista o
    no (`deps.py:85`). Sin esta comprobación, escribir la configuración de una empresa
    inexistente reventaría como error de llave foránea (500) en vez de decir 404."""
    if await db.get(Empresa, empresa_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No encontrado.")


@router_empresa.get("", response_model=ConfiguracionEmpresaOut)
async def obtener_configuracion_empresa(
    empresa_id: int,
    ctx: ContextoEmpresa = Depends(require_empresa(RolEmpresa.OPERADOR)),
    db: AsyncSession = Depends(get_db),
) -> ConfiguracionEmpresaOut:
    """Los tres campos, incluso cuando nunca se capturaron: viajan en `null`, no se omiten.
    "Sin zona salarial" es un estado que la pantalla tiene que poder mostrar —degrada las dos
    validaciones de salario mínimo de B-10— y un campo ausente en el JSON no lo comunica."""
    await _exige_empresa(db, empresa_id)
    config = await cfg.configuracion_de_empresa(db, empresa_id)
    return ConfiguracionEmpresaOut(
        empresa_id=empresa_id,
        zona_salarial=config.zona_salarial.value if config is not None and config.zona_salarial else None,
        dias_aguinaldo=config.dias_aguinaldo if config is not None else None,
        factor_prima_vacacional=config.factor_prima_vacacional if config is not None else None,
    )


@router_empresa.put("", response_model=ConfiguracionEmpresaOut)
async def guardar_configuracion_empresa(
    empresa_id: int,
    body: ConfiguracionEmpresaIn,
    ctx: ContextoEmpresa = Depends(require_empresa(RolEmpresa.OPERADOR)),
    db: AsyncSession = Depends(get_db),
) -> ConfiguracionEmpresaOut:
    """Reemplaza los tres campos de política laboral. `empresa_id` sale del path y ya lo validó
    `require_empresa`; el cuerpo no lo lleva, para que no exista la tentación de leerlo de ahí."""
    await _exige_empresa(db, empresa_id)
    config = await db.get(ConfiguracionEmpresa, empresa_id, with_for_update=True)
    anterior: dict[str, Any] | None = None
    if config is None:
        config = ConfiguracionEmpresa(empresa_id=empresa_id)
        db.add(config)
    else:
        anterior = _config_empresa_a_detalle(config)
    config.zona_salarial = body.zona_salarial
    config.dias_aguinaldo = body.dias_aguinaldo
    config.factor_prima_vacacional = body.factor_prima_vacacional
    await db.flush()
    await db.refresh(config)  # escala real de `Numeric(5,4)`; ver el comentario en `guardar_fiscal`

    await bitacora_service.registrar(
        db,
        actor=ctx.usuario.correo,
        accion="guardar_configuracion_empresa",
        entidad=f"empresa:{empresa_id}",
        detalle={"anterior": anterior, "nuevo": _config_empresa_a_detalle(config)},
    )
    await db.commit()
    return ConfiguracionEmpresaOut(
        empresa_id=empresa_id,
        zona_salarial=config.zona_salarial.value if config.zona_salarial else None,
        dias_aguinaldo=config.dias_aguinaldo,
        factor_prima_vacacional=config.factor_prima_vacacional,
    )


def _config_empresa_a_detalle(config: ConfiguracionEmpresa) -> dict[str, Any]:
    return {
        "zona_salarial": config.zona_salarial.value if config.zona_salarial else None,
        "dias_aguinaldo": config.dias_aguinaldo,
        "factor_prima_vacacional": (
            str(config.factor_prima_vacacional) if config.factor_prima_vacacional is not None else None
        ),
    }


@router_empresa.get("/mapeos", response_model=MapeosEmpresaOut)
async def obtener_mapeos(
    empresa_id: int,
    ctx: ContextoEmpresa = Depends(require_empresa(RolEmpresa.OPERADOR)),
    db: AsyncSession = Depends(get_db),
) -> MapeosEmpresaOut:
    await _exige_empresa(db, empresa_id)
    return await _leer_mapeos(db, empresa_id)


async def _leer_mapeos(db: AsyncSession, empresa_id: int) -> MapeosEmpresaOut:
    """Los dos mapeos de una empresa, en dos consultas (regla 11: nada de una por renglón)."""
    departamentos = (
        await db.execute(
            select(MapDepartamento.departamento_texto, MapDepartamento.centro_costo)
            .where(MapDepartamento.empresa_id == empresa_id)
            .order_by(MapDepartamento.departamento_texto)
        )
    ).all()
    conceptos = (
        await db.execute(
            select(
                MapConceptoProvision.naturaleza,
                MapConceptoProvision.tipo,
                MapConceptoProvision.clave,
                MapConceptoProvision.categoria,
            )
            .where(MapConceptoProvision.empresa_id == empresa_id)
            .order_by(MapConceptoProvision.naturaleza, MapConceptoProvision.tipo, MapConceptoProvision.clave)
        )
    ).all()
    return MapeosEmpresaOut(
        departamentos=[
            MapDepartamentoOut(departamento_texto=texto, centro_costo=centro) for texto, centro in departamentos
        ],
        conceptos_provision=[
            MapConceptoProvisionOut(naturaleza=naturaleza, tipo=tipo, clave=clave, categoria=categoria.value)
            for naturaleza, tipo, clave, categoria in conceptos
        ],
    )


@router_empresa.put("/mapeos", response_model=MapeosEmpresaOut)
async def guardar_mapeos(
    empresa_id: int,
    body: MapeosEmpresaIn,
    ctx: ContextoEmpresa = Depends(require_empresa(RolEmpresa.OPERADOR)),
    db: AsyncSession = Depends(get_db),
) -> MapeosEmpresaOut:
    """Reemplaza los dos mapeos completos de la empresa. B-06 agrupa por centro de costo y B-08
    ni siquiera se genera sin `map_concepto_provision`, así que lo que aquí se borra tiene
    efecto directo en los informes: por eso el `detalle` de la bitácora lleva las dos listas
    enteras, antes y después, y no solo un conteo."""
    await _exige_empresa(db, empresa_id)

    # Claves naturales duplicadas dentro del mismo cuerpo: dos renglones que se pisan entre sí.
    # Sin este rechazo, el último gana y el usuario ve guardado algo distinto de lo que mandó.
    _exige_sin_duplicados(
        [d.departamento_texto for d in body.departamentos],
        "departamentos",
        "`departamento_texto`",
    )
    _exige_sin_duplicados(
        [(c.naturaleza, c.tipo, c.clave) for c in body.conceptos_provision],
        "conceptos_provision",
        "la terna (`naturaleza`, `tipo`, `clave`)",
    )

    anterior = (await _leer_mapeos(db, empresa_id)).model_dump(mode="json")

    await db.execute(delete(MapDepartamento).where(MapDepartamento.empresa_id == empresa_id))
    await db.execute(delete(MapConceptoProvision).where(MapConceptoProvision.empresa_id == empresa_id))
    # Orden estable de inserción por clave natural: dos peticiones simultáneas de empresas
    # distintas nunca se cruzan (el `empresa_id` va en la PK), pero dos de la *misma* empresa
    # sí competirían por las mismas filas, y tomar los candados siempre en el mismo orden es lo
    # que impide el ciclo de espera — el mismo argumento que el `sorted()` del cargador de YAML.
    for depto in sorted(body.departamentos, key=lambda d: d.departamento_texto):
        db.add(
            MapDepartamento(
                empresa_id=empresa_id,
                departamento_texto=depto.departamento_texto,
                centro_costo=depto.centro_costo,
            )
        )
    for concepto in sorted(body.conceptos_provision, key=lambda c: (c.naturaleza, c.tipo, c.clave)):
        db.add(
            MapConceptoProvision(
                empresa_id=empresa_id,
                naturaleza=concepto.naturaleza,
                tipo=concepto.tipo,
                clave=concepto.clave,
                categoria=concepto.categoria,
            )
        )
    await db.flush()

    salida = await _leer_mapeos(db, empresa_id)
    await bitacora_service.registrar(
        db,
        actor=ctx.usuario.correo,
        accion="guardar_mapeos_empresa",
        entidad=f"empresa:{empresa_id}",
        detalle={"anterior": anterior, "nuevo": salida.model_dump(mode="json")},
    )
    await db.commit()
    return salida


def _exige_sin_duplicados(claves: list[Any], seccion: str, nombre: str) -> None:
    vistas: set[Any] = set()
    for clave in claves:
        if clave in vistas:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "codigo": "MAPEO_DUPLICADO",
                    "mensaje": (
                        f"`{seccion}` trae {nombre} repetida ({clave!r}). Dos renglones con la misma clave "
                        "se pisan entre sí: se guardaría el último y el resto se perdería en silencio."
                    ),
                },
            )
        vistas.add(clave)
