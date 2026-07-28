"""Enlaces firmados de descarga (doc 05 §6) — firma/verificación, y los endpoints
`GET /v1/tareas/{tarea_id}` y `GET /v1/descargas-archivo/{token}`."""

from __future__ import annotations

import os
import time

import pytest
from httpx import AsyncClient

from app.core.config import get_settings
from app.services import enlaces


def test_firmar_y_verificar_ida_y_vuelta() -> None:
    token = enlaces.firmar({"ruta": "11/comprobantes/x.xml"})
    payload = enlaces.verificar(token)
    assert payload["ruta"] == "11/comprobantes/x.xml"


def test_verificar_token_alterado_es_invalido() -> None:
    token = enlaces.firmar({"ruta": "11/comprobantes/x.xml"})
    alterado = token[:-4] + ("A" if token[-4] != "A" else "B") + token[-3:]
    with pytest.raises(enlaces.EnlaceInvalidoError):
        enlaces.verificar(alterado)


def test_verificar_token_mal_formado_es_invalido() -> None:
    with pytest.raises(enlaces.EnlaceInvalidoError):
        enlaces.verificar("esto-no-es-un-token-valido")


def test_verificar_token_vencido_es_invalido() -> None:
    token = enlaces.firmar({"ruta": "x.xml"}, ttl_seg=-1)
    time.sleep(0.01)
    with pytest.raises(enlaces.EnlaceInvalidoError):
        enlaces.verificar(token)


async def test_descargas_archivo_token_valido_200(client: AsyncClient) -> None:
    carpeta = os.path.join(get_settings().storage_root, "999")
    os.makedirs(carpeta, exist_ok=True)
    ruta_absoluta = os.path.join(carpeta, "prueba.xml")
    with open(ruta_absoluta, "wb") as f:
        f.write(b"<contenido/>")

    token = enlaces.firmar({"ruta": os.path.join("999", "prueba.xml")})
    r = await client.get(f"/v1/descargas-archivo/{token}")
    assert r.status_code == 200
    assert r.content == b"<contenido/>"


async def test_descargas_archivo_token_invalido_403(client: AsyncClient) -> None:
    r = await client.get("/v1/descargas-archivo/token-invalido")
    assert r.status_code == 403


async def test_descargas_archivo_token_vencido_403(client: AsyncClient) -> None:
    token = enlaces.firmar({"ruta": "999/prueba.xml"}, ttl_seg=-1)
    r = await client.get(f"/v1/descargas-archivo/{token}")
    assert r.status_code == 403


async def test_descargas_archivo_no_escapa_storage_root(client: AsyncClient) -> None:
    """Aunque el token esté firmado correctamente, una ruta que intente escapar
    `storage_root` (defensa en profundidad — nunca debería generarse, pero si se firmara
    a mano, tampoco debe servirse) responde 404."""
    token = enlaces.firmar({"ruta": "../../etc/passwd"})
    r = await client.get(f"/v1/descargas-archivo/{token}")
    assert r.status_code == 404


async def test_estado_tarea_pendiente_para_id_desconocido(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Limitación aceptada y documentada (doc 05 §6): sin tabla propia, un `tarea_id`
    inventado es indistinguible de "pendiente" — así responde Celery para cualquier id
    sin resultado en el backend. Redis real no está disponible en pruebas, así que se
    simula la misma respuesta que Celery daría para un id desconocido."""

    class _ResultadoFalso:
        state = "PENDING"
        result = None

    import celery.result

    monkeypatch.setattr(celery.result, "AsyncResult", lambda *a, **k: _ResultadoFalso())

    r = await client.get("/v1/tareas/id-que-no-existe")
    assert r.status_code == 200
    assert r.json()["estado"] == "pendiente"


async def test_estado_tarea_completada_con_descarga_url(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    class _ResultadoFalso:
        state = "SUCCESS"
        result = {"ruta": "11/exports/x.xlsx", "filas": 3}

    # `AsyncResult` se importa dentro de la función (import perezoso) — parcheamos el símbolo
    # del módulo `celery.result` directamente para que ese import perezoso lo recoja.
    import celery.result

    monkeypatch.setattr(celery.result, "AsyncResult", lambda *a, **k: _ResultadoFalso())

    r = await client.get("/v1/tareas/tarea-completada")
    assert r.status_code == 200
    body = r.json()
    assert body["estado"] == "completada"
    assert body["descarga_url"] is not None
    assert "/v1/descargas-archivo/" in body["descarga_url"]


async def test_estado_tarea_fallida(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    class _ResultadoFalso:
        state = "FAILURE"
        result = None

    import celery.result

    monkeypatch.setattr(celery.result, "AsyncResult", lambda *a, **k: _ResultadoFalso())

    r = await client.get("/v1/tareas/tarea-fallida")
    assert r.status_code == 200
    assert r.json()["estado"] == "fallida"
