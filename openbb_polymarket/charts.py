from __future__ import annotations

import json
from typing import Any

import plotly.graph_objects as go

from openbb_polymarket.formatting import timestamp_to_iso

ACCENT = "#2E5CFF"
_STATIC_CONFIG = {"displayModeBar": False, "doubleClick": False, "scrollZoom": False}


def _template(theme: str) -> str:
    return "plotly_dark" if theme == "dark" else "plotly_white"


def _to_chart(fig: go.Figure, static: bool = True) -> dict[str, Any]:
    chart = json.loads(fig.to_json())
    chart["config"] = (
        dict(_STATIC_CONFIG) if static else {"scrollZoom": True, "displayModeBar": False}
    )
    return chart


def empty_figure(message: str, theme: str) -> dict[str, Any]:
    fig = go.Figure()
    fig.add_annotation(
        text=message, xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False
    )
    fig.update_layout(template=_template(theme), margin=dict(l=36, r=24, t=20, b=36))
    return _to_chart(fig)


def _rangeselector(theme: str) -> dict[str, Any]:
    dark = theme != "light"
    return dict(
        buttons=[
            dict(count=1, label="1D", step="day", stepmode="backward"),
            dict(count=7, label="1W", step="day", stepmode="backward"),
            dict(count=1, label="1M", step="month", stepmode="backward"),
            dict(step="all", label="ALL"),
        ],
        bgcolor="#1d1d22" if dark else "#eef1f5",
        bordercolor="#2a2a31" if dark else "#e2e6ec",
        borderwidth=1,
        activecolor=ACCENT,
        font=dict(color="#f2f2f4" if dark else "#1f2328", size=11),
        x=1.0, xanchor="right", y=1.02, yanchor="bottom",
    )


def _wrap(text: str, width: int = 34) -> str:
    words = str(text).split()
    lines: list[str] = []
    current = ""
    for word in words:
        if current and len(current) + 1 + len(word) > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return "<br>".join(lines) or str(text)


def tag_volume(
    rows: list[dict[str, Any]],
    metric: str,
    metric_label: str,
    theme: str,
) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda r: r.get(metric, 0))
    labels = [_wrap(r.get("label") or r.get("slug", "")) for r in ordered]
    values = [r.get(metric, 0) for r in ordered]
    fig = go.Figure(
        go.Bar(
            x=values,
            y=labels,
            orientation="h",
            marker=dict(color=ACCENT),
            customdata=[
                [r.get("volume_24h", 0), r.get("open_interest", 0), int(r.get("event_count", 0))]
                for r in ordered
            ],
            hovertemplate=(
                "<b>%{y}</b><br>24h volume $%{customdata[0]:,.0f}<br>"
                "Open interest $%{customdata[1]:,.0f}<br>"
                "Events %{customdata[2]:,}<extra></extra>"
            ),
        )
    )
    fig.update_layout(
        template=_template(theme),
        margin=dict(l=8, r=24, t=12, b=36),
        xaxis=dict(title=metric_label),
        yaxis=dict(automargin=True, tickfont=dict(size=11), ticklabelposition="outside"),
        bargap=0.18,
    )
    return _to_chart(fig)


_LINE_PALETTE = (
    "#2E5CFF", "#2fbd6b", "#f5a623", "#f2566a",
    "#a872f0", "#22c1c3", "#ec6ba6", "#b3c63a",
)


def outcome_history(lines: list[dict[str, Any]], theme: str) -> dict[str, Any]:
    fig = go.Figure()
    ymax = 0.0
    for index, line in enumerate(lines):
        ys = [point[1] for point in line["points"]]
        ymax = max(ymax, max(ys) if ys else 0.0)
        fig.add_trace(
            go.Scatter(
                x=[timestamp_to_iso(point[0]) for point in line["points"]],
                y=ys,
                mode="lines",
                name=str(line.get("name", "")),
                line=dict(color=_LINE_PALETTE[index % len(_LINE_PALETTE)], width=1.8),
                hovertemplate="<b>%{fullData.name}</b> %{y:.0f}%<extra></extra>",
            )
        )
    top = max(10.0, min(100.0, (int(ymax) // 10 + 1) * 10.0))
    fig.update_xaxes(rangeselector=_rangeselector(theme), rangeslider=dict(visible=False))
    fig.update_yaxes(
        title_text="YES probability", range=[0, top], ticksuffix="%", fixedrange=True
    )
    fig.update_layout(
        template=_template(theme),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.08, x=0),
        margin=dict(l=48, r=24, t=40, b=36), uirevision="polymarket",
    )
    return _to_chart(fig, static=False)
