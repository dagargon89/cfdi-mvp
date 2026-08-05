"""Registro de informes (spec §7.1).

De aquí depende el endpoint de la tarea 13 para devolver un 404 limpio cuando la clave no
existe. Se aísla `REGISTRO` con `monkeypatch` en vez de depender de que esté vacío o lleno:
así las pruebas siguen siendo válidas cuando la tarea 11 agregue B-02.
"""

from __future__ import annotations

import pytest

from app.informes import registro


def test_catalogo_con_registro_vacio_devuelve_lista_vacia(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(registro, "REGISTRO", {})
    assert registro.catalogo() == []


def test_obtener_con_clave_desconocida_lanza_informe_desconocido(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(registro, "REGISTRO", {})
    with pytest.raises(registro.InformeDesconocidoError):
        registro.obtener("NO-EXISTE")


def test_informe_desconocido_error_es_capturable_como_key_error() -> None:
    """El endpoint traduce esta excepción a un 404; debe poder capturarla también como el
    `KeyError` que es, sin conocer el tipo específico."""
    assert issubclass(registro.InformeDesconocidoError, KeyError)
    with pytest.raises(KeyError):
        registro.obtener("NO-EXISTE")
