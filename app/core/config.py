"""Configuración vía variables de entorno (doc 02 §3.2, doc 04 §3.5 — nada de defaults inseguros)."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"

    database_url: str
    redis_url: str

    kek_path: str
    google_application_credentials: str
    firebase_project_id: str

    # Raíz donde el worker escribe los paquetes descargados del SAT (RF-DESC-06),
    # bajo storage_root/{empresa_id}/{job_id}/paquete_{n}.zip.
    storage_root: str = "./storage"

    # Secreto para firmar enlaces temporales de descarga (doc 05 §6) — HMAC, no es material
    # de e.firma, no usa la KEK. Rotar invalida enlaces en vuelo (aceptable: son de minutos).
    signing_secret: str
    # Host público de la API — los enlaces firmados los abre el navegador directo (no
    # `fetch` desde apps/web), así que deben ser absolutos contra la API, no contra la SPA.
    public_base_url: str = "http://localhost:8000"

    cors_origins: str = "http://localhost:5173"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # pydantic-settings resuelve desde el entorno/.env
