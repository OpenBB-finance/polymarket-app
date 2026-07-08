from __future__ import annotations

import asyncio
import time
from typing import Any

from diskcache import Cache

from openbb_polymarket.client import PolymarketClient
from openbb_polymarket.config import Settings
from openbb_polymarket.formatting import (
    build_market_key,
    iso_to_display,
    norm_tag,
    parse_iso_time,
    parse_json_list,
    pct,
    quantity,
    to_float,
)

SORT_FIELDS = {
    "trending": ("volume_24h", True),
    "volume": ("volume_total", True),
    "liquidity": ("liquidity", True),
    "open_interest": ("open_interest", True),
    "volatile": ("volatility", True),
    "new": ("start_ts", True),
    "ending_soon": ("end_ts", False),
    "fifty_fifty": ("fifty", False),
}


def _terms(search: str) -> list[str]:
    return [t for t in (search or "").lower().split() if t]


def _haystack(event: dict[str, Any]) -> str:
    return " ".join(
        str(event.get(field, ""))
        for field in ("title", "description", "slug")
    ).lower() + " " + " ".join(event.get("tag_slugs") or [])


def _outcome(market: dict[str, Any], event_id: str) -> dict[str, Any]:
    prices = parse_json_list(market.get("outcomePrices"))
    tokens = parse_json_list(market.get("clobTokenIds"))
    yes_price = prices[0] if prices else market.get("lastTradePrice")
    condition_id = market.get("conditionId", "")
    return {
        "name": market.get("groupItemTitle") or market.get("question") or condition_id,
        "question": market.get("question", ""),
        "condition_id": condition_id,
        "yes_token": tokens[0] if len(tokens) > 0 else "",
        "no_token": tokens[1] if len(tokens) > 1 else "",
        "probability_pct": pct(yes_price),
        "yes_bid_pct": pct(market.get("bestBid")),
        "yes_ask_pct": pct(market.get("bestAsk")),
        "spread_pct": pct(market.get("spread")),
        "price_change_pts": pct(market.get("oneDayPriceChange")),
        "volume_24h": quantity(market.get("volume24hr")),
        "volume_total": quantity(market.get("volumeNum") or market.get("volume")),
        "liquidity": quantity(market.get("liquidityNum") or market.get("liquidity")),
        "image": market.get("icon") or market.get("image") or "",
        "market_key": build_market_key(event_id, condition_id),
        "end_date": market.get("endDate", ""),
    }


def flatten_event(raw: dict[str, Any], tag_labels: dict[str, str] | None = None) -> dict[str, Any] | None:
    event_id = str(raw.get("id") or "")
    if not event_id:
        return None
    tags = []
    for tag in raw.get("tags") or []:
        if not isinstance(tag, dict):
            continue
        slug = str(tag.get("slug") or "").strip()
        if not slug:
            continue
        if tag_labels is not None:
            tag_labels.setdefault(slug, str(tag.get("label") or slug))
        tags.append(slug)
    outcomes = [
        _outcome(market, event_id)
        for market in (raw.get("markets") or [])
        if isinstance(market, dict) and market.get("conditionId")
    ]
    if not outcomes:
        return None
    start_dt = parse_iso_time(raw.get("startDate"))
    end_dt = parse_iso_time(raw.get("endDate"))
    volatility = max((abs(o["price_change_pts"]) for o in outcomes), default=0.0)
    fifty = min((abs(o["probability_pct"] - 50) for o in outcomes), default=50.0)
    return {
        "event_id": event_id,
        "slug": raw.get("slug", ""),
        "title": raw.get("title", ""),
        "description": raw.get("description", ""),
        "image": raw.get("image") or raw.get("icon") or "",
        "tag_slugs": tags,
        "volume_24h": quantity(raw.get("volume24hr")),
        "volume_total": quantity(raw.get("volume")),
        "liquidity": quantity(raw.get("liquidity")),
        "open_interest": quantity(raw.get("openInterest")),
        "featured": bool(raw.get("featured")),
        "close_time": iso_to_display(raw.get("endDate")),
        "start_ts": start_dt.timestamp() if start_dt else None,
        "end_ts": end_dt.timestamp() if end_dt else None,
        "volatility": round(volatility, 2),
        "fifty": round(fifty, 2),
        "outcomes": outcomes,
        "market_count": len(outcomes),
    }


_SNAPSHOT_KEY = "stats:snapshot"
_SCAN_LOCK_KEY = "stats:scanning"


class EventStatsCache:
    def __init__(self, client: PolymarketClient, settings: Settings, cache: Cache) -> None:
        self._client = client
        self._settings = settings
        self._cache = cache
        self._lock = asyncio.Lock()
        self._loaded = False
        self._created = 0.0
        self._events: list[dict[str, Any]] = []
        self._tag_labels: dict[str, str] = {}

    def _fresh(self) -> bool:
        return self._loaded and (time.time() - self._created < self._settings.stats_ttl)

    def _apply(self, snapshot: dict[str, Any]) -> None:
        self._events = snapshot["events"]
        self._tag_labels = snapshot["tag_labels"]
        self._created = snapshot["created"]
        self._loaded = True

    def _snapshot_if_fresh(self, snapshot: Any) -> bool:
        if isinstance(snapshot, dict) and time.time() - snapshot.get("created", 0) < self._settings.stats_ttl:
            self._apply(snapshot)
            return True
        return False

    async def ensure_fresh(self) -> None:
        if self._fresh():
            return
        async with self._lock:
            if self._fresh():
                return
            if self._snapshot_if_fresh(await asyncio.to_thread(self._cache.get, _SNAPSHOT_KEY)):
                return
            claimed = await asyncio.to_thread(
                self._cache.add, _SCAN_LOCK_KEY, True, self._settings.stats_scan_lock_ttl
            )
            if not claimed and await self._await_snapshot():
                return
            try:
                await self._scan()
            finally:
                if claimed:
                    await asyncio.to_thread(self._cache.delete, _SCAN_LOCK_KEY)

    async def _await_snapshot(self) -> bool:
        for _ in range(self._settings.stats_scan_lock_ttl):
            await asyncio.sleep(1.0)
            if self._snapshot_if_fresh(await asyncio.to_thread(self._cache.get, _SNAPSHOT_KEY)):
                return True
            if not await asyncio.to_thread(self._cache.get, _SCAN_LOCK_KEY):
                return False
        return False

    async def _scan(self) -> None:
        raw_events = await self._client.get_keyset(
            "/events/keyset",
            {
                "closed": "false",
                "order": "volume24hr",
                "ascending": "false",
                "limit": self._settings.stats_scan_limit,
            },
            items_key="events",
            max_pages=self._settings.stats_scan_max_pages,
            use_cache=False,
        )
        events: list[dict[str, Any]] = []
        tag_labels: dict[str, str] = {}
        for raw in raw_events:
            record = flatten_event(raw, tag_labels)
            if record is not None:
                events.append(record)
        snapshot = {"events": events, "tag_labels": tag_labels, "created": time.time()}
        self._apply(snapshot)
        await asyncio.to_thread(self._cache.set, _SNAPSHOT_KEY, snapshot, self._settings.stats_ttl)

    def _within_window(self, event: dict[str, Any], cutoff: float | None) -> bool:
        if cutoff is None:
            return True
        end_ts = event.get("end_ts")
        return end_ts is not None and end_ts <= cutoff

    @staticmethod
    def _is_open(event: dict[str, Any], now: float) -> bool:
        end_ts = event.get("end_ts")
        return end_ts is None or end_ts > now

    async def events(
        self,
        tag: str | None = None,
        close_within_days: int | None = None,
    ) -> list[dict[str, Any]]:
        await self.ensure_fresh()
        tag = norm_tag(tag)
        now = time.time()
        cutoff = None if close_within_days is None else now + close_within_days * 86400
        rows = self._events
        if tag:
            rows = [e for e in rows if tag in (e.get("tag_slugs") or [])]
        return [e for e in rows if self._is_open(e, now) and self._within_window(e, cutoff)]

    async def tags(self) -> list[dict[str, Any]]:
        await self.ensure_fresh()
        stats: dict[str, dict[str, float]] = {}
        for event in self._events:
            for slug in event.get("tag_slugs") or []:
                bucket = stats.setdefault(
                    slug, {"event_count": 0.0, "volume_24h": 0.0, "volume_total": 0.0}
                )
                bucket["event_count"] += 1
                bucket["volume_24h"] += event["volume_24h"]
                bucket["volume_total"] += event["volume_total"]
        return [
            {
                "slug": slug,
                "label": self._tag_labels.get(slug, slug),
                "event_count": int(values["event_count"]),
                "volume_24h": round(values["volume_24h"], 2),
                "volume_total": round(values["volume_total"], 2),
            }
            for slug, values in sorted(
                stats.items(), key=lambda kv: (-kv[1]["volume_24h"], kv[0])
            )
        ]

    async def by_tag(self, close_within_days: int | None = None) -> list[dict[str, Any]]:
        rows = await self.events(close_within_days=close_within_days)
        stats: dict[str, dict[str, float]] = {}
        for event in rows:
            for slug in event.get("tag_slugs") or []:
                bucket = stats.setdefault(
                    slug,
                    {"volume_24h": 0.0, "volume_total": 0.0, "open_interest": 0.0, "event_count": 0.0},
                )
                bucket["volume_24h"] += event["volume_24h"]
                bucket["volume_total"] += event["volume_total"]
                bucket["open_interest"] += event["open_interest"]
                bucket["event_count"] += 1
        return [
            {
                "slug": slug,
                "label": self._tag_labels.get(slug, slug),
                **{k: round(v, 2) for k, v in values.items()},
            }
            for slug, values in stats.items()
        ]

    async def default_event_id(self, tag: str | None = None) -> str:
        events = await self.discover_events(tag=tag, limit=1)
        return events[0]["event_id"] if events else ""

    async def discover_events(
        self,
        tag: str | None = None,
        search: str = "",
        sort: str = "volume",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        events = await self.events(tag=tag)
        terms = _terms(search)
        if terms:
            events = [e for e in events if all(t in _haystack(e) for t in terms)]

        field, descending = SORT_FIELDS.get(sort, SORT_FIELDS["volume"])
        events = self._sorted(events, field, descending)[:limit]
        rows = []
        for event in events:
            top = max(event["outcomes"], key=lambda o: o["volume_total"], default={})
            rows.append(
                {
                    "event_id": event["event_id"],
                    "slug": event["slug"],
                    "title": event["title"],
                    "tags": ", ".join(event.get("tag_slugs") or []),
                    "market_count": event["market_count"],
                    "volume_24h": event["volume_24h"],
                    "volume_total": event["volume_total"],
                    "liquidity": event["liquidity"],
                    "open_interest": event["open_interest"],
                    "close_time": event["close_time"],
                    "leading_outcome": top.get("name", ""),
                    "leading_pct": top.get("probability_pct", 0.0),
                }
            )
        return rows

    async def browse_events(
        self,
        tag: str | None = None,
        search: str = "",
        close_within_days: int | None = None,
        sort: str = "trending",
        reverse: bool = False,
        outcomes_per_event: int = 4,
        limit: int = 40,
    ) -> list[dict[str, Any]]:
        events = await self.events(tag=tag, close_within_days=close_within_days)
        terms = _terms(search)
        if terms:
            events = [e for e in events if all(t in _haystack(e) for t in terms)]

        field, descending = SORT_FIELDS.get(sort, SORT_FIELDS["trending"])
        if reverse:
            descending = not descending
        events = self._sorted(events, field, descending)[:limit]

        cards = []
        for event in events:
            outcomes = sorted(
                event["outcomes"], key=lambda o: to_float(o["volume_total"]), reverse=True
            )[:outcomes_per_event]
            cards.append({**event, "outcomes": outcomes})
        return cards

    @staticmethod
    def _sorted(events: list[dict[str, Any]], field: str, descending: bool) -> list[dict[str, Any]]:
        def key(event: dict[str, Any]) -> float:
            value = event.get(field)
            if value is None:
                return float("-inf") if descending else float("inf")
            return value

        return sorted(events, key=key, reverse=descending)
