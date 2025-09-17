# trino_tool.py
import os, json, re
from typing import Optional, List
import numpy as np, requests

from dotenv import load_dotenv
from trino.dbapi import connect
from trino.auth import BasicAuthentication
from trino.exceptions import TrinoUserError
from pathlib import Path

load_dotenv(dotenv_path=Path(__file__).with_name(".env"))

# ----------------------------- ENV ----------------------------- #
TRINO_HOST     = os.getenv("TRINO_HOST", "").strip()
TRINO_PORT     = int(os.getenv("TRINO_PORT", "8080"))
TRINO_USER     = os.getenv("TRINO_USER", "").strip()
TRINO_PASSWORD = os.getenv("TRINO_PASSWORD", "").strip()
TRINO_CATALOG  = os.getenv("TRINO_CATALOG", "timescale").strip()
TRINO_SCHEMA   = os.getenv("TRINO_SCHEMA", "public").strip()

# Canonical tables
SENSOR_TABLE  = os.getenv("TRINO_SENSOR_TABLE",  "timescale.public.sensor_metadata").strip()
METRICS_TABLE = os.getenv("TRINO_METRICS_TABLE", "timescale.public.sensor_readings").strip()

# Embedding search
TRINO_TABLE   = os.getenv("TRINO_TABLE", "").strip()
EMBED_API     = os.getenv("EMBED_API", "").strip()
EMBED_MODEL   = os.getenv("EMBED_MODEL", "").strip()

# --------------------------- Connection --------------------------- #
def trino_cursor():
    conn = connect(
        host=TRINO_HOST,
        port=TRINO_PORT,
        user=TRINO_USER,
        # Only use BasicAuthentication if password is set AND you're on https
        auth=BasicAuthentication(TRINO_USER, TRINO_PASSWORD) if TRINO_PASSWORD and TRINO_HOST.startswith("https") else None,
        catalog=TRINO_CATALOG,
        schema=TRINO_SCHEMA,
    )
    return conn.cursor()


def _fq(table: str) -> str:
    """Always expand to catalog.schema.table."""
    parts = table.split(".")
    if len(parts) == 3: return table
    if len(parts) == 2: return f"{TRINO_CATALOG}.{parts[0]}.{parts[1]}"
    return f"{TRINO_CATALOG}.{TRINO_SCHEMA}.{table}"

# ----------------------------- Tools ----------------------------- #
def list_sensors() -> str:
    cur = trino_cursor()
    sql = f"""
        SELECT sensor_id,
               COALESCE(sensor_name, CAST(sensor_id AS VARCHAR)) AS name
        FROM {_fq(SENSOR_TABLE)}
        ORDER BY sensor_id
        LIMIT 200
    """
    cur.execute(sql)
    rows = cur.fetchall()
    cur.close()
    return json.dumps([{"sensor_id": r[0], "name": r[1]} for r in rows], ensure_ascii=False)

def query_sensor(sensor_id: str, start: Optional[str]=None,
                 end: Optional[str]=None, window: Optional[str]=None) -> str:
    cur = trino_cursor()
    where = [f"sensor_id = '{sensor_id}'"]
    if window:
        unit = {"s": "SECOND","m":"MINUTE","h":"HOUR","d":"DAY"}[window[-1].lower()]
        n = int(window[:-1])
        where.append(f"timestamp >= (current_timestamp - INTERVAL '{n}' {unit})")
    else:
        if start: where.append(f"timestamp >= TIMESTAMP '{start}'")
        if end:   where.append(f"timestamp <= TIMESTAMP '{end}'")
    where_sql = " AND ".join(where)

    summary_sql = f"""
        SELECT MIN(timestamp), MAX(timestamp), COUNT(*),
               AVG(value), MIN(value), MAX(value)
        FROM {_fq(METRICS_TABLE)}
        WHERE {where_sql}
    """
    cur.execute(summary_sql)
    srow = cur.fetchone()
    summary = {
        "first_ts": srow[0].isoformat() if srow and srow[0] else None,
        "last_ts":  srow[1].isoformat() if srow and srow[1] else None,
        "count":    int(srow[2] or 0),
        "avg":      float(srow[3]) if srow[3] else None,
        "min":      float(srow[4]) if srow[4] else None,
        "max":      float(srow[5]) if srow[5] else None,
    }

    points_sql = f"""
        SELECT timestamp, value
        FROM {_fq(METRICS_TABLE)}
        WHERE {where_sql}
        ORDER BY timestamp DESC
        LIMIT 10
    """
    cur.execute(points_sql)
    rows = cur.fetchall()
    cur.close()
    points = [{"ts": r[0].isoformat(), "value": float(r[1])} for r in rows]

    return json.dumps({"sensor_id": sensor_id, "summary": summary, "last_points": points}, ensure_ascii=False)


def debug_trino_topology():
    """Print out the active Trino catalog/schema and the target sensor/metrics tables."""
    print("TRINO_HOST   =", TRINO_HOST)
    print("TRINO_PORT   =", TRINO_PORT)
    print("TRINO_USER   =", TRINO_USER)
    print("TRINO_CATALOG=", TRINO_CATALOG)
    print("TRINO_SCHEMA =", TRINO_SCHEMA)
    print("SENSOR_TABLE =", SENSOR_TABLE, "->", _fq(SENSOR_TABLE))
    print("METRICS_TABLE=", METRICS_TABLE, "->", _fq(METRICS_TABLE))

    cur = trino_cursor()
    cur.execute("SHOW CATALOGS")
    cats = [r[0] for r in cur.fetchall()]
    print("CATALOGS:", cats)

    if TRINO_CATALOG in cats:
        cur.execute(f"SHOW SCHEMAS FROM {TRINO_CATALOG}")
        schemas = [r[0] for r in cur.fetchall()]
        print(f"SCHEMAS in {TRINO_CATALOG}:", schemas)

        if TRINO_SCHEMA in schemas:
            cur.execute(f"SHOW TABLES FROM {TRINO_CATALOG}.{TRINO_SCHEMA}")
            tabs = [r[0] for r in cur.fetchall()]
            print(f"TABLES in {TRINO_CATALOG}.{TRINO_SCHEMA}:", tabs)

    try:
        cur.close()
    except Exception:
        pass
