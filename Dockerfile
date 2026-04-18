# [ЧТО] Production-образ API: устанавливает зависимости и запускает uvicorn.
# [ПОЧЕМУ] GHCR build-push и Kubernetes deployment ожидают готовый runtime-образ.
# [ОСТОРОЖНО] Секреты не bake-ятся в образ — только через env/Secret в runtime.
FROM python:3.12-slim AS runtime

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md /app/
COPY app /app/app
COPY alembic /app/alembic
COPY alembic.ini /app/alembic.ini

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

EXPOSE 8088

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8088"]
