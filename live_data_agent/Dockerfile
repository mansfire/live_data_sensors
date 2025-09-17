# RAG Agent Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y build-essential curl && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY live_data_agent.py trino_tool.py prompt.py server.py ./

# Expose SSE port
EXPOSE 9001

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "9001"]
