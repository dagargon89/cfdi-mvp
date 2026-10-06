FROM python:3.12-slim

WORKDIR /srv

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b \
    fonts-liberation fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini
# Semillas fiscales (`app/scripts/cargar_configuracion_fiscal.py`). En desarrollo llegan por un
# volumen; en producción la imagen tiene que traerlas. No son secretas.
COPY config ./config

# `/srv/storage` se crea aquí con dueño `appuser` porque Docker copia el dueño del directorio de
# la imagen a un volumen con nombre nuevo: sin esto el volumen nacería de root y el worker no
# podría escribir los paquetes del SAT. `/srv/secrets` es el punto de montaje (solo lectura).
RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /srv/storage /srv/secrets \
    && chown -R appuser:appuser /srv
USER appuser

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
