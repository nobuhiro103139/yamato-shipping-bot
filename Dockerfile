FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    xvfb \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir poetry

WORKDIR /app

COPY pyproject.toml poetry.lock* ./
RUN poetry config virtualenvs.create false \
    && poetry install --no-interaction --no-ansi --no-root

ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

RUN mkdir -p /ms-playwright \
    && python -m playwright install --with-deps chromium

COPY scripts/ scripts/

RUN adduser --disabled-password --gecos "" appuser \
    && mkdir -p /app/qr_codes \
    && chown -R appuser:appuser /app /ms-playwright

USER appuser

ENV PYTHONUNBUFFERED=1

CMD ["xvfb-run", "--auto-servernum", "--server-args=-screen 0 1280x960x24", "python", "-m", "scripts.ship"]
