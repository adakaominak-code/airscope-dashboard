from pathlib import Path
import os
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env')
DB = {"host": os.getenv('DB_HOST','127.0.0.1'), "port": int(os.getenv('DB_PORT','3306')),
      "user": os.getenv('DB_USER','root'), "password": os.getenv('DB_PASSWORD',''),
      "database": os.getenv('DB_NAME','urban_air_health')}
DB_SSL_CA = os.getenv('DB_SSL_CA', '').strip()
DB_CONNECT_TIMEOUT = int(os.getenv('DB_CONNECT_TIMEOUT', '10'))
if not 1 <= DB_CONNECT_TIMEOUT <= 31536000:
    raise ValueError('DB_CONNECT_TIMEOUT must be between 1 and 31536000 seconds')
SEED = int(os.getenv('RANDOM_SEED','20261106'))
RAW = ROOT/'data'/'raw'; REJECTED = ROOT/'data'/'rejected'; DOCS = ROOT/'docs'
