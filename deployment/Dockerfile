# Vision AI — Production Backend
# Multi-stage build for minimal image size

# Stage 1: Dependencies
FROM python:3.12-slim AS builder

WORKDIR /app

# System deps for scientific libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libffi-dev libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --default-timeout=1000 --no-cache-dir --prefix=/install -r requirements.txt

# Stage 2: Runtime
FROM python:3.12-slim

WORKDIR /app

# Install runtime library for postgres
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 && \
    rm -rf /var/lib/apt/lists/*

# Copy installed packages
COPY --from=builder /install /usr/local

# Copy application code
COPY backend/ backend/
COPY config/ config/
COPY models/ models/
COPY data/ data/
COPY .env .env

# Non-root user for security
RUN useradd --create-home appuser
RUN chown -R appuser:appuser /app
USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:${PORT:-10000}/health')" || exit 1

# Expose API port
EXPOSE ${PORT:-10000}

# Environment defaults
ENV LOG_LEVEL=INFO
ENV LOG_FORMAT=json
ENV PORT=10000
ENV REDIS_ENABLED=false
ENV PYTHONUNBUFFERED=1

# Start the API server — uses lifespan for deferred init
CMD ["uvicorn", "backend.src.api.main:app", "--host", "0.0.0.0", "--port", "10000", "--timeout-keep-alive", "120"]
