FROM python:3.11-slim

WORKDIR /app

# Build deps needed for C extensions: cryptography (python-jose), bcrypt, aiohttp (gremlin-python)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libssl-dev \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first — pip layer only rebuilds when requirements.txt changes
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code only (workers/ and sdk/ are separate Lambda deployments)
COPY api/ ./api/

EXPOSE 8000

# gunicorn as process manager with uvicorn ASGI workers
# -w 3  : (2 × 1 vCPU) + 1 = 3 workers, each with its own asyncpg pool
# --timeout 120: covers slow Neptune traversal on cold graph
# --access-logfile -: access logs to stdout → captured by CloudWatch
CMD ["gunicorn", "api.main:app", "-k", "uvicorn.workers.UvicornWorker", "-w", "3", "--bind", "0.0.0.0:8000", "--timeout", "120", "--access-logfile", "-"]
