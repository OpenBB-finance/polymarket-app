from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT_PATH = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT_PATH / ".env")
except ImportError:
    pass

DEFAULT_CORS_ORIGINS = (
    "https://pro.openbb.co",
    "https://pro.openbb.dev",
    "https://backends.openbb.co",
    "https://backends.openbb.dev",
    "https://excel.openbb.co",
    "https://excel.openbb.dev",
    "tauri://localhost",
    "http://localhost:1420",
    "http://localhost:7779",
    "https://127.0.0.1:7779",
)


@dataclass(frozen=True)
class Settings:
    gamma_base_url: str = "https://gamma-api.polymarket.com"
    data_base_url: str = "https://data-api.polymarket.com"
    clob_base_url: str = "https://clob.polymarket.com"
    leaderboard_base_url: str = "https://lb-api.polymarket.com"

    user_agent: str = "OpenBB-Polymarket-Market-Dashboard/1.0"
    http_timeout: float = 20.0
    rate_limit_per_sec: float = 8.0

    quote_ttl: int = 30
    realtime_ttl: int = 10
    taxonomy_ttl: int = 600

    cache_dir: str = str(ROOT_PATH / ".cache")
    cache_size_limit: int = 1_073_741_824

    stats_ttl: int = 600
    stats_scan_max_pages: int = 12
    stats_scan_limit: int = 500
    stats_scan_lock_ttl: int = 180

    cors_origins: tuple[str, ...] = field(default=DEFAULT_CORS_ORIGINS)

    @classmethod
    def from_env(cls) -> "Settings":
        def _int(name: str, default: int) -> int:
            try:
                return int(os.getenv(name, str(default)))
            except (TypeError, ValueError):
                return default

        return cls(
            gamma_base_url=os.getenv("POLYMARKET_GAMMA_BASE_URL", cls.gamma_base_url).rstrip("/"),
            data_base_url=os.getenv("POLYMARKET_DATA_BASE_URL", cls.data_base_url).rstrip("/"),
            clob_base_url=os.getenv("POLYMARKET_CLOB_BASE_URL", cls.clob_base_url).rstrip("/"),
            leaderboard_base_url=os.getenv("POLYMARKET_LEADERBOARD_BASE_URL", cls.leaderboard_base_url).rstrip("/"),
            http_timeout=float(os.getenv("POLYMARKET_HTTP_TIMEOUT", cls.http_timeout)),
            rate_limit_per_sec=float(os.getenv("POLYMARKET_RATE_LIMIT_PER_SEC", cls.rate_limit_per_sec)),
            cache_dir=os.getenv("POLYMARKET_CACHE_DIR", cls.cache_dir),
            cache_size_limit=_int("POLYMARKET_CACHE_SIZE_LIMIT", cls.cache_size_limit),
            quote_ttl=_int("POLYMARKET_QUOTE_TTL_SECONDS", cls.quote_ttl),
            realtime_ttl=_int("POLYMARKET_REALTIME_TTL_SECONDS", cls.realtime_ttl),
            taxonomy_ttl=_int("POLYMARKET_TAXONOMY_TTL_SECONDS", cls.taxonomy_ttl),
            stats_ttl=_int("POLYMARKET_STATS_TTL_SECONDS", cls.stats_ttl),
            stats_scan_max_pages=_int("POLYMARKET_STATS_SCAN_MAX_PAGES", cls.stats_scan_max_pages),
            stats_scan_lock_ttl=_int("POLYMARKET_STATS_SCAN_LOCK_TTL", cls.stats_scan_lock_ttl),
        )
