# Polymarket Market Explorer

OpenBB Workspace backend for public Polymarket prediction-market data.

A FastAPI backend that OpenBB Workspace registers as a custom data connector.
Workspace reads `widgets.json` for the widget definitions and `apps.json` for
the prebuilt **Polymarket Market Explorer** app layout.

Every parameter choice in the app (tag → event → market) is derived from a
single cached snapshot of **active events**, built by walking Polymarket's
keyset-paginated Gamma endpoint:

- [`GET /events/keyset`](https://docs.polymarket.com/api-reference/events/list-events-keyset-pagination) —
  active events ranked by 24h volume, each embedding its tags and nested markets.
  Pagination is **cursor-based** (`after_cursor`); the legacy `offset` is rejected.

Because the choice lists come from this snapshot rather than from re-scanning
live endpoints, filtering by tag and event is fast and consistent with the data
shown in the tables. Polymarket's `/tags` endpoint carries no activity metric,
so the **tag list is derived from the events that are actually active**, ranked
by aggregated volume. The Browse search box routes to
[`GET /public-search`](https://docs.polymarket.com/api-reference/search/search-markets-events-and-profiles)
for full-text search across all events.

## Quick Start (Docker)

```bash
docker compose up --build
```

This builds the image and runs the backend on `http://localhost:7779`, with the
on-disk cache (`POLYMARKET_CACHE_DIR=/data/cache`) persisted to the named volume
`polymarket-cache`. Because the active-events snapshot lives on that volume, a
`docker compose restart` reuses it instead of re-scanning the upstream API. The
container runs as a non-root user, `--init` reaps signals, and the server exits
cleanly on `docker stop` (bounded graceful shutdown).

Plain Docker with a named volume:

```bash
docker build -t openbb-polymarket .
docker run -d -p 7779:7779 --init -v polymarket-cache:/data/cache openbb-polymarket
```

Mount a host directory instead of a named volume only if it is writable by
uid 1000 (the container's `app` user): `-v /host/cache:/data/cache`. Set
`POLYMARKET_PUBLIC_BASE_URL` if Workspace reaches the backend at a different
host/port than the container sees.

## Quick Start (local)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 7779 --timeout-graceful-shutdown 5
```

`--timeout-graceful-shutdown 5` bounds how long uvicorn waits for open
connections on Ctrl+C. The app holds a long-lived SSE stream open
(`/selection_stream`, which syncs the selected market across widgets); without
the bound, shutdown stalls on *"Waiting for connections to close."* Running
`python main.py` applies the same timeout without the CLI flag.

Then add the backend URL in OpenBB Workspace → **Settings → Data Connectors →
Add Custom Backend**:

```text
http://localhost:7779
```

Workspace loads `widgets.json` and `apps.json` from that URL automatically.
Open **Apps** and launch **Polymarket Market Explorer**.

## Project Layout

```
main.py                  # thin entry point: exposes `app` for `uvicorn main:app`
openbb_polymarket/
├── app.py               # application factory: wiring + CORS + routers + /mcp mount
├── config.py            # Settings loaded from the environment (.env optional)
├── cache.py             # shared on-disk cache (diskcache) rooted at a mounted volume
├── client.py            # disk-cached async httpx wrapper; keyset cursor helper; rate limiter
├── stats.py             # EventStatsCache: active-events scan -> tags + discover/browse
├── service.py           # resolve + realtime: prices-history, book, trades, holders, search
├── transforms.py        # raw Polymarket objects -> flat widget rows
├── formatting.py        # value/format helpers + market_key codec + JSON-string parsing
├── charts.py            # Plotly figure builders
├── browse.py            # HTML event-card browser (iframe)
├── event_page.py        # HTML event details page
├── marketrules.py       # HTML market brief (resolution criteria + UMA)
├── ladder.py            # HTML orderbook ladder
├── dependencies.py      # FastAPI accessors for the shared singletons
├── mcp_server.py        # MCP server (mounted at /mcp) + market-selection pub/sub
└── routers/
    ├── meta.py          # health, manifests, thumbnail
    ├── options.py       # the tag -> event -> market cascade
    ├── discover.py      # volume by tag, browse markets, event details
    ├── events.py        # event metrics, outcomes, price history
    └── markets.py       # rules, orderbook, trades, holders, leaderboard
```

An `EventStatsCache` (`openbb_polymarket/stats.py`) pages the active-event book
once in the background (cursor pagination), maps each event to its tags, and
persists the snapshot to the on-disk cache. The Discover widgets serve from a
per-worker mirror instantly; a startup warmer and TTL keep it fresh.

## Caching & Persistence

All caching is backed by [`diskcache`](https://grantjenks.com/docs/diskcache/)
rooted at `POLYMARKET_CACHE_DIR` — **point this at a mounted volume in
production**. Both the HTTP responses and the active-events snapshot live on
disk (SQLite + spill files), so resident memory stays flat regardless of cache
size, and the expensive initial scan survives restarts and is shared by every
worker:

- **Initial ingest** is single-flight: a cross-worker lock (`cache.add`) means
  only one worker scans on a cold start; the rest wait for the snapshot to land
  on disk, then load it — no stampede on the upstream API, no duplicate RAM.
- **Restarts** reuse a still-fresh on-disk snapshot instead of re-scanning.
- **TTL** is enforced by diskcache `expire` plus the snapshot's own creation
  timestamp; `POLYMARKET_CACHE_SIZE_LIMIT` caps disk use (LRU eviction past it).

See `.env.example` for `POLYMARKET_CACHE_DIR`, `POLYMARKET_CACHE_SIZE_LIMIT`,
and `POLYMARKET_STATS_SCAN_LOCK_TTL`.

## How the Cascade Works

Each dropdown is populated by an options endpoint that depends only on the
choice above it, and every data widget falls back to the most active live
instrument when nothing is selected:

| Choice | Endpoint | Derived from |
|--------|----------|--------------|
| Tag    | `/options?field=tag` | active-events scan (ranked by volume) |
| Event  | `/options?field=event_id&tag=` | active-events scan (filtered by tag) |
| Market | `/options?field=market_key&event_id=` | resolved event's markets |

`market_key` is the opaque value passed between market widgets, encoded as
`event_id|condition_id`. The YES/NO CLOB token ids are re-derived from the
resolved market.

## Data Sources

| Data | API | Endpoint |
|------|-----|----------|
| Events / markets / tags | Gamma | `/events/keyset`, `/events/{id}`, `/markets/keyset` |
| Search | Gamma | `/public-search` |
| Price history | CLOB | `/prices-history` |
| Order book | CLOB | `/book` |
| Trade tape | Data | `/trades` |
| Top holders | Data | `/holders` |
| Leaderboard | Leaderboard | `/volume`, `/pnl` |

## Data Source and Safety

The backend uses only Polymarket public market-data endpoints. It does not
submit orders, read private portfolio data, or require credentials. Responses
are cached in memory for short intervals to reduce repeated API calls.

## Validate Locally

With the server running:

```bash
curl http://localhost:7779/
curl http://localhost:7779/widgets.json
curl "http://localhost:7779/options?field=tag"
curl "http://localhost:7779/volume_by_tag"
curl "http://localhost:7779/options?field=event_id&tag=politics"
```
