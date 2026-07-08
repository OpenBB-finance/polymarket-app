from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from openbb_polymarket.cache import create_cache
from openbb_polymarket.client import PolymarketClient
from openbb_polymarket.config import Settings
from openbb_polymarket.mcp_server import (
    begin_stream_shutdown,
    mcp as polymarket_mcp,
    set_context as set_mcp_context,
)
from openbb_polymarket.routers import discover, events, markets, meta, options
from openbb_polymarket.service import MarketDataService
from openbb_polymarket.stats import EventStatsCache


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    mcp_app = polymarket_mcp.streamable_http_app()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        cache = create_cache(settings)
        client = PolymarketClient(settings, cache)
        stats = EventStatsCache(client, settings, cache)
        service = MarketDataService(client, stats, settings)
        app.state.settings = settings
        app.state.cache = cache
        app.state.client = client
        app.state.stats = stats
        app.state.service = service
        set_mcp_context(service, stats)
        warmer = asyncio.create_task(_warm(stats))
        try:
            async with polymarket_mcp.session_manager.run():
                yield
        finally:
            begin_stream_shutdown()
            warmer.cancel()
            with suppress(asyncio.CancelledError):
                await warmer
            await client.aclose()
            await asyncio.to_thread(cache.close)

    app = FastAPI(
        title="Polymarket Market Dashboard",
        description="OpenBB Workspace backend for public Polymarket prediction-market data.",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_origin_regex=".*",
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["*"],
    )

    app.include_router(meta.router)
    app.include_router(options.router)
    app.include_router(discover.router)
    app.include_router(events.router)
    app.include_router(markets.router)
    static_dir = Path(__file__).resolve().parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    app.mount("/mcp", mcp_app)
    return app


async def _warm(stats: EventStatsCache) -> None:
    try:
        await stats.ensure_fresh()
    except asyncio.CancelledError:
        raise
    except Exception:
        pass
