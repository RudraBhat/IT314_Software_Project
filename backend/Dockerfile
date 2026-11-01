# ==============================================================================
# Stage 1: Builder
# ==============================================================================
FROM python:3.12-slim AS builder

WORKDIR /app

# Set Python environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install OS-level build dependencies (gcc, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment and install dependencies
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# ==============================================================================
# Stage 2: Production Runner
# ==============================================================================
FROM python:3.12-slim AS runner

WORKDIR /app

# Ensure security and performance variables are set
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

# Install runtime dependencies (e.g., pg driver, curl for health checks)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual env from builder
COPY --from=builder /opt/venv /opt/venv

# Copy application code
COPY . .

# Create a non-root user
RUN addgroup --system --gid 1001 fastapi && \
    adduser --system --uid 1001 fastapi && \
    chown -R fastapi:fastapi /app

USER fastapi

EXPOSE 8000

# Container healthcheck against /health endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run with Gunicorn backed by Uvicorn workers, dynamically binding to $PORT (Render) or 8000
CMD ["sh", "-c", "exec gunicorn main:app --workers ${WEB_CONCURRENCY:-1} --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:${PORT:-8000}"]
