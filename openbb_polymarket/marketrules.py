from __future__ import annotations

import json
from html import escape
from typing import Any

from openbb_polymarket.formatting import (
    compact_number,
    iso_to_display,
    money,
    parse_json_list,
    pct,
)


def _row(label: str, value: str) -> str:
    if not value:
        return ""
    return f'<div class="row"><span>{escape(label)}</span><strong>{value}</strong></div>'


def _section(title: str, body: str) -> str:
    if not body.strip():
        return ""
    return f'<section><h3>{escape(title)}</h3>{body}</section>'


def _uma_status(market: dict[str, Any]) -> str:
    statuses = parse_json_list(market.get("umaResolutionStatuses"))
    labels = []
    for status in statuses:
        if isinstance(status, dict):
            labels.append(str(status.get("status") or status.get("state") or ""))
        elif isinstance(status, str):
            labels.append(status)
    labels = [s for s in labels if s]
    return ", ".join(labels)


def render_market_rules(
    *,
    market: dict[str, Any],
    event: dict[str, Any],
    condition_id: str,
    event_id: str,
    theme: str,
    base_url: str = "",
    param_defs: list[dict[str, Any]] | None = None,
    sync_url: str = "",
    current_market: str = "",
) -> str:
    is_light = theme == "light"
    assets = base_url.rstrip("/")
    title = event.get("title") or market.get("question") or market.get("groupItemTitle") or "Market"
    outcome = market.get("groupItemTitle") or market.get("question") or ""
    prices = parse_json_list(market.get("outcomePrices"))
    yes_price = prices[0] if prices else market.get("lastTradePrice")
    yes = pct(yes_price)
    yes_bid = pct(market.get("bestBid"))
    yes_ask = pct(market.get("bestAsk"))

    criteria = escape(str(market.get("description") or "")).replace("\n", "<br/>")
    event_desc = escape(str(event.get("description") or "")).replace("\n", "<br/>")
    resolution = ""
    if criteria:
        resolution += f'<p class="lead">{criteria}</p>'
    if event_desc and event_desc != criteria:
        resolution += f"<p>{event_desc}</p>"
    if not resolution:
        resolution = "<p>Resolution criteria were not included in the API response.</p>"

    source = str(market.get("resolutionSource") or "").strip()
    if source:
        if source.startswith(("http://", "https://")):
            resolution += (
                f'<p class="note">Resolution source: '
                f'<a href="{escape(source)}" target="_blank" rel="noopener">{escape(source)}</a></p>'
            )
        else:
            resolution += f'<p class="note">Resolution source: {escape(source)}</p>'

    meta_rows = "".join(
        [
            _row("Outcome", escape(str(outcome))),
            _row("YES probability", f"{yes:.1f}%"),
            _row("Best bid / ask", f"{yes_bid:.1f}% / {yes_ask:.1f}%"),
            _row("Spread", f"{max(yes_ask - yes_bid, 0):.1f} pts"),
            _row("24h volume", f"${compact_number(market.get('volume24hr'))}"),
            _row("Total volume", f"${compact_number(market.get('volumeNum') or market.get('volume'))}"),
            _row("Liquidity", f"${compact_number(market.get('liquidityNum') or market.get('liquidity'))}"),
            _row("Last trade", f"{money(market.get('lastTradePrice')):g}"),
            _row("UMA status", escape(_uma_status(market))),
            _row("Condition ID", escape(condition_id)),
            _row("Event ID", escape(event_id)),
        ]
    )

    timeline = "".join(
        _row(label, escape(iso_to_display(market.get(key) or event.get(key))))
        for label, key in (("Starts", "startDate"), ("Ends", "endDate"))
        if market.get(key) or event.get(key)
    )

    sections = "".join(
        [
            _section("Resolution criteria", resolution),
            _section("Timeline", timeline),
        ]
    )

    cfg_json = json.dumps(
        {"paramDefs": param_defs or [], "current": current_market, "sync": sync_url}
    ).replace("</", "<\\/")

    return f"""
<!doctype html>
<html data-theme="{'light' if is_light else 'dark'}">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <link rel="stylesheet" href="{assets}/static/css/market_brief.css" />
</head>
<body>
  <div class="scroll">
  <main class="wrap">
    <div>
      <h2>{escape(str(title))}</h2>
      <div class="sub">{escape(str(outcome))}</div>
    </div>
    <div class="grid">
      <section><h3>Details</h3><div class="meta">{meta_rows}</div></section>
      <div>{sections}</div>
    </div>
  </main>
  </div>
  <script id="mb-cfg" type="application/json">{cfg_json}</script>
  <script src="{assets}/static/js/market_brief.js"></script>
</body>
</html>
""".strip()
