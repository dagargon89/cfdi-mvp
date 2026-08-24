"""Auditoría del nivel 2 — Empresa y e.firma. Pruebas **adversariales**.

Este nivel guarda la llave del contribuyente ante el SAT: su clave privada y la contraseña que
la abre. Un fallo aquí no filtra datos, filtra **la capacidad de actuar como el contribuyente**.
Por eso las pruebas no se conforman con lo que responde la API: van a leer la base de datos y
comprueban que el material no está ahí en claro.

Los identificadores `N2-xx` son los del documento `docs/auditoria/nivel-2-empresa-y-efirma.md`.
"""

from __future__ import annotations

import datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.efirma import Efirma
from app.models.enums import RolEmpresa, RolGlobal
from app.services import boveda
from tests._certs import generar_fiel_prueba
from tests.factories import asignar_permiso, crear_empresa, crear_usuario

pytestmark = pytest.mark.asyncio

RFC_EMPRESA = "EKU9003173C9"
RFC_AJENO = "XAXX010101000"


def _codigo(respuesta: object) -> str:
    return respuesta.json()["error"]["codigo"]  # type: ignore[attr-defined]


async def _empresa_con_operador(db: AsyncSession, *, uid: str, rfc: str = RFC_EMPRESA, rol: RolEmpresa = RolEmpresa.OPERADOR):
    usuario = await crear_usuario(db, uid=uid, correo=f"{uid}@x.mx")
    empresa = await crear_empresa(db, nombre="Con e.firma", rfc=rfc)
    await asignar_permiso(db, usuario, empresa, rol)
    return usuario, empresa


def _archivos(cer: bytes, key: bytes) -> dict[str, tuple[str, bytes, str]]:
    return {
        "cer": ("fiel.cer", cer, "application/octet-stream"),
        "key": ("fiel.key", key, "application/octet-stream"),
    }


# --------------------------------------------------------------------------- #
# Confidencialidad: el material nunca sale, y en la base no está en claro.
# --------------------------------------------------------------------------- #


async def test_n2_01_el_alta_no_devuelve_material_criptografico(client: AsyncClient, db: AsyncSession) -> None:
    """N2-01 · La respuesta del alta solo puede traer metadatos del certificado.

    Si la clave privada o la contraseña volvieran en el JSON, quedarían en el historial del
    navegador, en cualquier proxy intermedio y en las herramientas de desarrollo.
    """
    _, empresa = await _empresa_con_operador(db, uid="uid-op-1")
    cer, key, password = generar_fiel_prueba(rfc=RFC_EMPRESA)

    r = await client.post(
        f"/v1/empresas/{empresa.empresa_id}/efirma",
        headers={"Authorization": "Bearer uid-op-1"},
        files=_archivos(cer, key),
        data={"password": password},
    )
    assert r.status_code == 201

    cuerpo = r.text
    assert password not in cuerpo, "la contraseña de la FIEL viaja en la respuesta"
    assert "PRIVATE KEY" not in cuerpo and "BEGIN" not in cuerpo, "material PEM en la respuesta"
    assert set(r.json()) == {"num_serie", "not_before", "not_after", "dias_para_vencer"}


async def test_n2_02_la_clave_privada_no_queda_en_claro_en_la_base(client: AsyncClient, db: AsyncSession) -> None:
    """N2-02 · Lectura directa de la tabla: `key_cifrada` no puede contener el `.key` original.

    Es la prueba que un `SELECT` de un DBA (o un respaldo robado) tiene que suspender.
    """
    _, empresa = await _empresa_con_operador(db, uid="uid-op-2")
    cer, key, password = generar_fiel_prueba(rfc=RFC_EMPRESA)

    r = await client.post(
        f"/v1/empresas/{empresa.empresa_id}/efirma",
        headers={"Authorization": "Bearer uid-op-2"},
        files=_archivos(cer, key),
        data={"password": password},
    )
    assert r.status_code == 201

    fila = await db.scalar(select(Efirma).where(Efirma.empresa_id == empresa.empresa_id))
    assert fila is not None
    assert fila.key_cifrada != key, "el .key está guardado tal cual"
    assert key not in fila.key_cifrada, "el .key aparece dentro del blob cifrado"
    # Un cifrado que preserva el tamaño exacto delataría un XOR o un ECB sin nonce.
    assert len(fila.key_cifrada) > len(key), "falta el nonce/tag: el blob mide lo mismo que el original"


async def test_n2_03_la_contrasena_no_queda_en_claro_en_la_base(client: AsyncClient, db: AsyncSession) -> None:
    """N2-03 · La contraseña de la FIEL es tan sensible como la clave: sin ella la clave no abre."""
    _, empresa = await _empresa_con_operador(db, uid="uid-op-3")
    cer, key, password = generar_fiel_prueba(rfc=RFC_EMPRESA)

    await client.post(
        f"/v1/empresas/{empresa.empresa_id}/efirma",
        headers={"Authorization": "Bearer uid-op-3"},
        files=_archivos(cer, key),
        data={"password": password},
    )

    fila = await db.scalar(select(Efirma).where(Efirma.empresa_id == empresa.empresa_id))
    assert fila is not None
    assert password.encode() not in fila.password_cifrada, "la contraseña está en claro en la base"


async def test_n2_04_la_dek_esta_envuelta_y_no_sirve_por_si_sola(client: AsyncClient, db: AsyncSession) -> None:
    """N2-04 · La DEK viaja junto al dato que protege, así que **tiene** que estar envuelta.

    Guardar la DEK en claro al lado del blob cifrado sería como pegar la llave a la caja: el
    cifrado no aportaría nada frente a un respaldo robado. La KEK vive fuera de la base.
    """
    _, empresa = await _empresa_con_operador(db, uid="uid-op-4")
    cer, key, password = generar_fiel_prueba(rfc=RFC_EMPRESA)

    await client.post(
        f"/v1/empresas/{empresa.empresa_id}/efirma",
        headers={"Authorization": "Bearer uid-op-4"},
        files=_archivos(cer, key),
        data={"password": password},
    )

    fila = await db.scalar(select(Efirma).where(Efirma.empresa_id == empresa.empresa_id))
    assert fila is not None

    # La DEK envuelta no puede descifrar el material: hay que desenvolverla con la KEK primero.
    with pytest.raises(Exception):
        boveda.descifrar(fila.dek_envuelta, fila.key_cifrada)

    # Con la KEK real sí abre — control positivo, o la prueba de arriba no significaría nada.
    dek = boveda.desenvolver_dek(boveda.cargar_kek(), fila.dek_envuelta)
    assert boveda.descifrar(dek, fila.key_cifrada) == key


async def test_n2_05_sin_la_kek_correcta_el_material_no_abre(client: AsyncClient, db: AsyncSession) -> None:
    """N2-05 · Robar la base sin robar la KEK no alcanza. Es toda la tesis del diseño."""
    _, empresa = await _empresa_con_operador(db, uid="uid-op-5")
    cer, key, password = generar_fiel_prueba(rfc=RFC_EMPRESA)

    await client.post(
        f"/v1/empresas/{empresa.empresa_id}/efirma",
        headers={"Authorization": "Bearer uid-op-5"},
        files=_archivos(cer, key),
        data={"password": password},
    )

    fila = await db.scalar(select(Efirma).where(Efirma.empresa_id == empresa.empresa_id))
    assert fila is not None
    kek_del_atacante = boveda.generar_dek()

    with pytest.raises(Exception):
        boveda.desenvolver_dek(kek_del_atacante, fila.dek_envuelta)


async def test_n2_06_el_get_solo_expone_metadatos(client: AsyncClient, db: AsyncSession) -> None:
    """N2-06 · Consultar la e.firma no puede ser una vía para extraerla."""
    _, empresa = await _empresa_con_operador(db, uid="uid-op-6")
    cer, key, password = generar_fiel_prueba(rfc=RFC_EMPRESA)
    cabeceras = {"Authorization": "Bearer uid-op-6"}
    await client.post(
        f"/v1/empresas/{empresa.empresa_id}/efirma", headers=cabeceras, files=_archivos(cer, key), data={"password": password}
    )

    r = await client.get(f"/v1/empresas/{empresa.empresa_id}/efirma", headers=cabeceras)
    assert r.status_code == 200
    assert set(r.json()) == {"num_serie", "not_before", "not_after"}
    assert password not in r.text and "BEGIN" not in r.text


# --------------------------------------------------------------------------- #
# Identidad del certificado: no cualquier FIEL entra en cualquier empresa.
# --------------------------------------------------------------------------- #


async def test_n2_07_no_se_puede_subir_la_efirma_de_otro_contribuyente(client: AsyncClient, db: AsyncSession) -> None:
    """N2-07 · **El ataque más grave de este nivel.**

    Si el RFC del certificado no se comparara con el de la empresa, un operador podría subir la
    FIEL de un tercero (obtenida de un respaldo, un correo, un despacho contable) y el Hub
    descargaría los CFDI de ese tercero como si fueran suyos. La comparación es lo que ata la
    llave a su dueño.
    """
    _, empresa = await _empresa_con_operador(db, uid="uid-op-7", rfc=RFC_EMPRESA)
    cer, key, password = generar_fiel_prueba(rfc=RFC_AJENO)  # FIEL de OTRO RFC

    r = await client.post(
        f"/v1/empresas/{empresa.empresa_id}/efirma",
        headers={"Authorization": "Bearer uid-op-7"},
        files=_archivos(cer, key),
        data={"password": password},
    )
    assert r.status_code == 422
    assert _codigo(r) == "RFC_NO_COINCIDE"

    fila = await db.scalar(select(Efirma).where(Efirma.empresa_id == empresa.empresa_id))
    assert fila is None, "se guardó la e.firma de otro contribuyente"


async def test_n2_08_una_contrasena_incorrecta_no_da_de_alta_nada(client: AsyncClient, db: AsyncSession) -> None:
    """N2-08 · Sin la contraseña no se puede demostrar posesión de la clave."""
    _, empresa = await _empresa_con_operador(db, uid="uid-op-8")
    cer, key, _ = generar_fiel_prueba(rfc=RFC_EMPRESA)

    r = await client.post(
        f"/v1/empresas/{empresa.empresa_id}/efirma",
        headers={"Authorization": "Bearer uid-op-8"},
        files=_archivos(cer, key),
        data={"password": "contrasena-equivocada"},
    )
    assert r.status_code == 422
    assert _codigo(r) == "EFIRMA_NO_ABRE"

    fila = await db.scalar(select(Efirma).where(Efirma.empresa_id == empresa.empresa_id))
    assert fila is None


async def test_n2_09_una_efirma_vencida_no_se_da_de_alta(client: AsyncClient, db: AsyncSession) -> None:
    """N2-09 · Una FIEL vencida no sirve ante el SAT: aceptarla solo produciría jobs en ERROR
    y haría creer al operador que la bóveda está lista."""
    _, empresa = await _empresa_con_operador(db, uid="uid-op-9")
    cer, key, password = generar_fiel_prueba(
        rfc=RFC_EMPRESA,
        not_before=datetime.datetime(2019, 1, 1),
        not_after=datetime.datetime(2020, 1, 1),
    )

    r = await client.post(
        f"/v1/empresas/{empresa.empresa_id}/efirma",
        headers={"Authorization": "Bearer uid-op-9"},
        files=_archivos(cer, key),
        data={"password": password},
    )
    assert r.status_code == 422
    assert _codigo(r) == "EFIRMA_VENCIDA"


async def test_n2_10_un_key_que_no_corresponde_al_cer_se_rechaza(client: AsyncClient, db: AsyncSession) -> None:
    """N2-10 · Certificado de uno y clave privada de otro: el par tiene que corresponder."""
    _, empresa = await _empresa_con_operador(db, uid="uid-op-10")
    cer, _, password = generar_fiel_prueba(rfc=RFC_EMPRESA)
    _, key_de_otro, _ = generar_fiel_prueba(rfc=RFC_EMPRESA)  # otro par, mismo RFC

    r = await client.post(
        f"/v1/empresas/{empresa.empresa_id}/efirma",
        headers={"Authorization": "Bearer uid-op-10"},
        files=_archivos(cer, key_de_otro),
        data={"password": password},
    )
    assert r.status_code == 422, "se aceptó un .cer y un .key que no son pareja"

    fila = await db.scalar(select(Efirma).where(Efirma.empresa_id == empresa.empresa_id))
    assert fila is None


async def test_n2_11_archivos_basura_no_tumban_el_servidor(client: AsyncClient, db: AsyncSession) -> None:
    """N2-11 · Entrada malformada: debe dar un 422 explicado, nunca un 500.

    Un 500 aquí significaría que una excepción sin traducir llega al manejador global, y con
    ella un rastro de pila en los logs alrededor de material criptográfico.
    """
    _, empresa = await _empresa_con_operador(db, uid="uid-op-11")

    r = await client.post(
        f"/v1/empresas/{empresa.empresa_id}/efirma",
        headers={"Authorization": "Bearer uid-op-11"},
        files=_archivos(b"esto no es un certificado", b"ni esto una clave"),
        data={"password": "cualquiera"},
    )
    assert r.status_code == 422
    assert r.status_code != 500


async def test_n2_12_el_error_no_repite_la_contrasena(client: AsyncClient, db: AsyncSession) -> None:
    """N2-12 · Un mensaje de error que devuelve la contraseña la copia a los logs del cliente."""
    _, empresa = await _empresa_con_operador(db, uid="uid-op-12")
    cer, key, _ = generar_fiel_prueba(rfc=RFC_EMPRESA)
    secreta = "SuperSecreta123!"

    r = await client.post(
        f"/v1/empresas/{empresa.empresa_id}/efirma",
        headers={"Authorization": "Bearer uid-op-12"},
        files=_archivos(cer, key),
        data={"password": secreta},
    )
    assert r.status_code == 422
    assert secreta not in r.text, "el mensaje de error incluye la contraseña enviada"


# --------------------------------------------------------------------------- #
# Aislamiento y permisos sobre la bóveda.
# --------------------------------------------------------------------------- #


async def test_n2_13_no_se_alcanza_la_boveda_de_otra_empresa(client: AsyncClient, db: AsyncSession) -> None:
    """N2-13 · La bóveda de la empresa A no existe para el usuario de la empresa B."""
    usuario = await crear_usuario(db, uid="uid-vecino", correo="vecino@x.mx")
    propia = await crear_empresa(db, nombre="Propia", rfc=RFC_EMPRESA)
    ajena = await crear_empresa(db, nombre="Ajena", rfc=RFC_AJENO)
    await asignar_permiso(db, usuario, propia, RolEmpresa.OPERADOR)

    r = await client.get(f"/v1/empresas/{ajena.empresa_id}/efirma", headers={"Authorization": "Bearer uid-vecino"})
    assert r.status_code == 404


async def test_n2_14_el_rol_de_consulta_no_sube_efirma(client: AsyncClient, db: AsyncSession) -> None:
    """N2-14 · Dar de alta la llave fiscal no es una acción de solo lectura."""
    _, empresa = await _empresa_con_operador(db, uid="uid-solo-lee", rol=RolEmpresa.CONSULTA)
    cer, key, password = generar_fiel_prueba(rfc=RFC_EMPRESA)

    r = await client.post(
        f"/v1/empresas/{empresa.empresa_id}/efirma",
        headers={"Authorization": "Bearer uid-solo-lee"},
        files=_archivos(cer, key),
        data={"password": password},
    )
    assert r.status_code == 403


async def test_n2_15_el_rol_de_consulta_no_borra_efirma(client: AsyncClient, db: AsyncSession) -> None:
    """N2-15 · Borrar la e.firma deja a la empresa sin poder descargar: es destructivo."""
    _, empresa = await _empresa_con_operador(db, uid="uid-solo-lee-2", rol=RolEmpresa.CONSULTA)

    r = await client.delete(f"/v1/empresas/{empresa.empresa_id}/efirma", headers={"Authorization": "Bearer uid-solo-lee-2"})
    assert r.status_code == 403


async def test_n2_16_el_rol_de_consulta_si_ve_los_metadatos(client: AsyncClient, db: AsyncSession) -> None:
    """N2-16 · Control positivo: consulta debe poder ver la vigencia, o no podría avisar que vence."""
    _, empresa = await _empresa_con_operador(db, uid="uid-solo-lee-3", rol=RolEmpresa.CONSULTA)

    r = await client.get(f"/v1/empresas/{empresa.empresa_id}/efirma", headers={"Authorization": "Bearer uid-solo-lee-3"})
    assert r.status_code == 200


# --------------------------------------------------------------------------- #
# Empresas: la identidad fiscal que ata todo lo demás.
# --------------------------------------------------------------------------- #


async def test_n2_17_no_se_duplica_un_rfc(client: AsyncClient, db: AsyncSession) -> None:
    """N2-17 · Dos empresas con el mismo RFC partirían el acervo del mismo contribuyente en dos
    y harían que los informes discrepen según cuál se abra."""
    await crear_usuario(db, uid="uid-admin-e", correo="admin-e@x.mx", rol_global=RolGlobal.ADMIN)
    await crear_empresa(db, nombre="Primera", rfc=RFC_EMPRESA)

    r = await client.post(
        "/v1/empresas",
        headers={"Authorization": "Bearer uid-admin-e"},
        json={"nombre": "Segunda con el mismo RFC", "rfc": RFC_EMPRESA},
    )
    assert r.status_code == 409
    assert _codigo(r) == "RFC_DUPLICADO"


async def test_n2_18_un_rfc_malformado_se_rechaza(client: AsyncClient, db: AsyncSession) -> None:
    """N2-18 · El RFC es la clave con la que se le habla al SAT; uno inválido produce jobs que
    solo pueden fallar."""
    await crear_usuario(db, uid="uid-admin-f", correo="admin-f@x.mx", rol_global=RolGlobal.ADMIN)

    r = await client.post(
        "/v1/empresas",
        headers={"Authorization": "Bearer uid-admin-f"},
        json={"nombre": "RFC corto", "rfc": "ABC"},
    )
    assert r.status_code == 400
    assert _codigo(r) == "RFC_MALFORMADO"


async def test_n2_19_un_operador_no_crea_empresas(client: AsyncClient, db: AsyncSession) -> None:
    """N2-19 · Crear empresas es de administradores: es dar de alta un contribuyente nuevo."""
    await crear_usuario(db, uid="uid-op-g", correo="op-g@x.mx", rol_global=RolGlobal.OPERADOR)

    r = await client.post(
        "/v1/empresas",
        headers={"Authorization": "Bearer uid-op-g"},
        json={"nombre": "Empresa Pirata", "rfc": RFC_AJENO},
    )
    assert r.status_code == 403
