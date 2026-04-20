# SPECTRA Production Docker Image
# TEMPEST Class C compliant container for secure deployment

FROM python:3.11-slim-bookworm AS base

# Metadata
LABEL maintainer="SWORD-EPI"
LABEL description="SPECTRA - Production Telegram Archiver with TEMPEST Class C security"
LABEL version="3.0.0"

# Security: Create non-root user
RUN groupadd -r spectra && useradd -r -g spectra -s /bin/false spectra

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmagic1 \
    libsqlite3-0 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first (layer caching)
COPY requirements.txt /app/

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code needed by the unified web UI
COPY . /app/

# Install SPECTRA
RUN pip install --no-cache-dir -e .

# Create necessary directories with proper permissions
RUN mkdir -p /app/data /app/logs /app/media /app/checkpoints && \
    chown -R spectra:spectra /app

# Security: Drop to non-root user
USER spectra

# Environment variables (override at runtime)
ENV PYTHONUNBUFFERED=1 \
    SPECTRA_HOST=0.0.0.0 \
    SPECTRA_PORT=5000 \
    SPECTRA_DB_PATH=/app/data/spectra.db \
    SPECTRA_MEDIA_DIR=/app/media \
    SPECTRA_LOG_DIR=/app/logs \
    SPECTRA_CHECKPOINT_DIR=/app/checkpoints \
    SPECTRA_BOOTSTRAP_SECRET= \
    SPECTRA_SESSION_SECRET=change-me-in-production \
    SPECTRA_WEBAUTHN_ORIGIN= \
    SPECTRA_WEBAUTHN_RP_ID=

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request, sys; \
url = 'http://127.0.0.1:5000/login'; \
sys.exit(0 if urllib.request.urlopen(url, timeout=5).getcode() < 400 else 1)"

# Volumes for persistent data
VOLUME ["/app/data", "/app/logs", "/app/media", "/app/checkpoints"]

# Expose unified web UI port
EXPOSE 5000

# Default command
CMD ["sh", "-c", "python -m spectra_app.spectra_gui_launcher --host ${SPECTRA_HOST:-0.0.0.0} --port ${SPECTRA_PORT:-5000} --log-level ${LOG_LEVEL:-INFO}"]
