FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir poetry

WORKDIR /app

COPY backend/pyproject.toml backend/poetry.lock* ./
RUN poetry config virtualenvs.create false \
    && poetry install --no-interaction --no-ansi --no-root

RUN pip install playwright \
    && playwright install --with-deps chromium

COPY backend/ .

RUN mkdir -p /app/qr_codes /app/data

ENV PYTHONUNBUFFERED=1
ENV HEADLESS_BROWSER=true
ENV AUTH_STATE_PATH=/app/data/auth.json

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
