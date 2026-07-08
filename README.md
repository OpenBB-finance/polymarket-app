# Polymarket Market Explorer

FastAPI backend for [OpenBB Workspace](https://my.openbb.co) serving public Polymarket prediction-market data.

## Docker

```bash
docker compose up --build
```

Runs on `http://localhost:7779`. Cache is persisted to a named volume so restarts skip the initial scan.

## Local

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 7779 --timeout-graceful-shutdown 5
```

## Connect to OpenBB Workspace

**Settings → Data Connectors → Add Custom Backend** → `http://localhost:7779`

Workspace loads `widgets.json` and `apps.json` automatically. Open **Apps** and launch **Polymarket Market Explorer**.

## Environment

See `.env.example` for `POLYMARKET_CACHE_DIR`, `POLYMARKET_CACHE_SIZE_LIMIT`, and `POLYMARKET_PUBLIC_BASE_URL`.
