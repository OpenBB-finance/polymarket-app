from __future__ import annotations

import asyncio
import json
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations

from openbb_polymarket.service import MarketDataService
from openbb_polymarket.stats import EventStatsCache
from openbb_polymarket.transforms import (
    holder_rows,
    market_row,
    orderbook_rows,
    trade_row,
)

mcp = FastMCP(
    "Polymarket Markets",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)
mcp.settings.streamable_http_path = "/"

_ctx: dict[str, Any] = {}
_selection_subscribers: set[asyncio.Queue] = set()
_stream_shutdown = asyncio.Event()

STREAM_STOP = None


def subscribe_selection() -> asyncio.Queue:
    queue: asyncio.Queue = asyncio.Queue()
    _selection_subscribers.add(queue)
    return queue


def unsubscribe_selection(queue: asyncio.Queue) -> None:
    _selection_subscribers.discard(queue)


def begin_stream_shutdown() -> None:
    _stream_shutdown.set()
    for queue in list(_selection_subscribers):
        queue.put_nowait(STREAM_STOP)


def stream_shutdown_started() -> bool:
    return _stream_shutdown.is_set()


def set_context(service: MarketDataService, stats: EventStatsCache) -> None:
    _ctx["service"] = service
    _ctx["stats"] = stats


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, int(value)))


def set_selection(market_key: str) -> None:
    selection = (market_key or "").strip()
    if not selection or selection == _ctx.get("selection"):
        return
    _ctx["selection"] = selection
    for queue in list(_selection_subscribers):
        queue.put_nowait(selection)


def current_selection() -> str:
    return _ctx.get("selection", "")


@mcp.tool(annotations=ToolAnnotations(destructiveHint=True))
async def select_market(market_key: str) -> str:
    """Set the market shown by the Market Rules widget."""
    set_selection(market_key)
    return json.dumps({"selected": current_selection()})


@mcp.tool()
async def browse_polymarket_markets(tag: str = "All", search: str = "", limit: int = 20) -> str:
    """Top active Polymarket events filtered by tag and free-text search."""
    stats: EventStatsCache = _ctx["stats"]
    return json.dumps(
        await stats.discover_events(tag=tag, search=search, limit=_clamp(limit, 1, 100)),
        indent=2,
    )


@mcp.tool()
async def polymarket_event_markets(event_id: str) -> str:
    """All outcome markets for a Polymarket event, with YES probability, bid/ask, and volume."""
    service: MarketDataService = _ctx["service"]
    resolved = await service.resolve_event(event_id=event_id)
    rows = [market_row(m, resolved["event_id"]) for m in resolved["markets"]]
    return json.dumps(rows, indent=2)


@mcp.tool()
async def list_polymarket_tags(limit: int = 40) -> str:
    """Active Polymarket tags ranked by 24h trading volume, with event counts."""
    stats: EventStatsCache = _ctx["stats"]
    rows = await stats.tags()
    return json.dumps(rows[: _clamp(limit, 1, 200)], indent=2)


@mcp.tool()
async def polymarket_market_quote(market_key: str) -> str:
    """Current quote for one Polymarket market."""
    service: MarketDataService = _ctx["service"]
    resolved = await service.resolve_market(market_key)
    return json.dumps(market_row(resolved["market"], resolved["event_id"]), indent=2)


@mcp.tool()
async def polymarket_market_orderbook(market_key: str, side: str = "yes") -> str:
    """Live order book (price levels with resting size) for a Polymarket market token."""
    service: MarketDataService = _ctx["service"]
    resolved = await service.resolve_market(market_key)
    token = resolved["no_token"] if side.lower() == "no" else resolved["yes_token"]
    book = await service.fetch_orderbook(token)
    return json.dumps(orderbook_rows(book), indent=2)


@mcp.tool()
async def polymarket_recent_trades(market_key: str, limit: int = 50) -> str:
    """Recent trades (price, size, side, outcome, timestamp) for a Polymarket market."""
    service: MarketDataService = _ctx["service"]
    resolved = await service.resolve_market(market_key)
    trades = await service.fetch_trades(resolved["condition_id"], _clamp(limit, 1, 500))
    return json.dumps([trade_row(t) for t in trades], indent=2)


@mcp.tool()
async def polymarket_top_holders(market_key: str, limit: int = 20) -> str:
    """Largest YES/NO position holders for a Polymarket market."""
    service: MarketDataService = _ctx["service"]
    resolved = await service.resolve_market(market_key)
    payload = await service.fetch_holders(resolved["condition_id"], _clamp(limit, 1, 100))
    from openbb_polymarket.formatting import parse_json_list

    names = parse_json_list(resolved["market"].get("outcomes")) or ["Yes", "No"]
    return json.dumps(holder_rows(payload, names), indent=2)
