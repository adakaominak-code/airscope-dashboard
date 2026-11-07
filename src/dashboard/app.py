"""Citizen-friendly dashboard for the Urban Air Quality and Health Tracker."""
from datetime import date, timedelta
from time import perf_counter
import os

import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from src.config import ROOT
from src.dashboard.components import empty_state, error_state, health_actions_panel, hero_aqi_panel, insight_callout, kpi_card, section_header, simulated_chip
from src.dashboard.charts import CITY_PALETTE, PLOTLY_CONFIG, add_aqi_bands, apply_chart_style
from src.dashboard.theme import AQI_COLORS, AQI_BY_NAME, inject_theme
from src.db import engine as make_engine

st.set_page_config(page_title="Indian City Air Quality", page_icon="🌫️", layout="wide", initial_sidebar_state="auto")

COLORS = AQI_COLORS
ORDER = list(COLORS)
inject_theme()
pio.templates.default = "airscope_autumn"


@st.cache_resource
def db_engine():
    return make_engine()


@st.cache_data(ttl=300, show_spinner=False)
def query(sql: str, params: dict | None = None) -> pd.DataFrame:
    started = perf_counter()
    with db_engine().connect() as con:
        result = pd.read_sql(text(sql), con, params=params or {})
    result.attrs.update(sql=sql, query_ms=round((perf_counter() - started) * 1000, 1))
    return result


def view_sql(data: pd.DataFrame) -> None:
    with st.expander("View SQL & query time"):
        st.caption(f"Database execution: {data.attrs.get('query_ms', 0):,.1f} ms · cached results reused for five minutes.")
        st.code(data.attrs.get("sql", ""), language="sql")


def download_csv(df: pd.DataFrame, label: str, name: str):
    st.download_button(label, df.to_csv(index=False).encode("utf-8-sig"), name, "text/csv", key=name)


def message_for_db_error(err: Exception):
    """Show a safe, user-facing recovery path without database internals or secrets."""
    recovery = "The online data could not be opened. Please reload the page." if os.getenv('AIRSCOPE_SQLITE_PATH') else "Start MySQL in XAMPP, then refresh this page. Your dashboard data remains unchanged."
    error_state("The database is not reachable", recovery)


def _date_from_query(value: str | None, fallback: date, lower: date, upper: date) -> date:
    """Return a bounded ISO date from a query parameter, otherwise a safe fallback."""
    try:
        parsed = date.fromisoformat(value or "")
    except ValueError:
        return fallback
    return min(max(parsed, lower), upper)


def _set_period(city: str, start: date, end: date) -> None:
    st.session_state.filter_city = city
    st.session_state.filter_dates = (start, end)


def _reset_filters(city: str, start: date, end: date, pollutant: str) -> None:
    _set_period(city, start, end)
    st.session_state.filter_pollutant = pollutant
    st.session_state.filter_health = False


try:
    dates = query("SELECT MIN(`date`) first_day, MAX(`date`) last_day FROM city_day_aqi")
    cities = query("SELECT c.city_id,c.name,s.name state FROM city c JOIN state s ON s.state_id=c.state_id ORDER BY c.name")
    if cities.empty or dates.empty or pd.isna(dates.iloc[0].first_day):
        empty_state("◌", "No air-quality data has been loaded", "Load the supplied station-day files, then refresh the dashboard.")
        st.stop()
    first_day, last_day = pd.Timestamp(dates.iloc[0].first_day).date(), pd.Timestamp(dates.iloc[0].last_day).date()
    year_ranges = query("SELECT YEAR(`date`) year,MIN(`date`) first_day,MAX(`date`) last_day FROM city_day_aqi GROUP BY YEAR(`date`)")
    complete_years = [int(row.year) for row in year_ranges.itertuples(index=False)
                      if pd.Timestamp(row.first_day).date() == date(int(row.year),1,1)
                      and pd.Timestamp(row.last_day).date() == date(int(row.year),12,31)]
    full_year = max(complete_years) if complete_years else last_day.year
    default_start = max(first_day, date(full_year, 1, 1))
    default_end = min(last_day, date(full_year, 12, 31))
    if default_start > default_end:
        default_start, default_end = first_day, last_day

    city_names = cities.name.tolist()
    city_default = "Delhi" if "Delhi" in city_names else city_names[0]
    pollutant_names = query("SELECT name FROM pollutant ORDER BY name").name.tolist()
    pollutant_default = "PM2.5" if "PM2.5" in pollutant_names else pollutant_names[0]
    params = st.query_params
    initial_city = params.get("city") if params.get("city") in city_names else city_default
    initial_start = _date_from_query(params.get("start"), default_start, first_day, last_day)
    initial_end = _date_from_query(params.get("end"), default_end, first_day, last_day)
    if initial_start > initial_end:
        initial_start, initial_end = default_start, default_end
    if "filter_city" not in st.session_state:
        st.session_state.filter_city = initial_city
    if "filter_dates" not in st.session_state:
        st.session_state.filter_dates = (initial_start, initial_end)
    if "filter_pollutant" not in st.session_state:
        st.session_state.filter_pollutant = params.get("pollutant") if params.get("pollutant") in pollutant_names else pollutant_default
    if "filter_health" not in st.session_state:
        st.session_state.filter_health = False

    st.markdown("<div class='aqi-overline'>Urban Air Quality Tracker</div><h1 style='margin:.1rem 0 .35rem;letter-spacing:-.04em'>Air quality, made clear.</h1><p style='max-width:760px;color:var(--aqi-muted);margin:0 0 1.5rem'>Daily air-quality evidence for Indian cities, built from CPCB/Kaggle and matched OpenAQ observations. Explore a place, pick a period, then follow the story.</p>", unsafe_allow_html=True)
    with st.sidebar:
        st.markdown("<div class='aqi-brand'><span class='aqi-brand__mark'>A</span> AirScope</div><div class='aqi-overline'>Filter your view</div>", unsafe_allow_html=True)
        selected_state = st.selectbox("State / territory", ["All states"] + sorted(cities.state.unique()), help="Narrow the city list to a state or territory.")
        visible_cities = city_names if selected_state == "All states" else cities.loc[cities.state.eq(selected_state), "name"].tolist()
        if st.session_state.filter_city not in visible_cities:
            st.session_state.filter_city = visible_cities[0]
        selected_city = st.selectbox("City", visible_cities, key="filter_city", help="Choose the city to analyse.")
        city_id = int(cities.loc[cities.name.eq(selected_city), "city_id"].iloc[0])
        city_dates = query("SELECT MIN(`date`) first_day, MAX(`date`) last_day FROM city_day_aqi WHERE city_id=:city", {"city": city_id}).iloc[0]
        city_first, city_last = pd.Timestamp(city_dates.first_day).date(), pd.Timestamp(city_dates.last_day).date()
        current_dates = st.session_state.filter_dates
        if len(current_dates) == 2 and (current_dates[0] > city_last or current_dates[1] < city_first):
            latest_year = city_last.year if city_last.month == 12 and city_last.day == 31 else city_last.year - 1
            adjusted_start, adjusted_end = max(city_first, date(latest_year, 1, 1)), min(city_last, date(latest_year, 12, 31))
            if adjusted_start > adjusted_end:
                adjusted_start, adjusted_end = city_first, city_last
            st.session_state.filter_dates = (adjusted_start, adjusted_end)
        with st.form("date_filters", border=False):
            date_range = st.date_input("Date range", min_value=first_day, max_value=last_day, key="filter_dates", help=f"{selected_city} has observations from {city_first:%d %b %Y} to {city_last:%d %b %Y}.")
            st.form_submit_button("Run dashboard", type="primary", width="stretch")
            st.caption("Select your start and end dates, then click Run dashboard to apply them.")
        if isinstance(date_range, (tuple, list)) and len(date_range) == 2:
            start_day, end_day = date_range
        elif isinstance(date_range, (tuple, list)) and len(date_range) == 1:
            start_day = end_day = date_range[0]
        else:
            st.caption("Select a start date to continue.")
            st.stop()
        st.caption(f"{selected_city} coverage: {city_first:%b %Y}–{city_last:%b %Y}")
        st.markdown("<div class='aqi-overline'>Quick presets</div>", unsafe_allow_html=True)
        city_full_year = city_last.year if city_last.month == 12 and city_last.day == 31 else city_last.year - 1
        with st.container(key="preset_grid"):
            preset_columns = st.columns(3)
            preset_specs = [
                ("Delhi winter", "Delhi, 01 Dec 2019 – 29 Feb 2020", "Delhi" if "Delhi" in city_names else city_default, max(first_day,date(2019,12,1)),min(last_day,date(2020,2,29))),
                ("Diwali week", "Delhi, 24 – 30 Oct 2019", "Delhi" if "Delhi" in city_names else city_default, max(first_day,date(2019,10,24)),min(last_day,date(2019,10,30))),
                ("Last full year", "Latest full calendar year within this city's coverage.",selected_city,max(city_first,date(city_full_year,1,1)),min(city_last,date(city_full_year,12,31))),
            ]
            for column, (label, hint, preset_city, preset_start, preset_end) in zip(preset_columns,preset_specs):
                is_selected = selected_city == preset_city and (start_day,end_day) == (preset_start,preset_end)
                column.button(label,width="stretch",type="primary" if is_selected else "secondary",help=hint,on_click=_set_period,args=(preset_city,preset_start,preset_end))
        pollutant = st.selectbox("Pollutant", pollutant_names, key="filter_pollutant", help="Used by the station map and related detail views.")
        show_health = st.toggle("Show simulated health data", key="filter_health", help="Reveals fictional, simulated admissions used only to demonstrate the database model.")
        st.button("Reset filters", width="stretch", on_click=_reset_filters, args=(city_default, default_start, default_end, pollutant_default))
        st.divider()
        st.caption(f"Coverage · {first_day:%d %b %Y} – {last_day:%d %b %Y}")
        with st.expander("About this project"):
            st.write("CPCB/Kaggle data covers 2015–2020. Matched OpenAQ data extends Delhi coverage through 2026. Health data is simulated and not medical evidence.")

    st.query_params.update({"city": selected_city, "start": start_day.isoformat(), "end": end_day.isoformat(), "pollutant": pollutant})
    if os.getenv('AIRSCOPE_SQLITE_PATH'):
        st.caption("Online copy of the XAMPP dataset · works independently of the owner's computer. Local database changes appear after the next data refresh.")
    st.markdown(f"<div class='aqi-appbar'><div class='aqi-appbar__crumb'>AirScope / <b>{selected_city}</b> / Selected period</div><div class='aqi-appbar__status'>Database connected · {len(cities)} cities</div></div>", unsafe_allow_html=True)
    st.markdown("<div class='aqi-notice'><b>Live project dataset</b><span>Daily CPCB/Kaggle observations (2015–2020) and matched OpenAQ coverage for Delhi (2020–2026). Health records remain simulated and separated from air-quality evidence.</span></div>", unsafe_allow_html=True)

    period = {"city": city_id, "start": start_day, "end": end_day}
    daily = query("SELECT d.`date`,d.aqi,a.label category,d.pollutants_used,d.reporting_stations FROM city_day_aqi d LEFT JOIN aqi_category a ON a.category_id=d.category_id WHERE d.city_id=:city AND d.`date` BETWEEN :start AND :end ORDER BY d.`date`", period)
    if daily.empty:
        empty_state("◌", "No observations in this period", "Choose a wider date range or use Last full year in the filters.")
        st.stop()
    daily["date"] = pd.to_datetime(daily.date)
    valid = daily.dropna(subset=["aqi"]).copy()
    if valid.empty:
        st.info("No AQI could be calculated for these dates. Try a wider date range or another city.")
        st.stop()

    avg_aqi = float(valid.aqi.mean())
    worst = valid.loc[valid.aqi.idxmax()]
    poor_pct = 100 * (valid.aqi > 200).mean()
    reporting = query("SELECT COUNT(DISTINCT r.station_id) stations FROM reading r JOIN station s ON s.station_id=r.station_id WHERE s.city_id=:city AND r.`timestamp`>=:start AND r.`timestamp`<DATE_ADD(:end,INTERVAL 1 DAY)", period).iloc[0, 0]
    previous_len = (end_day - start_day).days + 1
    prev = {"city": city_id, "start": start_day - timedelta(days=previous_len), "end": start_day - timedelta(days=1)}
    previous = query("SELECT AVG(aqi) avg_aqi FROM city_day_aqi WHERE city_id=:city AND `date` BETWEEN :start AND :end", prev).iloc[0, 0]
    delta = None if pd.isna(previous) else round(avg_aqi - float(previous), 1)
    cat = str(valid.loc[(valid.aqi - avg_aqi).abs().idxmin(), "category"] or "Unknown")
    section_header(f"{selected_city} · {start_day:%d %b %Y} – {end_day:%d %b %Y}", "A concise readout of the selected period. Change filters at left to update every section.")
    sparkline = valid.aqi.tail(min(30, len(valid))).tolist()
    metric_cols = st.columns(4)
    with metric_cols[0]:
        kpi_card("Average AQI", f"{avg_aqi:.0f}", "AQI", delta, "vs previous period", sparkline, "Average AQI across valid days in the selected period.", category=cat)
    with metric_cols[1]:
        kpi_card("Worst day", int(worst.aqi), "AQI", None, worst.date.strftime("%d %b %Y"), None, "Highest daily AQI in the selected period.")
    with metric_cols[2]:
        kpi_card("Poor or worse", f"{poor_pct:.0f}%", "of valid days", None, f"{int((valid.aqi > 200).sum())} of {len(valid)} days", None, "Share of valid daily AQI values above 200.")
    with metric_cols[3]:
        kpi_card("Station coverage", int(reporting or 0), "stations", None, "during selected period", None, "Distinct monitoring stations with at least one reading.")

    advisory = query("SELECT health_advisory,color_hex FROM aqi_category WHERE label=:label", {"label": cat})
    health_advice = advisory.iloc[0].health_advisory if not advisory.empty else "Use this as a general air-quality guide."
    category_ui = AQI_BY_NAME.get(cat)
    color = COLORS.get(cat, "#64748b")
    text_color = category_ui.text_color if category_ui else "#FFFFFF"
    st.markdown(f"<div class='aqi-category-strip' style='border-left-color:{color}'><span class='aqi-badge' style='background:{color};color:{text_color}'>{cat}</span><span>{health_advice}</span></div>", unsafe_allow_html=True)

    health_actions_panel(cat, int(worst.aqi))

    tabs = st.tabs(["Overview", "Trends", "Map", "Compare cities", "Health (simulated)", "Data & DBMS"])
    with tabs[0]:
        hero_left, hero_right = st.columns([1, 1.7], gap="large")
        with hero_left:
            hero_aqi_panel(avg_aqi, cat, f"{selected_city} was Poor or worse on {poor_pct:.0f}% of valid days in this period.")
        with hero_right:
            peak_month = valid.assign(month=valid.date.dt.strftime("%B")).groupby("month").aqi.mean().sort_values(ascending=False)
            insight_callout(f"{peak_month.index[0]} had the highest average AQI ({peak_month.iloc[0]:.0f}), compared with {avg_aqi:.0f} across the selected period.")
            st.caption("How to read this: the shaded bands are official AQI categories; the line is the city’s daily AQI.")
        fig = go.Figure()
        add_aqi_bands(fig)
        fig.add_trace(go.Scatter(x=valid.date, y=valid.aqi, mode="lines", line={"color":"#D5AF7B","width":2.2}, name="Daily AQI", hovertemplate="%{x|%d %b %Y}<br>AQI %{y:.0f}<extra></extra>"))
        if start_day <= date(2020,5,31) and end_day >= date(2020,3,25):
            fig.add_vrect(x0=max(start_day,date(2020,3,25)), x1=min(end_day,date(2020,5,31)), fillcolor="#60A5FA", opacity=.08, line_width=0, annotation_text="COVID lockdown", annotation_position="top left")
        fig.update_xaxes(rangeslider={"visible": True, "thickness": .06})
        apply_chart_style(fig, height=450, y_title="AQI", x_title="Date")
        fig.update_yaxes(range=[0,500])
        st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG)
        view_sql(daily)
        download_csv(valid[["date","aqi","category","pollutants_used","reporting_stations"]].rename(columns={"date":"Date","aqi":"Air Quality Index (AQI)","category":"AQI category","pollutants_used":"Pollutants used","reporting_stations":"Stations reporting"}), "Download this data as CSV", "overview_daily_aqi.csv")
        main_pollutant = query("SELECT p.name,AVG(CASE WHEN (CASE WHEN p.name='CO' THEN FLOOR(d.val*10)/10 ELSE FLOOR(d.val) END)>=b.conc_high THEN 500 ELSE ROUND((b.index_high-b.index_low)/(b.conc_high-b.conc_low)*(CASE WHEN p.name='CO' THEN FLOOR(d.val*10)/10 ELSE FLOOR(d.val) END-b.conc_low)+b.index_low) END) avg_subindex FROM (SELECT r.station_id,r.pollutant_id,DATE(r.`timestamp`) day,AVG(r.value) val FROM reading r WHERE r.`timestamp`>=:start AND r.`timestamp`<DATE_ADD(:end,INTERVAL 1 DAY) GROUP BY r.station_id,r.pollutant_id,DATE(r.`timestamp`)) d JOIN station s ON s.station_id=d.station_id AND s.city_id=:city JOIN pollutant p ON p.pollutant_id=d.pollutant_id AND p.in_aqi=1 JOIN aqi_breakpoint b ON b.pollutant_id=p.pollutant_id AND (CASE WHEN p.name='CO' THEN FLOOR(d.val*10)/10 ELSE FLOOR(d.val) END)>=b.conc_low AND ((CASE WHEN p.name='CO' THEN FLOOR(d.val*10)/10 ELSE FLOOR(d.val) END)<b.conc_high OR b.category_id=(SELECT category_id FROM aqi_category WHERE label='Severe')) GROUP BY p.name ORDER BY avg_subindex DESC LIMIT 1", period)
        if not main_pollutant.empty:
            p = main_pollutant.iloc[0]
            st.markdown(f"<div class='aqi-notice'><b>Dominant AQI driver · {p['name']}</b><span>Its average sub-index contribution was {p.avg_subindex:.0f} across the selected period.</span></div>", unsafe_allow_html=True)
        calendar_year = st.selectbox("Calendar heatmap year", sorted(valid.date.dt.year.unique(), reverse=True), key="calendar_year")
        calendar = valid.loc[valid.date.dt.year.eq(calendar_year)].copy()
        if not calendar.empty:
            year_start = pd.Timestamp(int(calendar_year), 1, 1)
            calendar["week"] = ((calendar.date - year_start).dt.days + year_start.dayofweek) // 7 + 1
            calendar["weekday"] = calendar.date.dt.day_name().str[:3]
            calendar["weekday_num"] = calendar.date.dt.dayofweek
            heat = px.scatter(calendar, x="week", y="weekday_num", color="category", color_discrete_map=COLORS, category_orders={"weekday_num":[6,5,4,3,2,1,0]}, hover_data={"date":"|%d %b %Y", "aqi":":.0f", "category":True, "week":False, "weekday_num":False}, labels={"week":"Week of year", "weekday_num":"Day"}, title=f"Daily AQI calendar · {calendar_year}")
            heat.update_traces(marker={"symbol":"square", "size":11})
            apply_chart_style(heat, height=360, y_title="", x_title="Week of year")
            heat.update_layout(hovermode="closest", margin={"l":50,"r":24,"t":65,"b":90}, title={"text":f"Daily AQI calendar · {calendar_year}","x":.025,"y":.97,"font":{"color":"#F2E0CF","size":17}}, legend={"y":-.28,"yanchor":"top","font":{"color":"#D4C7B4"},"title":{"text":""}}, uirevision=f"calendar-{selected_city}-{calendar_year}")
            heat.update_xaxes(fixedrange=True, tickfont={"color":"#D4C7B4"})
            heat.update_yaxes(tickmode="array", tickvals=[6,5,4,3,2,1,0], ticktext=["Sun","Sat","Fri","Thu","Wed","Tue","Mon"], fixedrange=True, tickfont={"color":"#D4C7B4"})
            st.caption("Each square is one observed day. Hover for its date, AQI and category; gaps indicate missing observations.")
            st.plotly_chart(heat, width="stretch", config=PLOTLY_CONFIG, theme=None, key="daily_aqi_calendar")

    with tabs[1]:
        section_header("Trends & seasonality", "Patterns are calculated from the selected city and period—not hard-coded summaries.")
        monthly = valid.assign(month=valid.date.dt.to_period("M").dt.to_timestamp()).groupby("month",as_index=False).aqi.mean()
        fig = px.line(monthly, x="month", y="aqi", markers=True, labels={"month":"Month","aqi":"Average AQI"})
        fig.update_traces(line_color="#D5AF7B"); apply_chart_style(fig, height=340, y_title="Average AQI", x_title="Month")
        st.caption("How to read this: each point is the average of daily AQI values in that month.")
        st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG); download_csv(monthly.rename(columns={"month":"Month","aqi":"Average AQI"}),"Download this data as CSV","monthly_aqi.csv")
        st.subheader("Weekdays and weekends")
        valid["Day type"] = valid.date.dt.dayofweek.map(lambda d: "Weekend" if d >= 5 else "Weekday")
        wd=valid.groupby("Day type",as_index=False).aqi.mean()
        wf=px.bar(wd,x="Day type",y="aqi",color="Day type",color_discrete_map={"Weekday":"#D5AF7B","Weekend":"#D99A7A"},labels={"aqi":"Average AQI"})
        wf.update_layout(showlegend=False); apply_chart_style(wf, height=320, y_title="Average AQI", x_title="")
        if set(wd["Day type"]) == {"Weekend", "Weekday"}:
            difference = float(wd.loc[wd["Day type"].eq("Weekend"),"aqi"].iloc[0] - wd.loc[wd["Day type"].eq("Weekday"),"aqi"].iloc[0])
            insight_callout(f"Weekend AQI is {abs(difference):.0f} points {'higher' if difference > 0 else 'lower'} than weekday AQI in the selected period.")
        else:
            st.caption("Choose a longer period to compare weekdays and weekends.")
        st.plotly_chart(wf, width="stretch", config=PLOTLY_CONFIG); download_csv(wd.rename(columns={"aqi":"Average AQI"}),"Download this data as CSV","weekday_weekend_aqi.csv")
        st.subheader("Seasonal comparison")
        festivals=query("SELECT `date` FROM festival_date WHERE festival='Diwali'")
        diwali_dates=pd.to_datetime(festivals.date)
        valid["Season"] = valid.date.dt.month.map(lambda m: "Winter" if m in (12,1,2) else ("Monsoon" if m in (7,8,9) else "Other months"))
        for festival_day in diwali_dates:
            valid.loc[valid.date.between(festival_day-pd.Timedelta(days=3),festival_day+pd.Timedelta(days=3)),"Season"]="Diwali week"
        seasonal=valid.groupby("Season",as_index=False).aqi.mean()
        sf=px.bar(seasonal,x="Season",y="aqi",color="Season",color_discrete_map={"Winter":"#D4C7B4","Monsoon":"#BFC29A","Diwali week":"#D99A7A","Other months":"#D5AF7B"},labels={"aqi":"Average AQI"})
        sf.update_layout(showlegend=False); apply_chart_style(sf, height=320, y_title="Average AQI", x_title="Season")
        st.plotly_chart(sf, width="stretch", config=PLOTLY_CONFIG); download_csv(seasonal.rename(columns={"aqi":"Average AQI"}),"Download this data as CSV","seasonal_aqi.csv")

    with tabs[2]:
        section_header("Station map", "Marker size represents reading coverage. Approximate coordinates are always identified in the hover details.")
        station_data = query("SELECT s.name,s.latitude,s.longitude,s.coordinates_approximate,AVG(CASE WHEN p.name='PM2.5' THEN r.value END) pm25,COUNT(CASE WHEN p.name=:pollutant THEN 1 END) reading_count FROM station s LEFT JOIN reading r ON r.station_id=s.station_id AND r.`timestamp`>=:start AND r.`timestamp`<DATE_ADD(:end,INTERVAL 1 DAY) LEFT JOIN pollutant p ON p.pollutant_id=r.pollutant_id WHERE s.city_id=:city GROUP BY s.station_id,s.name,s.latitude,s.longitude,s.coordinates_approximate", {**period,"pollutant":pollutant})
        station_data=station_data.dropna(subset=["latitude","longitude"])
        if station_data.empty:
            st.info("No mapped station coordinates are available for this city yet.")
        else:
            station_data["Coordinate note"] = station_data.coordinates_approximate.map(lambda x:"Approximate city-centre location" if x else "Source coordinates")
            station_data["AQI category"] = pd.cut(station_data.pm25,[-1,30,60,90,120,250,float("inf")],labels=ORDER)
            station_data["AQI category"] = station_data["AQI category"].astype(str)
            station_data["marker_size"] = station_data.reading_count.clip(lower=1)
            st.caption("Station colours reflect average PM2.5 concentration bands, rather than full daily AQI. Some coordinates are approximate city-centre estimates.")
            fig=px.scatter_geo(station_data,lat="latitude",lon="longitude",size="marker_size",size_max=28,color="AQI category",color_discrete_map=COLORS,hover_name="name",hover_data={"pm25":":.1f","reading_count":True,"marker_size":False,"Coordinate note":True,"latitude":False,"longitude":False},projection="mercator",labels={"pm25":"Average PM2.5 (µg/m³)","reading_count":"Readings"})
            fig.update_geos(fitbounds="locations",showland=True,landcolor="#4A4737",showocean=True,oceancolor="#292921",showcoastlines=True,coastlinecolor="#7C7458",showcountries=True,countrycolor="#7C7458",bgcolor="rgba(0,0,0,0)")
            fig.update_layout(height=520,margin={"l":0,"r":0,"t":10,"b":0})
            st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG)
            view_sql(station_data)
            download_csv(station_data.rename(columns={"name":"Station","latitude":"Latitude","longitude":"Longitude","pm25":"Average PM2.5 (µg/m³)","reading_count":"Reading count","coordinates_approximate":"Coordinates approximate"}),"Download this data as CSV","station_map_data.csv")

    with tabs[3]:
        section_header("Compare cities", "Compare up to five cities over exactly the same selected dates.")
        selected = st.multiselect("Choose up to five cities", city_names, default=[selected_city], max_selections=5)
        if selected:
            placeholders=", ".join(f":c{i}" for i in range(len(selected)))
            params={f"c{i}":v for i,v in enumerate(selected)}; params.update({"start":start_day,"end":end_day})
            comp=query(f"SELECT c.name city,AVG(v.aqi) avg_aqi, SUM(v.aqi>200)/NULLIF(COUNT(v.aqi),0)*100 poor_pct,COUNT(v.aqi) valid_days FROM city_day_aqi v JOIN city c ON c.city_id=v.city_id WHERE c.name IN ({placeholders}) AND v.`date` BETWEEN :start AND :end GROUP BY c.city_id,c.name",params)
            if not comp.empty:
                missing_cities = sorted(set(selected) - set(comp.city))
                if missing_cities:
                    st.caption("No observations for these dates: " + ", ".join(missing_cities))
                comp=comp.sort_values("avg_aqi",ascending=False)
                fig=px.bar(comp,x="avg_aqi",y="city",orientation="h",color="city",color_discrete_sequence=CITY_PALETTE,labels={"avg_aqi":"Average AQI","city":"City"})
                fig.update_layout(yaxis={"categoryorder":"total ascending"},showlegend=False)
                apply_chart_style(fig, height=340, y_title="", x_title="Average AQI")
                st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG)
                view_sql(comp)
                comp_display=comp.rename(columns={"city":"City","avg_aqi":"Average AQI","poor_pct":"Poor or worse days (%)","valid_days":"Valid days"})
                st.dataframe(comp_display, width="stretch", hide_index=True); download_csv(comp_display,"Download this data as CSV","city_comparison.csv")
        else:
            st.info("Choose at least one city to compare.")
        years=query("SELECT DISTINCT YEAR(`date`) year FROM city_day_aqi ORDER BY year DESC").year.astype(int).tolist()
        if years:
            default_year=start_day.year if start_day.year in years else years[0]
            rank_year=st.selectbox("National city ranking · year",years,index=years.index(default_year))
            national=query("SELECT c.name city,AVG(d.aqi) avg_aqi FROM city_day_aqi d JOIN city c ON c.city_id=d.city_id WHERE YEAR(d.`date`)=:year AND d.aqi IS NOT NULL GROUP BY c.city_id,c.name ORDER BY avg_aqi DESC LIMIT 10",{"year":rank_year})
            if not national.empty:
                national["rank"]=range(1,len(national)+1)
                nf=px.bar(national.sort_values("avg_aqi"),x="avg_aqi",y="city",orientation="h",color="city",color_discrete_sequence=CITY_PALETTE,labels={"avg_aqi":"Average AQI","city":"City"},title=f"Ten highest city AQIs in {rank_year}")
                nf.update_layout(yaxis={"categoryorder":"total ascending"},showlegend=False)
                apply_chart_style(nf, height=410, y_title="", x_title="Average AQI")
                st.plotly_chart(nf, width="stretch", config=PLOTLY_CONFIG); download_csv(national.rename(columns={"city":"City","avg_aqi":"Average AQI","rank":"Rank"}),"Download this data as CSV","national_city_ranking.csv")

    with tabs[4]:
        if not show_health:
            empty_state("◈", "Simulated health view is off", "Enable it in the sidebar to explore the DBMS demonstration. It never represents real patient data or medical evidence.")
        else:
            st.markdown(f"<div class='sim-banner'><b>{simulated_chip()} &nbsp; SIMULATED DATA ONLY.</b> Every hospital, disease and admission record below is fictional. The displayed relationship is built into the generator and is <b>not</b> medical evidence or proof of a pollution-health effect.</div>",unsafe_allow_html=True)
            st.subheader("Simulated daily admissions alongside AQI")
            lag_days=st.slider("Compare admissions after this AQI lag (days)",0,3,1)
            st.caption("A lag of one day pairs each AQI date with simulated admissions on the following day. This demonstrates the generator's assumptions.")
            disease_group=st.selectbox("Disease group",["Respiratory diseases (SIMULATED)","Control diseases (SIMULATED)"])
            group_flag=1 if disease_group.startswith("Respiratory") else 0
            health=query("SELECT a.admit_date date,COUNT(*) admissions FROM admission a JOIN hospital h ON h.hospital_id=a.hospital_id JOIN disease d ON d.disease_id=a.disease_id WHERE h.city_id=:city AND d.is_respiratory=:respiratory AND a.admit_date BETWEEN DATE_SUB(:start,INTERVAL 3 DAY) AND :end GROUP BY a.admit_date ORDER BY a.admit_date",{**period,"respiratory":group_flag})
            if health.empty:
                st.info("No simulated admissions are available for this period.")
            else:
                health["date"]=pd.to_datetime(health.date); health["date"]=health.date-pd.to_timedelta(lag_days,unit="D")
                combined=valid.merge(health,on="date",how="inner")
                hf=go.Figure(); hf.add_trace(go.Scatter(x=combined.date,y=combined.aqi,name="AQI",line={"color":"#2563eb"})); hf.add_trace(go.Scatter(x=combined.date,y=combined.admissions,name="Admissions (SIMULATED)",yaxis="y2",line={"color":"#d97706"}))
                hf.update_layout(xaxis_title="Date",yaxis_title="AQI",yaxis2={"title":"Simulated admissions","overlaying":"y","side":"right"}, title="SIMULATED DATA · AQI and fictional admissions")
                apply_chart_style(hf, height=400, y_title="AQI", x_title="Date")
                st.plotly_chart(hf, width="stretch", config=PLOTLY_CONFIG); download_csv(combined.rename(columns={"date":"Date","aqi":"Air Quality Index (AQI)","category":"AQI category","pollutants_used":"Pollutants used","reporting_stations":"Stations reporting","admissions":"Admissions (SIMULATED)"}),"Download this data as CSV","simulated_health_aqi.csv")
                scatter=px.scatter(combined,x="aqi",y="admissions",labels={"aqi":"Air Quality Index (AQI)","admissions":"Admissions (SIMULATED)"},title="SIMULATED DATA · Method check: admissions and AQI")
                if len(combined) >= 3 and combined.aqi.nunique() > 1:
                    slope, intercept = np.polyfit(combined.aqi.astype(float), combined.admissions.astype(float), 1)
                    line_x = [float(combined.aqi.min()), float(combined.aqi.max())]
                    scatter.add_trace(go.Scatter(x=line_x, y=[slope*x+intercept for x in line_x], mode="lines", name="Simulated linear fit", line={"color":"#F59E0B"}))
                apply_chart_style(scatter, y_title="Simulated admissions", x_title="AQI")
                scatter.add_annotation(text="SIMULATED DATA", x=.5, y=.9, xref="paper", yref="paper", showarrow=False, opacity=.25, font={"size":25})
                scatter.update_traces(name="SIMULATED",showlegend=True); st.plotly_chart(scatter, width="stretch", config=PLOTLY_CONFIG)
                download_csv(combined.rename(columns={"date":"Date","aqi":"Air Quality Index (AQI)","admissions":"Admissions (SIMULATED)"})[["Date","Air Quality Index (AQI)","Admissions (SIMULATED)"]],"Download this data as CSV","simulated_health_scatter.csv")

    with tabs[5]:
        section_header("Methods & database design", "This page makes the DBMS work behind the dashboard visible without modifying the database.")
        under_left, under_right = st.columns(2, gap="large")
        with under_left:
            st.subheader("Normalized data model")
            er_path = ROOT / "docs" / "er_diagram.png"
            if er_path.exists(): st.image(str(er_path), caption="Entity relationship diagram · read-only project schema")
            st.write("The model separates location, monitoring stations, pollutants, measurements, AQI categories and simulated health entities. This keeps each fact stored once and supports efficient aggregation.")
        with under_right:
            st.subheader("Database objects used")
            st.markdown("- **Views:** reusable city-risk and reporting summaries\n- **Functions:** AQI sub-index calculation from pollutant breakpoints\n- **Triggers:** alerts and integrity handling during loads\n- **Stored procedures:** staged reading loads and city-day AQI refreshes\n- **Indexes:** station/time and pollutant/time access paths for dashboard queries")
            st.caption("Dashboard reads are aggregate SQL queries only; it does not write, refresh, or fire database triggers.")
        st.subheader("How to read these results")
        st.write("The project converts daily pollutant concentrations into sub-indices using CPCB concentration bands. A day’s AQI is the highest pollutant sub-index when enough pollutants are available. AQI categories follow the CPCB ranges and are shown with both a label and a color. Daily data is useful for comparison, but it does not reproduce every official hourly or 8-hour calculation rule.")
        st.write("**Sources:** CPCB daily city and station observations distributed through Kaggle (2015–2020); matched OpenAQ Delhi daily observations (2020–2026), stored with separate provenance. Unsupported OpenAQ gas units such as ppb are excluded instead of converted without required conditions. Station coordinates are supplied where available; city-centre estimates are marked approximate. Health records and hospitals are fictional and simulated.")
        count=query("SELECT COUNT(*) n, SUM(aqi IS NULL) missing FROM city_day_aqi WHERE city_id=:city AND `date` BETWEEN :start AND :end",period).iloc[0]
        missing_pct=100*count.missing/count.n if count.n else 0
        overall=query("SELECT COUNT(*) n,SUM(aqi IS NULL) missing FROM city_day_aqi").iloc[0]
        overall_missing=100*overall.missing/overall.n if overall.n else 0
        st.write(f"**Limitations:** {missing_pct:.1f}% of city-day records in this selection have no computable AQI ({overall_missing:.1f}% overall). Daily CO and ozone inputs approximate measures that CPCB normally assesses over 8 hours. Some coordinates may be approximate. City averages and coverage can change as monitoring networks change.")
        st.subheader("Data completeness by year")
        completeness=query("SELECT YEAR(`date`) year,COUNT(*) city_days,SUM(aqi IS NOT NULL) valid_aqi_days,ROUND(100*SUM(aqi IS NOT NULL)/COUNT(*),1) completeness_pct FROM city_day_aqi WHERE city_id=:city GROUP BY YEAR(`date`) ORDER BY year",{"city":city_id})
        completeness_display=completeness.rename(columns={"year":"Year","city_days":"City-days with observations","valid_aqi_days":"Days with computable AQI","completeness_pct":"AQI completeness (%)"})
        st.dataframe(completeness_display, width="stretch", hide_index=True); download_csv(completeness_display,"Download this data as CSV","data_completeness.csv")
        st.subheader("Agreement with Kaggle's city AQI")
        validation_path=ROOT/"docs"/"aqi_validation.md"
        if validation_path.exists():
            st.markdown(validation_path.read_text(encoding="utf-8"))
        st.subheader("Glossary")
        st.markdown("- **AQI:** Air Quality Index, a simple scale summarizing air pollution.\n- **PM2.5:** Fine particles small enough to travel deep into the lungs (µg/m³).\n- **PM10:** Larger inhalable particles (µg/m³).\n- **NO₂:** Nitrogen dioxide, commonly linked to combustion (µg/m³).\n- **O₃:** Ground-level ozone (µg/m³).\n- **CO:** Carbon monoxide (mg/m³).\n- **Valid day:** A date with a computable AQI.")
    st.divider()
    st.caption(f"Data coverage: {first_day:%d %b %Y} – {last_day:%d %b %Y} · Sources: CPCB via Kaggle and matched OpenAQ (Delhi). Hospital, disease, and admission data shown anywhere in this dashboard is simulated and is not medical evidence.")
except (SQLAlchemyError, OSError) as exc:
    message_for_db_error(exc)

