# >>> RUN THIS FILE INSTEAD OF live_data_agent.py <<<
import os, runpy

# Kill OpenAI SDK tracing/telemetry BEFORE any import initializes it
os.environ["OPENAI_SDK_DISABLE_TRACING"] = "1"
os.environ["OPENAI_TRACING"] = "0"
os.environ["OPENAI_TELEMETRY_OPTOUT"] = "1"
os.environ.pop("OPENAI_API_KEY", None)  # ensure nothing tries to auth to api.openai.com

# Hand off to your real script
runpy.run_path("live_data_agent.py", run_name="__main__")
