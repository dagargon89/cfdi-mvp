"""App Celery — sin tareas registradas todavía (Sprint 2 añade `ejecutar_job` y compañía,
doc 02 §3.6). Existe desde Sprint 0 para que `docker compose up` levante worker/beat limpios."""

from celery import Celery

from app.core.config import get_settings

_settings = get_settings()

celery_app = Celery("hub_cfdi", broker=_settings.redis_url, backend=_settings.redis_url)
celery_app.conf.update(task_serializer="json", result_serializer="json", accept_content=["json"])
