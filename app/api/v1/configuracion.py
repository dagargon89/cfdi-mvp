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

Y por qué las guardas de la confirmación tampoco viven aquí
------------------------------------------------------------
Por el mismo motivo, con un cliente más: además de la pantalla, confirma
`app/scripts/administrar_configuracion.py` (la persona que administra el Hub no siempre tiene
navegador delante). Si la comparación del importe y la de la huella vivieran en estos
endpoints, el script tendría que reimplementarlas y sería una puerta trasera con la forma
exacta de la puerta buena. Viven en `configuracion_fiscal.confirmar_param_fiscal` y
`confirmar_marca_percepcion`; aquí solo se traducen sus excepciones a códigos HTTP y se
escribe la fila de bitácora, que es lo único que sí cambia según por dónde se entró.

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
La configuración de una empresa es política laboral suya ⇒ `require_empresa`, con el
`empresa_id` del **path**, nunca del cuerpo: el que manda el navegador es un dato hostil.
Ahí el reparto es el mismo que en el resto de la API —leer `CONSULTA`, escribir `OPERADOR`—
y no por simetría: un usuario de `CONSULTA` ya puede generar los informes cuyo resultado
depende de la zona salarial, así que esconderle la entrada mientras se le muestra la salida
no protege nada y le deja un informe degradado que no puede explicarse.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ContextoEmpresa, get_db, require_admin, require_empresa
from app.api.v1.schemas import (
    AlertaVigenciaOut,
    CatalogoPercepcionesOut,
    ConceptoObservadoOut,
    ConfiguracionEmpresaIn,
    ConfiguracionEmpresaOut,
    ConfiguracionFiscalOut,
    DepartamentoObservadoOut,
    MapConceptoProvisionOut,
    MapDepartamentoOut,
    MapeosEmpresaIn,
    MapeosEmpresaOut,
    MarcaPercepcionConfirmarIn,
    MarcaPercepcionIn,
    MarcaPercepcionOut,
    MarcasPercepcion,
    ObservadosEmpresaOut,
    ParamFiscalConfirmarIn,
    ParamFiscalGuardarIn,
    ParamFiscalOut,
)
from app.informes import catalogos
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
from app.services import sincronizacion_fiscal as sincronizacion

router = APIRouter(prefix="/configuracion", tags=["configuracion-fiscal"])
router_empresa = APIRouter(prefix="/empresas/{empresa_id}/configuracion", tags=["configuracion-fiscal"])

# Re-exportado desde el servicio, donde vive junto a la guarda que lo usa. Se mantiene el
# nombre en este módulo porque es el que emite `MarcaPercepcionOut.nota_revision_hash`.
huella_de_nota = cfg.huella_de_nota


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


def _descripcion_percepcion(tipo: str) -> str | None:
    """La descripción de `c_TipoPercepcion` para un tipo, o `None` si no está.

    Usa `tipos_de` (cacheada, **falla abierto**) y no `catalog_code` por clave: listar las 44
    marcas haría 44 consultas al sqlite embebido, y aquí se está *leyendo*. Que falle abierto es
    lo correcto en esta dirección —una descripción ausente no impide revisar una marca—, al
    revés que en `exige_tipo_percepcion_conocido`, donde el mismo catálogo ilegible cierra la
    escritura con 503. El reparto es deliberado (ver el docstring de `app/informes/catalogos.py`).
    """
    return dict(catalogos.tipos_de("P")).get(tipo)


def _marca_a_salida(fila: CatalogoPercepcionMarca) -> MarcaPercepcionOut:
    return MarcaPercepcionOut(
        tipo_percepcion=fila.tipo_percepcion,
        descripcion_sat=_descripcion_percepcion(fila.tipo_percepcion),
        nota_revision_hash=huella_de_nota(fila.nota_revision),
        es_ingreso_ordinario=fila.es_ingreso_ordinario,
        base_exencion=fila.base_exencion.value,
        factor_exencion=fila.factor_exencion,
        integra_sbc=fila.integra_sbc,
        es_provisionable=fila.es_provisionable,
        sujeto_a_tope_conjunto=fila.sujeto_a_tope_conjunto,
        multiplicador_no_derivable=fila.multiplicador_no_derivable,
        nota_revision=fila.nota_revision,
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
        "sujeto_a_tope_conjunto": fila.sujeto_a_tope_conjunto,
        "multiplicador_no_derivable": fila.multiplicador_no_derivable,
        "nota_revision": fila.nota_revision,
        "confirmado": fila.confirmado_en is not None,
    }


def _marcas_de(body: MarcasPercepcion) -> cfg.MarcasQueSeConfirman:
    """El cuerpo Pydantic en la forma que entienden las guardas del servicio. La conversión es
    explícita y no un `model_dump()`: `MarcaPercepcionIn` y `MarcaPercepcionConfirmarIn` traen
    un campo de más cada uno, y un `**dict` los colaría o reventaría según cuál llegara."""
    return cfg.MarcasQueSeConfirman(
        es_ingreso_ordinario=body.es_ingreso_ordinario,
        base_exencion=body.base_exencion,
        factor_exencion=body.factor_exencion,
        integra_sbc=body.integra_sbc,
        es_provisionable=body.es_provisionable,
        sujeto_a_tope_conjunto=body.sujeto_a_tope_conjunto,
        multiplicador_no_derivable=body.multiplicador_no_derivable,
    )


# --------------------------------------------------------------------------------------
# param_fiscal
# --------------------------------------------------------------------------------------


@router.get("/fiscal", response_model=ConfiguracionFiscalOut)
async def listar_fiscal(
    admin: Usuario = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> ConfiguracionFiscalOut:
    """Todos los tramos capturados, confirmados o no, con su procedencia — más las claves
    conocidas de las que no hay ni propuesta, y **las alertas de vigencia**.

    Las alertas se calculan aquí y no se leen de una tabla: dependen de la fecha de hoy, y una
    alerta cacheada de anoche podría decir "al día" el 1 de febrero por la mañana. No hacen
    ninguna llamada de red (ver `app/services/sincronizacion_fiscal.py`), así que el `GET` no
    depende de que Banxico conteste.
    """
    filas = list(
        (await db.scalars(select(ParamFiscal).order_by(ParamFiscal.clave, ParamFiscal.vigencia_desde))).all()
    )
    con_valor = {fila.clave for fila in filas}
    alertas = await sincronizacion.alertas_de_vigencia(db, date.today())
    return ConfiguracionFiscalOut(
        parametros=[_param_a_salida(fila) for fila in filas],
        claves_sin_valor=sorted(cfg.CLAVES_PARAM_FISCAL - con_valor),
        alertas=[
            AlertaVigenciaOut(
                clave=alerta.clave,
                motivo=alerta.motivo,
                vigencia_desde=alerta.vigencia_desde,
                fecha_esperada=alerta.fecha_esperada,
                detalle=alerta.detalle,
            )
            for alerta in alertas
        ],
    )


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
    anterior = await cfg.snapshot_de_tramo(db, clave, body.vigencia_desde)
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
        detalle={"clave": clave, "anterior": anterior, "nuevo": cfg.detalle_de_tramo(fila)},
    )
    await db.commit()
    return _param_a_salida(fila)


@router.post("/fiscal/{clave}/confirmar", response_model=ParamFiscalOut)
async def confirmar_fiscal(
    clave: str,
    body: ParamFiscalConfirmarIn,
    admin: Usuario = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ParamFiscalOut:
    """Confirma un tramo propuesto: a partir de aquí `valor_vigente` lo devuelve y los informes
    calculan con él.

    Toda la guarda —el `FOR UPDATE` sobre el mismo rango que `guardar_param_fiscal` y el
    rechazo si el importe confirmado no coincide con el almacenado— vive en
    `cfg.confirmar_param_fiscal`, que es la misma que ejerce la línea de comandos. Aquí solo
    se traducen sus excepciones y se escribe la bitácora.
    """
    try:
        fila, cambio = await cfg.confirmar_param_fiscal(
            db, clave=clave, vigencia_desde=body.vigencia_desde, valor=body.valor, actor=admin.correo
        )
    except cfg.NoEncontrado as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No encontrado.") from exc
    except cfg.ValorCambio as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail={"codigo": "VALOR_CAMBIO", "mensaje": str(exc)}
        ) from exc

    if not cambio:
        # Idempotente: reconfirmar lo ya confirmado no cambia nada, así que tampoco deja
        # bitácora de un cambio que no ocurrió.
        return _param_a_salida(fila)

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


def _duda_nueva(fila: CatalogoPercepcionMarca, body: MarcaPercepcionIn) -> bool:
    """Si el `PUT` trae una duda que la marca no tenía, o una distinta de la que tenía.

    **Asimétrica a propósito**, y es lo que la distingue de `_difieren`:

    - nula → con nota, y nota → otra nota, devuelven la marca a la cola de revisión;
    - nota → nula, no. Resolver una duda no invalida nada; al contrario.

    Por qué la nota sí limpia la confirmación y la `fuente` de `param_fiscal` no, que parecen
    el mismo caso y no lo son: **`fuente` dice de dónde salió el valor; `nota_revision` dice
    que el valor podría estar mal.** Confirmar significa "una persona revisó esto y responde
    por ello"; si después aparece una duda que esa persona no tenía delante, mantener la
    confirmación afirma una revisión que, contra esa información, no ocurrió. Un campo neutro
    que cambia es ambiguo; un campo cuyo contenido *es* una advertencia, cuando aparece, no lo
    es — y esa falta de ambigüedad es justo lo que permite la regla asimétrica.
    """
    return body.nota_revision is not None and body.nota_revision != fila.nota_revision


# --------------------------------------------------------------------------------------
# catalogo_percepcion_marca (§3.1)
# --------------------------------------------------------------------------------------


def _exige_tipo_del_sat(tipo: str) -> None:
    """El `tipo` del path tiene que existir en `c_TipoPercepcion`, no solo medir 3 posiciones.

    Comprobar el largo dejaba pasar `ZZZ` y, peor, `150` por `015`: una marca huérfana que se
    captura y se confirma sin ruido mientras la `015` de verdad sigue sin confirmar y sin
    calcular — silencioso en las dos puntas. La lista blanca vive en el servicio y la comparte
    con el cargador de semillas, igual que `CLAVES_PARAM_FISCAL`.
    """
    try:
        cfg.exige_tipo_percepcion_conocido(tipo)
    except cfg.CatalogoDelSatIlegible as exc:
        # No es culpa del cuerpo que llegó: lo que falla es la herramienta de validación. Un
        # 422 le diría al usuario que corrija algo que está bien. `503` dice la verdad —el
        # servidor no puede atender esto ahora— y deja el rastro para el operador.
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"codigo": "CATALOGO_SAT_ILEGIBLE", "mensaje": str(exc)},
        ) from exc
    except cfg.ErrorDeConfiguracion as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"codigo": "TIPO_PERCEPCION_INVALIDO", "mensaje": str(exc)},
        ) from exc


@router.get("/percepciones", response_model=CatalogoPercepcionesOut)
async def listar_percepciones(
    admin: Usuario = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> CatalogoPercepcionesOut:
    """Las marcas capturadas **y las claves del catálogo del SAT que todavía no tienen ninguna**.

    `claves_sin_marcas` espeja `claves_sin_valor` de `/fiscal` y hace autoritativo el
    denominador del "0 de 44": sin él, el cliente necesita su propia copia del catálogo del SAT
    para saber qué tarjetas existen, y esa copia se desincroniza en cuanto sube la versión de
    `satcfdi`. Ver `CatalogoPercepcionesOut` para el argumento completo y para qué pasa cuando
    el catálogo no se puede leer.
    """
    filas = list(
        (await db.scalars(select(CatalogoPercepcionMarca).order_by(CatalogoPercepcionMarca.tipo_percepcion))).all()
    )
    con_marcas = {fila.tipo_percepcion for fila in filas}
    return CatalogoPercepcionesOut(
        marcas=[_marca_a_salida(fila) for fila in filas],
        claves_sin_marcas=sorted(clave for clave, _ in catalogos.tipos_de("P") if clave not in con_marcas),
    )


@router.put("/percepciones/{tipo}", response_model=MarcaPercepcionOut)
async def guardar_percepcion(
    tipo: str,
    body: MarcaPercepcionIn,
    admin: Usuario = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> MarcaPercepcionOut:
    """Captura o corrige las marcas de un tipo de percepción. Igual que los importes: **capturar
    no confirma**, y si algo cambia, la confirmación anterior se limpia — un `factor_exencion`
    distinto es una exención distinta y vuelve a la cola de revisión. Una **duda nueva** hace
    lo mismo, aunque las seis marcas no se muevan: ver `_duda_nueva`."""
    _exige_tipo_del_sat(tipo)

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
            sujeto_a_tope_conjunto=body.sujeto_a_tope_conjunto,
            multiplicador_no_derivable=body.multiplicador_no_derivable,
            nota_revision=body.nota_revision,
        )
        db.add(fila)
    else:
        if cfg.marcas_difieren(fila, _marcas_de(body)) or _duda_nueva(fila, body):
            fila.confirmado_por = None
            fila.confirmado_en = None
        fila.es_ingreso_ordinario = body.es_ingreso_ordinario
        fila.base_exencion = body.base_exencion
        fila.factor_exencion = body.factor_exencion
        fila.integra_sbc = body.integra_sbc
        fila.es_provisionable = body.es_provisionable
        fila.sujeto_a_tope_conjunto = body.sujeto_a_tope_conjunto
        fila.multiplicador_no_derivable = body.multiplicador_no_derivable
        fila.nota_revision = body.nota_revision
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
    body: MarcaPercepcionConfirmarIn,
    admin: Usuario = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> MarcaPercepcionOut:
    """Confirma las marcas de un tipo de percepción: a partir de aquí `marcas_de_percepcion`
    las devuelve y los informes calculan exenciones con ellas.

    Existe porque sin él la puerta de confirmación de esta tabla sería una puerta tapiada: la
    captura nunca confirma, así que ninguna marca podría llegar jamás a calcular. Y pide el
    juego completo de marcas —no solo el tipo— por la misma razón que los importes: lo que se
    confirma es *lo que se revisó*, y si cambió entre la pantalla y el clic, se rechaza con 409.

    El cuerpo son las seis marcas que calculan, **sin el texto de `nota_revision`** pero **con
    su huella**: confirmar no es editar —quien resuelve la duda la borra o la reescribe con un
    `PUT`, que es el otro acto—, pero sí es afirmar que se miró lo que se activa, y la duda es
    parte de eso. Ver `cfg.duda_no_vista` para el caso concurrente que cierra la huella y
    `MarcaPercepcionConfirmarIn` para por qué es la huella y no el texto.
    """
    try:
        fila, cambio = await cfg.confirmar_marca_percepcion(
            db,
            tipo=tipo,
            marcas=_marcas_de(body),
            nota_revision_hash=body.nota_revision_hash,
            actor=admin.correo,
        )
    except cfg.CatalogoDelSatIlegible as exc:
        # No es culpa del cuerpo que llegó: lo que falla es la herramienta de validación. Un
        # 422 le diría al usuario que corrija algo que está bien.
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"codigo": "CATALOGO_SAT_ILEGIBLE", "mensaje": str(exc)},
        ) from exc
    except cfg.NoEncontrado as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No encontrado.") from exc
    except cfg.DudaNoVista as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail={"codigo": "DUDA_NO_VISTA", "mensaje": str(exc)}
        ) from exc
    except cfg.MarcasCambiaron as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail={"codigo": "MARCAS_CAMBIARON", "mensaje": str(exc)}
        ) from exc
    except cfg.ErrorDeConfiguracion as exc:
        # Lo único que queda: el tipo no existe en `c_TipoPercepcion`.
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"codigo": "TIPO_PERCEPCION_INVALIDO", "mensaje": str(exc)},
        ) from exc

    if not cambio:
        return _marca_a_salida(fila)

    await bitacora_service.registrar(
        db,
        actor=admin.correo,
        accion="confirmar_marca_percepcion",
        entidad=f"catalogo_percepcion_marca:{tipo}",
        detalle={
            "tipo_percepcion": tipo,
            "anterior": {**cfg.detalle_de_marcas(_marcas_de(body)), "confirmado": False},
            "nuevo": {**cfg.detalle_de_marcas(_marcas_de(body)), "confirmado": True},
        },
    )
    await db.commit()
    return _marca_a_salida(fila)


# --------------------------------------------------------------------------------------
# Configuración por empresa
# --------------------------------------------------------------------------------------


async def _exige_empresa(db: AsyncSession, empresa_id: int) -> Empresa:
    """Un administrador global pasa `require_empresa` para *cualquier* `empresa_id`, exista o
    no (`deps.py:85`). Sin esta comprobación, escribir la configuración de una empresa
    inexistente reventaría como error de llave foránea (500) en vez de decir 404.

    Devuelve la empresa porque el universo de nómina se acota por su RFC (`rfc_emisor`), no
    solo por `empresa_id`: la empresa es el patrón (§11 del diseño)."""
    empresa = await db.get(Empresa, empresa_id)
    if empresa is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No encontrado.")
    return empresa


@router_empresa.get("", response_model=ConfiguracionEmpresaOut)
async def obtener_configuracion_empresa(
    empresa_id: int,
    # Leer pide CONSULTA, escribir pide OPERADOR — el reparto del resto de la API
    # (`informes.py:53` contra `:34`, y lo mismo en comprobantes, descargas, eventos y
    # efirma). Y el fondo pesa más que la simetría: un usuario de CONSULTA ya puede generar
    # los informes cuyo resultado depende de la zona salarial, así que esconderle la entrada
    # mientras se le muestra la salida no protege nada y le deja un informe degradado que no
    # puede explicarse.
    ctx: ContextoEmpresa = Depends(require_empresa(RolEmpresa.CONSULTA)),
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
        anterior = cfg.detalle_de_config_empresa(config)
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
        detalle={"anterior": anterior, "nuevo": cfg.detalle_de_config_empresa(config)},
    )
    await db.commit()
    return ConfiguracionEmpresaOut(
        empresa_id=empresa_id,
        zona_salarial=config.zona_salarial.value if config.zona_salarial else None,
        dias_aguinaldo=config.dias_aguinaldo,
        factor_prima_vacacional=config.factor_prima_vacacional,
    )


@router_empresa.get("/mapeos", response_model=MapeosEmpresaOut)
async def obtener_mapeos(
    empresa_id: int,
    ctx: ContextoEmpresa = Depends(require_empresa(RolEmpresa.CONSULTA)),
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
    try:
        # `_exige_sin_duplicados` atrapa las claves repetidas **exactas**; lo que no puede atrapar
        # es que dos textos distintos sean la misma clave para la colación de la tabla, porque eso
        # exigiría reimplementar `utf8mb4_unicode_ci` en Python. Lo dice la base y aquí se traduce.
        await cfg.escribir_mapeos(db)
    except cfg.ColisionDeMapeo as exc:
        await db.rollback()
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"codigo": "MAPEO_COLISION_DE_CLAVE", "mensaje": str(exc)},
        ) from exc

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


# --------------------------------------------------------------------------------------
# Lo que la nómina emitió de verdad: configurar es reconocer y elegir, no teclear
# --------------------------------------------------------------------------------------

@router_empresa.get("/conceptos-observados", response_model=ObservadosEmpresaOut)
async def conceptos_observados(
    empresa_id: int,
    ctx: ContextoEmpresa = Depends(require_empresa(RolEmpresa.CONSULTA)),
    db: AsyncSession = Depends(get_db),
) -> ObservadosEmpresaOut:
    """Los conceptos y departamentos que **aparecen de verdad** en los CFDI de nómina de la
    empresa, con su descripción y la categoría o el centro de costo que ya tengan.

    Existe porque pedirle al usuario que teclee `P/002/047` era pedirle un dato que no tiene:
    esas claves las inventa el sistema de nómina del patrón y nadie las conoce de memoria.
    Con esta lista la pantalla enumera lo que la nómina emitió, la persona **reconoce la
    descripción** —"Aguinaldo", "Prima vacacional"— y elige categoría; nunca teclea una clave.
    Es también la única forma de saber si la clasificación está **completa**, que es la
    condición que B-08 necesita para poder distinguir "no se pagó aguinaldo" de "sí se pagó y
    no sé en cuál concepto viene".

    **Sin filtro de fecha ni de estatus, a propósito.** No es un informe: es el inventario de
    lo que hay que configurar, y un concepto que solo apareció en una nómina de hace dos años
    o en un CFDI cancelado sigue necesitando categoría — si no, la clasificación nunca queda
    completa y B-08 nunca se genera.

    Cuatro consultas agregadas en total (una por naturaleza más la de departamentos), todas
    con `GROUP BY` en la base: ni una por renglón (regla 11). La consulta vive en
    `cfg.observados_de_empresa` porque `app/scripts/administrar_configuracion.py` enumera el
    mismo inventario, y dos copias mostrarían dos listas distintas de lo que falta clasificar.
    """
    empresa = await _exige_empresa(db, empresa_id)
    observados = await cfg.observados_de_empresa(db, empresa)

    conceptos = [
        ConceptoObservadoOut(
            naturaleza=c.naturaleza,
            tipo=c.tipo,
            clave=c.clave,
            concepto=c.concepto,
            descripcion_sat=catalogos.descripcion(c.naturaleza, c.tipo),
            comprobantes=c.comprobantes,
            importe=c.importe,
            categoria=c.categoria.value if c.categoria is not None else None,
        )
        for c in observados.conceptos
    ]
    departamentos = [
        DepartamentoObservadoOut(
            departamento_texto=d.departamento_texto,
            comprobantes=d.comprobantes,
            centro_costo=d.centro_costo,
            clave_en_la_base=d.clave_en_la_base,
        )
        for d in observados.departamentos
    ]

    return ObservadosEmpresaOut(
        conceptos=conceptos,
        departamentos=departamentos,
        # **Solo percepciones.** Un concepto sin clave no se puede clasificar (la clave va en la
        # PK del mapeo) y una deducción no puede ser aguinaldo —el aguinaldo no se le descuenta
        # a nadie—, así que ninguno de los dos cuenta como pendiente: contarlos dejaría el
        # marcador clavado en un número que solo baja capturando `NO_APLICA` en renglones que
        # nunca debieron entrar. El criterio vive en `cfg.percepciones_sin_clasificar` y es el
        # mismo que usa `app/scripts/administrar_configuracion.py`.
        sin_clasificar=len(cfg.percepciones_sin_clasificar(observados)),
        sin_mapear=sum(1 for d in departamentos if d.centro_costo is None),
    )
