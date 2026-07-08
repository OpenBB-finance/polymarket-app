from __future__ import annotations

from pathlib import Path

from diskcache import Cache

from openbb_polymarket.config import Settings


def create_cache(settings: Settings) -> Cache:
    Path(settings.cache_dir).mkdir(parents=True, exist_ok=True)
    return Cache(
        directory=settings.cache_dir,
        size_limit=settings.cache_size_limit,
        eviction_policy="least-recently-used",
        cull_limit=64,
        statistics=False,
    )
