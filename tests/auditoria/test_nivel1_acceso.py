"""Auditoría del nivel 1 — Acceso e identidad. Pruebas **adversariales**.

Estas pruebas no comprueban que entrar funcione (eso ya lo cubre la suite normal): intentan
**entrar donde no se debe**. Cada una nombra el ataque, no la función.

Los identificadores `N1-xx` son los del documento `docs/auditoria/nivel-1-acceso-e-identidad.md`.

Alcance y su límite honesto
---------------------------
La fixture `client` sustituye `verificar_id_token` por un doble donde el Bearer **es** el uid
(`tests/conftest.py`). Eso permite atacar toda la autorización local —registro, aprobación,
estado, rol, pertenencia a empresa— pero **no** la capa criptográfica de Firebase: firma,
expiración, audiencia y revocación no se ejercitan aquí. Esa parte se audita en vivo contra el
servidor real; ver la sección "Verificación en vivo" del documento.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import RolEmpresa, RolGlobal
from tests.factories import asignar_permiso, crear_empresa, crear_usuario

pytestmark = pytest.mark.asyncio


def _codigo(respuesta: object) -> str:
    """Código de negocio del envoltorio de error estándar (`app/main.py`): `{"error": {...}}`."""
    return respuesta.json()["error"]["codigo"]  # type: ignore[attr-defined]


def _sin_trace(respuesta: object) -> dict[str, object]:
    """El cuerpo del error sin su `trace_id` — es único por petición a propósito, y compararlo
    haría fallar cualquier prueba de igualdad entre dos respuestas."""
    cuerpo = dict(respuesta.json()["error"])  # type: ignore[attr-defined]
    cuerpo.pop("trace_id", None)
    return cuerpo


class _CuentaFirebase:
    """Doble de la cuenta que devuelve el Admin SDK (solo se usa `.email`)."""

    def __init__(self, email: str | None) -> None:
        self.email = email


# --------------------------------------------------------------------------- #
# Autenticación: nadie pasa sin un token que el servidor haya verificado.
# --------------------------------------------------------------------------- #


async def test_n1_01_sin_encabezado_authorization_no_se_entra(client: AsyncClient) -> None:
    """N1-01 · Petición desnuda a un endpoint de datos."""
    r = await client.get("/v1/me")
    assert r.status_code == 401


async def test_n1_02_un_esquema_de_autorizacion_distinto_no_sirve(client: AsyncClient) -> None:
    """N1-02 · `Basic` en lugar de `Bearer`: no se acepta ningún otro esquema."""
    r = await client.get("/v1/me", headers={"Authorization": "Basic YWRtaW46YWRtaW4="})
    assert r.status_code == 401


async def test_n1_03_un_token_que_no_verifica_no_sirve(client: AsyncClient) -> None:
    """N1-03 · Token rechazado por el verificador."""
    r = await client.get("/v1/me", headers={"Authorization": "Bearer invalido"})
    assert r.status_code == 401


async def test_n1_04_el_prefijo_bearer_debe_venir_completo(client: AsyncClient) -> None:
    """N1-04 · `Bearer` sin espacio ni token: no debe colarse como uid vacío."""
    r = await client.get("/v1/me", headers={"Authorization": "Bearer"})
    assert r.status_code == 401


# --------------------------------------------------------------------------- #
# Autorización local: un token válido NO basta para ser usuario del Hub.
# --------------------------------------------------------------------------- #


async def test_n1_05_una_cuenta_de_firebase_sin_usuario_local_no_entra(client: AsyncClient) -> None:
    """N1-05 · Token perfectamente válido de una cuenta que nadie dio de alta en el Hub.

    Es el ataque real contra un backend que confía en el proveedor de identidad: cualquiera
    puede crearse una cuenta en Firebase; eso no debe darle acceso a los datos.
    """
    r = await client.get("/v1/me", headers={"Authorization": "Bearer uid-de-un-extrano"})
    assert r.status_code == 403
    assert _codigo(r) == "NO_REGISTRADO"


async def test_n1_06_una_cuenta_pendiente_de_aprobacion_no_entra(client: AsyncClient, db: AsyncSession) -> None:
    """N1-06 · El auto-registro no puede ser una puerta de entrada por sí mismo."""
    await crear_usuario(db, uid="uid-pendiente", correo="pendiente@x.mx", aprobado=False)

    r = await client.get("/v1/me", headers={"Authorization": "Bearer uid-pendiente"})
    assert r.status_code == 403
    assert _codigo(r) == "CUENTA_PENDIENTE"


async def test_n1_07_una_cuenta_desactivada_no_entra(client: AsyncClient, db: AsyncSession) -> None:
    """N1-07 · Revocar el acceso a alguien tiene que surtir efecto de inmediato."""
    await crear_usuario(db, uid="uid-inactivo", correo="inactivo@x.mx", activo=False)

    r = await client.get("/v1/me", headers={"Authorization": "Bearer uid-inactivo"})
    assert r.status_code == 403
    assert _codigo(r) == "CUENTA_INACTIVA"


# --------------------------------------------------------------------------- #
# Aislamiento entre empresas: el corazón del multi-tenant.
# --------------------------------------------------------------------------- #


async def test_n1_08_no_se_alcanza_la_empresa_de_otro(client: AsyncClient, db: AsyncSession) -> None:
    """N1-08 · Usuario con acceso a la empresa A pidiendo los datos de la empresa B."""
    usuario = await crear_usuario(db, uid="uid-a", correo="a@x.mx")
    propia = await crear_empresa(db, nombre="Propia", rfc="EKU9003173C9")
    ajena = await crear_empresa(db, nombre="Ajena", rfc="XAXX010101000")
    await asignar_permiso(db, usuario, propia, RolEmpresa.OPERADOR)

    r = await client.get(f"/v1/empresas/{ajena.empresa_id}/comprobantes", headers={"Authorization": "Bearer uid-a"})
    assert r.status_code == 404


async def test_n1_09_una_empresa_ajena_y_una_inexistente_son_indistinguibles(client: AsyncClient, db: AsyncSession) -> None:
    """N1-09 · Anti-enumeración: la prueba dura del diseño de `deps.py`.

    Si la respuesta a "existe pero no es tuya" difiere de "no existe", un atacante barre el
    rango de `empresa_id` y **descubre cuántas empresas hay en el sistema y con qué ids**, sin
    ver ni un dato. Las dos respuestas tienen que ser idénticas: mismo código y mismo cuerpo.
    """
    usuario = await crear_usuario(db, uid="uid-b", correo="b@x.mx")
    propia = await crear_empresa(db, nombre="Propia B", rfc="EKU9003173C9")
    ajena = await crear_empresa(db, nombre="Ajena B", rfc="XAXX010101000")
    await asignar_permiso(db, usuario, propia, RolEmpresa.OPERADOR)
    cabeceras = {"Authorization": "Bearer uid-b"}

    r_ajena = await client.get(f"/v1/empresas/{ajena.empresa_id}/comprobantes", headers=cabeceras)
    r_inexistente = await client.get("/v1/empresas/987654/comprobantes", headers=cabeceras)

    assert r_ajena.status_code == r_inexistente.status_code == 404
    assert _sin_trace(r_ajena) == _sin_trace(r_inexistente), "la respuesta delata si la empresa existe"


async def test_n1_10_el_rol_de_consulta_no_puede_operar(client: AsyncClient, db: AsyncSession) -> None:
    """N1-10 · Escalada dentro de la propia empresa: consulta intentando lanzar una descarga.

    Importa más de lo que parece: una descarga gasta la cuota de solicitudes de la empresa
    ante el SAT y usa su e.firma.
    """
    usuario = await crear_usuario(db, uid="uid-consulta", correo="consulta@x.mx")
    empresa = await crear_empresa(db, nombre="Con Consulta", rfc="EKU9003173C9")
    await asignar_permiso(db, usuario, empresa, RolEmpresa.CONSULTA)

    r = await client.post(
        f"/v1/empresas/{empresa.empresa_id}/descargas",
        headers={"Authorization": "Bearer uid-consulta"},
        json={"tipo": "emitido", "solicitud": "CFDI", "desde": "2026-01-01", "hasta": "2026-01-31"},
    )
    assert r.status_code == 403


async def test_n1_11_el_admin_global_si_alcanza_cualquier_empresa(client: AsyncClient, db: AsyncSession) -> None:
    """N1-11 · Control positivo, para que las pruebas de arriba signifiquen algo.

    El acceso implícito del administrador es **intencional** (`deps.py`, `ContextoEmpresa`).
    Sin esta prueba, un cambio que rompiera todo acceso dejaría las demás en verde.
    """
    await crear_usuario(db, uid="uid-admin", correo="admin@x.mx", rol_global=RolGlobal.ADMIN)
    empresa = await crear_empresa(db, nombre="Sin permiso explícito", rfc="EKU9003173C9")

    r = await client.get(f"/v1/empresas/{empresa.empresa_id}/comprobantes", headers={"Authorization": "Bearer uid-admin"})
    assert r.status_code == 200


# --------------------------------------------------------------------------- #
# Escalada de privilegios: llegar a ser administrador sin serlo.
# --------------------------------------------------------------------------- #


async def test_n1_12_un_usuario_normal_no_lista_usuarios(client: AsyncClient, db: AsyncSession) -> None:
    """N1-12 · El padrón de usuarios es de administradores."""
    await crear_usuario(db, uid="uid-normal", correo="normal@x.mx", rol_global=RolGlobal.OPERADOR)

    r = await client.get("/v1/usuarios", headers={"Authorization": "Bearer uid-normal"})
    assert r.status_code == 403


async def test_n1_13_un_usuario_no_puede_hacerse_administrador(client: AsyncClient, db: AsyncSession) -> None:
    """N1-13 · Autoascenso: `PATCH` sobre su propio registro pidiendo `rol_global=admin`."""
    usuario = await crear_usuario(db, uid="uid-ambicioso", correo="ambicioso@x.mx", rol_global=RolGlobal.CONSULTA)

    r = await client.patch(
        f"/v1/usuarios/{usuario.usuario_id}",
        headers={"Authorization": "Bearer uid-ambicioso"},
        json={"rol_global": "admin"},
    )
    assert r.status_code == 403

    await db.refresh(usuario)
    assert usuario.rol_global is RolGlobal.CONSULTA, "el rol cambió pese al 403"


async def test_n1_14_un_usuario_no_puede_asignarse_permisos_sobre_empresas(client: AsyncClient, db: AsyncSession) -> None:
    """N1-14 · Autoservicio de permisos: darse acceso a una empresa que no le toca."""
    usuario = await crear_usuario(db, uid="uid-colado", correo="colado@x.mx", rol_global=RolGlobal.OPERADOR)
    ajena = await crear_empresa(db, nombre="Ajena C", rfc="XAXX010101000")

    r = await client.put(
        f"/v1/usuarios/{usuario.usuario_id}/permisos",
        headers={"Authorization": "Bearer uid-colado"},
        json={"permisos": [{"empresa_id": ajena.empresa_id, "rol": "operador"}]},
    )
    assert r.status_code == 403

    r2 = await client.get(f"/v1/empresas/{ajena.empresa_id}/comprobantes", headers={"Authorization": "Bearer uid-colado"})
    assert r2.status_code == 404, "el permiso se concedió pese al 403"


async def test_n1_15_una_cuenta_pendiente_no_puede_aprobarse_a_si_misma(client: AsyncClient, db: AsyncSession) -> None:
    """N1-15 · El caso que vuelve inútil todo el flujo de aprobación si falla."""
    usuario = await crear_usuario(db, uid="uid-auto", correo="auto@x.mx", aprobado=False)

    r = await client.patch(
        f"/v1/usuarios/{usuario.usuario_id}",
        headers={"Authorization": "Bearer uid-auto"},
        json={"aprobado": True},
    )
    assert r.status_code == 403

    await db.refresh(usuario)
    assert usuario.aprobado is False, "la cuenta se aprobó a sí misma"


# --------------------------------------------------------------------------- #
# Integridad del sistema de administración: no quedarse sin dueño ni abrir la puerta.
# --------------------------------------------------------------------------- #


async def test_n1_16_el_alta_de_arranque_se_cierra_al_primer_usuario(client: AsyncClient, db: AsyncSession) -> None:
    """N1-16 · El riesgo más grave del bootstrap: que siga abierto en producción.

    Si `POST /auth/bootstrap` funcionara con usuarios ya existentes, cualquiera con la URL se
    haría administrador del sistema.
    """
    await crear_usuario(db, uid="uid-ya-existe", correo="existente@x.mx", rol_global=RolGlobal.ADMIN)

    r = await client.post(
        "/v1/auth/bootstrap",
        json={"correo": "atacante@x.mx", "nombre": "Atacante", "password": "Sup3rS3cret!", "token": "cualquiera"},
    )
    assert r.status_code in (403, 409, 503)
    assert r.status_code != 200, "el bootstrap creó un segundo administrador"


async def test_n1_17_un_administrador_no_puede_eliminarse_a_si_mismo(client: AsyncClient, db: AsyncSession) -> None:
    """N1-17 · Evita el pie en el pie: quedarse fuera del sistema por accidente."""
    admin = await crear_usuario(db, uid="uid-admin-solo", correo="solo@x.mx", rol_global=RolGlobal.ADMIN)

    r = await client.delete(f"/v1/usuarios/{admin.usuario_id}", headers={"Authorization": "Bearer uid-admin-solo"})
    assert r.status_code == 409
    assert _codigo(r) == "NO_AUTO_ELIMINACION"


async def test_n1_18_no_se_puede_dejar_el_sistema_sin_administrador(client: AsyncClient, db: AsyncSession) -> None:
    """N1-18 · Degradar al último admin dejaría el sistema sin quien administre: irreversible
    sin tocar la base a mano."""
    admin_a = await crear_usuario(db, uid="uid-adm-a", correo="adma@x.mx", rol_global=RolGlobal.ADMIN)
    admin_b = await crear_usuario(db, uid="uid-adm-b", correo="admb@x.mx", rol_global=RolGlobal.ADMIN)
    cabeceras = {"Authorization": "Bearer uid-adm-a"}

    # Quitar el rol a B es legítimo: quedaría A.
    r_primero = await client.patch(f"/v1/usuarios/{admin_b.usuario_id}", headers=cabeceras, json={"rol_global": "consulta"})
    assert r_primero.status_code == 200

    # Quitárselo a A (el último) no puede permitirse.
    r_ultimo = await client.patch(f"/v1/usuarios/{admin_a.usuario_id}", headers=cabeceras, json={"rol_global": "consulta"})
    assert r_ultimo.status_code == 409
    assert _codigo(r_ultimo) == "ULTIMO_ADMIN"


async def test_n1_19_con_la_base_vacia_el_auto_registro_no_esta_disponible(client: AsyncClient) -> None:
    """N1-19 · El primer usuario del sistema no puede nacer por auto-registro.

    Si pudiera, el primer registro sería un `consulta` pendiente **y no habría nadie con
    permiso para aprobarlo**: el sistema quedaría cerrado sobre sí mismo. El primer usuario
    tiene que ser el administrador de arranque.
    """
    r = await client.post(
        "/v1/auth/registro",
        headers={"Authorization": "Bearer uid-primer-llegado"},
        json={"nombre": "Primer Llegado"},
    )
    assert r.status_code == 403
    assert _codigo(r) == "REGISTRO_NO_DISPONIBLE"


async def test_n1_20_el_auto_registro_nace_sin_acceso(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """N1-20 · Registrarse y quedar aprobado de un tirón sería una puerta abierta.

    Se sustituye `firebase_auth.get_user` porque el endpoint toma el correo **de Firebase y
    nunca del cuerpo** (para que nadie declare un correo ajeno); sin el doble, la prueba muere
    en el 400 de "no se pudo verificar la cuenta" y nunca llega a lo que se quiere auditar.
    """
    from app.api.v1 import auth_bootstrap

    await crear_usuario(db, uid="uid-admin-previo", correo="previo@x.mx", rol_global=RolGlobal.ADMIN)
    monkeypatch.setattr(auth_bootstrap, "firebase_app", lambda: None)
    monkeypatch.setattr(
        auth_bootstrap.firebase_auth, "get_user", lambda uid, app=None: _CuentaFirebase("nuevo@x.mx")
    )

    r = await client.post(
        "/v1/auth/registro",
        headers={"Authorization": "Bearer uid-recien-llegado"},
        json={"nombre": "Recien Llegado"},
    )
    assert r.status_code == 201

    r_datos = await client.get("/v1/me", headers={"Authorization": "Bearer uid-recien-llegado"})
    assert r_datos.status_code == 403, "una cuenta recien auto-registrada obtuvo acceso"
    assert _codigo(r_datos) == "CUENTA_PENDIENTE"


async def test_n1_21_un_correo_no_puede_registrarse_dos_veces(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """N1-21 · Dos usuarios con el mismo correo rompen la trazabilidad de la bitácora, que
    identifica al actor por su correo."""
    from app.api.v1 import auth_bootstrap

    await crear_usuario(db, uid="uid-admin-previo-2", correo="previo2@x.mx", rol_global=RolGlobal.ADMIN)
    await crear_usuario(db, uid="uid-ya-esta", correo="ocupado@x.mx", aprobado=True)
    monkeypatch.setattr(auth_bootstrap, "firebase_app", lambda: None)
    monkeypatch.setattr(
        auth_bootstrap.firebase_auth, "get_user", lambda uid, app=None: _CuentaFirebase("ocupado@x.mx")
    )

    r = await client.post(
        "/v1/auth/registro",
        headers={"Authorization": "Bearer uid-otro-distinto"},
        json={"nombre": "Impostor"},
    )
    assert r.status_code == 409
    assert _codigo(r) == "YA_REGISTRADO"
