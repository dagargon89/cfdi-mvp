"""Persistencia de las tarifas del ISR. Todo lo que decide *si* un dato es aceptable vive en
`app.services.tarifa_isr`; aquí solo se escribe y se lee.

**Ninguna función de escritura confirma.** `confirmar` es la única que toca `confirmado_por` y
`confirmado_en`, y exige la huella de lo que se revisó.

Ninguna función hace `commit`: quien llama escribe la bitácora en la misma transacción (regla 8).

Los cinco casos de reimportación (§5.5 del diseño), que las pruebas de este módulo fijan, más un
sexto que la práctica exige:

1. Reimportar el mismo documento (mismos renglones) es idempotente: no hay tarifa previa, o la
   hay y la huella no cambió.
2. Reimportar con renglones distintos sobre una tarifa **confirmada** limpia la confirmación:
   un valor distinto es un valor nuevo y necesita que alguien lo vuelva a mirar.
3. Reimportar sobre una tarifa **corregida a mano** que dice algo distinto se rechaza entero
   (`CorreccionManualProtegida`): no se pisa una corrección con un documento. Se comprueba dos
   veces: antes de escribir nada (para que el mensaje nombre la tarifa protegida, no la que se
   estaba escribiendo) y otra vez dentro de `_escribir`, ya bajo el candado `FOR UPDATE` — la
   primera es una lectura simple que puede quedarse con un snapshot viejo; la segunda es la que
   de verdad protege contra una carrera.
4. Corregir a mano marca `origen: MANUAL` y limpia la confirmación, siempre — no solo cuando
   los renglones cambian, porque el acto de corregir ya es una afirmación de que el dato
   anterior no era el bueno.
5. Reimportar con los mismos renglones sobre una tarifa confirmada conserva la confirmación:
   nada que revisar de nuevo.
6. Reimportar sobre una corrección manual **con la misma huella** (el documento coincide número
   por número con lo que se corrigió a mano) no se rechaza: el `origen` pasa de `MANUAL` a
   `IMPORTADA` en silencio. Es intencional — ya no hay nada que proteger, los renglones son
   idénticos — y a partir de ahí el documento vuelve a ser la fuente. Si los dos difieren, gana
   el caso 3.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.configuracion_fiscal import TarifaIsr, TarifaIsrRenglon
from app.models.enums import OrigenTarifa, PeriodicidadTarifa
from app.services import anexo8
from app.services import tarifa_isr as reglas

_LARGO_CONFIRMADO_POR = 128


class CorreccionManualProtegida(Exception):
    """Se intentó importar encima de una tarifa corregida a mano. No se pisa nada."""


class ValorCambio(Exception):
    """La tarifa cambió entre que alguien la revisó y le dio confirmar."""


class NoEncontrada(Exception):
    """No hay tarifa para ese ejercicio y periodicidad."""


class YaConfirmada(Exception):
    """La operación (borrar) no se permite sobre una tarifa confirmada."""


@dataclass(frozen=True)
class TarifaGuardada:
    ejercicio: int
    periodicidad: PeriodicidadTarifa
    origen: OrigenTarifa
    fuente: str
    documento_sha256: str | None
    encabezado: str
    importado_en: datetime
    confirmado_por: str | None
    confirmado_en: datetime | None
    renglones: tuple[reglas.Renglon, ...]

    @property
    def huella(self) -> str:
        return reglas.huella(list(self.renglones))

    @property
    def confirmada(self) -> bool:
        return self.confirmado_en is not None


def _ahora() -> datetime:
    """`datetime` sin zona, como todas las columnas `DateTime` del proyecto (que son naive en
    UTC). Mismo patrón que `configuracion_fiscal._ahora`."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _leer_renglones(
    db: AsyncSession, *, ejercicio: int, periodicidad: PeriodicidadTarifa
) -> list[reglas.Renglon]:
    """Los renglones de una tarifa, ordenados por `renglon`. Vacía si no hay ninguno."""
    filas = (
        await db.scalars(
            select(TarifaIsrRenglon)
            .where(
                TarifaIsrRenglon.ejercicio == ejercicio,
                TarifaIsrRenglon.periodicidad == periodicidad,
            )
            .order_by(TarifaIsrRenglon.renglon)
        )
    ).all()
    return [
        reglas.Renglon(
            renglon=f.renglon,
            limite_inferior=f.limite_inferior,
            limite_superior=f.limite_superior,
            cuota_fija=f.cuota_fija,
            tasa_excedente=f.tasa_excedente,
        )
        for f in filas
    ]


def _a_dataclass(cabecera: TarifaIsr, renglones: list[reglas.Renglon]) -> TarifaGuardada:
    return TarifaGuardada(
        ejercicio=cabecera.ejercicio,
        periodicidad=cabecera.periodicidad,
        origen=cabecera.origen,
        fuente=cabecera.fuente,
        documento_sha256=cabecera.documento_sha256,
        encabezado=cabecera.encabezado,
        importado_en=cabecera.importado_en,
        confirmado_por=cabecera.confirmado_por,
        confirmado_en=cabecera.confirmado_en,
        renglones=tuple(sorted(renglones, key=lambda r: r.renglon)),
    )


async def _escribir(
    db: AsyncSession,
    *,
    ejercicio: int,
    periodicidad: PeriodicidadTarifa,
    renglones: Sequence[reglas.Renglon],
    origen: OrigenTarifa,
    fuente: str,
    sha256: str | None,
    encabezado: str,
    proteger_correccion_manual: bool = False,
) -> TarifaGuardada:
    """Única puerta de escritura. Valida, decide si la confirmación sobrevive, reemplaza los
    renglones.

    **Se valida la tarifa completa**, no el renglón que cambió: editar un `limite_superior` rompe la
    continuidad con su vecino, y validar solo lo editado dejaría pasar justo el hueco que ese cambio
    abrió.

    Con `proteger_correccion_manual=True` (lo pone `guardar_importadas`, nunca `guardar_manual`;
    mismo nombre y semántica que en `configuracion_fiscal.guardar_param_fiscal`) **vuelve a
    comprobar el origen aquí, después de tomar el candado**, y no solo antes de llamar. La
    pre-comprobación de `guardar_importadas` es una lectura simple: en InnoDB lee el snapshot de la
    transacción, no el último committeado. Si entre esa lectura y este `FOR UPDATE` otra
    transacción convirtió la tarifa en `MANUAL` con una huella distinta, la pre-comprobación no lo
    vería, y sin esta segunda comprobación **bajo candado** la importación la pisaría en silencio —
    justo el invariante que existe para impedirlo.
    """
    reglas.validar(list(renglones))

    cabecera = await db.scalar(
        select(TarifaIsr)
        .where(TarifaIsr.ejercicio == ejercicio, TarifaIsr.periodicidad == periodicidad)
        .with_for_update()
    )
    huella_nueva = reglas.huella(list(renglones))

    if cabecera is None:
        cabecera = TarifaIsr(ejercicio=ejercicio, periodicidad=periodicidad)
        db.add(cabecera)
    else:
        anteriores = await _leer_renglones(db, ejercicio=ejercicio, periodicidad=periodicidad)
        cambio = reglas.huella(anteriores) != huella_nueva
        if proteger_correccion_manual and cabecera.origen is OrigenTarifa.MANUAL and cambio:
            raise CorreccionManualProtegida(
                f"Corregiste a mano la tarifa {periodicidad.value} de {ejercicio} y el documento dice "
                "otra cosa. No la sobreescribí. Si el documento nuevo es el bueno, descarta la tarifa "
                "y vuelve a importar."
            )
        if cambio:
            # Una cifra distinta es una tarifa nueva y necesita que alguien la vuelva a mirar. Sin
            # esto, una resolución posterior del SAT activaría cifras que nadie revisó.
            cabecera.confirmado_por = None
            cabecera.confirmado_en = None

    cabecera.origen = origen
    cabecera.fuente = fuente
    cabecera.documento_sha256 = sha256
    cabecera.encabezado = encabezado
    cabecera.importado_en = _ahora()

    # Reemplazo completo, no diff renglón por renglón: la lista es corta y un diff parcial puede
    # dejar vivo un renglón viejo que rompe la continuidad sin que nada lo note.
    await db.execute(
        delete(TarifaIsrRenglon).where(
            TarifaIsrRenglon.ejercicio == ejercicio,
            TarifaIsrRenglon.periodicidad == periodicidad,
        )
    )
    await db.flush()
    for r in renglones:
        db.add(
            TarifaIsrRenglon(
                ejercicio=ejercicio,
                periodicidad=periodicidad,
                renglon=r.renglon,
                limite_inferior=r.limite_inferior,
                limite_superior=r.limite_superior,
                cuota_fija=r.cuota_fija,
                tasa_excedente=r.tasa_excedente,
            )
        )
    await db.flush()
    return _a_dataclass(cabecera, list(renglones))


async def guardar_importadas(
    db: AsyncSession, extraidas: Sequence[anexo8.TarifaExtraida], *, fuente: str, sha256: str
) -> list[TarifaGuardada]:
    """Guarda todas las tarifas de un documento, o ninguna.

    Primera pasada: comprobar que ninguna choca con una corrección manual. Segunda: escribir. Sin la
    primera pasada, el mensaje de error nombraría la tarifa que se estaba escribiendo en vez de la
    protegida, y quien lo lee no sabría qué renglón corrigió a mano.
    """
    for extraida in extraidas:
        existente = await obtener(db, ejercicio=extraida.ejercicio, periodicidad=extraida.periodicidad)
        if existente is not None and existente.origen is OrigenTarifa.MANUAL:
            if existente.huella != reglas.huella(list(extraida.renglones)):
                raise CorreccionManualProtegida(
                    f"Corregiste a mano la tarifa {extraida.periodicidad.value} de {extraida.ejercicio} y el "
                    "documento dice otra cosa. No la sobreescribí. Si el documento nuevo es el bueno, "
                    "descarta la tarifa y vuelve a importar."
                )

    return [
        await _escribir(
            db,
            ejercicio=e.ejercicio,
            periodicidad=e.periodicidad,
            renglones=e.renglones,
            origen=OrigenTarifa.IMPORTADA,
            fuente=fuente,
            sha256=sha256,
            encabezado=e.encabezado,
            proteger_correccion_manual=True,
        )
        for e in extraidas
    ]


async def guardar_manual(
    db: AsyncSession, *, ejercicio: int, periodicidad: PeriodicidadTarifa, renglones: Sequence[reglas.Renglon], fuente: str
) -> TarifaGuardada:
    """Corrige a mano una tarifa (o la crea, si no existía). Marca `origen: MANUAL`, lo que la
    protege de una futura reimportación que diga otra cosa (ver `guardar_importadas`).

    Sin `documento_sha256`: una corrección a mano no tiene un archivo del que salga. `encabezado`
    se conserva como una cita fija en vez de un campo capturable, para que la pantalla siga
    mostrando de qué tabla salió el dato original.
    """
    encabezado = f"Corrección manual de la tarifa {periodicidad.value} de {ejercicio}"
    existente = await obtener(db, ejercicio=ejercicio, periodicidad=periodicidad)
    if existente is not None:
        encabezado = existente.encabezado
    return await _escribir(
        db,
        ejercicio=ejercicio,
        periodicidad=periodicidad,
        renglones=renglones,
        origen=OrigenTarifa.MANUAL,
        fuente=fuente,
        sha256=None,
        encabezado=encabezado,
    )


async def listar(db: AsyncSession) -> list[TarifaGuardada]:
    """Todas las tarifas guardadas, con sus renglones. Dos consultas —cabeceras y renglones— y
    se agrupan en memoria: una consulta por tarifa sería un N+1 (regla 11)."""
    cabeceras = (await db.scalars(select(TarifaIsr))).all()
    todos_los_renglones = (await db.scalars(select(TarifaIsrRenglon))).all()

    por_clave: dict[tuple[int, PeriodicidadTarifa], list[reglas.Renglon]] = {
        (c.ejercicio, c.periodicidad): [] for c in cabeceras
    }
    for f in todos_los_renglones:
        clave = (f.ejercicio, f.periodicidad)
        if clave in por_clave:
            por_clave[clave].append(
                reglas.Renglon(
                    renglon=f.renglon,
                    limite_inferior=f.limite_inferior,
                    limite_superior=f.limite_superior,
                    cuota_fija=f.cuota_fija,
                    tasa_excedente=f.tasa_excedente,
                )
            )

    return [_a_dataclass(c, por_clave[(c.ejercicio, c.periodicidad)]) for c in cabeceras]


async def obtener(db: AsyncSession, *, ejercicio: int, periodicidad: PeriodicidadTarifa) -> TarifaGuardada | None:
    """La tarifa de ese ejercicio y periodicidad, con sus renglones, o `None` si no existe."""
    cabecera = await db.scalar(
        select(TarifaIsr).where(TarifaIsr.ejercicio == ejercicio, TarifaIsr.periodicidad == periodicidad)
    )
    if cabecera is None:
        return None
    renglones = await _leer_renglones(db, ejercicio=ejercicio, periodicidad=periodicidad)
    return _a_dataclass(cabecera, renglones)


async def vigente(db: AsyncSession, *, ejercicio: int, periodicidad: PeriodicidadTarifa) -> TarifaGuardada | None:
    """La tarifa **confirmada** de ese ejercicio y periodicidad, o `None` si no hay ninguna o
    la que hay no está confirmada. Es lo único que un cálculo puede usar."""
    fila = await obtener(db, ejercicio=ejercicio, periodicidad=periodicidad)
    if fila is None or not fila.confirmada:
        return None
    return fila


async def confirmar(
    db: AsyncSession, *, ejercicio: int, periodicidad: PeriodicidadTarifa, huella_revisada: str, actor: str
) -> tuple[TarifaGuardada, bool]:
    """Confirma una tarifa propuesta: a partir de aquí `vigente` la devuelve y los cálculos la
    usan. Devuelve la fila y **si cambió algo** (falso al reconfirmar lo ya confirmado, que es
    idempotente y no merece renglón de bitácora).

    **Exige la huella de lo que se revisó y rechaza si no coincide con la almacenada.** Sin esa
    comparación, una tarifa que cambió entre que se leyó y que se confirmó —otra importación, otro
    administrador— se confirmaría a ciegas, que es justo el escenario contra el que existe el
    invariante.

    El `FOR UPDATE` toma el mismo candado que `_escribir`, así que una escritura simultánea de la
    misma tarifa espera en vez de colarse entre la comparación de la huella y la escritura de la
    confirmación.

    No escribe bitácora ni hace `commit`: quien llama lo hace en la misma transacción.
    """
    cabecera = await db.scalar(
        select(TarifaIsr)
        .where(TarifaIsr.ejercicio == ejercicio, TarifaIsr.periodicidad == periodicidad)
        .with_for_update()
    )
    if cabecera is None:
        raise NoEncontrada(
            f"No hay ninguna tarifa {periodicidad.value} de {ejercicio}. Impórtala o captúrala antes de confirmarla."
        )

    renglones = await _leer_renglones(db, ejercicio=ejercicio, periodicidad=periodicidad)
    if reglas.huella(renglones) != huella_revisada:
        raise ValorCambio(
            f"La tarifa {periodicidad.value} de {ejercicio} cambió mientras la revisabas. "
            "Vuelve a cargarla y revísala otra vez antes de confirmar."
        )

    if cabecera.confirmado_en is not None:
        # Idempotente: reconfirmar lo ya confirmado no cambia nada, así que tampoco reescribe
        # quién lo confirmó (sería borrar el rastro de quien sí lo revisó).
        return _a_dataclass(cabecera, renglones), False

    cabecera.confirmado_por = actor[:_LARGO_CONFIRMADO_POR]
    cabecera.confirmado_en = _ahora()
    await db.flush()
    return _a_dataclass(cabecera, renglones), True


async def borrar(db: AsyncSession, *, ejercicio: int, periodicidad: PeriodicidadTarifa) -> None:
    """Borra una tarifa propuesta (sus renglones se van con ella por `ON DELETE CASCADE`).

    **Se rechaza sobre una tarifa confirmada** (`YaConfirmada`): borrarla la haría desaparecer sin
    sustituto y convertiría un cálculo que funcionaba en un cálculo ausente, sin explicación. Para
    reemplazar una tarifa confirmada, se corrige a mano o se reimporta; no se borra primero.
    """
    cabecera = await db.scalar(
        select(TarifaIsr)
        .where(TarifaIsr.ejercicio == ejercicio, TarifaIsr.periodicidad == periodicidad)
        .with_for_update()
    )
    if cabecera is None:
        raise NoEncontrada(f"No hay ninguna tarifa {periodicidad.value} de {ejercicio} que borrar.")
    if cabecera.confirmado_en is not None:
        raise YaConfirmada(
            f"La tarifa {periodicidad.value} de {ejercicio} ya está confirmada y no se puede borrar así. "
            "Corrígela a mano o reemplázala reimportando el documento correcto."
        )
    await db.delete(cabecera)
    await db.flush()
