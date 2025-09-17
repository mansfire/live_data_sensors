#!/usr/bin/env python3
# Cube Live Data Agent — minimal, reliable tool router (no Agents SDK)

import os, re, logging, asyncio, inspect
from typing import Optional, Awaitable, Any, Tuple

from dotenv import load_dotenv
import httpx
from openai import AsyncOpenAI

# Tool implementations
from trino_tool import list_sensors as trino_list_sensors, query_sensor as trino_query_sensor
from prompt import LIVE_DATA_AGENT_PROMPT  # prepend to LLM prompts if you want

# -----------------------------------------------------------------------------
# Setup
# -----------------------------------------------------------------------------
load_dotenv()
logger = logging.getLogger(__name__)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

def _normalize_base_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    u = url.strip()
    if not re.match(r"^https?://", u):
        u = "http://" + u
    u = u.rstrip("/")
    if not u.endswith("/v1"):
        u = u + "/v1"
    return u

LLAMA_URL   = _normalize_base_url(os.getenv("LLAMA_URL") or os.getenv("OPENAI_BASE_URL"))
LLAMA_MODEL = os.getenv("LLAMA_MODEL") or os.getenv("OPENAI_MODEL") or os.getenv("MODEL")
LLAMA_API_KEY = os.getenv("LLAMA_API_KEY") or os.getenv("OPENAI_API_KEY") or "sk-local-not-used"
TOOL_TIMEOUT_S = int(os.getenv("TOOL_TIMEOUT_S", "10"))

if not LLAMA_URL or not LLAMA_MODEL:
    raise SystemExit(
        "Set LLAMA_URL and LLAMA_MODEL (e.g. http://127.0.0.1:31913/v1, meta-llama/Llama-3.1-8B-Instruct)"
    )

llama = AsyncOpenAI(
    base_url=LLAMA_URL,
    api_key=LLAMA_API_KEY,
    timeout=httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=30.0),
    max_retries=1,
)
logger.info("LLM base_url=%s model=%s", LLAMA_URL, LLAMA_MODEL)

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
async def _call_tool(fn, *args, **kwargs):
    """Run tool whether it's sync or async."""
    if inspect.iscoroutinefunction(fn):
        return await fn(*args, **kwargs)
    return await asyncio.to_thread(fn, *args, **kwargs)

async def _with_timeout(coro_or_fn, *args, **kwargs):
    """Unified timeout wrapper for tools."""
    return await asyncio.wait_for(
        _call_tool(coro_or_fn, *args, **kwargs), timeout=TOOL_TIMEOUT_S
    )

async def _try_get(url: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(url)
            return r.status_code == 200
    except Exception:
        return False

async def _preflight_models() -> None:
    if await _try_get(f"{LLAMA_URL}/models"):
        return
    alt = (
        LLAMA_URL.replace("/v1", "/openai/v1")
        if LLAMA_URL.endswith("/v1")
        else f"{LLAMA_URL}/openai/v1"
    )
    alt = alt.rstrip("/")
    if await _try_get(f"{alt}/models"):
        logger.info("Switched base URL to %s", alt)
        globals()["LLAMA_URL"] = alt
        llama._base_url = alt  # type: ignore[attr-defined]
        return
    raise SystemExit(f"Cannot reach {LLAMA_URL}/models or {alt}/models.")

async def _chat_once(prompt: str) -> str:
    """Non-streaming chat with tiny retry."""
    msg = (
        prompt
        if not LIVE_DATA_AGENT_PROMPT
        else f"{LIVE_DATA_AGENT_PROMPT.strip()}\n\nUser: {prompt}"
    )
    for attempt in range(2):
        try:
            resp = await llama.chat.completions.create(
                model=LLAMA_MODEL,
                messages=[{"role": "user", "content": msg}],
                stream=False,
                temperature=0.3,
                max_tokens=800,
            )
            return (resp.choices[0].message.content or "") if resp and resp.choices else ""
        except Exception as e:
            if attempt == 0:
                logger.warning("direct chat attempt failed (%s), retrying...", e)
                await asyncio.sleep(0.5)
            else:
                logger.error("direct chat failed: %s", e)
                return f"[direct chat error] {e}"
    return ""

# -----------------------------------------------------------------------------
# Tool router
# -----------------------------------------------------------------------------
SENSORS_PATTERNS = [
    re.compile(r"^\s*(list\s+)?sensors\s*$", re.I),
    re.compile(r"^\s*show\s+sensors\s*$", re.I),
    re.compile(r"^\s*what\s+sensors", re.I),
]

QUERY_PATTERN = re.compile(
    r"""^\s*
        (query|show|get)\s+sensor\s+
        (?P<id>[A-Za-z0-9_\-:.]+)
        (?:\s+window\s*=\s*(?P<window>[0-9]+[smhd]))?
        (?:\s+start\s*=\s*(?P<start>[^\s]+))?
        (?:\s+end\s*=\s*(?P<end>[^\s]+))?
        \s*$""",
    re.I | re.X,
)

async def handle_tools(user_msg: str) -> Tuple[bool, str]:
    """Returns (handled, text). If handled=True, we ran a tool and return its text."""
    if any(p.search(user_msg) for p in SENSORS_PATTERNS):
        try:
            out = await _with_timeout(trino_list_sensors)
            return True, str(out)
        except Exception as e:
            return True, f"[tool error] list_sensors: {e}"

    m = QUERY_PATTERN.match(user_msg)
    if m:
        sensor_id = m.group("id")
        window = m.group("window")
        start = m.group("start")
        end = m.group("end")
        try:
            out = await _with_timeout(
                trino_query_sensor, sensor_id=sensor_id, start=start, end=end, window=window
            )
            return True, str(out)
        except Exception as e:
            return True, f"[tool error] query_sensor({sensor_id}): {e}"

    return False, ""

# -----------------------------------------------------------------------------
# Terminal UI
# -----------------------------------------------------------------------------
async def _ainput(prompt: str = "") -> str:
    return await asyncio.to_thread(input, prompt)

async def main():
    await _preflight_models()
    hello = await _chat_once("Say 'Pong!' in one word.")
    logger.info("LLM probe: %r", hello)

    print("💬 Connected (simple tool router; non-streaming). Type a message (or /quit).\n")
    while True:
        user_msg = await _ainput("you> ")
        if not user_msg:
            continue
        if user_msg.strip().lower() in ("/q", "/quit", "exit"):
            print("bye!")
            break

        print("assistant> ", end="", flush=True)

        handled, text = await handle_tools(user_msg)
        if handled:
            print(text or "[empty tool result]")
            continue

        reply = await _chat_once(user_msg)
        print(reply or "[empty response]")

if __name__ == "__main__":
    asyncio.run(main())
