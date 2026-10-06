"""En producción no se publica la descripción de la API: ni `/docs` ni el esquema `/openapi.json`.

`app/main.py` cerraba `/docs` en producción pero dejaba `/openapi.json` con su default de FastAPI:
la página visual desaparecía y el esquema completo —cada endpoint, parámetro y modelo— seguía
respondiendo 200. Visto el 2026-10-06 preparando el despliegue.
"""

from __future__ import annotations

import importlib
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core import config


@pytest.fixture()
def app_en(monkeypatch: pytest.MonkeyPatch) -> Iterator[object]:
    """Construye `app.main` con el `ENVIRONMENT` pedido y la restaura al terminar."""
    import app.main as modulo

    def construir(entorno: str) -> TestClient:
        monkeypatch.setenv("ENVIRONMENT", entorno)
        config.get_settings.cache_clear()
        return TestClient(importlib.reload(modulo).app)

    yield construir
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    config.get_settings.cache_clear()
    importlib.reload(modulo)


def test_en_produccion_no_se_publica_el_esquema_openapi(app_en) -> None:  # type: ignore[no-untyped-def]
    cliente = app_en("production")
    assert cliente.get("/openapi.json").status_code == 404


def test_en_produccion_no_se_publica_docs(app_en) -> None:  # type: ignore[no-untyped-def]
    cliente = app_en("production")
    assert cliente.get("/docs").status_code == 404


def test_en_desarrollo_si_se_publican(app_en) -> None:  # type: ignore[no-untyped-def]
    """Control positivo: sin él, una app que no sirviera nada dejaría las dos de arriba en verde."""
    cliente = app_en("development")
    assert cliente.get("/openapi.json").status_code == 200
    assert cliente.get("/docs").status_code == 200
