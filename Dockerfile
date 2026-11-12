# RoadSense: one image runs the mock 311 server, the agent API (with its MCP servers) and the dashboard.
# CPU build by default; for an NVIDIA GPU use a CUDA base image and the matching torch wheel.
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir torch==2.7.1 torchvision==0.22.1 --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt
COPY roadsense ./roadsense
COPY scripts ./scripts
COPY pyproject.toml README.md SECURITY.md ./

ENV ROADSENSE_WEIGHTS_DIR=/app/weights ROADSENSE_DATA_DIR=/app/data ROADSENSE_DEVICE=cpu PYTHONUNBUFFERED=1
RUN useradd -m roadsense && mkdir -p /app/data /app/weights && chown -R roadsense /app
USER roadsense
EXPOSE 7860 8000 8311
CMD ["python", "scripts/run_all.py", "--host", "0.0.0.0"]
