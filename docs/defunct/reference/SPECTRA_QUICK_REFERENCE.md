# SPECTRA Quick Reference Guide

## System Overview
**Type:** CLI/TUI-based Telegram archiving and discovery system
**Status:** Production-ready
**DB:** SQLite (WAL mode)
**Main Language:** Python 3.10+

---

## Key Entry Points

### 1. Bash Launcher
```bash
./spectra [command]
# Commands: bootstrap, run, install, repair, help
```

### 2. CLI Main
```bash
python -m tgarchive [command] [args]
spectra [command] [args]
```

### 3. TUI (Default)
```bash
python -m tgarchive
# Launches interactive ncurses interface
```

---

## Command Categories (18+ commands)

| Category | Commands |
|----------|----------|
| **Core Ops** | archive, discover, network |
| **Batch** | batch, parallel discover/join/archive |
| **Accounts** | accounts (list/test/reset/import) |
| **Forward** | forward (single/total/traversal modes) |
| **Config** | config (set/view forward dest) |
| **Channels** | channels (update-access) |
| **Schedule** | schedule (add/list/remove/run) |
| **Migration** | migrate, migrate-report, rollback |
| **OSINT** | osint (add-target/remove/scan/network) |
| **Files** | sort (watch and organize) |
| **Users** | download-users |
| **Mirror** | mirror (group-to-group sync) |

---

## Core Files

### Architecture
```
/home/user/SPECTRA/
├── tgarchive/                 # Main package
│   ├── __main__.py            # CLI entry (1278 lines)
│   ├── core/                  # Business logic
│   │   ├── sync.py            # Archiving engine
│   │   ├── config_models.py   # Config structure
│   │   ├── deduplication.py   # Dedup logic
│   │   ├── tempest_security.py # Security features
│   │   └── production_monitor.py # Health checks
│   ├── ui/
│   │   └── tui.py             # TUI interface (ncurses)
│   ├── services/              # Background services
│   │   ├── scheduler_service.py
│   │   ├── file_sorting_manager.py
│   │   ├── group_mirror.py
│   │   └── ...
│   ├── utils/                 # Utilities
│   │   ├── discovery.py       # Network analysis
│   │   ├── group_manager.py   # Account rotation
│   │   ├── forwarding.py      # Message forwarding
│   │   └── ...
│   └── db.py                  # SQLite interface
├── deployment/
│   ├── docker/Dockerfile      # Container image
│   └── systemd/               # Service files
└── templates/readme.html      # Docs UI
```

---

## Database Schema (Key Tables)

**Message Data:**
- users, media, messages, checkpoints

**Channels:**
- account_channel_access
- channel_forward_schedule
- channel_forward_stats

**Files:**
- file_forward_schedule
- file_forward_queue
- channel_file_inventory
- topic_file_mapping
- file_hashes (SHA256, perceptual, fuzzy)

**Advanced:**
- category_to_group_mapping
- sorting_groups
- migration_progress

---

## Configuration

### File: spectra_config.json
```json
{
  "api_id": int,
  "api_hash": "str",
  "accounts": [{"api_id": int, "api_hash": "str", "session_name": "str"}],
  "proxy": {"host": "", "user": "", "password": "", "ports": []},
  "db_path": "spectra.db",
  "media_dir": "media",
  "download_media": true,
  "archive_topics": true,
  "forwarding": {"enable_deduplication": true},
  "deduplication": {"enable_near_duplicates": false},
  "vps": {"enabled": false}
}
```

### Config Sources (Priority)
1. CLI arguments (highest)
2. Environment variables (TG_API_ID, TG_API_HASH)
3. spectra_config.json
4. gen_config.py auto-import
5. Defaults (lowest)

---

## Feature Matrix

| Feature | Status | Details |
|---------|--------|---------|
| **CLI Interface** | ✅ COMPLETE | 18+ commands |
| **TUI Interface** | ✅ COMPLETE | npyscreen-based |
| **Archiving** | ✅ COMPLETE | Multi-account, topics |
| **Discovery** | ✅ COMPLETE | Seed-based, depth-configurable |
| **Network Analysis** | ✅ COMPLETE | Graph-based importance scoring |
| **Forwarding** | ✅ COMPLETE | Dedup, attribution, scheduling |
| **File Organization** | ✅ COMPLETE | Auto-sorting by type |
| **Parallel Processing** | ✅ COMPLETE | Multi-worker pools |
| **Account Rotation** | ✅ COMPLETE | With ban detection |
| **Web UI** | ❌ MISSING | Flask not implemented |
| **REST API** | ❌ MISSING | No API endpoints |
| **Full-Text Search** | ❌ MISSING | No search system |
| **Real-Time Dashboard** | ❌ MISSING | No web dashboard |
| **Export UI** | ⚠️ PARTIAL | CLI only |
| **Advanced Logging** | ⚠️ PARTIAL | No correlation |

---

## Important Classes

### Core Classes
- **Config** - Configuration management
- **SpectraDB** - SQLite wrapper with retries
- **GroupDiscovery** - Group discovery engine
- **NetworkAnalyzer** - Network analysis
- **AttachmentForwarder** - Message forwarding
- **ParallelTaskScheduler** - Multi-worker scheduler

### TUI Classes
- **StatusMessages** - Scrollable log widget
- **AsyncRunner** - Async executor for ncurses
- Various form and menu classes

### Services
- **SchedulerDaemon** - Cron-based task runner
- **FileSortingManager** - File organization
- **GroupMirrorManager** - Group mirroring
- **MassMigrationManager** - Channel migration

---

## Security Features

### Implemented
- TEMPEST Class C security module
- Secure string storage with memory scrubbing
- Account rotation and cooldown tracking
- Ban detection
- Proxy rotation support
- Application-level checksums
- Timing-safe comparisons

### Missing
- User authentication (web UI)
- API key management system
- Role-based access control
- Encryption at rest

---

## Deployment

### Docker
```bash
# Build
docker build -f deployment/docker/Dockerfile -t spectra:latest .

# Run
docker run -v /data:/app/data spectra:latest

# Compose
docker-compose -f deployment/docker/docker-compose.yml up
```

### Systemd
- `/etc/systemd/system/spectra.service`
- `/etc/systemd/system/spectra-scheduler.service`
- `/etc/systemd/system/spectra-health.service`

### Health Check
- HTTP endpoint on port 8080
- Database integrity check
- Resource monitoring

---

## Dependencies

### Critical
- telethon >= 1.40.0 (Telegram API)
- rich >= 13.0.0 (Terminal formatting)
- npyscreen >= 4.10.0 (TUI)
- networkx >= 3.0 (Graph analysis)

### Optional
- pysocks >= 1.7.1 (Proxy)
- imagehash >= 4.3.0 (Image similarity)
- datasketch >= 1.6.4 (MinHash/LSH)
- psutil >= 5.9.0 (System monitoring)

### Unused (in requirements but not active)
- Flask >= 2.3.3
- Flask-SocketIO >= 5.3.6

---

## Performance Notes

- WAL mode SQLite for concurrent access
- Exponential backoff for database locks
- Parallel processing with configurable workers
- Message deduplication (SHA256, perceptual, fuzzy)
- Account rotation to avoid rate limits
- Batch processing with configurable delays

---

## Common Commands

### Archive
```bash
spectra archive --entity @channel_name [--no-media] [--auto]
```

### Discover
```bash
spectra discover --seed @channel --depth 2 --export groups.json
```

### Network Analysis
```bash
spectra network --crawler-dir ./data --from-db --plot
```

### Parallel Operations
```bash
spectra parallel discover --seeds-file seeds.txt --depth 2
spectra parallel archive --from-db --limit 10 --max-workers 4
```

### Forwarding
```bash
spectra forward --origin @source --destination @dest --total-mode
```

### Scheduling
```bash
spectra schedule add --name task1 --schedule "*/5 * * * *" --command "archive ..."
spectra schedule run
```

---

## Logging

**Log Location:** `./logs/spectra_002_archiver_YYYYMMDD_HHMMSS.log`

**Log Components:**
- Archive operations
- Discovery activity
- Network analysis
- Forwarding status
- Error conditions

**TUI Status Display:**
- Real-time operation logging
- Scrollable message history
- Timestamp tracking

---

## Database Integrity

**Features:**
- WAL mode journaling
- Foreign key constraints
- Application-level checksums
- Integrity verification on startup

**Maintenance:**
```bash
# Integrity check
python -c "from tgarchive.db.integrity_checker import quick_integrity_check"
```

---

## Troubleshooting Quick Links

1. **Installation Issues** - See docs/INSTALLATION_GUIDE.md
2. **API Setup** - See docs/HOW_TO_SET_API_KEY.md
3. **Configuration** - See docs/guides/QUICK_START.md
4. **Advanced Usage** - See README.md

---

## Next Steps for Web Module

High-priority additions for all-in-one intelligence:

1. **REST API** - Convert CLI commands to HTTP endpoints
2. **Web Dashboard** - Real-time operation tracking
3. **Search System** - Full-text message search
4. **Export UI** - Progress tracking and scheduling
5. **Analytics** - Statistics and reporting
6. **Authentication** - User login and RBAC

