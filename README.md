This repo contains:

MQTT → TimescaleDB bridge (mqtt_to_timescaledb.py)

One-function Live Data Agent (LLM + Trino/Timescale tool) (run_live_data_agent(...)) wired through your trino_tool.query_sensor.

Use this to see your live MQTT data, ingest it into TimescaleDB, and query it via Trino inside an LLM chat.

0) Prereqs (what you already have)

Kubernetes cluster with:

Mosquitto MQTT service in esai-data-services
svc/mosquitto-mqtt-broker-mosquitto :1883

TimescaleDB (PostgreSQL) service in esai-data-services
svc/esai-data-services-timescaledb-postgresql :5432

Trino in esai-data-services (coordinator + workers) with a Timescale/Postgres catalog (e.g., timescale.public)

Passwords:

Postgres superuser: postgres / b8n45tPZ5s (from your secret)

Local tools: kubectl, Python 3.10+.

1) See live MQTT messages (sanity check)

Option A — from your laptop

# Forward broker → localhost:1883 (if 1883 busy, use 1884:1883)
kubectl -n esai-data-services port-forward svc/mosquitto-mqtt-broker-mosquitto 1883:1883
# In a 2nd terminal, watch all topics
mosquitto_sub -h localhost -p 1883 -v -t '#'


Option B — inside cluster (no local ports)

kubectl -n esai-data-services run mqtt-peek --rm -it --image=alpine --restart=Never -- ash -lc \
"apk add --no-cache mosquitto-clients >/dev/null && mosquitto_sub -h mosquitto-mqtt-broker-mosquitto.esai-data-services.svc.cluster.local -p 1883 -v -t '#'"


You should see lines like:
sensors/temp {"deviceId":"abc","temperature":23.9}

2) Bridge: MQTT → TimescaleDB
Install deps
pip install paho-mqtt psycopg2-binary python-dateutil

Port-forward TimescaleDB (if running bridge from your laptop)
kubectl -n esai-data-services port-forward svc/esai-data-services-timescaledb-postgresql 5432:5432

Run the bridge
PGHOST=localhost PGPORT=5432 PGDATABASE=postgres PGUSER=postgres \
PGPASSWORD='b8n45tPZ5s' \
MQTT_HOST=localhost MQTT_PORT=1883 MQTT_TOPICS='#' \
python /path/to/mqtt_to_timescaledb.py


The bridge will:

Ensure Timescale extension and create a hypertable: public.mqtt_events(ts timestamptz, topic text, payload jsonb)

Subscribe to MQTT_TOPICS (default #)

Batch insert rows (fast) and print progress like inserted total=...

Environment variables (override as needed)
Var	Purpose	Default
PGHOST, PGPORT	Timescale/Postgres host/port	localhost, 5432
PGDATABASE, PGUSER, PGPASSWORD	DB creds	postgres, postgres, from secret
PGSCHEMA, PGTABLE	Target schema/table	public, mqtt_events
MQTT_HOST, MQTT_PORT	MQTT broker	localhost, 1883
MQTT_TOPICS	Comma-sep topics or wildcard	#
BATCH_SIZE, FLUSH_SECS	Insert tuning	500, 3.0
Verify ingestion

If you have psql:

PGUSER=postgres PGPASSWORD='b8n45tPZ5s' psql -h localhost -d postgres \
  -c "SELECT count(*) FROM public.mqtt_events;"


Quick roll-up:

SELECT time_bucket('1 minute', ts) AS minute, topic, count(*)
FROM public.mqtt_events
WHERE ts > now() - interval '1 hour'
GROUP BY 1,2 ORDER BY 1 DESC,2;


Tip: If psql isn't installed locally, run it in-cluster:

kubectl -n esai-data-services run pg-client --rm -it --image=postgres:15 -- bash
# inside:
PGPASSWORD='b8n45tPZ5s' psql -h esai-data-services-timescaledb-postgresql -U postgres -d postgres -c "SELECT version();"

3) Trino tool (trino_tool.py)

This module exposes a single tool: query_sensor(...), which the agent calls. It connects to Trino (with Basic auth if needed) and queries your Timescale tables through the Trino catalog.

Expected .env keys

TRINO_HOST=localhost         # or service DNS if running inside cluster
TRINO_PORT=8080
TRINO_USER=your_user
TRINO_PASSWORD=your_password_or_blank
TRINO_CATALOG=timescale      # catalog mapped to Timescale/Postgres
TRINO_SCHEMA=public
SENSOR_READING_TABLE=sensor_readings
SENSOR_META_TABLE=sensor_metadata


query_sensor supports:

query_type = reading | description | agg

sensor_id, limit, since_minutes, start_ts, end_ts, agg, catalog, schema, reading_table, meta_table

4) Live Data Agent (one function)

A minimal, one-function runner (mirrors your RAG agent shape) is provided as run_live_data_agent(...). It uses your trino_tool.query_sensor once, then resumes LLM generation and streams events.

Expected .env keys (LLM)

LLAMA_URL=http://<your-llm-host>/v1
LLAMA_MODEL=<your-model-name>
LLAMA_API_KEY=dummy   # or real if required by your gateway

Example usage
import asyncio
from live_data_agent_trino import run_live_data_agent

async def demo():
    async for ev in run_live_data_agent(
        "Show last 5 readings for sensor ABC",
        sensor_id="ABC",
        query_type="reading",
        limit=5,
        since_minutes=60
    ):
        if ev["type"] in ("text_delta", "text"):
            print(ev["content"], end="", flush=True)
        elif ev["type"]=="tool_output":
            print(f"\n[tool] {ev['output']}\n", flush=True)

asyncio.run(demo())


Event stream spec

{"type":"text_delta","content":"..."} — incremental model tokens

{"type":"tool_output","output":"...json..."} — Trino tool result

{"type":"text","content":"..."} — non-delta text blocks (if your framework emits them)

{"type":"done"} — end of stream

5) Common pitfalls & fixes

MQTT local port 1883 already in use

Use a different local port for forwarding: 1884:1883 and set MQTT_PORT=1884.

Or kill the process using 1883: lsof -nPi :1883 → kill -9 <PID>.

Timescale/Postgres auth fails

Use the cluster secret values (we decoded postgres-password: b8n45tPZ5s).

If connecting in-cluster, use service DNS: PGHOST=esai-data-services-timescaledb-postgresql.

Trino connection fails (NameResolution / TLS)

If you’re on your laptop, port-forward Trino coordinator:
kubectl -n esai-data-services port-forward svc/esai-data-services-trino-trino-coordinator 8080:8080
then TRINO_HOST=localhost.

For HTTPS, pass http_scheme="https" and proper auth in the Trino client.

No rows ingested / “silent” bridge

First verify messages with mosquitto_sub.

Ensure the bridge is subscribed to the right topics (MQTT_TOPICS).

Increase FLUSH_SECS (or lower BATCH_SIZE) to see faster insert logs.

6) Optional: Run the bridge inside Kubernetes

If you don’t want local port-forwards, deploy the bridge as a one-off job or Deployment that uses service DNS for MQTT & TimescaleDB:

kubectl -n esai-data-services run mqtt-to-ts --restart=Never --image=python:3.11 -it -- \
bash -lc "pip install -q paho-mqtt psycopg2-binary python-dateutil && \
PGHOST=esai-data-services-timescaledb-postgresql PGPORT=5432 PGDATABASE=postgres PGUSER=postgres PGPASSWORD='b8n45tPZ5s' \
MQTT_HOST=mosquitto-mqtt-broker-mosquitto.esai-data-services.svc.cluster.local MQTT_PORT=1883 MQTT_TOPICS='#' \
python - <<'PY'
# paste contents of mqtt_to_timescaledb.py here if you want a fully in-cluster run
PY"


(For production, create a small Deployment + Secret instead of an ad-hoc run.)

7) File map (what’s where)

mqtt_to_timescaledb.py — Bridge service (MQTT → TimescaleDB hypertable)

trino_tool.py — Trino tool with query_sensor(...)

live_data_agent_trino.py — One-function agent runner run_live_data_agent(...)

prompt.py — LIVE_DATA_AGENT_PROMPT system prompt

.env — LLM & Trino config (see sections above)

8) Quick start (TL;DR)
# Watch MQTT
kubectl -n esai-data-services port-forward svc/mosquitto-mqtt-broker-mosquitto 1883:1883
mosquitto_sub -h localhost -p 1883 -v -t '#'

# Start bridge
kubectl -n esai-data-services port-forward svc/esai-data-services-timescaledb-postgresql 5432:5432
PGHOST=localhost PGPORT=5432 PGDATABASE=postgres PGUSER=postgres PGPASSWORD='b8n45tPZ5s' \
MQTT_HOST=localhost MQTT_PORT=1883 MQTT_TOPICS='#' \
python mqtt_to_timescaledb.py

# Query via agent (Trino → Timescale)
# (ensure your Trino .env and LLM .env are set)
python -c "import asyncio; from live_data_agent_trino import run_live_data_agent as r; \
async def m(): \
    async for e in r('last 5 readings for sensor ABC', sensor_id='ABC', limit=5, since_minutes=60): \
        print(e); \
asyncio.run(m())"s
