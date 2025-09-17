#!/usr/bin/env python3
import os
import sys
import json
import argparse
import re

from dotenv import load_dotenv

# OpenAI-compatible client (sync, simple)
try:
    from openai import OpenAI
except Exception:
    print("Please `pip install openai python-dotenv trino`", file=sys.stderr)
    raise

# Your Trino/Timescale tool (already written)
from trino_tool import query_sensor

load_dotenv()

LLAMA_URL   = os.getenv("LLAMA_URL")
LLAMA_MODEL = os.getenv("LLAMA_MODEL")
LLAMA_API_KEY = os.getenv("LLAMA_API_KEY", "dummy")

if not LLAMA_URL or not LLAMA_MODEL:
    print("[warn] LLAMA_URL or LLAMA_MODEL not set. Check your environment.", file=sys.stderr)

client = OpenAI(base_url=LLAMA_URL, api_key=LLAMA_API_KEY)

SYSTEM_PROMPT = (
    "You are a helpful assistant. When the user asks normal questions, answer normally. "
    "If the user issues a '!sensor ...' command, they intend to query live sensor data "
    "via a database tool. Do not invent results; just acknowledge or summarize tool output."
)

def llm_stream(prompt: str):
    """
    Stream tokens from the LLM (OpenAI-compatible chat.completions).
    """
    stream = client.chat.completions.create(
        model=LLAMA_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        stream=True,
    )
    for chunk in stream:
        delta = chunk.choices[0].delta.content if chunk.choices and chunk.choices[0].delta else None
        if delta:
            yield delta

def parse_kv_args(arg_line: str) -> dict:
    """
    Parse key=value pairs from a line. Example:
      'sensor_id=ABC query_type=reading limit=5 since_minutes=60'
    Returns dict with proper ints where appropriate.
    """
    result = {}
    for m in re.finditer(r'(\w+)=(".*?"|\'.*?\'|\S+)', arg_line):
        k = m.group(1)
        v = m.group(2).strip('"\'')
        # cast simple ints if they look like ints
        if v.isdigit():
            v = int(v)
        result[k] = v
    return result

def handle_sensor_command(cmd: str) -> str:
    """
    Execute the !sensor command via trino_tool.query_sensor and return pretty JSON string.
    Usage: !sensor sensor_id=ABC query_type=reading limit=5 since_minutes=60
           !sensor sensor_id=ABC query_type=agg agg=avg since_minutes=30
           !sensor sensor_id=ABC query_type=description
    """
    args_line = cmd[len("!sensor"):].strip()
    if not args_line:
        return "Error: usage: !sensor sensor_id=... [query_type=reading|description|agg] [limit=...] [since_minutes=...] [start_ts=...] [end_ts=...] [agg=avg|min|max|count]"
    kv = parse_kv_args(args_line)

    # defaults
    kv.setdefault("query_type", "reading")
    kv.setdefault("limit", 100)

    try:
        res = query_sensor(
            sensor_id=kv.get("sensor_id"),
            query_type=kv.get("query_type"),
            limit=kv.get("limit"),
            catalog=kv.get("catalog"),
            schema=kv.get("schema"),
            reading_table=kv.get("reading_table"),
            meta_table=kv.get("meta_table"),
            since_minutes=kv.get("since_minutes"),
            start_ts=kv.get("start_ts"),
            end_ts=kv.get("end_ts"),
            agg=kv.get("agg", "avg"),
        )
        # res is JSON string per your tool; pretty-print for terminal
        try:
            parsed = json.loads(res)
            return json.dumps(parsed, indent=2, default=str)
        except Exception:
            return res
    except Exception as e:
        return f"Tool error: {e}"

def run_once(prompt: str):
    """
    One-shot: if the prompt is a !sensor command, run the tool; else chat with the LLM.
    """
    if prompt.strip().startswith("!sensor"):
        out = handle_sensor_command(prompt.strip())
        print(out)
        return
    # else: normal LLM answer
    for token in llm_stream(prompt):
        print(token, end="", flush=True)
    print()

def run_chat():
    """
    Interactive chat. Type `!sensor ...` to call the tool.
    Type `exit` or `quit` to leave.
    """
    print("Live Chat (LLM + Trino tool). Type 'exit' to quit.")
    print("Use '!sensor sensor_id=ABC query_type=reading limit=5 since_minutes=60' to query live data.\n")
    while True:
        try:
            q = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break
        if q.lower() in ("exit", "quit"):
            print("Bye.")
            break
        if q.startswith("!sensor"):
            out = handle_sensor_command(q)
            print(out)
            continue
        for token in llm_stream(q):
            print(token, end="", flush=True)
        print()

def main():
    ap = argparse.ArgumentParser(description="Single-command chat with optional Trino tool calls.")
    ap.add_argument("prompt", nargs="*", help="Optional one-shot message. If omitted, interactive chat starts.")
    args = ap.parse_args()

    # Basic sanity checks
    if not LLAMA_URL or not LLAMA_MODEL:
        print("[error] Set LLAMA_URL and LLAMA_MODEL env vars first.", file=sys.stderr)
        sys.exit(1)

    if args.prompt:
        run_once(" ".join(args.prompt))
    else:
        run_chat()

if __name__ == "__main__":
    main()
