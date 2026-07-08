from __future__ import annotations

from typing import Any

from openbb_polymarket.formatting import (
    build_market_key,
    iso_to_display,
    money,
    parse_json_list,
    pct,
    quantity,
    timestamp_to_iso,
    to_float,
)


def market_row(market: dict[str, Any], event_id: str = "") -> dict[str, Any]:
    prices = parse_json_list(market.get("outcomePrices"))
    tokens = parse_json_list(market.get("clobTokenIds"))
    yes_price = prices[0] if prices else market.get("lastTradePrice")
    condition_id = market.get("conditionId", "")
    yes_bid = pct(market.get("bestBid"))
    yes_ask = pct(market.get("bestAsk"))
    return {
        "market_key": build_market_key(event_id, condition_id),
        "name": market.get("groupItemTitle") or market.get("question") or condition_id,
        "question": market.get("question", ""),
        "condition_id": condition_id,
        "yes_token": tokens[0] if len(tokens) > 0 else "",
        "no_token": tokens[1] if len(tokens) > 1 else "",
        "probability_pct": pct(yes_price),
        "yes_bid_pct": yes_bid,
        "yes_ask_pct": yes_ask,
        "spread_pct": round(max(yes_ask - yes_bid, 0), 2),
        "price_change_pts": pct(market.get("oneDayPriceChange")),
        "volume_24h": quantity(market.get("volume24hr")),
        "volume_total": quantity(market.get("volumeNum") or market.get("volume")),
        "liquidity": quantity(market.get("liquidityNum") or market.get("liquidity")),
        "best_bid": money(market.get("bestBid")),
        "best_ask": money(market.get("bestAsk")),
        "last_price": money(yes_price),
        "close_time": iso_to_display(market.get("endDate")),
    }


def trade_row(trade: dict[str, Any]) -> dict[str, Any]:
    size = quantity(trade.get("size"))
    price = money(trade.get("price"))
    return {
        "timestamp": timestamp_to_iso(trade.get("timestamp")),
        "side": str(trade.get("side", "")).upper(),
        "outcome": trade.get("outcome", ""),
        "size": size,
        "price": price,
        "price_pct": round(price * 100, 2),
        "notional": round(size * price, 2),
        "trader": trade.get("name") or trade.get("pseudonym") or "",
        "wallet": trade.get("proxyWallet", ""),
        "tx_hash": trade.get("transactionHash", ""),
    }


def orderbook_rows(orderbook: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    bids = sorted(
        (lvl for lvl in orderbook.get("bids", []) if isinstance(lvl, dict)),
        key=lambda lvl: to_float(lvl.get("price")),
        reverse=True,
    )
    asks = sorted(
        (lvl for lvl in orderbook.get("asks", []) if isinstance(lvl, dict)),
        key=lambda lvl: to_float(lvl.get("price")),
    )
    for side, levels in (("BID", bids), ("ASK", asks)):
        for level, item in enumerate(levels, start=1):
            price = money(item.get("price"))
            size = quantity(item.get("size"))
            rows.append(
                {
                    "side": side,
                    "level": level,
                    "price": price,
                    "probability_pct": round(price * 100, 2),
                    "size": size,
                    "notional": round(price * size, 2),
                }
            )
    return rows


def holder_rows(
    payload: list[dict[str, Any]], outcome_names: list[str]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for entry in payload or []:
        if not isinstance(entry, dict):
            continue
        for rank, holder in enumerate(entry.get("holders") or [], start=1):
            if not isinstance(holder, dict):
                continue
            index = holder.get("outcomeIndex")
            outcome = (
                outcome_names[index]
                if isinstance(index, int) and 0 <= index < len(outcome_names)
                else (str(index) if index is not None else "")
            )
            rows.append(
                {
                    "rank": rank,
                    "outcome": outcome,
                    "trader": holder.get("name") or holder.get("pseudonym") or "",
                    "wallet": holder.get("proxyWallet", ""),
                    "shares": quantity(holder.get("amount")),
                }
            )
    rows.sort(key=lambda r: r["shares"], reverse=True)
    return rows


def leaderboard_row(entry: dict[str, Any], rank: int) -> dict[str, Any]:
    return {
        "rank": rank,
        "trader": entry.get("name") or entry.get("pseudonym") or "",
        "wallet": entry.get("proxyWallet", ""),
        "amount": quantity(entry.get("amount")),
    }
