from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse

from openbb_polymarket.dependencies import get_service, get_stats
from openbb_polymarket.formatting import parse_json_list, parse_market_key, to_float
from openbb_polymarket.ladder import render_ladder
from openbb_polymarket.marketrules import render_market_rules
from openbb_polymarket.mcp_server import (
    STREAM_STOP,
    current_selection,
    set_selection,
    stream_shutdown_started,
    subscribe_selection,
    unsubscribe_selection,
)
from openbb_polymarket.service import MarketDataService
from openbb_polymarket.stats import EventStatsCache
from openbb_polymarket.transforms import holder_rows, leaderboard_row, orderbook_rows, trade_row

router = APIRouter()

_NO_MARKET = "No active markets"
_NO_MARKET_HINT = "Try another tag, or select an event."


def _event_ok(market_key: str, event_id: str) -> bool:
    if not event_id:
        return True
    mk_event = parse_market_key(market_key).get("event_id", "")
    return not mk_event or mk_event == event_id


async def effective_market_key(
    market_key: str = Query(""),
    event_id: str = Query(""),
    tag: str = Query("All"),
    service: MarketDataService = Depends(get_service),
    stats: EventStatsCache = Depends(get_stats),
) -> str:
    eid = (event_id or "").strip()
    mk = (market_key or "").strip()
    if mk and _event_ok(mk, eid):
        return mk
    selected = current_selection()
    if selected and _event_ok(selected, eid):
        return selected
    eid = eid or await stats.default_event_id(tag=tag)
    if not eid:
        return ""
    return await service.default_market_key(eid)


def _has(market_key: str) -> bool:
    return bool((market_key or "").strip())


def _prompt_html(theme: str) -> str:
    color = "#667085" if theme == "light" else "#9a9aa4"
    bg = "#ffffff" if theme == "light" else "#0f0f12"
    return (
        f'<html><body style="margin:0;height:100vh;display:flex;align-items:center;'
        f"justify-content:center;background:{bg};color:{color};"
        f'font-family:-apple-system,Segoe UI,sans-serif;font-size:13px;text-align:center;padding:24px">'
        f"<div><strong>{_NO_MARKET}</strong><br/>{_NO_MARKET_HINT}</div></body></html>"
    )


@router.get("/market_brief")
async def market_brief(
    request: Request,
    market_key: str = Depends(effective_market_key),
    theme: str = Query("dark"),
    service: MarketDataService = Depends(get_service),
) -> HTMLResponse:
    if not _has(market_key):
        return HTMLResponse(content=_prompt_html(theme))
    selected = await service.resolve_market(market_key)
    html = render_market_rules(
        market=selected["market"],
        event=selected["event"],
        condition_id=selected["condition_id"],
        event_id=selected["event_id"],
        theme=theme,
        param_defs=[],
        sync_url="/selection_stream",
        current_market=selected["market_key"],
    )
    return HTMLResponse(content=html)


_STREAM_HEARTBEAT_SECONDS = 10.0


@router.get("/selection_stream")
async def selection_stream() -> StreamingResponse:
    async def events():
        queue = subscribe_selection()
        try:
            yield f"data: {current_selection()}\n\n"
            while not stream_shutdown_started():
                try:
                    market_key = await asyncio.wait_for(queue.get(), timeout=_STREAM_HEARTBEAT_SECONDS)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                if market_key is STREAM_STOP:
                    break
                yield f"data: {market_key}\n\n"
        finally:
            unsubscribe_selection(queue)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _book_levels(levels: Any) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for level in levels or []:
        if isinstance(level, dict):
            out.append((to_float(level.get("price")) * 100, to_float(level.get("size"))))
    return out


@router.get("/orderbook_ladder")
async def orderbook_ladder(
    request: Request,
    market_key: str = Depends(effective_market_key),
    side: str = Query("yes"),
    raw: bool = Query(False),
    theme: str = Query("dark"),
    service: MarketDataService = Depends(get_service),
) -> Any:
    if not _has(market_key):
        return [] if raw else HTMLResponse(content=_prompt_html(theme))
    set_selection(market_key)
    selected = await service.resolve_market(market_key)
    side = "no" if (side or "").lower() == "no" else "yes"
    token = selected["no_token"] if side == "no" else selected["yes_token"]
    book = await service.fetch_orderbook(token)
    if raw:
        return orderbook_rows(book)

    market = selected["market"]
    bids = sorted(_book_levels(book.get("bids")), key=lambda lvl: lvl[0], reverse=True)
    asks = sorted(_book_levels(book.get("asks")), key=lambda lvl: lvl[0])
    last = book.get("last_trade_price")
    last_pct = round(to_float(last) * 100, 1) if last not in (None, "") else None
    outcomes = parse_json_list(market.get("outcomes")) or ["Yes", "No"]
    side_name = outcomes[1] if side == "no" and len(outcomes) > 1 else outcomes[0]
    html = render_ladder(
        title=market.get("groupItemTitle") or market.get("question") or selected["condition_id"],
        subtitle=f"{side_name} book",
        market_label=selected["condition_id"][:14] + "…",
        asks=asks,
        bids=bids,
        last_price=last_pct,
        side=side,
        theme=theme,
    )
    return HTMLResponse(content=html)


@router.get("/selected_trades")
async def selected_trades(
    market_key: str = Depends(effective_market_key),
    limit: int = Query(100, ge=1, le=500),
    service: MarketDataService = Depends(get_service),
) -> list[dict[str, Any]]:
    if not _has(market_key):
        return []
    set_selection(market_key)
    selected = await service.resolve_market(market_key)
    trades = await service.fetch_trades(selected["condition_id"], limit=limit)
    return [trade_row(trade) for trade in trades]


@router.get("/top_holders")
async def top_holders(
    market_key: str = Depends(effective_market_key),
    limit: int = Query(20, ge=1, le=100),
    service: MarketDataService = Depends(get_service),
) -> list[dict[str, Any]]:
    if not _has(market_key):
        return []
    selected = await service.resolve_market(market_key)
    payload = await service.fetch_holders(selected["condition_id"], limit=limit)
    names = parse_json_list(selected["market"].get("outcomes")) or ["Yes", "No"]
    return holder_rows(payload, names)


@router.get("/leaderboard")
async def leaderboard(
    rank_by: str = Query("volume"),
    window: str = Query("7d"),
    limit: int = Query(50, ge=1, le=100),
    service: MarketDataService = Depends(get_service),
) -> list[dict[str, Any]]:
    entries = await service.fetch_leaderboard(rank_by=rank_by, window=window, limit=limit)
    return [leaderboard_row(entry, rank) for rank, entry in enumerate(entries, start=1)]
