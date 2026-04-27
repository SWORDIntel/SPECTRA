# SPECTRA Docker Image
# ====================
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

LABEL maintainer="SPECTRA Project"
LABEL version="1.0.0"
LABEL description="SPECTRA Intelligence Gathering Platform"

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmagic1 \
    curl \
    jq \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for security
RUN groupadd -r spectra && useradd -r -g spectra -d /home/spectra -m spectra

# Set working directory
WORKDIR /app

# Copy Python dependencies from builder
COPY --from=builder /root/.local /home/spectra/.local

# Copy application code
COPY --chown=spectra:spectra . .

# Create necessary directories
RUN mkdir -p /app/data /app/logs /app/config /app/media /app/checkpoints && \
    chown -R spectra:spectra /app

# Set environment variables
ENV PATH="/home/spectra/.local/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    SPECTRA_DEBUG=false \
    SPECTRA_TESTING=false \
    SPECTRA_PORT=5000 \
    SPECTRA_HOST=0.0.0.0 \
    SPECTRA_BOOTSTRAP_SECRET= \
    SPECTRA_SESSION_SECRET=change-me-in-production \
    SPECTRA_JWT_SECRET=change-me-in-production \
    SPECTRA_WEBAUTHN_ORIGIN= \
    SPECTRA_WEBAUTHN_RP_ID=

# Set user
USER spectra

# Health check targets the public login surface so it still works when
# the rest of the UI is auth-gated.
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -fsS http://localhost:5000/login || exit 1

# Expose port
EXPOSE 5000

# Default entrypoint: Unified Web Console
CMD ["python", "-m", "spectra_app.spectra_gui_launcher", "--host", "0.0.0.0", "--port", "5000"]
