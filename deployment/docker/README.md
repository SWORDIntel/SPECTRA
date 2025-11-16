# SPECTRA Docker Deployment

Production-ready Docker containers for SPECTRA with TEMPEST Class C security controls.

## Quick Start

### 1. Prerequisites

- Docker 20.10+
- Docker Compose 2.0+
- At least 4GB RAM available
- 10GB+ free disk space

### 2. Configuration

Create `.env` file:

```bash
cd deployment/docker
cp .env.example .env
nano .env  # Edit with your credentials
```

Required variables:
```env
TG_API_ID=your_api_id
TG_API_HASH=your_api_hash_32_chars
```

### 3. Build and Start

```bash
docker-compose up -d
```

### 4. Verify

```bash
# Check status
docker-compose ps

# View logs
docker-compose logs -f spectra

# Health check
curl http://localhost:8080/health
```

## Services

### spectra
Main archiver service with full functionality.

**Resources:**
- CPU: 0.5-2.0 cores
- Memory: 1-4GB
- Storage: Unlimited (volume-based)

**Security:**
- Non-root user
- No new privileges
- Minimal capabilities
- Read-only root filesystem (where possible)

### spectra-health
Health check and monitoring endpoint.

**Endpoints:**
- `GET /health` - Overall health status
- `GET /metrics` - Resource metrics (Prometheus format)
- `GET /status` - Detailed component status

**Resources:**
- CPU: Up to 0.5 cores
- Memory: Up to 512MB

### spectra-scheduler
Background task scheduler for automated archiving.

**Features:**
- Cron-based scheduling
- Automatic channel updates
- Batch processing

**Resources:**
- CPU: Up to 1.0 cores
- Memory: Up to 1GB

## Volumes

### Persistent Data

```yaml
spectra-data:      # Database files
spectra-media:     # Downloaded media
spectra-logs:      # Application logs
spectra-checkpoints: # Recovery checkpoints
```

### Backup Volumes

```bash
# Backup database
docker run --rm \
  -v spectra-data:/data \
  -v $(pwd)/backups:/backup \
  alpine tar czf /backup/spectra-data-$(date +%Y%m%d).tar.gz /data

# Restore database
docker run --rm \
  -v spectra-data:/data \
  -v $(pwd)/backups:/backup \
  alpine tar xzf /backup/spectra-data-20250115.tar.gz -C /
```

## Configuration Files

### Config Directory Structure

```
deployment/docker/config/
├── spectra_config.json       # Main configuration
├── accounts.json             # Account credentials (gitignored)
└── schedules.json           # Scheduled tasks
```

Mount as read-only:
```yaml
volumes:
  - ./config:/app/config:ro
```

### Example spectra_config.json

```json
{
  "accounts": [
    {
      "api_id": 123456,
      "api_hash": "your_32_char_hash",
      "session_name": "spectra_1"
    }
  ],
  "db_path": "/app/data/spectra.db",
  "media_dir": "/app/media",
  "download_media": true,
  "batch": 500,
  "sleep_between_batches": 1.0
}
```

## Security

### TEMPEST Class C Features

1. **Memory Protection**
   - Secure credential storage
   - Automatic memory scrubbing
   - No credential leakage in logs

2. **Filesystem Isolation**
   - Read-only root filesystem
   - Minimal write permissions
   - Isolated tmp directories

3. **Network Isolation**
   - Dedicated bridge network
   - No host network access
   - Optional proxy support

4. **Process Isolation**
   - Non-root user (UID 1000)
   - Dropped Linux capabilities
   - No privilege escalation

### Hardening Checklist

- [ ] Use `.env` file, not environment in compose
- [ ] Set restrictive file permissions (600 for .env)
- [ ] Use secrets management (Docker Swarm/Kubernetes)
- [ ] Enable TLS for health endpoints
- [ ] Configure log rotation
- [ ] Set up automated backups
- [ ] Monitor resource usage
- [ ] Regular security updates

## Resource Management

### CPU Limits

Adjust in docker-compose.yml:

```yaml
deploy:
  resources:
    limits:
      cpus: '2.0'      # Max 2 cores
    reservations:
      cpus: '0.5'      # Minimum 0.5 cores
```

### Memory Limits

```yaml
deploy:
  resources:
    limits:
      memory: 4G       # Max 4GB
    reservations:
      memory: 1G       # Minimum 1GB
```

### Disk Space

Monitor volume usage:

```bash
docker system df -v
```

Cleanup:

```bash
# Remove stopped containers
docker-compose down

# Prune unused volumes (CAREFUL!)
docker volume prune

# Clean build cache
docker builder prune
```

## Monitoring

### Health Checks

Built-in health check runs every 30 seconds:

```bash
docker inspect --format='{{json .State.Health}}' spectra-archiver | jq
```

### Logs

```bash
# Follow logs
docker-compose logs -f

# Last 100 lines
docker-compose logs --tail=100

# Specific service
docker-compose logs -f spectra

# Since timestamp
docker-compose logs --since 2025-01-15T10:00:00
```

### Metrics

Health service provides Prometheus metrics:

```bash
curl http://localhost:8080/metrics
```

Example prometheus.yml:

```yaml
scrape_configs:
  - job_name: 'spectra'
    static_configs:
      - targets: ['localhost:8080']
```

## Operations

### Start Services

```bash
# All services
docker-compose up -d

# Specific service
docker-compose up -d spectra
```

### Stop Services

```bash
# Graceful stop
docker-compose stop

# Force stop
docker-compose kill
```

### Restart Services

```bash
# All services
docker-compose restart

# Specific service
docker-compose restart spectra
```

### Update Images

```bash
# Pull latest images
docker-compose pull

# Rebuild from source
docker-compose build --no-cache

# Deploy update
docker-compose up -d --force-recreate
```

### Scale Services

```bash
# Run multiple archiver instances
docker-compose up -d --scale spectra=3
```

### Execute Commands

```bash
# Interactive shell
docker-compose exec spectra bash

# Run Python script
docker-compose exec spectra python -c "print('hello')"

# Database integrity check
docker-compose exec spectra python -m tgarchive.db.integrity_checker
```

## Troubleshooting

### Container Won't Start

Check logs:
```bash
docker-compose logs spectra
```

Common issues:
- Missing .env file
- Invalid credentials
- Port already in use
- Insufficient resources

### Permission Denied

Verify volume permissions:

```bash
docker-compose exec spectra ls -la /app/data
```

Fix ownership:

```bash
docker-compose exec -u root spectra chown -R spectra:spectra /app/data
```

### Out of Memory

Check memory usage:

```bash
docker stats
```

Increase limit in docker-compose.yml:

```yaml
deploy:
  resources:
    limits:
      memory: 8G  # Increase to 8GB
```

### Database Locked

Stop all services:

```bash
docker-compose stop
```

Check for stale locks:

```bash
docker-compose exec spectra python -c "
import sqlite3
conn = sqlite3.connect('/app/data/spectra.db')
conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
conn.close()
"
```

Restart:

```bash
docker-compose up -d
```

### Network Issues

Reset network:

```bash
docker-compose down
docker network prune
docker-compose up -d
```

### High CPU Usage

Check processes:

```bash
docker-compose exec spectra ps aux
```

Review batch size configuration:

```json
{
  "batch": 100,  // Reduce from 500
  "sleep_between_batches": 2.0  // Increase delay
}
```

## Production Deployment

### Docker Swarm

```bash
# Initialize swarm
docker swarm init

# Deploy stack
docker stack deploy -c docker-compose.yml spectra

# Check services
docker service ls

# Scale service
docker service scale spectra_spectra=3
```

### Kubernetes

See `deployment/kubernetes/` for Helm charts and manifests.

### CI/CD Integration

Example GitHub Actions workflow:

```yaml
name: Deploy SPECTRA
on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Build image
        run: docker build -f deployment/docker/Dockerfile -t spectra:latest .
      - name: Push to registry
        run: docker push spectra:latest
      - name: Deploy
        run: docker-compose -f deployment/docker/docker-compose.yml up -d
```

## Maintenance

### Database Optimization

```bash
# VACUUM database
docker-compose exec spectra sqlite3 /app/data/spectra.db "VACUUM;"

# Update statistics
docker-compose exec spectra sqlite3 /app/data/spectra.db "ANALYZE;"
```

### Log Rotation

Configure in docker-compose.yml:

```yaml
logging:
  driver: "json-file"
  options:
    max-size: "10m"
    max-file: "5"
```

### Automated Backups

Create backup script:

```bash
#!/bin/bash
# backup.sh
DATE=$(date +%Y%m%d-%H%M%S)
docker run --rm \
  -v spectra-data:/data \
  -v $(pwd)/backups:/backup \
  alpine tar czf /backup/spectra-${DATE}.tar.gz /data
```

Add to crontab:

```bash
0 2 * * * /path/to/backup.sh
```

## Support

- GitHub Issues: https://github.com/SWORDIntel/SPECTRA/issues
- Documentation: /docs/
- Security: security@swordep.io
