"""Fetch 2026 year-to-date OpenAQ daily data for Kaggle-matched Delhi stations."""
import os
import re
import time
import argparse
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

from src.config import ROOT

BASE = 'https://api.openaq.org/v3'
DELHI_BBOX = (28.35, 28.90, 76.75, 77.50)
ALIASES = {
    'dtu': 'delhi technological university',
    'ito': 'income tax office',
    'dr karni singh shooting range': 'karni singh shooting range',
}


def key(name):
    value = str(name).lower()
    value = re.sub(r'\b(new\s+)?delhi\b', ' ', value)
    value = re.sub(r'\b(dpcc|cpcb|imd|iim|iitm|imd|hspcb)\b', ' ', value)
    value = re.sub(r'[^a-z0-9]+', ' ', value).strip()
    value = re.sub(r'\s+', ' ', value)
    for short, long in ALIASES.items():
        if value == short or value.startswith(short + ' '):
            value = value.replace(short, long, 1)
    return value


def get(session, path, params=None):
    for attempt in range(7):
        try:
            response = session.get(BASE + path, params=params, timeout=(15, 90))
        except requests.exceptions.RequestException:
            if attempt == 6:
                raise
            time.sleep(min(2 ** attempt, 30))
            continue
        if response.status_code == 429 or response.status_code >= 500:
            time.sleep(min(2 ** attempt, 30))
            continue
        response.raise_for_status()
        return response.json()
    raise RuntimeError(f'OpenAQ request repeatedly failed: {path}')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--start', default='2026-01-01')
    parser.add_argument('--end', default='2026-11-06')
    args = parser.parse_args()
    start_date = date.fromisoformat(args.start)
    end_date = date.fromisoformat(args.end)
    if end_date < start_date:
        raise ValueError('--end must be on or after --start')
    start = start_date.isoformat()
    end = end_date.isoformat()
    api_to = (end_date + timedelta(days=1)).isoformat()
    tag = f'{start[:4]}_{end[:4]}'
    load_dotenv(ROOT / '.env')
    api_key = os.getenv('OPENAQ_API_KEY', '').strip()
    if not api_key:
        raise RuntimeError('Set OPENAQ_API_KEY in .env before fetching OpenAQ readings.')

    kaggle = pd.read_csv(ROOT / 'data' / 'raw' / 'stations.csv')
    kaggle = kaggle[kaggle['City'].astype(str).str.casefold().eq('delhi')].copy()
    kaggle['match_key'] = kaggle['StationName'].map(key)
    locations = pd.read_csv(ROOT / 'stations.csv')
    locations['lat'] = pd.to_numeric(locations['lat'], errors='coerce')
    locations['lon'] = pd.to_numeric(locations['lon'], errors='coerce')
    locations = locations.dropna(subset=['location_id', 'lat', 'lon'])
    south, north, west, east = DELHI_BBOX
    locations = locations[locations['lat'].between(south, north) & locations['lon'].between(west, east)].copy()
    locations['match_key'] = locations['name'].map(key)

    matches = []
    for station in kaggle.itertuples(index=False):
        station_key = station.match_key
        candidates = locations[
            locations['match_key'].eq(station_key)
            | locations['match_key'].str.startswith(station_key + ' ')
            | locations['match_key'].str.startswith(station_key + ',')
            | locations['match_key'].apply(lambda candidate: len(candidate) >= 6 and candidate in station_key)
        ]
        for loc in candidates.itertuples(index=False):
            matches.append({'StationId': station.StationId, 'StationName': station.StationName,
                            'location_id': int(loc.location_id), 'name': loc.name,
                            'lat': float(loc.lat), 'lon': float(loc.lon)})
    match_df = pd.DataFrame(matches).drop_duplicates(['StationId', 'location_id'])
    if match_df.empty:
        raise RuntimeError('No matching Delhi stations found between the supplied Kaggle and OpenAQ station lists.')
    print(f'Matched {match_df.StationId.nunique()} Kaggle stations to {match_df.location_id.nunique()} OpenAQ locations; checking sensor coverage.', flush=True)

    session = requests.Session()
    session.headers.update({'X-API-Key': api_key, 'Accept': 'application/json'})
    out = ROOT / 'data' / 'processed'
    out.mkdir(parents=True, exist_ok=True)
    station_path = out / f'delhi_openaq_{tag}_matched_stations.csv'
    readings_path = out / f'delhi_openaq_{tag}_matched_readings.csv'
    report_path = out / f'delhi_openaq_{tag}_match_report.csv'
    checkpoint_path = out / f'.delhi_openaq_{tag}_readings_checkpoint.csv'
    done_path = out / f'.delhi_openaq_{tag}_locations_done.txt'
    rows = pd.read_csv(checkpoint_path).to_dict('records') if checkpoint_path.exists() else []
    done = set(done_path.read_text(encoding='utf-8').splitlines()) if done_path.exists() else set()
    location_ids = sorted(match_df['location_id'].unique())
    for location_number, loc_id in enumerate(location_ids, 1):
        if str(loc_id) in done:
            print(f'Location {location_number}/{len(location_ids)} already saved; skipping.', flush=True)
            continue
        loc = match_df[match_df.location_id == loc_id].iloc[0]
        sensor_page = get(session, f'/locations/{loc_id}/sensors', {'limit': 1000, 'page': 1})
        sensors = sensor_page.get('results', [])
        location_rows = []
        for sensor in sensors:
            parameter = sensor.get('parameter', {})
            pollutant = str(parameter.get('name', '')).strip().lower()
            if pollutant not in {'pm25', 'pm2.5', 'pm10', 'no', 'no2', 'nox', 'nh3', 'co', 'so2', 'o3', 'benzene', 'toluene', 'xylene'}:
                continue
            last = sensor.get('datetimeLast', {})
            last_date = str(last.get('local') or last.get('utc') or '')[:10] if isinstance(last, dict) else str(last)[:10]
            first = sensor.get('datetimeFirst', {})
            first_date = str(first.get('local') or first.get('utc') or '')[:10] if isinstance(first, dict) else str(first)[:10]
            if (last_date and last_date < start) or (first_date and first_date > end):
                continue
            sensor_id = sensor.get('id')
            page = 1
            while True:
                payload = get(session, f'/sensors/{sensor_id}/days', {
                    'date_from': start, 'date_to': api_to, 'limit': 1000, 'page': page
                })
                results = payload.get('results', [])
                for item in results:
                    period = item.get('period', {}).get('datetimeFrom', {})
                    local_dt = period.get('local') or period.get('utc') or ''
                    day = str(local_dt)[:10]
                    if start <= day <= end:
                        location_rows.append({'location_id': int(loc_id), 'sensor_id': int(sensor_id),
                                              'pollutant': pollutant, 'unit': parameter.get('units'),
                                              'date': day, 'value': item.get('value')})
                meta = payload.get('meta', {})
                found = meta.get('found')
                if not results or len(results) < 1000 or (found is not None and page * 1000 >= found):
                    break
                page += 1
            time.sleep(0.05)
        if location_rows:
            pd.DataFrame(location_rows).to_csv(checkpoint_path, mode='a', header=not checkpoint_path.exists(), index=False)
            rows.extend(location_rows)
        with done_path.open('a', encoding='utf-8') as stream:
            stream.write(f'{loc_id}\n')
        done.add(str(loc_id))
        print(f'Checked location {location_number}/{len(location_ids)}; records collected so far: {len(rows)}.', flush=True)

    match_df[['location_id', 'name', 'lat', 'lon']].drop_duplicates('location_id').to_csv(station_path, index=False)
    pd.DataFrame(rows, columns=['location_id', 'sensor_id', 'pollutant', 'unit', 'date', 'value']).to_csv(readings_path, index=False)
    match_df.to_csv(report_path, index=False)
    checkpoint_path.unlink(missing_ok=True)
    done_path.unlink(missing_ok=True)
    print(f'Matched {match_df.StationId.nunique()} Kaggle stations to {match_df.location_id.nunique()} OpenAQ locations.')
    print(f'Fetched {len(rows)} daily sensor records for {start} through {end}.')
    print(f'Readings: {readings_path}')
    print(f'Stations: {station_path}')
    print(f'Match audit: {report_path}')


if __name__ == '__main__':
    main()
