from __future__ import annotations

from fastapi import Request

from openbb_polymarket.client import PolymarketClient
from openbb_polymarket.service import MarketDataService
from openbb_polymarket.stats import EventStatsCache


def get_client(request: Request) -> PolymarketClient:
    return request.app.state.client


def get_stats(request: Request) -> EventStatsCache:
    return request.app.state.stats


def get_service(request: Request) -> MarketDataService:
    return request.app.state.service
