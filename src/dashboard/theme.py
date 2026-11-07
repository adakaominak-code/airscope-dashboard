"""Shared visual tokens and one-time stylesheet injection for the dashboard."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import streamlit as st


@dataclass(frozen=True)
class AqiCategory:
    """CPCB AQI display metadata, independent of the database calculation logic."""

    name: str
    minimum: int
    maximum: int
    color: str
    text_color: str
    icon: str
    meaning: str
    guidance: str


# The visual system uses the official CPCB palette requested for the product UI.
# Database breakpoints and AQI calculation remain in SQL and are not changed here.
AQI_CATEGORIES: tuple[AqiCategory, ...] = (
    AqiCategory("Good", 0, 50, "#00B050", "#062F19", "●", "Air is clean for most people.", "Minimal impact."),
    AqiCategory("Satisfactory", 51, 100, "#92D050", "#173009", "●", "Air quality is generally acceptable.", "Minor breathing discomfort to sensitive people."),
    AqiCategory("Moderate", 101, 200, "#FFD600", "#3D3100", "●", "Sensitive people may notice discomfort.", "Sensitive people may be affected."),
    AqiCategory("Poor", 201, 300, "#FF9900", "#4A2700", "●", "Limit long or intense outdoor activity.", "Breathing discomfort on prolonged exposure."),
    AqiCategory("Very Poor", 301, 400, "#FF0000", "#FFFFFF", "●", "Reduce prolonged outdoor exertion.", "Respiratory illness on prolonged exposure."),
    AqiCategory("Severe", 401, 500, "#C00000", "#FFFFFF", "●", "Avoid prolonged outdoor exertion where possible.", "Affects healthy people."),
)

AQI_BY_NAME = {category.name: category for category in AQI_CATEGORIES}
AQI_COLORS = {category.name: category.color for category in AQI_CATEGORIES}


def category_for_aqi(value: float | int | None) -> AqiCategory | None:
    """Return visual metadata for a numeric AQI, or ``None`` when unavailable."""
    if value is None:
        return None
    return next((item for item in AQI_CATEGORIES if item.minimum <= value <= item.maximum), None)


def inject_theme() -> None:
    """Emit one stylesheet on every render so widget reruns retain the design."""
    css_path = Path(__file__).parent / "static" / "theme.css"
    st.markdown(f"<style>{css_path.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)
