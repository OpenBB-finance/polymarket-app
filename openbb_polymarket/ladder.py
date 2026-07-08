from __future__ import annotations

from html import escape


def _price(value: float) -> str:
    return (f"{value:.1f}".rstrip("0").rstrip(".")) + "¢"


def _total(value: float) -> str:
    return f"${value:,.2f}"


def _amount(value: float) -> str:
    return f"{int(value):,}" if float(value).is_integer() else f"{value:,.2f}"


def _cumulative(levels: list[tuple[float, float]]) -> list[tuple[float, float, float]]:
    out: list[tuple[float, float, float]] = []
    cum = 0.0
    for price, size in levels:
        cum += size * price / 100.0
        out.append((price, size, cum))
    return out


def _row(price: float, size: float, cum: float, side: str, max_cum: float, label: str) -> str:
    width = 0.0 if max_cum <= 0 else min(100.0, cum / max_cum * 100)
    lab = f'<span class="seclab">{label}</span>' if label else ""
    return (
        f'<div class="row {side}"><span class="bar" style="width:{width:.1f}%"></span>{lab}'
        f'<span class="c price">{_price(price)}</span>'
        f'<span class="c ct">{_amount(size)}</span>'
        f'<span class="c tot">{_total(cum)}</span></div>'
    )


def render_ladder(
    *,
    title: str,
    subtitle: str,
    market_label: str,
    asks: list[tuple[float, float]],
    bids: list[tuple[float, float]],
    last_price: float | None,
    side: str,
    theme: str,
    base_url: str = "",
) -> str:
    asks_c = _cumulative(asks)
    bids_c = _cumulative(bids)
    max_cum = max([c for *_, c in (asks_c + bids_c)] or [0.0])

    ask_disp = list(reversed(asks_c))
    ask_html = "".join(
        _row(p, sz, cu, "ask", max_cum, "Asks" if i == len(ask_disp) - 1 else "")
        for i, (p, sz, cu) in enumerate(ask_disp)
    ) or '<div class="empty">No asks</div>'
    bid_html = "".join(
        _row(p, sz, cu, "bid", max_cum, "Bids" if i == 0 else "")
        for i, (p, sz, cu) in enumerate(bids_c)
    ) or '<div class="empty">No bids</div>'

    is_no = side == "no"
    side_label = "Trade No" if is_no else "Trade Yes"
    last_label = f"Last {_price(last_price)}" if last_price else ""
    assets = base_url.rstrip("/")

    return f"""
<!doctype html>
<html data-theme="{'light' if theme == 'light' else 'dark'}">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <link rel="stylesheet" href="{assets}/static/css/ladder.css" />
</head>
<body data-side="{'no' if is_no else 'yes'}">
  <main class="shell">
    <div class="head">
      <div>
        <div class="title">{escape(title)}</div>
        <div class="subtitle">{escape(subtitle)}</div>
      </div>
      <div class="ticker">{escape(market_label)}</div>
    </div>
    <div class="colhead"><span>Price</span><span>Shares</span><span>Total</span></div>
    <div class="book">
      {ask_html}
      <div class="divider"><span class="lbl">{side_label}<small>{last_label}</small></span></div>
      {bid_html}
    </div>
  </main>
</body>
</html>
""".strip()
