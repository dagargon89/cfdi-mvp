"""Esquemas Pydantic — espejo de las formas JSON de doc 05 (contrato `ApiClient` congelado)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, EmailStr, Field, field_validator, model_validator

from app.models.enums import (
    BaseExencion,
    CategoriaProvision,
    RolEmpresa,
    RolGlobal,
    SolicitudTipo,
    TipoEvento,
    TipoJob,
    ZonaSalarial,
)


class EfirmaResumenOut(BaseModel):
    presente: bool
    not_after: str | None


class EmpresaResumenOut(BaseModel):
    empresa_id: int
    nombre: str
    rfc: str
    rol: str
    activo: bool
    efirma: EfirmaResumenOut | None


class MeOut(BaseModel):
    usuario_id: int
    correo: str
    nombre: str
    rol_global: str
    empresas: list[EmpresaResumenOut]


class EmpresaCrearIn(BaseModel):
    nombre: str
    rfc: str


class EmpresaPatchIn(BaseModel):
    activo: bool | None = None


class EfirmaAltaOut(BaseModel):
    num_serie: str
    not_before: str
    not_after: str
    dias_para_vencer: int


class EfirmaMetaOut(BaseModel):
    num_serie: str
    not_before: str
    not_after: str


class BootstrapStatusOut(BaseModel):
    needs_bootstrap: bool


class AutomatizacionesConfig(BaseModel):
    """Interruptores de las tareas automáticas (beat). True = activa (comportamiento por defecto)."""

    sync_diaria: bool
    lista_69b: bool
    re_verificar: bool
    limpieza: bool
    # Alarma de vigencia fiscal + sincronización del tipo de cambio (informes fase 3, tarea 6).
    #
    # **Es el único con default**, y no por descuido: los otros cuatro son del contrato congelado
    # (doc 05 §9) y este llegó después. Un cliente viejo que haga `PUT` sin el campo no debe
    # recibir 422 — pero tampoco debe resetear a `true` un interruptor que el admin apagó. La
    # pantalla real hace `{...autos, [clave]: valor}` sobre lo que devolvió el `GET`, así que el
    # valor viaja de ida y vuelta y el default nunca llega a aplicarse en esa ruta.
    vigencia_fiscal: bool = True


class BootstrapAdminIn(BaseModel):
    correo: EmailStr
    nombre: str
    password: str = Field(min_length=8)
    token: str


class RegistroIn(BaseModel):
    nombre: str


class RegistroOut(BaseModel):
    estado: str


class UsuarioCrearIn(BaseModel):
    correo: EmailStr
    nombre: str
    rol_global: RolGlobal


class UsuarioOut(BaseModel):
    usuario_id: int
    correo: str
    nombre: str
    rol_global: str
    activo: bool
    aprobado: bool


class PermisoEmpresaOut(BaseModel):
    empresa_id: int
    empresa_nombre: str
    rol: str


class UsuarioAdminOut(UsuarioOut):
    permisos: list[PermisoEmpresaOut]


class PermisoIn(BaseModel):
    empresa_id: int
    rol: RolEmpresa


class PermisosIn(BaseModel):
    permisos: list[PermisoIn]


class UsuarioPatchIn(BaseModel):
    activo: bool | None = None
    rol_global: RolGlobal | None = None
    aprobado: bool | None = None


class DescargaCrearIn(BaseModel):
    tipo: TipoJob
    solicitud: SolicitudTipo
    desde: date
    hasta: date


class DescargaCrearOut(BaseModel):
    job_ids: list[int]
    ventanas: int


class JobOut(BaseModel):
    job_id: int
    tipo: str
    solicitud: str
    origen: str
    desde: str
    hasta: str
    estado: str
    intentos: int
    paquetes: int
    mensaje: str | None
    updated_at: str
    id_solicitud: str | None


class JobPageOut(BaseModel):
    data: list[JobOut]
    page: int
    per_page: int
    total: int


class MetadataPreviewOut(BaseModel):
    headers: list[str]
    filas: list[list[str]]
    total: int
    page: int
    per_page: int


class ComprobanteOut(BaseModel):
    comprobante_id: int
    uuid: str
    folio: str | None
    rfc_emisor: str
    rfc_receptor: str
    razon_social_emisor: str | None
    total: float | None
    fecha_emision: str | None
    tipo_comprobante: str | None
    estatus: str
    estatus_verificado_at: str | None
    xml_path: str | None


class ComprobantePageOut(BaseModel):
    data: list[ComprobanteOut]
    page: int
    per_page: int
    total: int


class AlcanceUuids(BaseModel):
    uuids: list[str]


class ValidarLoteIn(BaseModel):
    alcance: Literal["no_verificados", "todos"] | AlcanceUuids


class ComprobanteIdsIn(BaseModel):
    comprobante_ids: list[int]


class TareaCrearOut(BaseModel):
    tarea_id: str


class TareaEstadoOut(BaseModel):
    estado: Literal["pendiente", "completada", "fallida"]
    descarga_url: str | None = None


class EventoOut(BaseModel):
    evento_id: int
    tipo: str
    detalle: dict[str, object]
    created_at: str


class EventoPageOut(BaseModel):
    data: list[EventoOut]
    page: int
    per_page: int
    total: int


class Efos69bEstadoOut(BaseModel):
    version_lista: str | None
    registros: int


class NotificacionDestinoIn(BaseModel):
    correo: EmailStr
    eventos: list[TipoEvento]


class NotificacionesGuardarIn(BaseModel):
    destinos: list[NotificacionDestinoIn]


class NotificacionDestinoOut(BaseModel):
    correo: str
    eventos: list[str]


class NotificacionesOut(BaseModel):
    destinos: list[NotificacionDestinoOut]


class ConfigSmtpOut(BaseModel):
    configurado: bool
    host: str | None
    port: int | None
    usuario: str | None
    remitente: str | None
    tls: bool | None


class ConfigSmtpIn(BaseModel):
    host: str
    port: int = 587
    usuario: str
    # `None`/vacío conserva la contraseña ya guardada (editar host/remitente sin reteclearla).
    password: str | None = None
    remitente: str
    tls: bool = True


class ConfigSmtpProbarIn(ConfigSmtpIn):
    correo_destino: EmailStr


class InformeCatalogoOut(BaseModel):
    """Entrada del catálogo de informes. `parametros` es el JSON Schema de la clase
    `Parametros` del informe: el frontend genera su formulario desde ahí (spec §7.2)."""

    clave: str
    nombre: str
    grupo: str
    descripcion: str
    parametros: dict[str, Any]


class NormalizarIn(BaseModel):
    """Alcance del reproceso del ETL. `pendientes` es lo normal; `todos` se usa tras subir
    `ETL_VERSION`, cuando hay que releer el histórico completo."""

    alcance: Literal["pendientes", "todos"] = "pendientes"


class BitacoraOut(BaseModel):
    bitacora_id: int
    actor: str
    accion: str
    entidad: str
    detalle: dict[str, object] | None
    created_at: str


class BitacoraPageOut(BaseModel):
    data: list[BitacoraOut]
    page: int
    per_page: int
    total: int


# --------------------------------------------------------------------------------------
# Configuración fiscal (§12 del diseño, §2.12 y §3.1 del documento fuente)
# --------------------------------------------------------------------------------------


def _sin_float(bruto: Any) -> Any:
    """Rechaza un importe que llegó como **número** JSON, porque ya perdió precisión.

    Pydantic construye el `Decimal` de un número JSON pasando por `float`: verificado, un
    cuerpo con `{"valor": 12345678901.123456}` llega al validador como el `float`
    `12345678901.123455` y el `Decimal` resultante **ya trae el error**; no hay nada que
    corregir después. Un número entrecomillado (`"12345678901.123456"`) llega como texto y
    se convierte exacto. Es la misma regla —y por la misma razón— que el cargador de
    semillas aplica al YAML (`_decimal` en `app/services/configuracion_fiscal.py`).

    Los enteros JSON sí se aceptan: no pasan por `float` y son exactos.
    """
    if isinstance(bruto, float):
        raise ValueError(
            "manda el importe entre comillas (\"117.31\"), no como número JSON: un número se convierte "
            "pasando por float y pierde precisión antes de que el servidor pueda revisarlo."
        )
    return bruto


# Importe fiscal de entrada. La salida es un `Decimal` normal: Pydantic lo serializa a JSON
# como **cadena** conservando la escala exacta que trae la columna `Numeric` ("117.310000"),
# así que el valor sobrevive el viaje de ida y vuelta sin tocar un `float` en ningún punto.
ImporteExacto = Annotated[Decimal, BeforeValidator(_sin_float)]


class ParamFiscalOut(BaseModel):
    """Un tramo de `param_fiscal` con su procedencia y su estado de confirmación.

    `confirmado` es redundante con `confirmado_en` a propósito: es el dato que decide si el
    valor calcula, y la pantalla no debería tener que deducirlo de la nulidad de una fecha.
    """

    clave: str
    ejercicio: int
    valor: Decimal
    vigencia_desde: date
    vigencia_hasta: date | None
    origen: str
    fuente: str
    sincronizado_en: str | None
    confirmado: bool
    confirmado_por: str | None
    confirmado_en: str | None


class AlertaVigenciaOut(BaseModel):
    """Un valor fiscal (o una pieza de la maquinaria) que necesita atención hoy.

    `motivo` ∈ `AUSENTE|SIN_CONFIRMAR|CADUCADO` para los valores —capturar / un clic /
    actualizar el ejercicio— y `CATALOGO_ILEGIBLE|LIBRERIA_DESACTUALIZADA|SINCRONIZACION_FALLIDA`
    para la maquinaria. Los seis piden acciones distintas; fusionarlos haría que la alerta
    mintiera (un catálogo que no se puede abrir no es un valor "ausente").

    `detalle` es la frase lista para mostrar: `motivo` es una etiqueta de máquina y las alertas
    de maquinaria no se explican solas.
    """

    clave: str
    motivo: str
    vigencia_desde: date | None
    fecha_esperada: date | None
    detalle: str


class ConfiguracionFiscalOut(BaseModel):
    """`claves_sin_valor` hace visible el tercer estado del cuadro de degradación: una clave
    conocida de la que no hay **ni siquiera** una propuesta. Sin ella la pantalla solo podría
    distinguir "confirmado" de "propuesto", y la ausencia —el caso que hay que ir a
    capturar— sería un renglón que simplemente no aparece.

    `alertas` es lo que `claves_sin_valor` no puede decir: **que un valor confirmado ya
    caducó**. Una UMA de 2025 confirmada aparece como "confirmada" en todas las columnas de
    arriba y no está en `claves_sin_valor`, aunque el 1 de febrero de 2026 ya pasó y el valor
    esté mal. Los dos campos conviven: `claves_sin_valor` sigue cubriendo `TIPO_CAMBIO_USD`,
    que queda fuera de la alarma de calendario a propósito (ver
    `app/services/sincronizacion_fiscal.py`).
    """

    parametros: list[ParamFiscalOut]
    claves_sin_valor: list[str]
    alertas: list[AlertaVigenciaOut]


class ParamFiscalGuardarIn(BaseModel):
    """Captura o corrección manual de un tramo. **No confirma**: confirmar es otra llamada."""

    valor: ImporteExacto
    vigencia_desde: date
    vigencia_hasta: date | None = None
    fuente: str = Field(min_length=1, max_length=500)
    # Nulo = el año de `vigencia_desde`, que es lo correcto salvo para un tramo que arranca
    # a mitad de un ejercicio distinto del suyo.
    ejercicio: int | None = None


class ParamFiscalConfirmarIn(BaseModel):
    """El cliente manda **el valor que está confirmando**. Si no coincide con el almacenado
    el servidor responde 409: entre que la pantalla se pintó y que se hizo clic, la propuesta
    pudo cambiar (una recarga de semillas, otro administrador), y confirmar a ciegas es
    exactamente lo que el invariante de confirmación existe para evitar."""

    vigencia_desde: date
    valor: ImporteExacto


class MarcasPercepcion(BaseModel):
    """Las seis marcas del §3.1 que **calculan**: lo que se revisa y lo que se confirma.

    Mismas reglas que el cargador de semillas (`_leer_marca`): sin base de exención no hay
    factor, y con base sí lo hay.

    **Los seis campos son obligatorios, incluido `sujeto_a_tope_conjunto`.** No lleva default
    a propósito: este es el cuerpo que también confirma, y confirmar es afirmar que se miró
    lo que se está activando. Con un default de `false`, un cliente que ni menciona el campo
    confirmaría —o crearía— una marca de previsión social **sin el tope a la vista**, que es
    literalmente la condición que la migración `c7a1e0b4d92f` declaró inaceptable cuando
    limpió las 44 confirmaciones anteriores. Un 422 por un campo que falta es barato; una
    exención de más en B-03 no.
    """

    es_ingreso_ordinario: bool
    base_exencion: BaseExencion
    # `Numeric(9,4)` en la columna: 5 dígitos enteros y 4 decimales. Los límites evitan que un
    # valor fuera de molde salga como 500 de MySQL en vez de 422 con su explicación.
    factor_exencion: Annotated[Decimal, BeforeValidator(_sin_float), Field(gt=0, lt=Decimal("100000"), decimal_places=4)] | None = None
    integra_sbc: bool
    es_provisionable: bool
    # Si la exención de este tipo cae bajo el tope conjunto de previsión social del penúltimo
    # párrafo del art. 93 de la LISR (1 UMA anual sobre la SUMA de varios tipos). No es
    # derivable de `factor_exencion`: son los seis tipos 015/029/030/034/035/037 contra otros
    # diez con la misma `base_exencion: PORCENTAJE` pero exceptuados del tope.
    sujeto_a_tope_conjunto: bool

    @model_validator(mode="after")
    def _coherencia_de_exencion(self) -> MarcasPercepcion:
        if self.base_exencion is BaseExencion.NINGUNA and self.factor_exencion is not None:
            raise ValueError("con `base_exencion: NINGUNA` no puede haber `factor_exencion`.")
        if self.base_exencion is not BaseExencion.NINGUNA and self.factor_exencion is None:
            raise ValueError(f"`base_exencion: {self.base_exencion.value}` exige un `factor_exencion`.")
        if self.sujeto_a_tope_conjunto and self.base_exencion is BaseExencion.NINGUNA:
            # Misma regla que `_leer_marca` en el cargador: el tope limita una exención, y
            # aquí no hay ninguna que limitar.
            raise ValueError(
                "`sujeto_a_tope_conjunto: true` no tiene sentido con `base_exencion: NINGUNA` — o el "
                "tipo sí tiene exención y falta capturarla, o la marca del tope sobra."
            )
        return self


class MarcaPercepcionIn(MarcasPercepcion):
    """Cuerpo del `PUT`: las seis marcas **más** la duda declarada del renglón.

    `nota_revision` es editable porque **resolver la duda es parte de revisarla**. Un
    administrador que corrige una marca contra el texto del art. 93 tiene que poder decir "ya
    lo verifiqué, la duda queda resuelta" o dejar una más estrecha; si la nota quedara
    congelada en lo que escribió la semilla, la pantalla mostraría para siempre un aviso que
    ya no aplica, y la gente aprendería a ignorarlo — que es la forma más rápida de gastar la
    misma puerta que estas notas vinieron a proteger.

    **Obligatorio aunque admita `null`**, por la misma razón que el tope: con un default,
    un `PUT` que corrige un factor y no menciona la nota **borraría en silencio** una duda que
    alguien derivó contra la LISR. Borrarla tiene que costar escribir `null`.

    No está en el cuerpo de `POST .../confirmar` (`MarcasPercepcion`): confirmar no es editar,
    y la nota tampoco entra en la comparación que devuelve `409` — ver `_difieren` en
    `app/api/v1/configuracion.py`. Lo que sí hace, cuando **aparece o cambia** en un `PUT`, es
    limpiar la confirmación de esa marca; que desaparezca, no (ver `_duda_nueva`).
    """

    nota_revision: str | None

    @field_validator("nota_revision", mode="after")
    @classmethod
    def _normaliza_nota(cls, valor: str | None) -> str | None:
        # "" y "   " son la misma intención que `null` (no hay duda declarada) y tienen que
        # guardarse igual, o `GET` devolvería a veces `""` y a veces `null` para el mismo
        # estado y la pantalla tendría que comprobar los dos.
        if valor is None:
            return None
        limpio = valor.strip()
        return limpio or None


class MarcaPercepcionOut(BaseModel):
    tipo_percepcion: str
    # La descripción del catálogo `c_TipoPercepcion` del SAT ("Becas para trabajadores y/o
    # hijos"), resuelta del mismo `satcfdi` que valida la escritura. Sin ella, el cliente
    # necesitaba su propia copia del catálogo —dos copias del mismo dato, y la del cliente sin
    # actualizarse cuando se actualiza la librería—. `null` si la clave no está en la versión
    # instalada o si el catálogo no se pudo leer: leer falla abierto, escribir no (503).
    descripcion_sat: str | None
    es_ingreso_ordinario: bool
    base_exencion: str
    factor_exencion: Decimal | None
    integra_sbc: bool
    es_provisionable: bool
    sujeto_a_tope_conjunto: bool
    # La duda declarada, para que la pantalla la enseñe al lado del botón de confirmar. 39 de
    # los 44 tipos sembrados traen una; sin ella en la respuesta, confirmar sería a ciegas.
    nota_revision: str | None
    confirmado: bool
    confirmado_por: str | None
    confirmado_en: str | None


class ConfiguracionEmpresaIn(BaseModel):
    """Política laboral de una organización. Los tres campos admiten nulo **a propósito**:
    ver el docstring de `app/models/configuracion_fiscal.py`. Un PUT reemplaza los tres, así
    que mandar `null` es la forma de borrar un valor mal capturado."""

    zona_salarial: ZonaSalarial | None = None
    # Mínimo legal 15 días (art. 87 LFT); el tope solo evita un dedazo absurdo, no es política.
    dias_aguinaldo: int | None = Field(default=None, ge=1, le=365)
    # `Numeric(5,4)` en la columna: 9.9999 es el máximo representable y son 4 decimales. El
    # mínimo legal es 0.25 (art. 80 LFT) y cada patrón puede dar más, así que por abajo solo
    # se exige positivo. Los límites de arriba evitan que un valor fuera de molde salga como
    # 500 de MySQL en vez de 422 con su explicación.
    factor_prima_vacacional: Annotated[Decimal, BeforeValidator(_sin_float), Field(gt=0, le=Decimal("9.9999"), decimal_places=4)] | None = None


class ConfiguracionEmpresaOut(BaseModel):
    """Los tres campos viajan siempre, incluso nulos: "no configurado" es un estado que la
    pantalla tiene que poder mostrar (y que degrada B-10), no una ausencia que se omite."""

    empresa_id: int
    zona_salarial: str | None
    dias_aguinaldo: int | None
    factor_prima_vacacional: Decimal | None


class MapDepartamentoIn(BaseModel):
    departamento_texto: str = Field(min_length=1, max_length=100)
    centro_costo: str = Field(min_length=1, max_length=100)


class MapConceptoProvisionIn(BaseModel):
    # Claves de catálogo del SAT como texto: '001' nunca 1, los ceros a la izquierda cuentan.
    naturaleza: str = Field(min_length=1, max_length=1)
    tipo: str = Field(min_length=3, max_length=3)
    clave: str = Field(min_length=1, max_length=15)
    categoria: CategoriaProvision


class MapeosEmpresaIn(BaseModel):
    """Reemplazo completo de los dos mapeos de una empresa: lo que no venga en las listas
    deja de existir. Es un PUT, no un PATCH, para que borrar un renglón sea expresable."""

    departamentos: list[MapDepartamentoIn]
    conceptos_provision: list[MapConceptoProvisionIn]


class MapDepartamentoOut(BaseModel):
    departamento_texto: str
    centro_costo: str


class MapConceptoProvisionOut(BaseModel):
    naturaleza: str
    tipo: str
    clave: str
    categoria: str


class MapeosEmpresaOut(BaseModel):
    departamentos: list[MapDepartamentoOut]
    conceptos_provision: list[MapConceptoProvisionOut]


class ConceptoObservadoOut(BaseModel):
    """Un concepto de nómina que la empresa **realmente emitió**, con lo que hace falta para
    reconocerlo sin conocer su clave.

    `clave` es la clave interna del sistema de nómina del patrón y puede venir nula: el
    complemento no la exige y B-02 ya emite `CLAVE_VACIA` por ello. Un concepto sin clave no
    se puede mapear (`map_concepto_provision` la lleva en la PK), así que la pantalla lo
    muestra para que se vea el hueco, pero no lo puede clasificar.

    `concepto` es el texto libre que escribió el patrón —"AGUINALDO", "PRIMA VACACIONAL"—, y
    es lo que la persona reconoce. Cuando el mismo `(naturaleza, tipo, clave)` viajó con
    varios textos distintos se muestra uno solo; B-02 ya señala esa inconsistencia con
    `CONCEPTO_INCONSISTENTE`, así que aquí no se repite el diagnóstico.
    """

    naturaleza: str
    tipo: str
    clave: str | None
    concepto: str | None
    descripcion_sat: str | None
    comprobantes: int
    importe: Decimal
    categoria: str | None


class DepartamentoObservadoOut(BaseModel):
    departamento_texto: str
    comprobantes: int
    centro_costo: str | None


class ObservadosEmpresaOut(BaseModel):
    """Lo que la nómina de la empresa emitió de verdad, para que configurar sea **reconocer y
    elegir**, no teclear.

    Nadie conoce de memoria las claves internas de su sistema de nómina —las inventa ese
    sistema—, así que pedirlas era pedir un dato que el usuario no tiene. Esta lista invierte
    el flujo: el servidor enumera lo que existe con su descripción, y la persona solo asigna
    categoría o centro de costo.

    `sin_clasificar` / `sin_mapear` son los conteos que la pantalla necesita para decir "te
    faltan 3": mientras `sin_clasificar` no sea cero, B-08 no puede distinguir "no se pagó
    aguinaldo" de "sí se pagó y no sé dónde".
    """

    conceptos: list[ConceptoObservadoOut]
    departamentos: list[DepartamentoObservadoOut]
    sin_clasificar: int
    sin_mapear: int
