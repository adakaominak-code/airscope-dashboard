"""Small reusable display components used by dashboard sections."""

from __future__ import annotations

from collections.abc import Iterable
from html import escape

import streamlit as st

from src.dashboard.theme import AQI_BY_NAME, AqiCategory, category_for_aqi


def _html(value: object) -> str:
    return escape(str(value), quote=True)


def _sparkline(values: Iterable[float] | None, color: str = "var(--primary-color)") -> str:
    points = [float(value) for value in values or []]
    if len(points) < 2:
        return ""
    lower, upper = min(points), max(points)
    spread = upper - lower or 1
    coords = [f"{index / (len(points) - 1) * 100:.1f},{28 - ((value - lower) / spread * 24 + 2):.1f}" for index, value in enumerate(points)]
    return f'<svg class="aqi-sparkline" viewBox="0 0 100 30" role="img" aria-label="Metric trend"><polyline points="{" ".join(coords)}" fill="none" stroke="{color}" stroke-width="3" vector-effect="non-scaling-stroke" stroke-linecap="round"/></svg>'


def kpi_card(label: str, value: str | int | float, unit: str = "", delta: float | None = None, delta_label: str = "", sparkline: Iterable[float] | None = None, help: str = "", category: str | None = None) -> None:
    """Render a metric card; deltas use AQI-safe red/green directionality."""
    delta_class = "neutral" if delta is None else ("up" if delta > 0 else "down")
    delta_text = delta_label if delta is None and delta_label else ("No comparison" if delta is None else f"{'+' if delta > 0 else ''}{delta:g} {delta_label}".strip())
    if delta is not None and delta != 0:
        delta_text = ("↑ " if delta > 0 else "↓ ") + delta_text
    category_text_colors = {"Good":"#8FDAAA", "Satisfactory":"#B4D97B", "Moderate":"#F2CB61", "Poor":"#FFBA80", "Very Poor":"#FFAAA0", "Severe":"#FF9FAF"}
    value_style = f' style="color:{category_text_colors[category]}"' if category in category_text_colors else ""
    badge = aqi_badge(category) if category else ""
    tooltip = f' title="{_html(help)}"' if help else ""
    sparkline_html = _sparkline(sparkline) or '<span class="aqi-sparkline" aria-hidden="true"></span>'
    st.markdown(
        f'<div class="aqi-kpi"{tooltip}><span class="aqi-kpi__label">{_html(label)}</span><div class="aqi-kpi__value"{value_style}>{_html(value)} <span class="aqi-kpi__unit">{_html(unit)}</span></div>{badge}<span class="aqi-kpi__delta aqi-kpi__delta--{delta_class}">{_html(delta_text)}</span>{sparkline_html}</div>',
        unsafe_allow_html=True,
    )


def aqi_badge(category: str | AqiCategory) -> str:
    """Return a safe inline category pill for use inside custom component HTML."""
    item = AQI_BY_NAME.get(category) if isinstance(category, str) else category
    if item is None:
        return '<span class="aqi-badge" style="background:#64748B;color:#FFFFFF">● Unavailable</span>'
    tokens = {"Good":("#DFF2E6","#19754C"), "Satisfactory":("#EDF4DF","#456B19"), "Moderate":("#FFF4D5","#805B00"), "Poor":("#FFF0DF","#9B4B09"), "Very Poor":("#FDE9E6","#B52D21"), "Severe":("#F9E3E7","#9B1C2E")}
    background, foreground = tokens[item.name]
    return f'<span class="aqi-badge" style="background:{background};color:{foreground}">{item.icon} {_html(item.name)}</span>'


def hero_aqi_panel(aqi: float | int, category: str | None = None, summary: str | None = None) -> None:
    """Render the primary AQI story with non-medical CPCB category guidance."""
    item = AQI_BY_NAME.get(category) if category else category_for_aqi(aqi)
    badge = aqi_badge(item) if item else aqi_badge("Unavailable")
    meaning = summary or (item.meaning if item else "A category could not be calculated for this period.")
    guidance = item.guidance if item else "No general guidance is available."
    st.markdown(
        f'<section class="aqi-hero"><span class="aqi-overline">Selected-period average</span><div class="aqi-hero__value">{float(aqi):.0f} <span class="aqi-kpi__unit">AQI</span></div><div>{badge}</div><strong>{_html(meaning)}</strong><div class="aqi-hero__guidance"><b>General CPCB category guidance, not medical advice:</b> {_html(guidance)}</div></section>',
        unsafe_allow_html=True,
    )


def section_header(title: str, subtitle: str = "") -> None:
    st.markdown(f'<header class="aqi-section-header"><h2>{_html(title)}</h2><p>{_html(subtitle)}</p></header>', unsafe_allow_html=True)


def insight_callout(text: str) -> None:
    st.markdown(f'<aside class="aqi-callout"><b>Insight</b><br>{_html(text)}</aside>', unsafe_allow_html=True)


def chart_card(title: str, caption: str, body: str = "") -> None:
    """Open a chart wrapper. Use ``st.container`` for the actual Plotly chart beneath it."""
    st.markdown(f'<section class="aqi-chart-card"><h3>{_html(title)}</h3><p class="aqi-chart-card__caption">{_html(caption)}</p>{body}</section>', unsafe_allow_html=True)


def empty_state(icon: str, title: str, hint: str) -> None:
    st.markdown(f'<section class="aqi-empty"><div class="aqi-empty__icon">{_html(icon)}</div><h3>{_html(title)}</h3><p>{_html(hint)}</p></section>', unsafe_allow_html=True)


def error_state(title: str = "The database is not reachable", hint: str = "Start MySQL in XAMPP and refresh.") -> None:
    st.markdown(f'<section class="aqi-error"><div class="aqi-error__icon">⚠</div><h3>{_html(title)}</h3><p>{_html(hint)}</p></section>', unsafe_allow_html=True)


def data_source_chip(source: str) -> str:
    labels = {"cpcb_kaggle": "CPCB / Kaggle", "openaq": "OpenAQ", "sample": "Sample"}
    return f'<span class="aqi-chip" style="background:var(--secondary-background-color);color:var(--text-color);border:1px solid var(--aqi-border)">Source · {_html(labels.get(source, source))}</span>'


def simulated_chip() -> str:
    return '<span class="aqi-chip aqi-simulated">SIMULATED DATA</span>'


def health_actions_panel(category: str, worst_aqi: int) -> None:
    """Explain historical AQI bands using CPCB impacts and Indian health advice."""
    guidance = {
        "Good": ("Minimal expected health impact.", "No special activity precautions are generally needed.", "Sensitive people should follow their usual individual care advice."),
        "Satisfactory": ("Some sensitive people may experience mild breathing discomfort.", "Most people can continue usual activities.", "Sensitive people can shorten prolonged or strenuous outdoor exercise."),
        "Moderate": ("People with heart or lung conditions, children and older adults may experience discomfort.", "Reduce prolonged or strenuous outdoor exertion.", "Vulnerable people should avoid prolonged or strenuous outdoor exertion."),
        "Poor": ("Prolonged exposure may cause breathing discomfort; vulnerable people can be affected sooner.", "Avoid outdoor physical exertion; choose a less strenuous indoor activity.", "Vulnerable people should avoid outdoor physical activities."),
        "Very Poor": ("Sustained exposure can affect breathing, with greater impacts on vulnerable people.", "Avoid outdoor physical activities, especially in the morning and late evening.", "Vulnerable people should stay indoors and keep activity levels low."),
        "Severe": ("Respiratory impacts can affect healthy people; vulnerable people face more serious risks.", "Avoid outdoor physical activities.", "Vulnerable people should stay indoors and keep activity levels low."),
    }
    item = AQI_BY_NAME.get(category)
    if item is None:
        return
    meaning, general, sensitive = guidance[category]
    worst_category = category_for_aqi(worst_aqi)
    worst_label = worst_category.name if worst_category else "Unavailable"
    st.markdown(
        f'<section class="aqi-health-actions" style="border-left-color:{item.color}">'
        f'<h3>Health effects and practical actions · {_html(category)} <span>(selected-period average)</span></h3>'
        f'<div class="aqi-health-actions__grid"><div><h4>What this level can mean</h4><p>{_html(meaning)}</p></div>'
        f'<div><h4>What may help</h4><ul><li>{_html(general)}</li><li>{_html(sensitive)}</li></ul></div></div>'
        '<p class="aqi-health-actions__note">General exposure guidance, not a diagnosis or a guarantee of protection. '
        f'The worst day reached {_html(worst_label)} (AQI {worst_aqi}). '
        'A period average can hide high-pollution days; check current local AQI before planning today’s activities. '
        'Sources: <a href="https://airquality.cpcb.gov.in/ccr_docs/FINAL-REPORT_AQI_.pdf" target="_blank" rel="noopener noreferrer">CPCB AQI health bands</a> and '
        '<a href="https://ncdc.mohfw.gov.in/wp-content/uploads/2024/05/2-Public-Health-Advisory-on-Air-Pollution-and-Health-2021-Revised.pdf" target="_blank" rel="noopener noreferrer">NCDC public health guidance</a>.</p></section>',
        unsafe_allow_html=True,
    )
