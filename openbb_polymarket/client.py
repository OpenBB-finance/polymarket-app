from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import httpx
from diskcache import Cache
from fastapi import HTTPException

from openbb_polymarket.config import Settings


def _clean_params(params: dict[str, Any] | None) -> dict[str, Any]:
    return {
        key: value
        for key, value in (params or {}).items()
        if value is not None and value != ""
    }


class RateLimiter:
    def __init__(self, rate_per_sec: float) -> None:
        self._rate = max(1.0, rate_per_sec)
        self._tokens = self._rate
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        while True:
            async with self._lock:
                now = time.monotonic()
                self._tokens = min(self._rate, self._tokens + (now - self._updated) * self._rate)
                self._updated = now
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
                wait = (1 - self._tokens) / self._rate
            await asyncio.sleep(wait)


class PolymarketClient:
    def __init__(self, settings: Settings, cache: Cache) -> None:
        self._settings = settings
        self._cache = cache
        self._limiter = RateLimiter(settings.rate_limit_per_sec)
        self._client = httpx.AsyncClient(
            base_url=settings.gamma_base_url,
            headers={"User-Agent": settings.user_agent},
            timeout=settings.http_timeout,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    @staticmethod
    def _cache_key(path: str, params: dict[str, Any]) -> str:
        return "http:" + json.dumps([path, params], sort_keys=True)

    async def get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        ttl: int | None = None,
        *,
        use_cache: bool = True,
    ) -> Any:
        ttl = self._settings.quote_ttl if ttl is None else ttl
        clean = _clean_params(params)
        key = self._cache_key(path, clean)

        if use_cache:
            cached = await asyncio.to_thread(self._cache.get, key)
            if cached is not None:
                return cached

        response = await self._request(path, clean)
        data = response.json()
        if use_cache and ttl > 0:
            await asyncio.to_thread(self._cache.set, key, data, ttl)
        return data

    async def get_keyset(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        items_key: str,
        max_pages: int = 10,
        ttl: int | None = None,
        use_cache: bool = True,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        cursor: str | None = None
        for _ in range(max_pages):
            page_params = dict(params or {})
            if cursor:
                page_params["after_cursor"] = cursor
            data = await self.get(path, page_params, ttl=ttl, use_cache=use_cache)
            page = data.get(items_key) if isinstance(data, dict) else None
            if isinstance(page, list):
                items.extend(item for item in page if isinstance(item, dict))
            cursor = data.get("next_cursor") if isinstance(data, dict) else None
            if not cursor or not page:
                break
        return items

    async def _request(self, path: str, params: dict[str, Any]) -> httpx.Response:
        for attempt in range(3):
            await self._limiter.acquire()
            try:
                response = await self._client.get(path, params=params)
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code
                if status_code == 429 and attempt < 2:
                    retry_after = exc.response.headers.get("Retry-After")
                    delay = float(retry_after) if (retry_after or "").isdigit() else 1.0 * (attempt + 1)
                    await asyncio.sleep(delay)
                    continue
                raise HTTPException(
                    status_code=502 if status_code >= 500 else status_code,
                    detail=f"Polymarket API error for {path}: {exc.response.text[:300]}",
                ) from exc
            except httpx.HTTPError as exc:
                raise HTTPException(
                    status_code=502,
                    detail=f"Polymarket API request failed for {path}: {exc}",
                ) from exc
        raise HTTPException(status_code=502, detail=f"Polymarket API rate limited for {path}")
