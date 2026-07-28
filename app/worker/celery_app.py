"""App Celery — `include` registra `app.worker.tasks` (Sprint 2: `ejecutar_job`, doc 02 §3.6)
sin crear un import circular (tasks.py importa `celery_app` de este módulo)."""

from celery import Celery

from app.core.config import get_settings

_settings = get_settings()

celery_app = Celery("hub_cfdi", broker=_settings.redis_url, backend=_settings.redis_url, include=["app.worker.tasks"])
celery_app.conf.update(task_serializer="json", result_serializer="json", accept_content=["json"])
