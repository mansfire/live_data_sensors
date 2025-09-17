#!/usr/bin/env python3
import os, re, json, asyncio
from typing import Optional
from fastapi import FastAPI, Query, Body
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn

# —— live data hooks ——
# Uses YOUR working trino_tool (no changes)
from trino_tool import list_sensors as trino_list_sensors, query_sensor as trino_query_sensor

# —— LLM (OpenAI-compatible; vLLM) ——
from openai import AsyncOpenAI
import httpx

LLAMA_URL   = os.getenv("LLAMA_URL", "http://127.0.0.1:31913/v1").rstrip("/")
LLAMA_MODEL = os.getenv("LLAMA_MODEL", "meta-llama/Llama-3.1-8B-Instruct")
LLAMA_API_KEY = os.getenv("LLAMA_API_KEY", "sk-local-not-used")

client = AsyncOpenAI(
    base_url=LLAMA_URL,
    api_key=LLAMA_API_KEY,
    timeout=httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=30.0),
)

app = FastAPI(title="Live Data Agent UI")

# Serve ./static for the front-end files
app.mount("/static", StaticFiles(directory="static"), name="static")


# -------------------- API: sensors --------------------
@app.get("/api/sensors")
async def api_list_sensors():
    try:
        data = trino_list_sensors()  # returns JSON string
        return JSONResponse(content=json.loads(data))
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/sensor")
async def api_query_sensor(
    sensor_id: str = Query(..., description="sensor_id to query"),
    window: Optional[str] = Query(None, description="e.g. 1h, 24h"),
    start: Optional[str] = Query(None, description="ISO8601 start"),
    end: Optional[str]   = Query(None, description="ISO8601 end"),
):
    try:
        data = trino_query_sensor(sensor_id=sensor_id, start=start, end=end, window=window)
        return JSONResponse(content=json.loads(data))
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


# -------------------- API: chat (LLM) --------------------
class ChatIn(BaseModel):
    message: str

SYSTEM_PROMPT = (
    "You can answer normally, but when users ask about sensors or readings, "
    "guide them to use the controls on the left (List sensors, pick sensor, choose window). "
    "Be concise."
)

@app.post("/api/chat")
async def api_chat(payload: ChatIn):
    try:
        resp = await client.chat.completions.create(
            model=LLAMA_MODEL,
            messages=[
                {"role":"system","content": SYSTEM_PROMPT},
                {"role":"user","content": payload.message}
            ],
            temperature=0.3,
            max_tokens=600,
            stream=False
        )
        text = (resp.choices[0].message.content or "").strip()
        return PlainTextResponse(text)
    except Exception as e:
        return PlainTextResponse(f"[chat error] {e}", status_code=500)


# Root -> simple redirect to static index
@app.get("/")
async def root():
    html = '<meta http-equiv="refresh" content="0; url=/static/index.html">'
    return PlainTextResponse(html, media_type="text/html")


if __name__ == "__main__":
    # Run:  python server.py
    uvicorn.run("server:app", host="0.0.0.0", port=int(os.getenv("PORT", "8088")), reload=True)
