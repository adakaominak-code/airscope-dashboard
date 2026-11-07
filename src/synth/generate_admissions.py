"""Generate clearly labeled simulated admissions for the method demonstration."""
import argparse

import numpy as np
import pandas as pd
from sqlalchemy import text

from src.config import DOCS, SEED
from src.db import engine


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--target', type=int, default=300000)
    args = parser.parse_args()
    rng = np.random.default_rng(SEED)
    db = engine()
    with db.begin() as con:
        cities = pd.read_sql(text('SELECT city_id,name FROM city ORDER BY city_id'), con)
        observed = pd.read_sql(text('SELECT city_id,`date`,aqi FROM city_day_aqi ORDER BY city_id,`date`'), con)
        con.execute(text('DELETE FROM admission'))
        for _, city in cities.iterrows():
            for hospital_number in range(1, 4):
                con.execute(text('INSERT IGNORE INTO hospital(name,city_id) VALUES (:name,:city_id)'), {
                    'name': f'Simulated {city["name"]} {hospital_number} General Hospital',
                    'city_id': int(city['city_id']),
                })
        hospitals = pd.read_sql(text('SELECT hospital_id,city_id FROM hospital'), con)
        diseases = pd.read_sql(text('SELECT disease_id,name,is_respiratory FROM disease'), con)

    observed['date'] = pd.to_datetime(observed['date'])
    complete = []
    for city_id, group in observed.groupby('city_id'):
        all_days = pd.date_range(group['date'].min(), group['date'].max(), freq='D')
        daily = group.set_index('date').reindex(all_days)
        daily['city_id'] = city_id
        daily['lag_aqi'] = daily['aqi'].shift(1).ffill().fillna(group['aqi'].median())
        complete.append(daily.rename_axis('date').reset_index()[['city_id', 'date', 'lag_aqi']])
    days = pd.concat(complete, ignore_index=True)

    factors = {'Asthma': 1.0, 'COPD': .9, 'Acute Bronchitis': .65,
               'Pneumonia': .55, 'Acute Respiratory Infection': .8,
               'Fracture': .35, 'Gastroenteritis': .35, 'Diabetes Complication': .3}
    scale = args.target / (sum(factors.values()) * len(days))
    pending = []

    def flush():
        nonlocal pending
        if pending:
            with db.begin() as con:
                con.execute(text('INSERT INTO admission(hospital_id,admit_date,disease_id,age_group,patient_gender,is_synthetic) VALUES (:hospital,:day,:disease,:age,:gender,1)'), pending)
            pending = []

    for day_number, (_, day) in enumerate(days.iterrows(), 1):
        available_hospitals = hospitals.loc[hospitals.city_id.eq(day['city_id']), 'hospital_id'].to_numpy()
        for _, disease in diseases.iterrows():
            respiratory = bool(disease['is_respiratory'])
            weekday_factor = 1.12 if day['date'].weekday() < 5 else .9
            lam = scale * factors[disease['name']] * (1 + (.55 if respiratory else 0) * day['lag_aqi'] / 250) * weekday_factor
            for _ in range(rng.poisson(lam)):
                pending.append({
                    'hospital': int(rng.choice(available_hospitals)), 'day': day['date'].date(),
                    'disease': int(disease['disease_id']),
                    'age': rng.choice(['0-17', '18-44', '45-64', '65+'], p=[.25,.30,.20,.25] if respiratory else [.15,.45,.27,.13]),
                    'gender': rng.choice(['M','F','O'], p=[.49,.49,.02]),
                })
        if len(pending) >= 10000:
            flush()
        if day_number % 10000 == 0:
            print(f'Generated simulated records for {day_number:,}/{len(days):,} city-days.', flush=True)
    flush()

    with db.connect() as con:
        total = con.execute(text('SELECT COUNT(*) FROM admission')).scalar()
    DOCS.mkdir(exist_ok=True)
    (DOCS / 'synthetic_data_methodology.md').write_text(f'''# Simulated health data methodology

**HEALTH DATA IS SIMULATED.** Seed: `{SEED}`. Generated admissions: {total}. This generator uses a Poisson model with a one-calendar-day lagged AQI, a built-in respiratory response, weekday variation, and fictional hospitals and patient demographics. Control diseases have no AQI multiplier.

## Limitations

There are no real patient records. The city-level model omits weather, epidemics, access to care, and socioeconomic factors. The respiratory relationship is intentionally built into the generator, so a correlation with AQI is circular and is not evidence of a real health effect.
''', encoding='utf-8')
    print(f'Generated {total:,} simulated admissions across {len(cities)} cities and {len(days):,} city-days.')


if __name__ == '__main__':
    main()
