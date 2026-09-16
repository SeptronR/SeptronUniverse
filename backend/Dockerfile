# SeptronUniverse API image — Prompts/00_PREREQUISITE_Project_Setup.md §3.27 (Phase 44 turns this into a multi-stage build)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# WeasyPrint + python-magic runtime libraries, curl for the compose healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpango-1.0-0 libpangoft2-1.0-0 libcairo2 libgdk-pixbuf-2.0-0 libffi8 libmagic1 \
        fonts-noto-core curl tini \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN groupadd --system app && useradd --system --gid app --home /app app \
    && mkdir -p /app/uploads && chown -R app:app /app
USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 CMD curl -fsS http://localhost:8000/health || exit 1

ENTRYPOINT ["tini", "--", "sh", "/app/docker-entrypoint.sh"]
CMD ["gunicorn", "-k", "uvicorn.workers.UvicornWorker", "-w", "4", "-b", "0.0.0.0:8000", "--timeout", "60", "--graceful-timeout", "30", "main:app"]
