from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, Query

from openbb_polymarket.dependencies import get_service, get_stats
from openbb_polymarket.formatting import (
    ALL,
    compact_number,
    parse_market_key,
    timestamp_to_iso,
    to_float,
)
from openbb_polymarket.service import MarketDataService, TOP_HISTORY_OUTCOME_COUNT
from openbb_polymarket.stats import EventStatsCache, _outcome
from openbb_polymarket.transforms import market_row

router = APIRouter()

_HISTORY_FIELD_RE = re.compile(r"[^0-9A-Za-z]+")

_OUTCOME_FIELDS = (
    "name",
    "probability_pct",
    "yes_bid_pct",
    "yes_ask_pct",
    "spread_pct",
    "price_change_pts",
    "volume_total",
    "liquidity",
    "condition_id",
    "close_time",
    "market_key",
)


async def effective_event_id(
    event_id: str = Query(""),
    tag: str = Query(ALL),
    stats: EventStatsCache = Depends(get_stats),
) -> str:
    identifier = (event_id or "").strip()
    return identifier or await stats.default_event_id(tag=tag)


@router.get("/event_metrics")
async def event_metrics(
    event_id: str = Depends(effective_event_id),
    service: MarketDataService = Depends(get_service),
) -> list[dict[str, str]]:
    if not event_id:
        return [{"label": "No active events", "value": "—", "subvalue": "Try another tag"}]
    resolved = await service.resolve_event(event_id=event_id)
    event = resolved["event"]
    rows = [market_row(m, resolved["event_id"]) for m in resolved["markets"]]
    total_volume = sum(row["volume_total"] for row in rows)
    total_liquidity = sum(row["liquidity"] for row in rows)
    top = max(rows, key=lambda row: row["probability_pct"], default=None)
    tags = [t.get("slug") for t in (event.get("tags") or []) if isinstance(t, dict)]

    question = str(event.get("title") or resolved["event_id"])
    return [
        {
            "label": "Event",
            "value": question,
            "subvalue": " · ".join(
                part for part in ((tags[0] if tags else "Polymarket"), f"Event {resolved['event_id']}") if part
            ),
        },
        {"label": "Markets", "value": str(len(rows)), "subvalue": "Outcomes"},
        {
            "label": "Event Volume",
            "value": f"${compact_number(total_volume)}",
            "subvalue": "Across outcomes",
        },
        {
            "label": "Liquidity",
            "value": f"${compact_number(total_liquidity)}",
            "subvalue": "Across outcomes",
        },
        {
            "label": "Top Outcome",
            "value": f"{top['probability_pct']:.1f}%" if top else "N/A",
            "subvalue": top["name"][:48] if top else "No markets returned",
        },
    ]


@router.get("/event_outcomes")
async def event_outcomes(
    event_id: str = Depends(effective_event_id),
    service: MarketDataService = Depends(get_service),
) -> list[dict[str, Any]]:
    if not event_id:
        return []
    resolved = await service.resolve_event(event_id=event_id)
    rows = [market_row(m, resolved["event_id"]) for m in resolved["markets"]]
    active = [r for r in rows if to_float(r["volume_total"]) > 0 or to_float(r["liquidity"]) > 0]
    rows = active or rows
    rows.sort(key=lambda row: (row["volume_24h"], row["volume_total"], row["probability_pct"]), reverse=True)
    return [{field: row.get(field) for field in _OUTCOME_FIELDS} for row in rows]


def _history_selection(history_market_key: Any) -> tuple[str, set[str]]:
    raw_values = history_market_key if isinstance(history_market_key, list) else [history_market_key]
    values = [
        part.strip()
        for value in raw_values
        for part in str(value or "").split(",")
        if part and part.strip()
    ]
    if any(value == ALL for value in values):
        return "all", set()
    condition_ids = {
        parsed["condition_id"]
        for parsed in (parse_market_key(value) for value in values)
        if parsed["condition_id"]
    }
    if condition_ids:
        return "selected", condition_ids
    return "top", set()


def _history_field(name: Any, condition_id: Any, used: set[str]) -> str:
    label = str(name or condition_id or "outcome").strip()
    base = _HISTORY_FIELD_RE.sub("_", label.lower()).strip("_") or "outcome"
    if base[0].isdigit():
        base = f"outcome_{base}"
    field = base
    counter = 2
    while field in used:
        field = f"{base}_{counter}"
        counter += 1
    used.add(field)
    return field


@router.get("/event_history_chart")
async def event_history_chart(
    event_id: str = Depends(effective_event_id),
    history_market_key: list[str] | None = Query(None),
    raw: bool = Query(False),
    service: MarketDataService = Depends(get_service),
) -> Any:
    if not event_id:
        return []
    resolved = await service.resolve_event(event_id=event_id)
    outcomes = [_outcome(m, resolved["event_id"]) for m in resolved["markets"]]
    mode, selected_conditions = _history_selection(history_market_key)

    if mode == "all":
        top_n = len(outcomes)
        pinned: set[str] = set()
    elif mode == "selected":
        pinned = {o["yes_token"] for o in outcomes if o["condition_id"] in selected_conditions}
        top_n = TOP_HISTORY_OUTCOME_COUNT
    else:
        pinned = set()
        top_n = TOP_HISTORY_OUTCOME_COUNT

    histories = await service.outcome_histories(outcomes, top_n=top_n, pinned_tokens=pinned)
    lines = [
        {"name": h["name"], "condition_id": h["condition_id"], "points": h["points"]}
        for h in histories
        if h["points"]
    ]
    used: set[str] = set()
    fields = [_history_field(line["name"], line["condition_id"], used) for line in lines]

    rows_by_time: dict[str, dict[str, Any]] = {}
    for line, field in zip(lines, fields, strict=True):
        for ts, value in line["points"]:
            time = timestamp_to_iso(ts)
            if not time:
                continue
            row = rows_by_time.setdefault(time, {"time": time})
            row[field] = value

    rows: list[dict[str, Any]] = []
    for time in sorted(rows_by_time):
        row = rows_by_time[time]
        for field in fields:
            row.setdefault(field, None)
        rows.append(row)
    return rows
