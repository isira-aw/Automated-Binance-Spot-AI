# syntax=docker/dockerfile:1
FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# CPU-only by design (§52): no CUDA packages, no GPU runtime.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini pyproject.toml ./
COPY app ./app

# Run as an unprivileged user; the persistent volumes are mounted with matching
# ownership by docker compose.
RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /project/logs /project/data /project/models /project/artifacts /project/backups \
    && chown -R appuser:appuser /app /project
USER appuser

EXPOSE 8000

# 127.0.0.1 for the same reason as the frontend probe: uvicorn binds 0.0.0.0
# (IPv4).  curl happens to retry over IPv4, but relying on that is luck.
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
    CMD curl -fsS http://127.0.0.1:8000/api/v1/system/ping || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]


FROM base AS dev
USER root
RUN pip install --no-cache-dir -r requirements-dev.txt
USER appuser
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
