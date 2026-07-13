from __future__ import annotations

import json
from copy import deepcopy
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from openbb_polymarket.config import ROOT_PATH
from openbb_polymarket.dependencies import get_service, get_stats
from openbb_polymarket.formatting import build_market_key, parse_json_list, pct
from openbb_polymarket.service import MarketDataService, TOP_HISTORY_OUTCOME_COUNT
from openbb_polymarket.stats import EventStatsCache

router = APIRouter()


@lru_cache(maxsize=4)
def _load_manifest(name: str) -> Any:
    with (ROOT_PATH / name).open("r", encoding="utf-8") as handle:
        return json.load(handle)


@router.get("/")
async def root(request: Request) -> dict[str, str]:
    return {
        "status": "ok",
        "app": "Polymarket Market Dashboard",
        "gamma_api": request.app.state.settings.gamma_base_url,
    }


def _is_empty_default(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, (list, tuple, set)):
        return len(value) == 0
    return not str(value).strip()


async def _top_history_market_keys(service: MarketDataService, event_id: str) -> list[str]:
    if not (event_id or "").strip():
        return []
    try:
        resolved = await service.resolve_event(event_id=event_id)
    except HTTPException:
        return []

    def probability(market: dict[str, Any]) -> float:
        prices = parse_json_list(market.get("outcomePrices"))
        return pct(prices[0]) if prices else pct(market.get("lastTradePrice"))

    markets = sorted(resolved["markets"], key=probability, reverse=True)
    return [
        build_market_key(resolved["event_id"], market.get("conditionId", ""))
        for market in markets[:TOP_HISTORY_OUTCOME_COUNT]
        if market.get("conditionId")
    ]


async def _selection_defaults(stats: EventStatsCache, service: MarketDataService) -> dict[str, Any]:
    event_id = await stats.default_event_id()
    market_key = await service.default_market_key(event_id) if event_id else ""
    history = await _top_history_market_keys(service, event_id)
    return {"event_id": event_id, "market_key": market_key, "history_market_key": history}


def _apply_value_defaults(manifest: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    for widget_id, widget in manifest.items():
        if not isinstance(widget, dict):
            continue
        # The browser iframe defaults to the event list; only a click selects an
        # event, so never seed it with a default event_id/market_key.
        if widget_id == "browse_markets":
            continue
        for param in widget.get("params", []):
            name = param.get("paramName")
            if name in defaults and defaults[name] and _is_empty_default(param.get("value")):
                param["value"] = defaults[name]
    return manifest


def _apply_group_defaults(manifest: Any, defaults: dict[str, Any]) -> Any:
    apps = manifest if isinstance(manifest, list) else [manifest]
    for app in apps:
        if not isinstance(app, dict):
            continue
        for group in app.get("groups", []):
            name = group.get("paramName")
            if name in defaults and defaults[name] and _is_empty_default(group.get("defaultValue")):
                group["defaultValue"] = defaults[name]
    return manifest


@router.get("/widgets.json")
async def widgets(
    stats: EventStatsCache = Depends(get_stats),
    service: MarketDataService = Depends(get_service),
) -> JSONResponse:
    manifest = deepcopy(_load_manifest("widgets.json"))
    _apply_value_defaults(manifest, await _selection_defaults(stats, service))
    return JSONResponse(content=manifest)


@router.get("/apps.json")
async def apps(
    stats: EventStatsCache = Depends(get_stats),
    service: MarketDataService = Depends(get_service),
) -> JSONResponse:
    manifest = deepcopy(_load_manifest("apps.json"))
    _apply_group_defaults(manifest, await _selection_defaults(stats, service))
    return JSONResponse(content=manifest)


@router.get("/agents.json")
async def agents() -> JSONResponse:
    return JSONResponse(content={})
