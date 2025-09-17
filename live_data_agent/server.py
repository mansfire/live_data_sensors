# server.py
import os
import asyncio
from functools import partial

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

# your working trino helpers
from trino_tool import list_sensors as trino_list_sensors, query_sensor as trino_query_sensor

app = FastAPI(title="Live Data Agent API")

# CORS for your static index.html/app.js in a browser
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # tighten later
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/health")
async def health():
    return {"ok": True}

# helper to run sync Trino calls off the event loop
async def _run_bg(fn, *args, **kwargs):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(fn, *args, **kwargs))

@app.get("/api/sensors")
async def api_list_sensors():
    try:
        data = await _run_bg(trino_list_sensors)
        # list_sensors already returns JSON string; but FastAPI will double-encode.
        # Return as dict so the client gets proper JSON, not a quoted string.
        import json
        return json.loads(data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"list_sensors failed: {e}")

@app.get("/api/sensor/{sensor_id}")
async def api_query_sensor(
    sensor_id: str,
    window: str | None = Query(None, description="e.g. 1h, 24h, 10m"),
    start: str | None = None,
    end: str | None = None,
):
    try:
        data = await _run_bg(trino_query_sensor, sensor_id=sensor_id, start=start, end=end, window=window)
        import json
        return json.loads(data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"query_sensor failed: {e}")
