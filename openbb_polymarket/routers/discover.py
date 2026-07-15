from __future__ import annotations

import time
from typing import Any
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse

from openbb_polymarket import charts
from openbb_polymarket.browse import render_browse
from openbb_polymarket.dependencies import get_service, get_stats
from openbb_polymarket.event_page import render_event_page
from openbb_polymarket.formatting import ALL, clamp_limit, norm_tag
from openbb_polymarket.service import MarketDataService
from openbb_polymarket.stats import EventStatsCache, SORT_FIELDS, flatten_event

router = APIRouter()

_METRIC_LABELS = {
    "volume_24h": "24h Volume (USD)",
    "open_interest": "Open Interest (USD)",
    "volume_total": "Total Volume (USD)",
}

_VALID_SORTS = set(SORT_FIELDS)


def _event_row(event: dict[str, Any]) -> dict[str, Any]:
    top = event["outcomes"][0] if event.get("outcomes") else {}
    return {
        "title": event.get("title", ""),
        "tags": ", ".join(event.get("tag_slugs") or []),
        "event_id": event.get("event_id", ""),
        "market_count": event.get("market_count", 0),
        "leading_outcome": top.get("name", ""),
        "leading_pct": top.get("probability_pct"),
        "volume_24h": event.get("volume_24h", 0),
        "volume_total": event.get("volume_total", 0),
        "liquidity": event.get("liquidity", 0),
        "open_interest": event.get("open_interest", 0),
        "close_time": event.get("close_time", ""),
        "market_key": top.get("market_key", ""),
    }


def _days(close_within: str) -> int | None:
    value = (close_within or "").strip()
    if not value or value in ("any", "all", "0"):
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _coerce(value: Any, options: list[dict[str, Any]], fallback: str) -> str:
    text = "" if value is None else str(value)
    return text if any(o["value"] == text for o in options) else fallback


async def _browse_param_defs(
    stats: EventStatsCache,
    *,
    tag: str = "All",
    search: str = "",
    sort: str = "trending",
    close_within: str = "",
    reverse: bool = False,
    limit: int = 40,
    offset: int = 0,
) -> list[dict[str, Any]]:
    tag_options = [{"label": "All tags", "value": "All"}]
    tag_options += [{"label": f"{t['label']} ({t['event_count']})", "value": t["slug"]} for t in await stats.tags()]
    sort_options = [
        {"label": "Trending", "value": "trending"},
        {"label": "Volume", "value": "volume"},
        {"label": "Liquidity", "value": "liquidity"},
        {"label": "Open Interest", "value": "open_interest"},
        {"label": "Volatile", "value": "volatile"},
        {"label": "New", "value": "new"},
        {"label": "Ending soon", "value": "ending_soon"},
        {"label": "50-50", "value": "fifty_fifty"},
    ]
    close_options = [
        {"label": "Any time", "value": ""},
        {"label": "24 hours", "value": "1"},
        {"label": "7 days", "value": "7"},
        {"label": "30 days", "value": "30"},
        {"label": "90 days", "value": "90"},
    ]
    return [
        {"paramName": "search", "label": "Search", "type": "text", "value": search or ""},
        {
            "paramName": "tag",
            "label": "Tag",
            "type": "text",
            "value": _coerce(tag, tag_options, "All"),
            "options": tag_options,
        },
        {
            "paramName": "sort",
            "label": "Sort",
            "type": "text",
            "value": _coerce(sort, sort_options, "trending"),
            "options": sort_options,
        },
        {
            "paramName": "close_within",
            "label": "Ends Within",
            "type": "text",
            "value": _coerce(close_within, close_options, ""),
            "options": close_options,
        },
        {"paramName": "reverse", "label": "Reverse sort", "type": "boolean", "value": "true" if reverse else "false"},
        {
            "paramName": "limit",
            "label": "Per page",
            "type": "number",
            "value": str(limit),
            "min": 1,
            "max": 150,
            "step": 10,
        },
        {
            "paramName": "offset",
            "label": "Offset",
            "type": "number",
            "value": str(max(0, offset)),
            "min": 0,
            "step": limit,
        },
    ]


async def _volume_by_event(stats: EventStatsCache, slug: str, metric: str, close_within: str) -> list[dict[str, Any]]:
    events = await stats.events(tag=slug, close_within_days=_days(close_within))
    events = sorted(events, key=lambda e: e.get(metric) or 0, reverse=True)[:60]
    tag_label = next((t["label"] for t in await stats.tags() if t["slug"] == slug), slug)
    return [
        {
            "label": tag_label,
            "tag": slug,
            "event_title": event.get("title", ""),
            "volume_24h": event.get("volume_24h", 0),
            "volume_total": event.get("volume_total", 0),
            "open_interest": event.get("open_interest", 0),
            "event_count": event.get("market_count", 0),
        }
        for event in events
    ]


@router.get("/volume_by_tag")
async def volume_by_tag(
    metric: str = Query("volume_24h"),
    close_within: str = Query(""),
    tag: str = Query(ALL),
    stats: EventStatsCache = Depends(get_stats),
) -> Any:
    metric = metric if metric in _METRIC_LABELS else "volume_24h"
    slug = norm_tag(tag)
    if slug:
        return await _volume_by_event(stats, slug, metric, close_within)
    rows = await stats.by_tag(close_within_days=_days(close_within))
    rows = sorted(rows, key=lambda r: r.get(metric, 0), reverse=True)[:30]
    return [{**row, "tag": row.get("slug", ""), "event_title": ""} for row in rows]


async def _browse_cards(
    stats: EventStatsCache,
    service: MarketDataService,
    *,
    tag: str,
    search: str,
    close_within: str,
    sort: str,
    reverse: bool,
    limit: int,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    if search.strip():
        found = await service.search_events(search, tag=norm_tag(tag) or None)
        cards = [flatten_event(raw) for raw in found["events"]]
        now = time.time()
        cutoff = None if _days(close_within) is None else now + _days(close_within) * 86400
        cards = [
            c for c in cards
            if c
            and (c.get("end_ts") is None or c["end_ts"] > now)
            and (cutoff is None or (c.get("end_ts") is not None and c["end_ts"] <= cutoff))
        ]
        field, descending = SORT_FIELDS.get(sort, SORT_FIELDS["trending"])
        if reverse:
            descending = not descending
        cards = EventStatsCache._sorted(cards, field, descending)
        total = len(cards)
        cards = cards[max(0, offset): max(0, offset) + limit]
        for card in cards:
            card["outcomes"] = sorted(card["outcomes"], key=lambda o: o["probability_pct"], reverse=True)[:4]
        return cards, total
    return await stats.browse_events(
        tag=tag, close_within_days=_days(close_within), sort=sort,
        reverse=reverse, limit=limit, offset=offset,
    )


@router.get("/browse_markets")
async def browse_markets(
    request: Request,
    tag: str = Query("All"),
    search: str = Query("", max_length=120),
    sort: str = Query("trending"),
    close_within: str = Query(""),
    event_id: str = Query(""),
    market_key: str = Query(""),
    view: str = Query(""),
    reverse: bool = Query(False),
    limit: int = Query(40, ge=1, le=150),
    offset: int = Query(0, ge=0),
    theme: str = Query("dark"),
    raw: bool = Query(False),
    stats: EventStatsCache = Depends(get_stats),
    service: MarketDataService = Depends(get_service),
) -> Any:
    sort = sort if sort in _VALID_SORTS else "trending"
    limit = clamp_limit(limit, maximum=150)
    filters = {
        "tag": tag,
        "search": search,
        "sort": sort,
        "close_within": close_within,
        "reverse": "true" if reverse else "",
        "theme": theme,
    }
    back_qs = urlencode({k: v for k, v in filters.items() if v and v != ALL})

    if not raw and view.strip():
        return await _event_detail_response(
            request, service, event_id=view.strip(), market_key=market_key,
            theme=theme, back=back_qs, filters=filters,
        )

    cards, total = await _browse_cards(
        stats,
        service,
        tag=tag,
        search=search,
        close_within=close_within,
        sort=sort,
        reverse=reverse,
        limit=limit,
        offset=offset,
    )
    rows = [_event_row(card) for card in cards]
    if raw:
        return rows

    html = render_browse(
        cards,
        rows=rows,
        param_defs=await _browse_param_defs(
            stats,
            tag=tag,
            search=search,
            sort=sort,
            close_within=close_within,
            reverse=reverse,
            limit=limit,
            offset=offset,
        ),
        total=total,
        search=search,
        theme=theme,
        back_qs=back_qs,
        limit=limit,
        offset=offset,
    )
    return HTMLResponse(content=html)


async def _event_figure(service: MarketDataService, resolved: dict[str, Any], theme: str) -> dict[str, Any] | None:
    from openbb_polymarket.stats import _outcome

    outcomes = [_outcome(m, resolved["event_id"]) for m in resolved["markets"]]
    histories = await service.outcome_histories(outcomes)
    lines = [{"name": h["name"], "points": h["points"]} for h in histories if h["points"]]
    return charts.outcome_history(lines, theme) if lines else None


async def _event_detail_response(
    request: Request,
    service: MarketDataService,
    *,
    event_id: str,
    market_key: str,
    theme: str,
    back: str,
    filters: dict[str, Any] | None = None,
) -> HTMLResponse:
    from openbb_polymarket.formatting import parse_market_key

    identifier = (event_id or "").strip() or parse_market_key(market_key)["event_id"]
    resolved = await service.resolve_event(event_id=identifier or None)
    figure = await _event_figure(service, resolved, theme)
    back_url = f"/browse_markets?{back}" if back else f"/browse_markets?theme={theme}"
    poll_url = f"/event_chart?event_id={quote(resolved['event_id'])}&theme={quote(theme)}"
    html = render_event_page(
        event=resolved["event"],
        markets=resolved["markets"],
        event_id=resolved["event_id"],
        theme=theme,
        back_url=back_url,
        history_figure=figure,
        poll_url=poll_url,
        market_key=market_key,
        filters=filters or {},
    )
    return HTMLResponse(content=html)


@router.get("/event_details")
async def event_details(
    request: Request,
    event_id: str = Query(""),
    market_key: str = Query(""),
    theme: str = Query("dark"),
    back: str = Query(""),
    service: MarketDataService = Depends(get_service),
) -> HTMLResponse:
    return await _event_detail_response(
        request, service, event_id=event_id, market_key=market_key, theme=theme, back=back,
    )


@router.get("/event_chart")
async def event_chart(
    event_id: str = Query(""),
    theme: str = Query("dark"),
    service: MarketDataService = Depends(get_service),
) -> Any:
    identifier = (event_id or "").strip()
    if not identifier:
        return JSONResponse(content=charts.empty_figure("No event selected", theme))
    resolved = await service.resolve_event(event_id=identifier)
    figure = await _event_figure(service, resolved, theme)
    return JSONResponse(content=figure or charts.empty_figure("No price history available", theme))
