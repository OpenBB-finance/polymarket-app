from __future__ import annotations

import json
from html import escape
from typing import Any

from openbb_polymarket.formatting import (
    compact_number,
    iso_to_display,
    parse_iso_time,
    parse_json_list,
    pct,
    quantity,
    to_float,
)


def _time_el(iso: Any, prefix: str = "") -> str:
    display = escape(iso_to_display(iso))
    dt = parse_iso_time(iso) if iso else None
    if not dt:
        return f"{prefix}{display}" if display else ""
    return (
        f'<time class="ts-d" data-ts="{int(dt.timestamp() * 1000)}" '
        f'data-prefix="{escape(prefix)}">{prefix}{display}</time>'
    )


def _payout(probability_pct: float) -> str:
    return f"{100 / probability_pct:.2f}x" if probability_pct > 0 else "—"


def _outcome_row(market: dict[str, Any]) -> dict[str, Any]:
    prices = parse_json_list(market.get("outcomePrices"))
    yes_price = prices[0] if prices else market.get("lastTradePrice")
    return {
        "name": market.get("groupItemTitle") or market.get("question") or market.get("conditionId", ""),
        "probability_pct": pct(yes_price),
        "yes_bid_pct": pct(market.get("bestBid")),
        "yes_ask_pct": pct(market.get("bestAsk")),
        "volume_total": quantity(market.get("volumeNum") or market.get("volume")),
        "liquidity": quantity(market.get("liquidityNum") or market.get("liquidity")),
        "image_url": market.get("icon") or market.get("image") or "",
    }


def _outcome_html(outcome: dict[str, Any]) -> str:
    prob = max(0.0, min(100.0, outcome["probability_pct"]))
    width = max(2.0, prob)
    color = "#27ae60" if prob >= 50 else ("#f2994a" if prob >= 20 else "#8b8b94")
    image = outcome.get("image_url") or ""
    thumb = (
        f"<span class=\"thumb\" style=\"background-image:url('{escape(image)}')\"></span>"
        if image else f'<span class="dot" style="background:{color}"></span>'
    )
    return f"""
    <tr>
      <td class="oc">{thumb}<span class="oc-name">{escape(str(outcome["name"]))}</span></td>
      <td class="bar"><div class="track"><span style="width:{width:.1f}%;background:{color}"></span></div></td>
      <td class="num strong">{prob:.1f}%</td>
      <td class="num muted">{outcome["yes_bid_pct"]:.0f} / {outcome["yes_ask_pct"]:.0f}</td>
      <td class="num muted">{_payout(prob)}</td>
      <td class="num">${compact_number(outcome["volume_total"])}</td>
      <td class="num">${compact_number(outcome["liquidity"])}</td>
    </tr>
    """


def _section(title: str, body: str) -> str:
    return f'<section><h3>{escape(title)}</h3>{body}</section>' if body.strip() else ""


def render_event_page(
    *,
    event: dict[str, Any],
    markets: list[dict[str, Any]],
    event_id: str,
    theme: str,
    base_url: str = "",
    back_url: str = "",
    history_figure: dict[str, Any] | None = None,
    poll_url: str = "",
    market_key: str = "",
    filters: dict[str, Any] | None = None,
) -> str:
    is_light = theme == "light"
    assets = base_url.rstrip("/")
    chart_section = (
        '<section><h3>Price history</h3>'
        '<div id="ev-chart" class="chart" style="height:340px;padding:4px"></div></section>'
        if history_figure else ""
    )
    figure_json = json.dumps(history_figure or {}).replace("</", "<\\/")
    cfg_json = json.dumps(
        {
            "poll": poll_url,
            "event_id": event_id,
            "market_key": market_key,
            "theme": theme,
            "filters": filters or {},
        }
    ).replace("</", "<\\/")
    all_outcomes = sorted(
        (_outcome_row(m) for m in markets),
        key=lambda o: to_float(o["volume_total"]),
        reverse=True,
    )
    total_volume = sum(o["volume_total"] for o in all_outcomes)
    total_liquidity = sum(o["liquidity"] for o in all_outcomes)

    def _active(outcome: dict[str, Any]) -> bool:
        return to_float(outcome["volume_total"]) > 0 or to_float(outcome["liquidity"]) > 0

    outcomes = [o for o in all_outcomes if _active(o)] or all_outcomes
    hidden = len(all_outcomes) - len(outcomes)
    rep = markets[0] if markets else {}
    tags = ", ".join(
        str(t.get("slug") or t.get("label") or "")
        for t in (event.get("tags") or [])[:4]
        if isinstance(t, dict)
    )

    meta = " · ".join(
        part for part in (
            escape(tags),
            f"{len(outcomes)} of {len(all_outcomes)} markets" if hidden else f"{len(all_outcomes)} markets",
            f"${compact_number(total_volume)} volume",
            f"${compact_number(total_liquidity)} liquidity",
            (_time_el(event.get("endDate"), "ends ") if event.get("endDate") else ""),
        ) if part
    )

    rows = "".join(_outcome_html(o) for o in outcomes) or '<tr><td colspan="7" class="muted">No markets.</td></tr>'
    if hidden:
        rows += (
            f'<tr><td colspan="7" class="muted" style="text-align:center;padding-top:12px">'
            f"{hidden} inactive market{'s' if hidden != 1 else ''} hidden (no volume or liquidity)</td></tr>"
        )

    resolution = ""
    if event.get("description"):
        resolution += f'<p class="lead">{escape(str(event["description"]))}</p>'
    elif rep.get("description"):
        resolution += f'<p class="lead">{escape(str(rep["description"]))}</p>'
    source = str(rep.get("resolutionSource") or "").strip()
    if source.startswith(("http://", "https://")):
        resolution += (
            f'<p class="note">Resolution source: '
            f'<a href="{escape(source)}" target="_blank" rel="noopener">{escape(source)}</a></p>'
        )

    return f"""
<!doctype html>
<html data-theme="{'light' if is_light else 'dark'}">
<head>
  <meta charset="utf-8" />
  <title>{escape(str(event.get("title") or event_id))}</title>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
  <link rel="stylesheet" href="{assets}/static/css/event_page.css" />
</head>
<body>
  <div class="scroll">
  <main class="wrap">
    <a class="back" href="{escape(back_url)}">← Back to events</a>
    <h1>{escape(str(event.get("title") or event_id))}</h1>
    <div class="meta">{meta}</div>
    {chart_section}
    <section>
      <h3>Markets</h3>
      <table>
        <thead><tr>
          <th class="l">Outcome</th><th></th><th>YES</th><th>Bid / Ask</th>
          <th>Payout</th><th>Volume</th><th>Liquidity</th>
        </tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </section>
    {_section("Resolution", resolution)}
    <div class="meta" style="margin-top:24px">Event <code>{escape(str(event_id))}</code></div>
  </main>
  </div>
  <script id="ev-fig" type="application/json">{figure_json}</script>
  <script id="ev-cfg" type="application/json">{cfg_json}</script>
  <script src="{assets}/static/js/event_page.js"></script>
</body>
</html>
""".strip()
