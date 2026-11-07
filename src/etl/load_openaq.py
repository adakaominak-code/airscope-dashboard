"""Load the supplied OpenAQ location and daily-reading CSV files."""
import argparse
import math
import time
from pathlib import Path

import pandas as pd
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from src.config import DOCS, RAW, REJECTED, ROOT
from src.db import engine, staging_load_lock
from src.etl.clean_and_load import CITIES, LIMITS

POLLUTANT_NAMES = {
    'pm25': 'PM2.5', 'pm2.5': 'PM2.5', 'pm10': 'PM10',
    'no': 'NO', 'no2': 'NO2', 'nox': 'NOx', 'nh3': 'NH3',
    'co': 'CO', 'so2': 'SO2', 'o3': 'O3', 'benzene': 'Benzene',
    'toluene': 'Toluene', 'xylene': 'Xylene',
}
CITY_RADIUS_KM = 60


def nearest_city(lat, lon):
    best = (None, float('inf'))
    for name, (state, city_lat, city_lon, _) in CITIES.items():
        distance = 2 * 6371 * math.asin(math.sqrt(
            math.sin(math.radians(lat - city_lat) / 2) ** 2
            + math.cos(math.radians(city_lat)) * math.cos(math.radians(lat))
            * math.sin(math.radians(lon - city_lon) / 2) ** 2
        ))
        if distance < best[1]:
            best = (name, distance)
    return best if best[1] <= CITY_RADIUS_KM else (None, best[1])


def canonical_unit(value):
    return str(value).strip().lower().replace('μ', 'u').replace('µ', 'u').replace('³', '3').replace(' ', '')


def normalize_id(value):
    if pd.isna(value):
        return None
    result = str(value).strip()
    return result[:-2] if result.endswith('.0') else result


def main():
    parser = argparse.ArgumentParser()
    processed = ROOT / 'data' / 'processed'
    parser.add_argument('--stations', type=Path, default=processed / 'delhi_openaq_2026_matched_stations.csv' if (processed / 'delhi_openaq_2026_matched_stations.csv').exists() else ROOT / 'stations.csv')
    parser.add_argument('--readings', type=Path, default=processed / 'delhi_openaq_2026_matched_readings.csv' if (processed / 'delhi_openaq_2026_matched_readings.csv').exists() else ROOT / 'readings.csv')
    parser.add_argument('--match-report', type=Path, default=processed / 'delhi_openaq_2026_match_report.csv')
    args = parser.parse_args()
    for path in (args.stations, args.readings):
        if not path.is_file():
            raise FileNotFoundError(f'OpenAQ input not found: {path}')

    stations = pd.read_csv(args.stations)
    readings = pd.read_csv(args.readings)
    required_stations = {'location_id', 'name', 'lat', 'lon'}
    required_readings = {'location_id', 'pollutant', 'unit', 'date', 'value'}
    if not required_stations.issubset(stations.columns):
        raise ValueError(f'{args.stations} must contain: {sorted(required_stations)}')
    if not required_readings.issubset(readings.columns):
        raise ValueError(f'{args.readings} must contain: {sorted(required_readings)}')

    stations['location_id'] = stations['location_id'].map(normalize_id)
    stations['lat'] = pd.to_numeric(stations['lat'], errors='coerce')
    stations['lon'] = pd.to_numeric(stations['lon'], errors='coerce')
    stations = stations.dropna(subset=['location_id', 'name', 'lat', 'lon']).drop_duplicates('location_id')
    assignments = {}
    matched_delhi = {}
    if args.match_report.is_file():
        match_report = pd.read_csv(args.match_report)
        if {'location_id','StationId'}.issubset(match_report.columns):
            matched_delhi = {normalize_id(r.location_id): 'Delhi' for r in match_report.itertuples(index=False)}
    for row in stations.itertuples(index=False):
        city, distance = nearest_city(float(row.lat), float(row.lon))
        city = matched_delhi.get(normalize_id(row.location_id), city)
        assignments[normalize_id(row.location_id)] = (row, city, distance)

    readings['location_id'] = readings['location_id'].map(normalize_id)
    readings['pollutant_name'] = readings['pollutant'].astype(str).str.strip().str.lower().map(POLLUTANT_NAMES)
    readings['timestamp'] = pd.to_datetime(readings['date'], errors='coerce').dt.normalize()
    readings['value'] = pd.to_numeric(readings['value'], errors='coerce')
    readings['unit_norm'] = readings['unit'].map(canonical_unit)
    readings['source_station_code'] = 'OA-' + readings['location_id']
    reasons = []
    accepted = []
    for row in readings.itertuples(index=False):
        reason = None
        assignment = assignments.get(row.location_id)
        if assignment is None:
            reason = 'station_metadata_missing'
        elif assignment[1] is None:
            reason = 'outside_configured_city_radius'
        elif pd.isna(row.timestamp) or pd.isna(row.value):
            reason = 'invalid_date_or_value'
        elif pd.isna(row.pollutant_name):
            reason = 'unsupported_pollutant'
        else:
            expected = 'mg/m3' if row.pollutant_name == 'CO' else 'ug/m3'
            val = float(row.value)
            if row.pollutant_name == 'CO' and row.unit_norm == 'ug/m3':
                val /= 1000
            elif row.unit_norm != expected:
                reason = 'unsupported_unit'
            if reason is None and (val < 0 or val > LIMITS[row.pollutant_name]):
                reason = 'negative_or_physical_outlier'
        if reason:
            reasons.append({'location_id': row.location_id, 'pollutant': row.pollutant,
                            'date': row.date, 'value': row.value, 'unit': row.unit,
                            'reason': reason})
            continue
        accepted.append({'source_station_code': row.source_station_code,
                         'pollutant_name': row.pollutant_name, 'timestamp': row.timestamp,
                         'value': val})

    long = pd.DataFrame(accepted, columns=['source_station_code', 'pollutant_name', 'timestamp', 'value'])
    if not long.empty:
        long = long.groupby(['source_station_code', 'pollutant_name', 'timestamp'], as_index=False)['value'].mean()
        long['source'] = 'openaq'

    e = engine()
    REJECTED.mkdir(parents=True, exist_ok=True)
    DOCS.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(reasons).to_csv(REJECTED / 'rejected_openaq_readings.csv', index=False)
    with staging_load_lock():
        with e.begin() as con:
            con.execute(text("UPDATE station SET source='openaq',coordinates_approximate=FALSE,city_id=(SELECT city_id FROM city WHERE name='Delhi') WHERE source_station_code LIKE 'OA-%'"))
            con.execute(text("UPDATE reading r JOIN station s ON s.station_id=r.station_id SET r.source='openaq' WHERE s.source_station_code LIKE 'OA-%'"))
            for state in sorted({CITIES[city][0] for _, city, _ in assignments.values() if city}):
                con.execute(text('INSERT IGNORE INTO state(name) VALUES (:name)'), {'name': state})
            for city in sorted({city for _, city, _ in assignments.values() if city}):
                state, _, _, population = CITIES[city]
                con.execute(text('INSERT IGNORE INTO city(name,state_id,population) SELECT :city,state_id,:population FROM state WHERE name=:state'),
                            {'city': city, 'state': state, 'population': population})
            for location_id, (row, city, _) in assignments.items():
                if city is None:
                    continue
                station_code = f'OA-{location_id}'
                name = str(row.name).strip()
                lowered = name.lower()
                kind = 'industrial' if any(word in lowered for word in ('industrial', 'industries', 'sidco')) else ('traffic' if any(word in lowered for word in ('road', 'chowk', 'crossing', 'isbt')) else 'residential')
                con.execute(text("INSERT IGNORE INTO station(source_station_code,name,city_id,latitude,longitude,station_type,coordinates_approximate,source) SELECT :code,:name,city_id,:lat,:lon,:kind,FALSE,'openaq' FROM city WHERE name=:city"),
                            {'code': station_code, 'name': name, 'city': city, 'lat': float(row.lat), 'lon': float(row.lon), 'kind': kind})
            con.execute(text('TRUNCATE TABLE staging_reading'))

        batch_size = 2000
        for offset in range(0, len(long), batch_size):
            batch = long.iloc[offset:offset + batch_size]
            with e.begin() as con:
                batch.to_sql('staging_reading', con, if_exists='append', index=False, method='multi', chunksize=1000)
            for attempt in range(4):
                try:
                    with e.connect() as con:
                        con.execute(text('SET @skip_alert_trigger=1'))
                        con.execute(text('CALL sp_bulk_load_readings()'))
                        con.commit()
                    break
                except OperationalError as exc:
                    with e.connect() as cleanup:
                        cleanup.execute(text('SET @skip_alert_trigger=0'))
                        cleanup.commit()
                    code = getattr(getattr(exc, 'orig', None), 'args', [None])[0]
                    if code != 1213 or attempt == 3:
                        raise
                    time.sleep(2 ** attempt)
            print(f'Imported {min(offset + len(batch), len(long)):,}/{len(long):,} OpenAQ rows.', flush=True)

        with e.connect() as con:
            con.execute(text('SET @skip_alert_trigger=0'))
            con.execute(text('DELETE FROM alert WHERE YEAR(alert_date)=2026'))
            con.execute(text('CALL sp_refresh_city_day_aqi()'))
            con.execute(text('CALL sp_backfill_alerts()'))
            con.commit()

    start = long['timestamp'].min().date() if not long.empty else None
    end = long['timestamp'].max().date() if not long.empty else None
    mapped = sum(city is not None for _, city, _ in assignments.values())
    report = f'''# OpenAQ loading report

Source files: `{args.stations.name}` and `{args.readings.name}`.

- Locations supplied: {len(stations)}
- Locations within {CITY_RADIUS_KM} km of a configured city center: {mapped}
- Distinct normalized readings loaded/updated: {len(long)}
- Rejected source rows: {len(reasons)}
- Date range loaded: {start} to {end}
- Unmapped locations are skipped; unsupported pollutant units (including gases in ppb) are rejected rather than converted without temperature/pressure data.
- OpenAQ location coordinates are supplied coordinates. Matched Delhi station IDs in the fetch audit are assigned to Delhi; other locations are assigned to the nearest configured city within {CITY_RADIUS_KM} km.
- Station and reading provenance is stored as `openaq`; CPCB Kaggle and sample imports retain their own separate source labels.
'''
    (DOCS / 'openaq_loading_report.md').write_text(report, encoding='utf-8')
    print(f'Loaded or updated {len(long)} OpenAQ readings; rejected {len(reasons)} source rows.')


if __name__ == '__main__':
    main()
