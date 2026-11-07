"""Shared Plotly conventions for fast, readable, theme-compatible charts."""

from __future__ import annotations

from typing import Any

import plotly.graph_objects as go
import plotly.io as pio

from src.dashboard.theme import AQI_CATEGORIES


CITY_PALETTE = ("#D5AF7B", "#D99A7A", "#BFC29A", "#D4C7B4", "#B7B8D6")
pio.templates["airscope_autumn"] = go.layout.Template(
    layout={"font":{"color":"#F2E0CF"}, "paper_bgcolor":"#38372C", "plot_bgcolor":"#38372C", "colorway":list(CITY_PALETTE), "xaxis":{"gridcolor":"#555243","zerolinecolor":"#555243"}, "yaxis":{"gridcolor":"#555243","zerolinecolor":"#555243"}}
)
PLOTLY_CONFIG: dict[str, Any] = {
    "displaylogo": False,
    "displayModeBar": True,
    "scrollZoom": False,
    "responsive": True,
    "modeBarButtonsToRemove": ["lasso2d", "select2d", "autoScale2d", "toggleSpikelines"],
    "toImageButtonOptions": {"format": "png", "filename": "urban_air_quality_chart", "height": 900, "width": 1600, "scale": 2},
}


def apply_chart_style(figure: go.Figure, *, height: int = 390, y_title: str = "AQI", x_title: str = "") -> go.Figure:
    """Apply the shared neutral chart grammar without setting a fixed light/dark fill."""
    figure.update_layout(
        template="airscope_autumn",
        height=height,
        margin={"l": 12, "r": 18, "t": 28, "b": 12},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": "Segoe UI Variable Text, Segoe UI, Aptos, sans-serif", "color":"#F2E0CF"},
        hovermode="x unified",
        hoverlabel={"bgcolor": "#25251E", "font": {"color": "#F2E0CF"}, "bordercolor": "#B48954"},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "left", "x": 0, "font":{"color":"#D4C7B4"}},
        modebar={"bgcolor":"#38372C","color":"#D4C7B4","activecolor":"#D5AF7B"},
        transition={"duration": 0},
        xaxis={"title": x_title, "showgrid": False, "zeroline": False, "fixedrange": False},
        yaxis={"title": y_title, "gridcolor": "rgba(212,199,180,.16)", "zeroline": False, "fixedrange": False},
    )
    return figure


def add_aqi_bands(figure: go.Figure) -> go.Figure:
    """Overlay labelled CPCB AQI bands on a standard Cartesian AQI chart."""
    for item in AQI_CATEGORIES:
        figure.add_hrect(
            y0=item.minimum,
            y1=item.maximum,
            fillcolor=item.color,
            opacity=0.09,
            line_width=0,
            annotation_text=item.name,
            annotation_position="right",
            annotation_font={"size": 10, "color": "#D4C7B4"},
        )
    return figure
