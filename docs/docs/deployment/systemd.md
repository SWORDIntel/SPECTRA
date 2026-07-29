---
id: systemd
title: Systemd Deployment
sidebar_position: 2
description: Production-ready systemd service units for SPECTRA
tags: [deployment, systemd, linux, services]
---

# SPECTRA Systemd Service Configuration

SPECTRA ships five systemd service units covering three functional areas: the
main archiver stack, the live index workers, and a health endpoint. All units
are in `deployment/systemd/`.

## Service Overview

| Unit | Mode | Purpose |
|---|---|---|
| `spectra.service` | system | Main archiver — Telegram collection, forwarding, REST API |
| `spectra-scheduler.service` | system | Background cron-style job scheduler |
| `spectra-health.service` | system | Lightweight HTTP health endpoint on port 8080 |
| `spectra-index.service` | system *or* user | Continuous index watcher — primary database (`spectra.db`) |
| `spectra-index-tasks.service` | system *or* user | Continuous index watcher — task/audit sidecar (`spectra.tasks.sqlite3`) |

The two index services are independent of the archiver stack and can be run as
**system units** (multi-user server) or **user units** (workstation/developer).

---

## Index Watcher Services (spectra-index + spectra-index-tasks)

These services drain the `index_outbox` and keep KEYSTONE, QIHSE, FTS, and
graph projections current. They must be running whenever the downloader,
crawler, or archiver is active.

### Automated Installation (system units)

Use the bundled installer for system-wide deployment:

```bash
sudo bash deployment/systemd/install-index-services.sh \
  --project-dir /opt/spectra \
  --config     /etc/spectra/config.json \
  --database   /opt/spectra/data/spectra.db \
  --task-database /opt/spectra/data/spectra.tasks.sqlite3 \
  --python     /opt/spectra/.venv/bin/python \
  --user       spectra \
  --group      spectra \
  --environment-file /etc/spectra/environment
```

The installer:
- Substitutes all `@PLACEHOLDER@` values in the template unit files.
- Writes the filled units to `/etc/systemd/system/` (or `--unit-dir`).
- Runs `systemctl daemon-reload`, enables, and starts the units.
- **Never touches** the transient `spectra-index-live.service` /
  `spectra-index-tasks-live.service` units if they are active. Pass
  `--force-start` to override the deferral.

**Installer options:**

| Flag | Default | Description |
|---|---|---|
| `--project-dir PATH` | *(required)* | SPECTRA checkout or install root |
| `--config PATH` | *(required)* | JSON config file |
| `--database PATH` | *(required)* | Primary SQLite database |
| `--task-database PATH` | *(required)* | Task/audit SQLite database |
| `--python PATH` | `PROJECT/.venv/bin/python` | Python interpreter |
| `--user USER` | `spectra` | Service account |
| `--group GROUP` | `spectra` | Service group |
| `--environment-file PATH` | — | Credentials env file (`EnvironmentFile=`) |
| `--unit-dir PATH` | `/etc/systemd/system` | Unit destination |
| `--no-enable` | — | Install but do not enable |
| `--no-start` | — | Install and enable but do not start |
| `--force-start` | — | Start even with active transient units |
| `--uninstall` | — | Stop, disable, and remove the durable units |

To uninstall:

```bash
sudo bash deployment/systemd/install-index-services.sh --uninstall
```

### User-Unit Installation (workstation / developer)

For single-operator workstations where SPECTRA runs as your own user:

```bash
# 1. Copy the pre-filled units (already done for this checkout)
mkdir -p ~/.config/systemd/user

cat > ~/.config/systemd/user/spectra-index.service << 'EOF'
[Unit]
Description=SPECTRA index watcher — primary database (spectra.db)
Documentation=file:///fast/SPECTRA/docs/docs/api/indexing-architecture.md
After=network.target
Wants=spectra-index-tasks.service

[Service]
Type=simple
WorkingDirectory=/fast/SPECTRA
ExecStart=/usr/bin/python -m tgarchive \
    --config /fast/SPECTRA/spectra_config.json \
    --db /fast/SPECTRA/spectra.db \
    --output json \
    index watch \
    --batch-size 1000 \
    --poll-interval 0.1 \
    --max-backoff 60

Restart=on-failure
RestartSec=5
StartLimitIntervalSec=60
StartLimitBurst=5

Environment=PYTHONPATH=/fast/SPECTRA
EnvironmentFile=-/fast/SPECTRA/.env

KillSignal=SIGINT
TimeoutStopSec=30

StandardOutput=journal
StandardError=journal
SyslogIdentifier=spectra-index

[Install]
WantedBy=default.target
EOF

cat > ~/.config/systemd/user/spectra-index-tasks.service << 'EOF'
[Unit]
Description=SPECTRA index watcher — task sidecar (spectra.tasks.sqlite3)
Documentation=file:///fast/SPECTRA/docs/docs/api/indexing-architecture.md
After=network.target

[Service]
Type=simple
WorkingDirectory=/fast/SPECTRA
ExecStart=/usr/bin/python -m tgarchive \
    --config /fast/SPECTRA/spectra_config.json \
    --db /fast/SPECTRA/spectra.tasks.sqlite3 \
    --output json \
    index watch \
    --batch-size 1000 \
    --poll-interval 0.1 \
    --max-backoff 60

Restart=on-failure
RestartSec=5
StartLimitIntervalSec=60
StartLimitBurst=5

Environment=PYTHONPATH=/fast/SPECTRA
EnvironmentFile=-/fast/SPECTRA/.env

KillSignal=SIGINT
TimeoutStopSec=30

StandardOutput=journal
StandardError=journal
SyslogIdentifier=spectra-index-tasks

[Install]
WantedBy=default.target
EOF

# 2. Enable linger so user units survive logout
loginctl enable-linger "$USER"

# 3. Reload, enable, and start
systemctl --user daemon-reload
systemctl --user enable spectra-index.service spectra-index-tasks.service
systemctl --user start  spectra-index.service spectra-index-tasks.service
```

:::note
If the transient `spectra-index-live.service` / `spectra-index-tasks-live.service`
units are already running (started via `systemd-run`), the persistent units will
be enabled but not started. Stop the transient units first or wait for them to
exit, then start the persistent ones:

```bash
systemctl --user stop spectra-index-live.service spectra-index-tasks-live.service
systemctl --user start spectra-index.service spectra-index-tasks.service
```
:::

### Index Worker Key Behaviours

- **Drain loop** — claims up to `--batch-size` outbox events per cycle, projects
  each one with a per-event savepoint, and acknowledges the batch in a single
  follow-up transaction.
- **Claim tokens** — opaque per-lease tokens prevent an expired worker from
  overwriting the current owner's acknowledgement.
- **Backoff** — failed projection batches use capped exponential backoff up to
  `--max-backoff` seconds; clean cycles reset immediately to `--poll-interval`.
- **Graceful drain** — `SIGINT` triggers a clean drain of the current batch
  before exit; `TimeoutStopSec=30` allows this before a forced `SIGKILL`.
- **Verification drift** — `spectra index verify` exits `7` if projection
  checksums drift; the watcher emits a redacted JSON diagnostic to stderr.
- **Restart policy** — `Restart=on-failure`, `RestartSec=5`, up to 5 attempts
  per 60-second window (system units: 10 bursts per 5 minutes).

### Index Worker Management

```bash
# Status
systemctl --user status spectra-index.service spectra-index-tasks.service

# Live logs
journalctl --user -u spectra-index -f
journalctl --user -u spectra-index-tasks -f

# Manual one-shot operations (no service required)
spectra index status --output json
spectra index drain
spectra index verify --projection all --native
spectra index rebuild --projection all
```

---

## Archiver Services (spectra + spectra-scheduler + spectra-health)

These system units run the main SPECTRA collection and API stack under a
dedicated `spectra` service account.

### spectra.service

Main archiver service with security hardening and resource limits.

**Key settings:** `MemoryMax=4G`, `CPUQuota=200%`, `NoNewPrivileges=true`,
`ProtectSystem=strict`, `PrivateTmp=true`, `KillSignal=SIGINT`.

### spectra-scheduler.service

Background scheduler for automated archiving jobs.

**Key settings:** `MemoryMax=1G`, `CPUQuota=50%`, depends on `spectra.service`.

### spectra-health.service

Lightweight HTTP health endpoint on port 8080.

**Key settings:** Always running; provides `/health` for monitoring integration.

### Installation

#### 1. Create service user and directories

```bash
sudo useradd -r -s /bin/false -d /opt/spectra spectra
sudo mkdir -p /opt/spectra/{data,logs,media,venv}
sudo mkdir -p /etc/spectra
sudo chown -R spectra:spectra /opt/spectra
sudo chmod 750 /etc/spectra
```

#### 2. Install SPECTRA

```bash
sudo -u spectra python3 -m venv /opt/spectra/venv
sudo -u spectra /opt/spectra/venv/bin/pip install -e /path/to/SPECTRA
```

#### 3. Create environment and config files

`/etc/spectra/environment`:
```bash
TG_API_ID=your_api_id
TG_API_HASH=your_api_hash
SPECTRA_DB_PATH=/opt/spectra/data/spectra.db
LOG_LEVEL=INFO
```

```bash
sudo chmod 600 /etc/spectra/environment
sudo chown spectra:spectra /etc/spectra/environment
sudo cp spectra_config.json /etc/spectra/config.json
sudo chmod 600 /etc/spectra/config.json
sudo chown spectra:spectra /etc/spectra/config.json
```

#### 4. Install and enable archiver units

```bash
sudo cp deployment/systemd/spectra.service \
        deployment/systemd/spectra-scheduler.service \
        deployment/systemd/spectra-health.service \
        /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now spectra.service spectra-scheduler.service spectra-health.service
```

#### 5. Install index workers alongside the archiver

```bash
sudo bash deployment/systemd/install-index-services.sh \
  --project-dir /opt/spectra \
  --config     /etc/spectra/config.json \
  --database   /opt/spectra/data/spectra.db \
  --task-database /opt/spectra/data/spectra.tasks.sqlite3 \
  --environment-file /etc/spectra/environment
```

---

## Management Reference

### Status

```bash
# Archiver stack
sudo systemctl status spectra spectra-scheduler spectra-health

# Index workers (system)
sudo systemctl status spectra-index spectra-index-tasks

# Index workers (user)
systemctl --user status spectra-index spectra-index-tasks
```

### Logs

```bash
# Follow live (system)
sudo journalctl -u spectra-index -f
sudo journalctl -u spectra-index-tasks -f

# Follow live (user)
journalctl --user -u spectra-index -f
journalctl --user -u spectra-index-tasks -f

# Last 100 lines
sudo journalctl -u spectra -n 100

# Since last boot
sudo journalctl -u spectra -b
```

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
