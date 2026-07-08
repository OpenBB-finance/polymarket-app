from __future__ import annotations

import asyncio
from typing import Any

from fastapi import HTTPException

from openbb_polymarket.client import PolymarketClient
from openbb_polymarket.config import Settings
from openbb_polymarket.formatting import (
    build_market_key,
    clamp_limit,
    parse_json_list,
    parse_market_key,
    to_float,
)
from openbb_polymarket.stats import EventStatsCache

TOP_HISTORY_OUTCOME_COUNT = 3


def _is_event_id(value: str) -> bool:
    return value.isdigit()


class MarketDataService:
    def __init__(
        self,
        client: PolymarketClient,
        stats: EventStatsCache,
        settings: Settings,
    ) -> None:
        self._client = client
        self._stats = stats
        self._settings = settings

    def _data_url(self, path: str) -> str:
        return f"{self._settings.data_base_url}/{path.lstrip('/')}"

    def _clob_url(self, path: str) -> str:
        return f"{self._settings.clob_base_url}/{path.lstrip('/')}"

    def _leaderboard_url(self, path: str) -> str:
        return f"{self._settings.leaderboard_base_url}/{path.lstrip('/')}"


    async def fetch_event(self, event_id_or_slug: str) -> dict[str, Any]:
        identifier = (event_id_or_slug or "").strip()
        path = f"/events/{identifier}" if _is_event_id(identifier) else f"/events/slug/{identifier}"
        data = await self._client.get(path)
        event = data[0] if isinstance(data, list) and data else data
        if not isinstance(event, dict) or not event.get("id"):
            raise HTTPException(status_code=404, detail=f"Event not found: {identifier}")
        markets = event.get("markets")
        return {
            "event": event,
            "markets": [m for m in (markets or []) if isinstance(m, dict)],
            "event_id": str(event.get("id")),
        }

    async def fetch_market_by_condition(self, condition_id: str) -> dict[str, Any]:
        markets = await self._client.get_keyset(
            "/markets/keyset",
            {"condition_ids": condition_id, "closed": "false", "include_tag": "true"},
            items_key="markets",
            max_pages=1,
        )
        return markets[0] if markets else {}

    async def resolve_event(
        self,
        event_id: str | None = None,
        tag: str | None = None,
    ) -> dict[str, Any]:
        identifier = (event_id or "").strip()
        if not identifier:
            identifier = await self._stats.default_event_id(tag=tag)
        if not identifier:
            raise HTTPException(
                status_code=404,
                detail="No Polymarket events available for the current selection.",
            )
        return await self.fetch_event(identifier)

    async def resolve_market(self, market_key: str | None) -> dict[str, Any]:
        parsed = parse_market_key(market_key)
        event_id = parsed["event_id"]
        condition_id = parsed["condition_id"]

        event: dict[str, Any] = {}
        markets: list[dict[str, Any]] = []
        if event_id:
            try:
                resolved = await self.resolve_event(event_id=event_id)
                event = resolved["event"]
                markets = resolved["markets"]
            except HTTPException:
                event, markets = {}, []

        market: dict[str, Any] = {}
        if condition_id:
            market = next(
                (m for m in markets if m.get("conditionId") == condition_id), {}
            )
        if not market and condition_id:
            market = await self.fetch_market_by_condition(condition_id)
        if not market and markets:
            market = max(markets, key=lambda m: to_float(m.get("volume24hr")), default={})

        if not market:
            raise HTTPException(
                status_code=404, detail=f"Market not found for key: {market_key}"
            )

        condition_id = market.get("conditionId", condition_id)
        tokens = parse_json_list(market.get("clobTokenIds"))
        if not event:
            embedded = market.get("events") or []
            event = embedded[0] if embedded and isinstance(embedded[0], dict) else {}
            event_id = event_id or str(event.get("id") or "")

        return {
            "market": market,
            "event": event,
            "event_id": event_id or str(event.get("id") or ""),
            "condition_id": condition_id,
            "yes_token": tokens[0] if len(tokens) > 0 else "",
            "no_token": tokens[1] if len(tokens) > 1 else "",
            "market_key": build_market_key(event_id or str(event.get("id") or ""), condition_id),
        }

    async def default_market_key(self, event_id: str) -> str:
        if not (event_id or "").strip():
            return ""
        try:
            resolved = await self.resolve_event(event_id=event_id)
        except HTTPException:
            return ""
        markets = sorted(
            resolved["markets"], key=lambda m: to_float(m.get("volume24hr")), reverse=True
        )
        if not markets:
            return ""
        return build_market_key(resolved["event_id"], markets[0].get("conditionId", ""))


    async def fetch_orderbook(self, token_id: str) -> dict[str, Any]:
        if not token_id:
            return {}
        try:
            data = await self._client.get(
                self._clob_url("/book"), {"token_id": token_id}, ttl=self._settings.realtime_ttl
            )
        except HTTPException:
            return {}
        return data if isinstance(data, dict) else {}

    async def fetch_trades(self, condition_id: str, limit: int = 100) -> list[dict[str, Any]]:
        if not condition_id:
            return []
        data = await self._client.get(
            self._data_url("/trades"),
            {"market": condition_id, "limit": clamp_limit(limit, maximum=500)},
            ttl=self._settings.realtime_ttl,
        )
        return data if isinstance(data, list) else []

    async def fetch_holders(self, condition_id: str, limit: int = 20) -> list[dict[str, Any]]:
        if not condition_id:
            return []
        data = await self._client.get(
            self._data_url("/holders"),
            {"market": condition_id, "limit": clamp_limit(limit, maximum=100)},
            ttl=self._settings.quote_ttl,
        )
        return data if isinstance(data, list) else []

    async def fetch_leaderboard(
        self, rank_by: str = "volume", window: str = "7d", limit: int = 50
    ) -> list[dict[str, Any]]:
        metric = "profit" if (rank_by or "").lower() in ("pnl", "profit") else "volume"
        window = window if window in ("1d", "7d", "30d", "all") else "7d"
        try:
            data = await self._client.get(
                self._leaderboard_url(f"/{metric}"),
                {"window": window, "limit": clamp_limit(limit, maximum=100)},
                ttl=self._settings.quote_ttl,
            )
        except HTTPException:
            return []
        return data if isinstance(data, list) else []

    async def fetch_prices_history(
        self, token_id: str, interval: str = "1m", fidelity: int = 60
    ) -> list[tuple[int, float]]:
        if not token_id:
            return []
        interval = interval if interval in ("1h", "6h", "1d", "1w", "1m", "max") else "1m"
        params = {"market": token_id, "interval": interval, "fidelity": fidelity}
        try:
            data = await self._client.get(self._clob_url("/prices-history"), params, ttl=30)
        except HTTPException:
            return []
        history = data.get("history") if isinstance(data, dict) else None
        out: list[tuple[int, float]] = []
        for point in history or []:
            ts = point.get("t")
            price = point.get("p")
            if ts is not None and price is not None:
                out.append((int(ts), round(to_float(price) * 100, 2)))
        return out

    async def outcome_histories(
        self,
        outcomes: list[dict[str, Any]],
        top_n: int = TOP_HISTORY_OUTCOME_COUNT,
        pinned_tokens: set[str] | None = None,
        interval: str = "1m",
        fidelity: int = 60,
    ) -> list[dict[str, Any]]:
        ranked = sorted(outcomes, key=lambda o: to_float(o.get("probability_pct")), reverse=True)
        chosen = ranked[:top_n]
        chosen_tokens = {o.get("yes_token") for o in chosen}
        for outcome in outcomes:
            token = outcome.get("yes_token")
            if pinned_tokens and token in pinned_tokens and token not in chosen_tokens:
                chosen.append(outcome)
                chosen_tokens.add(token)

        max_concurrent = max(2, min(16, int(self._settings.rate_limit_per_sec * 2)))
        limiter = asyncio.Semaphore(max_concurrent)

        async def history(outcome: dict[str, Any]) -> dict[str, Any]:
            async with limiter:
                points = await self.fetch_prices_history(
                    outcome.get("yes_token", ""), interval=interval, fidelity=fidelity
                )
            return {
                "name": outcome.get("name", ""),
                "token": outcome.get("yes_token", ""),
                "condition_id": outcome.get("condition_id", ""),
                "points": [[ts, val] for ts, val in points],
            }

        return list(await asyncio.gather(*[history(o) for o in chosen]))


    async def search_events(
        self,
        query: str,
        status: str = "active",
        tag: str | None = None,
        limit_per_type: int = 40,
    ) -> dict[str, Any]:
        query = (query or "").strip()
        if not query:
            return {"events": [], "tags": [], "pagination": {}}
        params: dict[str, Any] = {
            "q": query,
            "limit_per_type": clamp_limit(limit_per_type, maximum=100),
            "events_status": status,
            "search_tags": "true",
        }
        if (tag or "").strip():
            params["events_tag"] = tag
        data = await self._client.get("/public-search", params, ttl=self._settings.quote_ttl)
        if not isinstance(data, dict):
            return {"events": [], "tags": [], "pagination": {}}
        return {
            "events": [e for e in (data.get("events") or []) if isinstance(e, dict)],
            "tags": [t for t in (data.get("tags") or []) if isinstance(t, dict)],
            "pagination": data.get("pagination") or {},
        }
