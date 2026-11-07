"""Read-only cloud snapshot; local development continues to use XAMPP."""
import math
import re
from pathlib import Path
from sqlalchemy import create_engine, event


def portable_sql(statement):
    statement = re.sub(
        r"DATE_(ADD|SUB)\(([^,]+),\s*INTERVAL\s+(\d+)\s+DAY\)",
        lambda m: f"date({m[2]}, '{'+' if m[1].upper() == 'ADD' else '-'}{m[3]} day')",
        statement, flags=re.I,
    )
    # MySQL divides integers as decimals; SQLite otherwise truncates percentages.
    statement = statement.replace('SUM(v.aqi>200)/', '1.0*SUM(v.aqi>200)/')
    return statement.replace('100*SUM(', '100.0*SUM(')


def snapshot_engine(path):
    uri = Path(path).resolve().as_uri() + '?mode=ro&immutable=1'
    import sqlite3
    db = create_engine('sqlite://', creator=lambda: sqlite3.connect(uri, uri=True, check_same_thread=False))

    @event.listens_for(db, 'connect')
    def functions(connection, record):
        connection.create_function('YEAR', 1, lambda x: int(str(x)[:4]) if x else None, deterministic=True)
        # FLOAT matches MySQL FLOOR(DECIMAL), including division in the CO formula.
        connection.create_function('FLOOR', 1, lambda x: float(math.floor(x)) if x is not None else None, deterministic=True)

    @event.listens_for(db, 'before_cursor_execute', retval=True)
    def translate(connection, cursor, statement, parameters, context, many):
        return portable_sql(statement), parameters

    return db
