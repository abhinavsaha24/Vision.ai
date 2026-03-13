# Vision AI — Production Backend
# Multi-stage build for minimal image size

# Stage 1: Dependencies
FROM python:3.11-slim AS builder

WORKDIR /app

# System deps for scientific libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libffi-dev && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Stage 2: Runtime
FROM python:3.11-slim

WORKDIR /app

# Copy installed packages
COPY --from=builder /install /usr/local

# Copy application code
COPY config/ config/
COPY src/ src/
COPY models/ models/
COPY data/ data/
COPY .env .env

# Non-root user for security
RUN useradd --create-home appuser
USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:10000/health')" || exit 1

# Expose API port
EXPOSE 10000

# Environment defaults
ENV LOG_LEVEL=INFO
ENV LOG_FORMAT=json
ENV PORT=10000

# Start the API server
CMD ["python", "-m", "src.api.main"]
