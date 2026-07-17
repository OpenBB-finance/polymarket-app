from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from openbb_polymarket.dependencies import get_service, get_stats
from openbb_polymarket.formatting import ALL, norm_tag, to_float
from openbb_polymarket.service import MarketDataService, TOP_HISTORY_OUTCOME_COUNT
from openbb_polymarket.stats import EventStatsCache

router = APIRouter()

Option = dict[str, Any]


def _truncate(text: str, length: int) -> str:
    text = text or ""
    return text if len(text) <= length else text[: length - 1] + "…"


async def _tag_options(stats: EventStatsCache) -> list[Option]:
    options: list[Option] = [{"label": "All tags", "value": ALL}]
    for entry in await stats.tags():
        options.append(
            {
                "label": f"{entry['label']} ({entry['event_count']})",
                "value": entry["slug"],
            }
        )
    return options


async def _event_options(stats: EventStatsCache, tag: str) -> list[Option]:
    events = await stats.discover_events(tag=tag, limit=250)
    options: list[Option] = []
    for event in events:
        event_id = event.get("event_id", "")
        if not event_id:
            continue
        options.append(
            {"label": _truncate(event.get("title") or event_id, 100), "value": event_id}
        )
    return options


async def _market_options(
    service: MarketDataService,
    event_id: str,
    market_key: str,
    include_all: bool = False,
    include_top: bool = False,
    sort: str = "",
) -> list[Option]:
    options: list[Option] = [{"label": "All outcomes", "value": ALL}] if include_all else []
    ticker = (event_id or "").strip()
    if not ticker:
        from openbb_polymarket.formatting import parse_market_key

        ticker = parse_market_key(market_key)["event_id"]
    if not ticker:
        return options
    resolved = await service.resolve_event(event_id=ticker)
    markets = resolved["markets"]
    from openbb_polymarket.formatting import build_market_key, parse_json_list, pct

    def probability(market: dict[str, Any]) -> float:
        prices = parse_json_list(market.get("outcomePrices"))
        return pct(prices[0]) if prices else pct(market.get("lastTradePrice"))

    def volume(market: dict[str, Any]) -> float:
        return to_float(market.get("volume24hr"))

    def active(market: dict[str, Any]) -> bool:
        vol = to_float(market.get("volumeNum") or market.get("volume"))
        liq = to_float(market.get("liquidityNum") or market.get("liquidity"))
        return vol > 0 or liq > 0

    markets = [m for m in markets if active(m)] or markets
    probability_mode = include_top or sort == "probability"
    sort_key = probability if probability_mode else volume
    ranked = sorted(markets, key=sort_key, reverse=True)
    selected_limit = TOP_HISTORY_OUTCOME_COUNT if probability_mode else 0
    selected_count = 0
    seen: set[str] = set()
    for market in ranked[:200]:
        condition_id = market.get("conditionId", "")
        if not condition_id or condition_id in seen:
            continue
        seen.add(condition_id)
        label_text = market.get("groupItemTitle") or market.get("question") or condition_id
        option: Option = {
            "label": f"{_truncate(label_text, 80)} ({probability(market):.0f}%)",
            "value": build_market_key(resolved["event_id"], condition_id),
        }
        if selected_count < selected_limit:
            option["selected"] = True
            selected_count += 1
        options.append(option)
    return options


@router.get("/options")
@router.get("/options/{group_id}")
async def options(
    group_id: str = "",
    field: str = Query(""),
    tag: str = Query(ALL),
    event_id: str = Query(""),
    market_key: str = Query(""),
    include_all: bool = Query(False),
    include_top: bool = Query(False),
    sort: str = Query(""),
    stats: EventStatsCache = Depends(get_stats),
    service: MarketDataService = Depends(get_service),
) -> list[Option]:
    field = field or group_id.removesuffix("-options") or "tag"
    tag = norm_tag(tag) or ALL
    if field == "event_id":
        return await _event_options(stats, tag)
    if field in ("market_key", "history_market_key"):
        return await _market_options(service, event_id, market_key, include_all, include_top, sort)
    return await _tag_options(stats)
