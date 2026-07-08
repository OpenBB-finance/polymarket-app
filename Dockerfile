FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    POLYMARKET_CACHE_DIR=/data/cache

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Non-root user owning the mounted cache volume.
RUN useradd --create-home --uid 1000 app \
    && mkdir -p /data/cache \
    && chown -R app:app /data
USER app

VOLUME ["/data/cache"]
EXPOSE 7779

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-7779}"]
