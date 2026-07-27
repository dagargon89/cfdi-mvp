"""Taxonomía de errores del núcleo (doc 05 §4).

Regla: ``Engine`` traduce las excepciones crudas de ``satcfdi`` a esta jerarquía;
la carcasa solo ve ``HubError`` y sus subclases, nunca excepciones de la librería.
"""

from __future__ import annotations


class HubError(Exception):
    """Raíz de todos los errores del núcleo."""


# --- FIEL / credenciales --------------------------------------------------- #


class FielError(HubError):
    """Error relacionado con la carga o validación de la FIEL."""


class FielVencidaError(FielError):
    """El certificado no está vigente (RF-FIEL-02); el job no se encola."""


class FielPasswordError(FielError):
    """Contraseña incorrecta o llave privada corrupta (sin exponer la contraseña)."""


# --- SAT / Web Service ----------------------------------------------------- #


class SatError(HubError):
    """Error del WS del SAT; envuelve las excepciones de ``satcfdi``."""


class SatRechazoError(SatError):
    """Rechazo definitivo del SAT → el job pasa a ERROR."""


class SatReintentableError(SatError):
    """Intermitencia transitoria → se reintenta con espera (RF-DESC-05)."""


# --- Persistencia ---------------------------------------------------------- #


class StoreError(HubError):
    """Error de la capa de persistencia."""


class TransicionIlegalError(StoreError):
    """``save_job`` con una transición no permitida por la máquina de estados (SRS §4)."""


# --- Configuración --------------------------------------------------------- #


class ConfigError(HubError):
    """Configuración inválida o inconsistente (RF-CFG-01)."""
