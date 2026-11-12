# RoadSense: one image runs the mock 311 server, the agent API (with its MCP servers) and the web app.
# CPU build by default; for an NVIDIA GPU use a CUDA base image and the matching torch wheel.
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 curl \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.lock .
RUN pip install --no-cache-dir torch==2.14.1 torchvision==0.29.2 --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.lock
COPY roadsense ./roadsense
COPY scripts ./scripts
COPY pyproject.toml README.md SECURITY.md ./

ENV ROADSENSE_WEIGHTS_DIR=/app/weights ROADSENSE_DATA_DIR=/app/data ROADSENSE_DEVICE=cpu PYTHONUNBUFFERED=1 \
    ROADSENSE_COOKIE_SECURE=1
RUN useradd -m roadsense && mkdir -p /app/data /app/weights && chown -R roadsense /app
USER roadsense
EXPOSE 7860 8000 8311
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/health && curl -fsS -o /dev/null http://127.0.0.1:7860/ || exit 1
CMD ["python", "scripts/run_all.py", "--host", "0.0.0.0"]
