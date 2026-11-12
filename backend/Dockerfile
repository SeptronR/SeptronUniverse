# SeptronUniverse API / worker / beat image — Prompts/44 §44.6 docker 1 (multi-stage, non-root, tini).
# One image serves the API (gunicorn + uvicorn workers), every Celery worker queue, beat and flower; the command
# differs per compose service. Build: docker build -t ghcr.io/septronr/universe-api:<tag> backend/

# ---- builder: wheels for every requirement ------------------------------------------------------------------------
FROM python:3.12-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update && apt-get install -y --no-install-recommends build-essential libffi-dev libpq-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /wheels
COPY requirements.txt .
RUN pip wheel --wheel-dir /wheels -r requirements.txt

# ---- runtime ------------------------------------------------------------------------------------------------------
FROM python:3.12-slim
ARG APP_VERSION=dev
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_VERSION=${APP_VERSION} \
    WEB_CONCURRENCY=4 \
    SCHEMA_SQL_PATH=/app/Database_Schema.sql \
    FEATURE_DOC_PATH=/app/docs/Feature_Flags.md

# WeasyPrint (pango / cairo / gdk-pixbuf), python-magic, Noto fonts incl. Indic scripts for certificates / hall
# tickets, curl for healthchecks, tini as PID 1, pg client for the restore drill / ops scripts
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpango-1.0-0 libpangoft2-1.0-0 libcairo2 libgdk-pixbuf-2.0-0 libffi8 libmagic1 libpq5 \
        fonts-noto-core fonts-noto-extra fonts-noto-ui-core curl tini postgresql-client \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=builder /wheels /wheels
RUN pip install --no-index --find-links=/wheels /wheels/*.whl && rm -rf /wheels

# The build context is backend/; CI copies Database_Schema.sql (revision 0001) and docs/Feature_Flags.md into it first
# (see .github/workflows/build.yml) so the image migrates a fresh database without the repository checkout.
COPY . .
# Fixed uid/gid 10002: orbit-infra chowns the bind-mounted uploads directory to it
RUN groupadd --system --gid 10002 app && useradd --system --uid 10002 --gid app --home /app app \
    && mkdir -p /app/uploads /app/reports && chown -R app:app /app/uploads /app/reports \
    && chmod +x /app/docker-entrypoint.sh
USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 CMD curl -fsS http://localhost:8000/health || exit 1
STOPSIGNAL SIGTERM

ENTRYPOINT ["tini", "--", "/app/docker-entrypoint.sh"]
CMD ["sh", "-c", "exec gunicorn -k uvicorn.workers.UvicornWorker -w ${WEB_CONCURRENCY} -b 0.0.0.0:8000 --timeout 60 --graceful-timeout 30 --max-requests 5000 --max-requests-jitter 500 --access-logfile - main:app"]
