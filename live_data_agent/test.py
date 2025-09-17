#!/usr/bin/env python3
import os
import re
import json
import sys
from typing import Any, Dict, Tuple

from dotenv import load_dotenv
from openai import OpenAI
from trino_tool import query_sensor  # uses the fixed SQL with date_add()

load_dotenv()

LLAMA_URL   = os.getenv("LLAMA_URL", "http://localhost:8000/v1")
LLAMA_KEY   = os.getenv("LLAMA_API_KEY", "dummy")
LLAMA_MODEL = os.getenv("LLAMA_MODEL", "meta-llama/Llama-3.1-8B-Instruct")

client = OpenAI(base_url=LLAMA_URL, api_key=LLAMA_KEY)

SYSTEM_PROMPT = """You are a precise assistant wired to a sensor database.

When a question genuinely needs live sensor data (readings, metadata, or aggregates),
respond with **only** this JSON (no prose, no extra lines):

{
  "action": "call_query_sensor",
  "args": {
    "sensor_id": "<sensor id>",
    "query_type": "reading" | "description" | "agg",
    "limit": 100,
    "since_minutes": 15,
    "start_ts": null,
    "end_ts": null,
    "agg": "avg"
  }
}

Otherwise, answer normally in plain text.
Prefer calling the tool for requests like:
- last N readings for SENSOR_*
- avg/min/max of SENSOR_* over a time window
- what does SENSOR_* measure (unit/location)
"""

def probe_models():
    try:
        res = client.models.list()
        names = [m.id for m in getattr(res, "data", [])]
        print("Models on server:", names)
        if LLAMA_MODEL not in names:
            print(f"❌ Model '{LLAMA_MODEL}' not found on the server.")
            print(f"   Set LLAMA_MODEL to one of: {names}")
            sys.exit(1)
    except Exception as e:
        print(f"❌ Could not list models from {LLAMA_URL}. Details: {e}")
        sys.exit(1)

def parse_json_block(text: str) -> Dict[str, Any] | None:
    if not text:
        return None
    m = re.search(r"```json\s*(\{.*?\})\s*```", text, flags=re.S)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    m2 = re.search(r"(\{.*\})", text, flags=re.S)
    if m2:
        raw = m2.group(1)
        last = raw.rfind("}")
        if last != -1:
            raw = raw[:last+1]
        try:
            return json.loads(raw)
        except Exception:
            return None
    return None

def call_llm(messages):
    print(f"[debug] calling {LLAMA_URL}/chat/completions with model={LLAMA_MODEL}")
    r = client.chat.completions.create(
        model=LLAMA_MODEL,
        messages=messages,
        temperature=0.2,
    )
    return r.choices[0].message.content or ""

def run_tool(args: Dict[str, Any]) -> str:
    clean = {
        "sensor_id": args.get("sensor_id"),
        "query_type": args.get("query_type", "reading"),
        "limit": args.get("limit", 100),
        "catalog": args.get("catalog"),
        "schema": args.get("schema"),
        "reading_table": args.get("reading_table"),
        "meta_table": args.get("meta_table"),
        "since_minutes": args.get("since_minutes"),
        "start_ts": args.get("start_ts"),
        "end_ts": args.get("end_ts"),
        "agg": args.get("agg", "avg"),
    }
    clean = {k: v for k, v in clean.items() if v is not None}
    return query_sensor(**clean)

def answer_with_optional_tool(user_text: str) -> Tuple[str, str | None]:
    msgs = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_text},
    ]
    first = call_llm(msgs)

    req = parse_json_block(first)
    if isinstance(req, dict) and req.get("action") == "call_query_sensor":
        args = req.get("args", {}) or {}
        tool_json = run_tool(args)

        # If the tool returned an error, show it verbatim and STOP pretending
        try:
            parsed = json.loads(tool_json)
        except Exception:
            parsed = {"raw": tool_json}

        if isinstance(parsed, dict) and parsed.get("error"):
            return f"❌ Tool error: {parsed['error']}", tool_json

        # Synthesize a nice answer
        msgs.extend([
            {"role": "assistant", "content": first},
            {"role": "system", "content": "Tool call executed. Use TOOL_RESULT_JSON to answer."},
            {"role": "user", "content": f"TOOL_RESULT_JSON:\n{tool_json}\n\nWrite a concise, helpful answer."}
        ])
        final = call_llm(msgs)
        return final, tool_json

    # No tool call requested—just return the LLM text
    return first, None

def repl():
    print("Ask things like:")
    print("  - last 10 readings for SENSOR_123")
    print("  - average of SENSOR_123 over 30 minutes")
    print("  - what is SENSOR_123 measuring?")
    print("Type 'exit' to quit.")
    while True:
        q = input("\nYou: ").strip()
        if q.lower() in {"exit", "quit"}:
            break
        if not q:
            continue
        final, tool_json = answer_with_optional_tool(q)
        if tool_json:
            print("[tool] raw JSON:", tool_json)
        print("LLM:", final)

def main():
    probe_models()
    repl()

if __name__ == "__main__":
    main()
