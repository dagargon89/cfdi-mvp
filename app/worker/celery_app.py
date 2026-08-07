"""App Celery — `include` registra `app.worker.tasks` (Sprint 2: `ejecutar_job`, doc 02 §3.6)
sin crear un import circular (tasks.py importa `celery_app` de este módulo)."""

from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings

_settings = get_settings()

celery_app = Celery("hub_cfdi", broker=_settings.redis_url, backend=_settings.redis_url, include=["app.worker.tasks"])
celery_app.conf.update(task_serializer="json", result_serializer="json", accept_content=["json"])

# Cada hora, no una única vez a la hora exacta configurada (RNF-05): así una caída del
# proceso `beat` se autorecupera sola en el siguiente tick, en vez de perderse el día entero.
celery_app.conf.beat_schedule = {
    "disparar-sync-diaria": {"task": "app.worker.tasks.disparar_sync_diaria", "schedule": crontab(minute=0)},
    "actualizar-lista-69b": {"task": "app.worker.tasks.actualizar_lista_69b", "schedule": crontab(hour=1, minute=30)},
    "re-verificar-vigentes": {"task": "app.worker.tasks.re_verificar_vigentes", "schedule": crontab(hour=4, minute=0)},
    "limpiar-almacenamiento": {"task": "app.worker.tasks.limpiar_almacenamiento", "schedule": crontab(hour=3, minute=0)},
    # Alarma de vigencia fiscal (informes fase 3, tarea 6). Fuera del bloque de madrugada de
    # arriba a propósito: 13:30 UTC son ~07:30 en el centro de México, ya publicado el tipo de
    # cambio FIX del día hábil anterior y justo antes de que alguien abra la pantalla. Una
    # alarma que corre a las 3 de la mañana llega igual, pero con el dato de Banxico un día más
    # viejo de lo necesario.
    "revisar-vigencia-fiscal": {"task": "app.worker.tasks.revisar_vigencia_fiscal", "schedule": crontab(hour=13, minute=30)},
}
