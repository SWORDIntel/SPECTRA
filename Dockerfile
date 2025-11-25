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
RUN pip install --no-cache-dir --user -r requirements.txt


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
RUN groupadd -r spectra && useradd -r -g spectra spectra

# Set working directory
WORKDIR /app

# Copy Python dependencies from builder
COPY --from=builder /root/.local /home/spectra/.local

# Copy application code
COPY --chown=spectra:spectra . .

# Create necessary directories
RUN mkdir -p /app/data /app/logs /app/config && \
    chown -R spectra:spectra /app

# Set environment variables
ENV PATH="/home/spectra/.local/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    SPECTRA_DEBUG=false \
    SPECTRA_TESTING=false \
    SPECTRA_PORT=5000 \
    SPECTRA_HOST=0.0.0.0 \
    SPECTRA_JWT_SECRET=change-me-in-production

# Set user
USER spectra

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:5000/health || exit 1

# Expose port
EXPOSE 5000

# Default entrypoint: Web server
CMD ["python", "-m", "tgarchive.web", "--host", "0.0.0.0", "--port", "5000"]
