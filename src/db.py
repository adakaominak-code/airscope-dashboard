import sys
from contextlib import contextmanager
from pathlib import Path
from sqlalchemy import URL, create_engine, text
from src.config import DB, DB_CONNECT_TIMEOUT, DB_SSL_CA


def connection_options():
    """Keep local XAMPP defaults; verify remote TLS when a CA file is supplied."""
    options = {"connect_timeout": DB_CONNECT_TIMEOUT}
    if DB_SSL_CA:
        options.update(ssl_ca=DB_SSL_CA, ssl_verify_cert=True, ssl_verify_identity=True)
    return options

def engine():
    import os
    if os.getenv('AIRSCOPE_SQLITE_PATH'):
        from src.cloud_database import snapshot_engine
        return snapshot_engine(os.environ['AIRSCOPE_SQLITE_PATH'])
    url = URL.create(
        "mysql+pymysql", username=DB['user'], password=DB['password'],
        host=DB['host'], port=DB['port'], database=DB['database'],
        query={"charset": "utf8mb4"},
    )
    return create_engine(
        url, future=True, pool_pre_ping=True, pool_recycle=300,
        connect_args=connection_options(),
    )

@contextmanager
def staging_load_lock(timeout=180):
    """Serialize ETL jobs that share the staging_reading table."""
    db = engine()
    with db.connect() as con:
        acquired = con.execute(text("SELECT GET_LOCK('urban_air_health_staging_load', :timeout)"), {'timeout': timeout}).scalar()
        con.commit()
        if acquired != 1:
            raise TimeoutError('Another reading load is active; wait for it to finish and retry.')
        try:
            yield
        finally:
            con.execute(text("SELECT RELEASE_LOCK('urban_air_health_staging_load')"))
            con.commit()

def run_file(path):
    # mysql routines contain semicolons; driver needs whole multi-statement splitting.
    import pymysql
    script=Path(path).read_text(encoding='utf8').replace('DELIMITER $$','').replace('DELIMITER ;','').replace('$$',';')
    params=dict(DB)
    params.update(connection_options(), charset='utf8mb4')
    if Path(path).name == '01_schema.sql':
        params.pop('database', None)
    con=pymysql.connect(**params, autocommit=True, client_flag=pymysql.constants.CLIENT.MULTI_STATEMENTS)
    try:
        with con.cursor() as cur:
            cur.execute(script)
            while cur.nextset(): pass
    finally: con.close()
if __name__ == '__main__':
    if len(sys.argv)>2 and sys.argv[1]=='run-sql':
        for f in sys.argv[2:]: run_file(f)
