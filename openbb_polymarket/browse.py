from __future__ import annotations

import json
from html import escape
from typing import Any
from urllib.parse import quote

from openbb_polymarket.formatting import compact_number

_AGGRID = "32.2.0"

_MANIFESTS = [
    {
        "widgetId": "browse_markets_events",
        "name": "Browse Markets — Events",
        "description": "Active Polymarket events with leading outcome, probability, markets, and volumes.",
        "category": "Polymarket",
        "dataType": "table",
    }
]


def _payout(probability_pct: float) -> str:
    return f"{100 / probability_pct:.2f}x" if probability_pct > 0 else "—"


def _outcome_html(outcome: dict[str, Any], selected_market_key: str = "") -> str:
    prob = max(0.0, min(100.0, float(outcome.get("probability_pct") or 0)))
    name = escape(str(outcome.get("name") or ""))
    image = outcome.get("image") or ""
    market_key = str(outcome.get("market_key") or "")
    selected = " selected" if market_key and market_key == selected_market_key else ""
    avatar = (
        f"<span class=\"oc-img has-img\" style=\"background-image:url('{escape(image)}')\"></span>"
        if image else '<span class="oc-img"></span>'
    )
    return f"""
    <div class="outcome{selected}" data-market-key="{escape(market_key)}">
      {avatar}
      <div class="oc-name"><span>{name}</span></div>
      <div class="oc-payout">{_payout(prob)}</div>
      <div class="oc-pill">{prob:.0f}%</div>
    </div>
    """


def _event_html(
    event: dict[str, Any],
    theme: str,
    base_url: str,
    back_qs: str,
    selected_event_id: str = "",
    selected_market_key: str = "",
) -> str:
    image = str(event.get("image") or "")
    thumb = (
        f"<span class=\"ev-img has-img\" style=\"background-image:url('{escape(image)}')\"></span>"
        if image else '<span class="ev-img"></span>'
    )
    outcomes = "".join(_outcome_html(o, selected_market_key) for o in event.get("outcomes", []))
    more = event.get("market_count", 0) - len(event.get("outcomes", []))
    more_html = f'<div class="more">+{more} more</div>' if more > 0 else ""
    tags = ", ".join(str(t) for t in (event.get("tag_slugs") or [])[:3])
    close_ts = event.get("end_ts")
    if close_ts:
        close_html = f'<time class="ts-d" data-ts="{int(close_ts * 1000)}" data-prefix="ends "></time>'
    elif event.get("close_time"):
        close_html = f'ends {escape(str(event.get("close_time"))[:16])}'
    else:
        close_html = ""
    sub = " · ".join(part for part in (escape(tags), close_html) if part)
    event_id = str(event.get("event_id") or "")
    market_key = str((event.get("outcomes") or [{}])[0].get("market_key") or "")
    href = f"{base_url}/event_details?event_id={quote(event_id)}&theme={quote(theme)}"
    if market_key:
        href += f"&market_key={quote(market_key, safe='')}"
    if back_qs:
        href += f"&back={quote(back_qs, safe='')}"
    selected = " selected" if event_id and event_id == selected_event_id else ""
    return f"""
    <a class="event{selected}" href="{href}" data-event-id="{escape(event_id)}" data-market-key="{escape(market_key)}">
      <header>
        {thumb}
        <div class="ev-head">
          <div class="title">{escape(str(event.get("title") or event_id))} <span class="open">↗</span></div>
          <div class="sub">{sub}</div>
        </div>
      </header>
      <div class="outcomes">{outcomes}{more_html}</div>
      <footer>
        <span>${compact_number(event.get("volume_total"))} vol</span>
        <span>{event.get("market_count", 0)} markets</span>
      </footer>
    </a>
    """


def render_browse(
    events: list[dict[str, Any]],
    *,
    rows: list[dict[str, Any]],
    param_defs: list[dict[str, Any]],
    total: int,
    search: str,
    theme: str,
    base_url: str = "",
    back_qs: str = "",
    limit: int = 40,
    offset: int = 0,
    selected_event_id: str = "",
    selected_market_key: str = "",
    emit_on_load: bool = False,
) -> str:
    is_light = theme == "light"
    grid_theme = "ag-theme-quartz" if is_light else "ag-theme-quartz-dark"
    assets = base_url.rstrip("/")
    if events:
        body = "".join(
            _event_html(e, theme, base_url, back_qs, selected_event_id, selected_market_key)
            for e in events
        )
    else:
        hint = f' for "{escape(search)}"' if search else ""
        body = f'<div class="empty">No markets found{hint}.</div>'

    offset = max(0, offset)
    first = offset + 1 if events else 0
    last = offset + len(events)
    caption = (
        f"{first}–{last} of {total} open events" if events else f"0 of {total} open events"
    ) + (f' · "{escape(search)}"' if search else "")
    prev_off = max(0, offset - limit)
    next_off = offset + limit
    prev_dis = " disabled" if offset <= 0 else ""
    next_dis = " disabled" if next_off >= total else ""
    pager = (
        f'<div class="pager">'
        f'<button id="ob-prev" type="button" data-offset="{prev_off}"{prev_dis}>‹ Prev</button>'
        f'<button id="ob-next" type="button" data-offset="{next_off}"{next_dis}>Next ›</button>'
        f"</div>"
    )

    def _emb(value: Any) -> str:
        return json.dumps(value).replace("</", "<\\/")

    rowdata = _emb(rows)
    manifests = _emb(_MANIFESTS)
    params = _emb(param_defs)
    cfg = _emb({
        "base": base_url,
        "theme": theme,
        "back": back_qs,
        "limit": limit,
        "offset": offset,
        "total": total,
        "selectedEventId": selected_event_id,
        "selectedMarketKey": selected_market_key,
        "emitOnLoad": emit_on_load,
    })

    return f"""
<!doctype html>
<html data-theme="{'light' if is_light else 'dark'}">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/ag-grid-community@{_AGGRID}/styles/ag-grid.css" />
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/ag-grid-community@{_AGGRID}/styles/ag-theme-quartz.css" />
  <link rel="stylesheet" href="{assets}/static/css/browse.css" />
</head>
<body>
  <main class="wrap">
    <div class="toolbar">
      <div class="caption">{caption}</div>
      {pager}
      <div class="views">
        <button id="ob-view-cards" class="active" type="button">Cards</button>
        <button id="ob-view-table" type="button">Table</button>
        <button id="ob-csv" class="ob-hidden" type="button">Export CSV</button>
      </div>
    </div>
    <div class="content">
      <div id="ob-cards">{body}</div>
      <div id="ob-grid" class="{grid_theme} ob-hidden"></div>
    </div>
  </main>
  <script id="ob-manifests" type="application/json">{manifests}</script>
  <script id="ob-params" type="application/json">{params}</script>
  <script id="ob-rowdata" type="application/json">{rowdata}</script>
  <script id="ob-cfg" type="application/json">{cfg}</script>
  <script src="https://cdn.jsdelivr.net/npm/ag-grid-community@{_AGGRID}/dist/ag-grid-community.min.js"></script>
  <script src="{assets}/static/js/browse.js"></script>
</body>
</html>
""".strip()
