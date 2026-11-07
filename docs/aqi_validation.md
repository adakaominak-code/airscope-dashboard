# AQI validation against Kaggle city-day AQI

The measured comparison joins `data/raw/city_day.csv` to the current refreshed `city_day_aqi` by city and date. Kaggle rows with AQI above 400 are excluded because Kaggle's AQI field is uncapped while this implementation caps its output at 500. Because the live city-day table includes CPCB and matched Delhi OpenAQ station readings where dates overlap, this is a comparison of the current blended city aggregation against the CPCB Kaggle city AQI, not a CPCB-only recomputation. Rows compared are limited to matching Kaggle dates.

| Measure | Result |
|---|---:|
| Rows compared | 23,449 |
| Pearson correlation | 0.9412 |
| Mean absolute error (AQI points) | 20.41 |
| Bias (ours minus Kaggle, AQI points) | -7.82 |
| Exact integer match | 2.20% |
| Same category | 74.38% |

These are agreement measures, not independent ground truth: both results derive from CPCB monitoring data, while the current summary additionally includes matched OpenAQ readings where available and averages station-level AQIs before computing the city-day value.
