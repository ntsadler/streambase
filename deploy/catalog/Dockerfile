FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    STREAMBASE_CATALOG_DB_PATH=/app/catalog_data/catalog.sqlite \
    STREAMBASE_CATALOG_AUDIO_ROOT=/app/catalog_data/audio

WORKDIR /app

RUN groupadd --system catalog \
    && useradd --system --gid catalog --home-dir /app catalog

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --requirement requirements.txt

COPY --chown=catalog:catalog src ./src
COPY --chown=catalog:catalog catalog_data ./catalog_data

USER catalog

CMD ["sh", "-c", "exec uvicorn src.catalog_api:app --host 0.0.0.0 --port \"${PORT:-8080}\""]
