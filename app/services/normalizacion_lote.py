"""Normalización por lote: lee el XML de disco, lo parsea y lo persiste (spec §6.3).

Compartido por el disparador 2 (tarea de reproceso) y el disparador 3 (pre-vuelo del
informe). Ningún XML individual aborta el lote.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.comprobante import Comprobante
from app.repositories import normalizacion as repo_normalizacion
from app.services import normalizacion, representaciones

logger = logging.getLogger(__name__)

# Códigos de error de MySQL que significan "otra transacción se te adelantó", no "el dato
# está mal". `asyncmy` los entrega como `asyncmy.errors.OperationalError(codigo, mensaje)`
# —1213 está mapeado explícitamente a `OperationalError` en `asyncmy/errors.pyx`, y 1205 cae
# ahí por el default de códigos ≥ 1000— y SQLAlchemy los reenvuelve en
# `sqlalchemy.exc.OperationalError` conservando el original en `.orig.args[0]`.
_CODIGOS_CONCURRENCIA = frozenset({1213, 1205})  # ER_LOCK_DEADLOCK, ER_LOCK_WAIT_TIMEOUT


def _es_fallo_de_concurrencia(exc: BaseException) -> bool:
    """`True` si el fallo es de dos transacciones peleándose, no del contenido del XML.

    Dos pre-vuelos simultáneos sobre el mismo comprobante (basta un doble clic en "Generar":
    el endpoint responde `202` de inmediato y cada generación arranca su propio pre-vuelo) se
    pisan en `_upsert_detalle`, que hace SELECT-luego-INSERT sin protección, y en
    `_limpiar_hijos`, que borra 14 tablas por `comprobante_id`. El resultado es un
    `IntegrityError` por PK duplicada o —lo más probable— un deadlock de InnoDB.

    **Limitación conocida: la protección es completa para el 1062 y parcial para el 1213.**
    Lo que hace el caller al detectar concurrencia es re-consultar `necesita_normalizar`, y
    eso solo funciona si el proceso ganador **ya commiteó**:

    - Con `IntegrityError` (1062, PK duplicada) el orden es forzoso: la clave duplicada solo
      existe si el ganador commiteó. La re-consulta siempre lo ve y el comprobante sano nunca
      se marca.
    - Con un deadlock (1213) no: InnoDB aborta a la víctima **mientras** el ganador sigue con
      su transacción abierta. En ese orden —el real— la re-consulta no ve nada todavía,
      `necesita_normalizar` sigue devolviendo `True` y sí se registra el error sobre un
      comprobante sano. La prueba de deadlock de la suite tiene al ganador ya commiteado, así
      que cubre la condición de esta función, no esa carrera temporal.

    **Lo robusto sería reintentar** la normalización una vez ante un fallo de concurrencia,
    en vez de consultar el estado de inmediato: el reintento espera de forma natural a que el
    ganador termine, y solo entonces `necesita_normalizar` da la respuesta buena. Queda
    anotado como deuda.

    Se acepta dejarlo así porque el residual ya no produce un dato falso silencioso: con la
    bandera `DATOS_DE_CORRIDA_ANTERIOR` de B-02, un comprobante marcado por error sigue
    entrando al informe con sus importes y llega al patrón como un aviso visible que se
    puede investigar, no como una fila que desaparece.
    """
    if isinstance(exc, IntegrityError):
        return True
    if isinstance(exc, OperationalError):
        argumentos: tuple[object, ...] = getattr(exc.orig, "args", ())
        return bool(argumentos) and argumentos[0] in _CODIGOS_CONCURRENCIA
    return False


async def normalizar_lote(db: AsyncSession, empresa_id: int, comprobante_ids: list[int]) -> dict[str, int]:
    """Devuelve `{"normalizados": n, "con_error": n, "omitidos": n}`.

    `omitidos` son los que no había nada que hacerles: los que ya estaban al día (mismo hash,
    misma `ETL_VERSION`), los que **no tienen XML en disco** (sin XML no hay nada que
    normalizar, y eso no es un error) y los que otro proceso normalizó mientras este los
    procesaba. Commitea
    por comprobante: un lote largo que se interrumpa deja avanzado lo que ya procesó.

    **Contrato para quien reusa `db` después de llamar esta función (pre-vuelo de la
    tarea 13: normalizar y luego, con la misma sesión, consultar el informe):** al
    retornar, `db` **no tiene una transacción abierta**. Si el lote entero cae en las
    ramas de "omitido" o "id de otra empresa" (el caso normal de reprocesar una empresa
    que ya está al día), el único `SELECT` de arriba habría dejado abierta la
    transacción implícita de lectura sin este cierre explícito — y quien siga usando
    `db` heredaría el snapshot de `REPEATABLE READ` de antes de normalizar, sin ver lo
    que él mismo acaba de escribir. Por eso se cierra siempre al final, aunque no haya
    nada pendiente que guardar (cada comprobante ya commiteó lo suyo por su cuenta).
    """
    storage_root = get_settings().storage_root
    resumen = {"normalizados": 0, "con_error": 0, "omitidos": 0}

    for comprobante_id in comprobante_ids:
        comprobante = await db.scalar(
            select(Comprobante).where(Comprobante.comprobante_id == comprobante_id, Comprobante.empresa_id == empresa_id)
        )
        if comprobante is None:
            continue  # id de otra empresa: se ignora, igual que en `validar_lote`

        # Sin `xml_path` el comprobante nunca se descargó: es metadata del SAT y no hay nada
        # que normalizar. Se OMITE, no se marca con error. `ids_pendientes` ya lo excluye,
        # pero `ids_todos` (la vía documentada para forzar el reproceso tras subir
        # `ETL_VERSION`, alcance="todos") no filtra nada y los trae todos. Registrarlo como
        # error dejaría una fila con hash falso (`"0"*64`) y el mensaje "el XML no está en
        # disco" sobre un comprobante que simplemente todavía no se ha descargado, recontado
        # como `con_error` en cada corrida.
        if not comprobante.xml_path:
            resumen["omitidos"] += 1
            continue

        xml_bytes = representaciones.leer_xml_de_disco(storage_root, comprobante)
        if xml_bytes is None:
            # Aquí sí es un error, y grave: `xml_path` dice que el XML se resguardó y el
            # archivo ya no está. Eso es pérdida de datos, no un comprobante pendiente.
            await repo_normalizacion.registrar_error(
                db, comprobante_id, "0" * 64, f"El XML resguardado ya no está en disco: {comprobante.xml_path}"
            )
            await db.commit()
            resumen["con_error"] += 1
            continue

        xml_hash = normalizacion.hash_xml(xml_bytes)
        if not await repo_normalizacion.necesita_normalizar(db, comprobante_id, xml_hash):
            resumen["omitidos"] += 1
            continue

        try:
            await repo_normalizacion.escribir(db, comprobante_id, normalizacion.normalizar(xml_bytes), xml_hash)
            await db.commit()
            resumen["normalizados"] += 1
        except Exception as exc:  # noqa: BLE001 — un XML corrupto no aborta el lote
            await db.rollback()
            # Un fallo de concurrencia NO es un fallo del dato. Si otro proceso ya normalizó
            # este comprobante mientras nosotros lo intentábamos, marcar el error sería
            # calumniar a un comprobante sano — y de forma PERMANENTE: `xml_hash` y
            # `etl_version` ya coinciden con los del ganador, así que `necesita_normalizar`
            # devolvería `False` en toda corrida posterior y nadie limpiaría la marca.
            if _es_fallo_de_concurrencia(exc) and not await repo_normalizacion.necesita_normalizar(db, comprobante_id, xml_hash):
                logger.info(
                    "normalizar_lote: comprobante %s lo normalizó otro proceso en paralelo (%s); se omite sin marcar error.",
                    comprobante_id,
                    exc.__class__.__name__,
                )
                resumen["omitidos"] += 1
                continue
            logger.warning("normalizar_lote: comprobante %s no se pudo normalizar: %s", comprobante_id, exc)
            await repo_normalizacion.registrar_error(db, comprobante_id, xml_hash, str(exc))
            await db.commit()
            resumen["con_error"] += 1

    await db.rollback()  # cierra la transacción de lectura que deja abierta el `select` de arriba
    return resumen
