# SPECTRA Systemd Service Configuration

Production-ready systemd service units for SPECTRA deployment on Linux systems.

## Services

### spectra.service
Main SPECTRA archiver service with comprehensive security hardening and resource limits.

**Features:**
- TEMPEST Class C security controls
- Resource limits (4GB RAM, 200% CPU)
- Automatic restart on failure
- Graceful shutdown handling
- Protected system directories
- Credential isolation via environment files

### spectra-scheduler.service
Background scheduler for automated archiving tasks.

**Features:**
- Depends on main service
- Reduced resource limits (1GB RAM, 50% CPU)
- Automatic restart
- Cron-based job execution

### spectra-health.service
Health check HTTP endpoint for monitoring.

**Features:**
- Lightweight service (always running)
- Provides /health endpoint on port 8080
- Real-time resource metrics
- Integration with monitoring systems

## Installation

### 1. Create Service User

```bash
sudo useradd -r -s /bin/false -d /opt/spectra spectra
```

### 2. Setup Directory Structure

```bash
sudo mkdir -p /opt/spectra/{data,logs,media,venv}
sudo mkdir -p /etc/spectra
sudo chown -R spectra:spectra /opt/spectra
sudo chmod 750 /etc/spectra
```

### 3. Install SPECTRA

```bash
cd /opt/spectra
sudo -u spectra python3 -m venv venv
sudo -u spectra venv/bin/pip install -e /path/to/SPECTRA
```

### 4. Create Environment File

Create `/etc/spectra/environment`:

```bash
# Telegram API Credentials
TG_API_ID=your_api_id
TG_API_HASH=your_api_hash

# Optional: Database path
SPECTRA_DB_PATH=/opt/spectra/data/spectra.db

# Optional: Log level
LOG_LEVEL=INFO
```

Secure the file:

```bash
sudo chmod 600 /etc/spectra/environment
sudo chown spectra:spectra /etc/spectra/environment
```

### 5. Create Configuration File

Copy your config to `/etc/spectra/config.json` and secure it:

```bash
sudo cp spectra_config.json /etc/spectra/config.json
sudo chmod 600 /etc/spectra/config.json
sudo chown spectra:spectra /etc/spectra/config.json
```

### 6. Install Service Files

```bash
sudo cp deployment/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
```

### 7. Enable and Start Services

```bash
# Enable services to start on boot
sudo systemctl enable spectra.service
sudo systemctl enable spectra-scheduler.service
sudo systemctl enable spectra-health.service

# Start services
sudo systemctl start spectra.service
sudo systemctl start spectra-scheduler.service
sudo systemctl start spectra-health.service
```

## Management

### Check Status

```bash
sudo systemctl status spectra
sudo systemctl status spectra-scheduler
sudo systemctl status spectra-health
```

### View Logs

```bash
# Real-time logs
sudo journalctl -u spectra -f

# Last 100 lines
sudo journalctl -u spectra -n 100

# Since boot
sudo journalctl -u spectra -b
```

### Restart Services

```bash
sudo systemctl restart spectra
```

### Stop Services

```bash
sudo systemctl stop spectra
sudo systemctl stop spectra-scheduler
sudo systemctl stop spectra-health
```

### Reload Configuration

```bash
sudo systemctl reload spectra
```

## Monitoring

### Health Check Endpoint

The health service provides an HTTP endpoint:

```bash
curl http://localhost:8080/health
```

Response:
```json
{
  "status": "healthy",
  "timestamp": "2025-01-15T10:30:00Z",
  "checks": [
    {
      "component": "cpu",
      "status": "healthy",
      "metrics": {"cpu_percent": 15.3}
    },
    {
      "component": "memory",
      "status": "healthy",
      "metrics": {"memory_percent": 45.2}
    },
    {
      "component": "disk",
      "status": "healthy",
      "metrics": {"disk_free_gb": 125.5}
    }
  ]
}
```

### Resource Usage

```bash
# Memory usage
systemctl show spectra --property=MemoryCurrent

# CPU usage
systemd-cgtop
```

## Security Hardening

The service files implement TEMPEST Class C security controls:

1. **Filesystem Isolation**
   - `ProtectSystem=strict` - Read-only root filesystem
   - `ProtectHome=true` - No access to user home directories
   - `ReadWritePaths=...` - Only specified directories writable
   - `PrivateTmp=true` - Isolated /tmp directory

2. **Privilege Restrictions**
   - `NoNewPrivileges=true` - Cannot gain new privileges
   - `ProtectKernelTunables=true` - No kernel parameter access
   - `ProtectKernelModules=true` - No module loading
   - `RestrictNamespaces=true` - Limited namespace creation

3. **Resource Limits**
   - `MemoryMax=4G` - Maximum memory usage
   - `CPUQuota=200%` - CPU core limit
   - `TasksMax=100` - Process/thread limit

4. **Credential Protection**
   - Credentials in environment file (not config)
   - Environment file secured with 600 permissions
   - Config file secured with 600 permissions
   - Service runs as dedicated user

## Troubleshooting

### Service Won't Start

Check logs:
```bash
sudo journalctl -u spectra -xe
```

Common issues:
- Missing environment file: Create `/etc/spectra/environment`
- Wrong permissions: Check file ownership and permissions
- Missing dependencies: Reinstall Python packages
- Database locked: Check for stale lock files

### Permission Denied Errors

Verify ownership:
```bash
sudo chown -R spectra:spectra /opt/spectra
sudo chown spectra:spectra /etc/spectra/config.json
sudo chown spectra:spectra /etc/spectra/environment
```

### High Resource Usage

Check current limits:
```bash
systemctl show spectra --property=MemoryMax
systemctl show spectra --property=CPUQuota
```

Adjust limits in service file and reload:
```bash
sudo systemctl daemon-reload
sudo systemctl restart spectra
```

### Database Integrity Issues

Run integrity check:
```bash
sudo -u spectra /opt/spectra/venv/bin/python -c "
from tgarchive.db.integrity_checker import DatabaseIntegrityChecker
checker = DatabaseIntegrityChecker('/opt/spectra/data/spectra.db')
checker.run_all_checks()
checker.print_report()
"
```

## Backup and Recovery

### Automated Backups

Create backup timer (spectra-backup.timer):

```ini
[Unit]
Description=SPECTRA Database Backup Timer
Requires=spectra-backup.service

[Timer]
OnCalendar=daily
Persistent=true

[Install]
WantedBy=timers.target
```

### Manual Backup

```bash
sudo -u spectra sqlite3 /opt/spectra/data/spectra.db ".backup /opt/spectra/backups/spectra-$(date +%Y%m%d).db"
```

## Maintenance

### Log Rotation

Configure journald in `/etc/systemd/journald.conf`:

```ini
[Journal]
SystemMaxUse=1G
SystemMaxFileSize=100M
MaxRetentionSec=30day
```

### Database Optimization

```bash
# Run VACUUM to reclaim space
sudo -u spectra sqlite3 /opt/spectra/data/spectra.db "VACUUM;"

# Update statistics for query optimization
sudo -u spectra sqlite3 /opt/spectra/data/spectra.db "ANALYZE;"
```

## Integration with Monitoring Systems

### Prometheus

Add to prometheus.yml:

```yaml
scrape_configs:
  - job_name: 'spectra'
    static_configs:
      - targets: ['localhost:8080']
```

### Nagios/Icinga

```bash
/usr/lib/nagios/plugins/check_http -H localhost -p 8080 -u /health -s "healthy"
```

## Support

For issues and questions:
- GitHub Issues: https://github.com/SWORDIntel/SPECTRA/issues
- Documentation: /opt/spectra/docs/
