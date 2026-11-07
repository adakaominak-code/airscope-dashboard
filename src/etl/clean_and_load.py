"""Clean Kaggle station_day data into the normalized Reading table; --sample creates compatible fallback files."""
import argparse, hashlib
from pathlib import Path
import numpy as np, pandas as pd
from sqlalchemy import text
from src.config import RAW, REJECTED, DOCS, SEED
from src.db import engine, staging_load_lock
POLS=['PM2.5','PM10','NO','NO2','NOx','NH3','CO','SO2','O3','Benzene','Toluene','Xylene']
CITIES={
 'Ahmedabad':('Gujarat',23.0225,72.5714,5570585),'Aizawl':('Mizoram',23.7271,92.7176,293416),'Amaravati':('Andhra Pradesh',16.5062,80.6480,1030000),'Amritsar':('Punjab',31.6340,74.8723,1132383),
 'Bengaluru':('Karnataka',12.9716,77.5946,8443675),'Bhopal':('Madhya Pradesh',23.2599,77.4126,1798218),'Brajrajnagar':('Odisha',21.8167,83.9167,81000),'Chandigarh':('Chandigarh',30.7333,76.7794,1055450),
 'Chennai':('Tamil Nadu',13.0827,80.2707,4646732),'Coimbatore':('Tamil Nadu',11.0168,76.9558,1061447),'Delhi':('Delhi',28.6139,77.2090,16787941),'Ernakulam':('Kerala',9.9816,76.2999,677381),
 'Gurugram':('Haryana',28.4595,77.0266,876824),'Guwahati':('Assam',26.1445,91.7362,957352),'Hyderabad':('Telangana',17.3850,78.4867,6993262),'Jaipur':('Rajasthan',26.9124,75.7873,3046163),
 'Jorapokhar':('Jharkhand',23.7200,86.4100,120000),'Kochi':('Kerala',9.9312,76.2673,677381),'Kolkata':('West Bengal',22.5726,88.3639,4486679),'Lucknow':('Uttar Pradesh',26.8467,80.9462,2817105),
 'Mumbai':('Maharashtra',19.0760,72.8777,12442373),'Patna':('Bihar',25.5941,85.1376,1684222),'Shillong':('Meghalaya',25.5788,91.8933,143229),'Talcher':('Odisha',20.9500,85.2300,400000),
 'Thiruvananthapuram':('Kerala',8.5241,76.9366,957730),'Visakhapatnam':('Andhra Pradesh',17.6868,83.2185,1730320)
}
LIMITS={'PM2.5':1000,'PM10':1500,'NO':1000,'NO2':1000,'NOx':1500,'NH3':3000,'CO':100,'SO2':3000,'O3':2000,'Benzene':500,'Toluene':1000,'Xylene':1000}
def station_key(value):
 import re
 return re.sub(r'[^a-z0-9]+',' ',str(value).casefold()).strip()
def sample():
 out=RAW.parent/'sample'; out.mkdir(parents=True,exist_ok=True); rng=np.random.default_rng(SEED); dates=pd.date_range('2018-01-01','2020-12-31'); sts=[]; rows=[]
 for city,(state,_,_,_) in CITIES.items():
  for j in range(2):
   code=f'{city[:3].upper()}{j+1:03d}'; sts.append({'StationId':code,'StationName':f'{city} {"Industrial" if j else "Central"} Monitoring Station','City':city,'State':state})
   seasonal=1+0.65*np.cos(2*np.pi*(dates.dayofyear-15)/365)
   for d,s in zip(dates,seasonal):
    base={'PM2.5':55,'PM10':105,'NO':18,'NO2':43,'NOx':52,'NH3':30,'CO':1.2,'SO2':16,'O3':34,'Benzene':2,'Toluene':6,'Xylene':2}
    row={'StationId':code,'Date':d.strftime('%Y-%m-%d'),'AQI':np.nan,'AQI_Bucket':None}
    for p,v in base.items(): row[p]=round(max(0,rng.normal(v*s, max(1,v*.15))),2) if rng.random()>.025 else np.nan
    rows.append(row)
 pd.DataFrame(sts).to_csv(out/'stations.csv',index=False); pd.DataFrame(rows).to_csv(out/'station_day.csv',index=False); pd.DataFrame().to_csv(out/'city_day.csv',index=False)
 return out
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--sample',action='store_true'); a=ap.parse_args()
 source=sample() if a.sample else RAW
 missing=[name for name in ('stations.csv','station_day.csv') if not (source/name).exists()]
 if missing:
  raise FileNotFoundError(f"Missing required input(s) in {source}: {', '.join(missing)}. Supply the Kaggle CSVs or pass --sample.")
 stations=pd.read_csv(source/'stations.csv'); day=pd.read_csv(source/'station_day.csv'); stations.columns=stations.columns.str.strip(); day.columns=day.columns.str.strip(); day['Date']=pd.to_datetime(day['Date'],errors='coerce')
 stations=stations[stations.StationId.astype(str).isin(day.StationId.astype(str))].copy()
 source_name='sample' if a.sample else 'cpcb_kaggle'
 oa_path=RAW.parent/'openaq'/'stations.csv'; oa={}
 if not a.sample and oa_path.exists():
  oa_df=pd.read_csv(oa_path)
  if {'name','lat','lon'}.issubset(oa_df.columns):
   oa_df['match_key']=oa_df.name.map(station_key)
   oa={r.match_key:(float(r.lat),float(r.lon)) for r in oa_df.itertuples() if pd.notna(r.lat) and pd.notna(r.lon)}
 con=engine(); REJECTED.mkdir(parents=True,exist_ok=True); DOCS.mkdir(parents=True,exist_ok=True)
 state_names=stations.State.dropna().astype(str).str.strip().drop_duplicates().tolist()
 with con.begin() as c:
  c.execute(text('INSERT IGNORE INTO state(name) VALUES (:name)'),[{'name':x} for x in state_names])
 with con.connect() as c: state_ids={name:int(sid) for sid,name in c.execute(text('SELECT state_id,name FROM state')).all()}
 city_rows=[]
 for city,state in stations[['City','State']].drop_duplicates().itertuples(index=False,name=None):
  city=str(city).strip(); state=str(state).strip(); meta=CITIES.get(city,(state,None,None,None))
  city_rows.append({'city':city,'state_id':state_ids[state],'pop':meta[3]})
 with con.begin() as c:
  c.execute(text('INSERT IGNORE INTO city(name,state_id,population) VALUES (:city,:state_id,:pop)'),city_rows)
 with con.connect() as c: city_ids={name:int(cid) for cid,name in c.execute(text('SELECT city_id,name FROM city')).all()}
 station_rows=[]
 for r in stations.itertuples(index=False):
  city=str(r.City).strip(); meta=CITIES.get(city,(str(r.State).strip(),None,None,None)); exact=oa.get(station_key(r.StationName))
  if exact: lat,lon=exact; approx=0
  elif meta[1] is None or meta[2] is None: lat=lon=None; approx=1
  else:
   h=int(hashlib.sha1(str(r.StationId).encode()).hexdigest()[:8],16); lat=meta[1]+((h%1000)/10000-.05); lon=meta[2]+(((h//1000)%1000)/10000-.05); approx=1
  n=str(r.StationName); lower=n.lower(); typ='industrial' if any(x in lower for x in ['industrial','industries','sidco']) else ('traffic' if any(x in lower for x in ['road','chowk','crossing','isbt']) else 'unknown')
  station_rows.append({'code':str(r.StationId),'name':n,'city_id':city_ids[city],'lat':lat,'lon':lon,'typ':typ,'approx':approx,'source':source_name})
 with con.begin() as c:
  c.execute(text('INSERT IGNORE INTO station(source_station_code,name,city_id,latitude,longitude,station_type,coordinates_approximate,source) VALUES (:code,:name,:city_id,:lat,:lon,:typ,:approx,:source)'),station_rows)
 print(f'Prepared station metadata for {len(stations)} stations; reading and cleaning {len(day)} daily rows.',flush=True)
 long=day.melt(id_vars=['StationId','Date'],value_vars=[x for x in POLS if x in day],var_name='pollutant_name',value_name='value').dropna(); long=long.rename(columns={'StationId':'source_station_code','Date':'timestamp'}); long['value']=pd.to_numeric(long.value,errors='coerce')
 ceilings=long.pollutant_name.map(LIMITS); invalid=(long.value<0)|(long.value>ceilings); bad=long.loc[invalid].copy(); bad['reason']='negative_or_physical_outlier'; bad.to_csv(REJECTED/'rejected_readings.csv',index=False); good=long.loc[~invalid].drop_duplicates(['source_station_code','pollutant_name','timestamp'])
 good=good.copy(); good['source']=source_name
 chunk_rows=10000
 with staging_load_lock():
  for start in range(0,len(good),chunk_rows):
   chunk=good.iloc[start:start+chunk_rows]
   chunk.to_sql('staging_reading',con,if_exists='append',index=False,method='multi',chunksize=1000)
   with con.connect() as c:
    c.execute(text('SET @skip_alert_trigger=1')); c.execute(text('CALL sp_bulk_load_readings()')); c.commit()
   print(f'Loaded {min(start+len(chunk),len(good)):,}/{len(good):,} readings.',flush=True)
  with con.connect() as c:
   c.execute(text('SET @skip_alert_trigger=0')); c.execute(text('CALL sp_backfill_alerts()')); c.commit()
 missing=day[[p for p in POLS if p in day]].isna().sum().to_dict(); report=f'# Data cleaning report\n\nGenerated by `clean_and_load.py`. Source mode: {"sample" if a.sample else "Kaggle CSV"}.\n\n- Source wide rows: {len(day)}\n- Long non-null values loaded/updated: {len(good)}\n- Rejected: {len(bad)}\n- Stations: {len(stations)}; cities: {stations.City.nunique()}\n- Date range: {day.Date.min().date()} to {day.Date.max().date()}\n- Missing by pollutant: {missing}\n\nAQI validation was measured against `city_day.csv` after SQL objects were installed; see `docs/aqi_validation.md` for the executed metrics.\n'; (DOCS/'data_cleaning_report.md').write_text(report)
 print(f'loaded {len(good)} readings; rejected {len(bad)}')
if __name__=='__main__': main()
