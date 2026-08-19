# SPECTRA Docker Image [CLI-First & Headless Worker]
# ====================================================
# Multi-stage build for optimized image size

# Stage 1: Builder
FROM python:3.11-slim as builder

WORKDIR /tmp
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN grep -v '^qdrant-client>=' requirements.txt > /tmp/requirements.osint-node.txt && \
    pip install --no-cache-dir --user -r /tmp/requirements.osint-node.txt


# Stage 2: Runtime
FROM python:3.11-slim

LABEL maintainer="SWORD Intelligence"
LABEL version="1.0.0"
LABEL description="SPECTRA Forensic-Grade Intelligence & Archiving Platform"

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmagic1 \
    curl \
    jq \
    procps \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for security
RUN groupadd -r spectra && useradd -r -g spectra -d /home/spectra -m spectra

# Set working directory
WORKDIR /app

# Copy Python dependencies from builder
COPY --from=builder /root/.local /home/spectra/.local

# Copy application code
COPY --chown=spectra:spectra . .

# Create necessary runtime directories
RUN mkdir -p /app/data /app/logs /app/config /app/media /app/checkpoints && \
    chmod +x /app/spectra && \
    chown -R spectra:spectra /app

# Set environment variables
ENV PATH="/home/spectra/.local/bin:/app:$PATH" \
    PYTHONUNBUFFERED=1 \
    SPECTRA_DEBUG=false

# Set user
USER spectra

# Healthcheck verifies worker process presence
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD pgrep -f "python" || exit 1

# Default entrypoint: Process Intelligence Queue
CMD ["./spectra", "process-queue"]
