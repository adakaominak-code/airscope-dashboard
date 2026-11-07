"""Fit a Poisson method check for the built-in SIMULATED respiratory AQI effect."""
import pandas as pd
import numpy as np
import statsmodels.api as sm
import statsmodels.formula.api as smf
from sqlalchemy import text

from src.config import DOCS
from src.db import engine


def main():
    with engine().connect() as con:
        aq = pd.read_sql(text('SELECT city_id,`date`,aqi FROM city_day_aqi ORDER BY city_id,`date`'), con)
        counts = pd.read_sql(text('SELECT h.city_id,a.admit_date `date`,d.is_respiratory,COUNT(*) admissions FROM admission a JOIN hospital h ON h.hospital_id=a.hospital_id JOIN disease d ON d.disease_id=a.disease_id GROUP BY h.city_id,a.admit_date,d.is_respiratory'), con)
        admission_total = con.execute(text('SELECT COUNT(*) FROM admission')).scalar()

    aq['date'] = pd.to_datetime(aq['date'])
    counts['date'] = pd.to_datetime(counts['date'])
    frames = []
    for city_id, group in aq.groupby('city_id'):
        dates = pd.date_range(group['date'].min(), group['date'].max(), freq='D')
        daily = group.set_index('date').reindex(dates)
        lag = daily['aqi'].shift(1).ffill().fillna(group['aqi'].median())
        city_counts = counts[counts.city_id.eq(city_id)].pivot(index='date',columns='is_respiratory',values='admissions').reindex(dates).fillna(0)
        for resp in (0, 1):
            y = city_counts[resp] if resp in city_counts else pd.Series(0,index=dates)
            frames.append(pd.DataFrame({'city_id':city_id,'date':dates,'lag_aqi_100':lag.to_numpy()/100,'respiratory':resp,'admissions':y.to_numpy()}))
    model_data = pd.concat(frames,ignore_index=True)
    model_data['weekday'] = pd.to_datetime(model_data['date']).dt.day_of_week
    fit = smf.glm('admissions ~ lag_aqi_100 * respiratory + C(city_id) + C(weekday)',data=model_data,family=sm.families.Poisson()).fit()

    control_beta = float(fit.params['lag_aqi_100'])
    interaction = float(fit.params['lag_aqi_100:respiratory'])
    respiratory_beta = control_beta + interaction
    control_ci = fit.conf_int().loc['lag_aqi_100'].tolist()
    control_p = float(fit.pvalues['lag_aqi_100'])
    contrast = np.zeros(len(fit.params))
    contrast[fit.params.index.get_loc('lag_aqi_100')] = 1
    contrast[fit.params.index.get_loc('lag_aqi_100:respiratory')] = 1
    resp_test = fit.t_test((contrast,0))
    resp_ci = np.asarray(resp_test.conf_int()).reshape(-1).tolist()
    resp_p = float(np.asarray(resp_test.pvalue).reshape(-1)[0])
    resp_p_display = f'{resp_p:.4g}' if resp_p > 0 else '<1e-300 (underflow)'
    expected = 1 + .55 * 100 / 250

    report = f'''# SIMULATED health-effect recovery test

**This is a method check on SIMULATED data, not evidence of a real health effect.** The generator intentionally multiplies respiratory admissions by `1 + 0.55 × previous-day AQI / 250`; control diseases have no AQI multiplier. The estimated associations therefore test whether the regression can recover the generator's known design, not whether air pollution causes real admissions.

## Fit

A Poisson generalized linear model was fit to aggregated city-day counts with previous-calendar-day AQI per 100 points, an interaction between AQI and respiratory-disease status, city fixed effects, and weekday fixed effects. Missing city dates were reindexed and lagged within city, matching the generator's calendar-day logic. Data rows: {len(model_data):,} city-day × disease-group records. SIMULATED admissions used: {admission_total:,}.

| Effect per 100 AQI points | Log coefficient | Incidence-rate ratio | 95% coefficient interval | p-value |
|---|---:|---:|---:|---:|
| Control diseases | {control_beta:.4f} | {__import__('math').exp(control_beta):.3f} | [{control_ci[0]:.4f}, {control_ci[1]:.4f}] | {control_p:.4g} |
| Respiratory diseases | {respiratory_beta:.4f} | {__import__('math').exp(respiratory_beta):.3f} | [{resp_ci[0]:.4f}, {resp_ci[1]:.4f}] | {resp_p_display} |

The generator's direct multiplicative respiratory target for a 100-point AQI increase is approximately `{expected:.3f}`. The control coefficient should remain near zero, while the respiratory AQI interaction should be positive. Sampling noise and the log-linear approximation can move fitted values away from the exact generator multiplier.
'''
    DOCS.mkdir(exist_ok=True)
    (DOCS/'health_recovery_test.md').write_text(report,encoding='utf-8')
    print(f'Poisson rows={len(model_data):,}; admissions={admission_total:,}; control beta={control_beta:.4f}, IRR={__import__("math").exp(control_beta):.3f}, p={control_p:.4g}; respiratory beta={respiratory_beta:.4f}, IRR={__import__("math").exp(respiratory_beta):.3f}, p={resp_p_display}; expected generator IRR={expected:.3f}')


if __name__ == '__main__':
    main()
