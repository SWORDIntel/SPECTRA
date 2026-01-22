# SPECTRA Project - Comprehensive Architecture Analysis

## Executive Summary
SPECTRA is an advanced Telegram network discovery and forensic archiving system built in Python. It operates as a **CLI/TUI-based application** with **no web interface currently**, though Flask/Flask-SocketIO are in requirements.txt as placeholder dependencies. The system uses a **SQLite database** for persistence and supports **multi-account, parallel processing**, and sophisticated **discovery and forwarding capabilities**.

---

# 1. CURRENT UI/UX COMPONENTS

## 1.1 Web Interfaces
**Status: MINIMAL - Documentation/GUI endpoints only**
- **No active Flask web UI for core operations**
- **Static HTML templates only:**
  - `/home/user/SPECTRA/templates/readme.html` - Documentation UI (Jinja2-based)
  - `/home/user/SPECTRA/tgarchive/osint/template.html` - OSINT archive template
  - `/home/user/SPECTRA/tgarchive/osint/rss_template.html` - RSS feed template
  - `/home/user/SPECTRA/tgarchive/example/template.html` - Example template

**Framework Status:**
- Flask 2.3.3 and Flask-SocketIO 5.3.6 in requirements.txt but not actively used
- Only serving static documentation via HTTP server in scheduler_service.py
- No REST API endpoints currently implemented

## 1.2 CLI/TUI Interfaces
**Status: PRIMARY INTERFACE - FULLY FUNCTIONAL**

### Entry Points:
1. **Main entry point:** `/home/user/SPECTRA/spectra` (bash launcher)
   - Auto-bootstraps and launches TUI
   - Supports `bootstrap`, `run`, `install`, `repair` commands

2. **Python CLI:** `python -m tgarchive` or `spectra` command
   - **Primary handler:** `/home/user/SPECTRA/tgarchive/__main__.py` (1278 lines)
   - **Parser:** GroupedHelpFormatter with 15+ command categories

### CLI Commands Available (18+ commands):

**Core Operations:**
- `archive` - Archive a Telegram channel/group
- `discover` - Discover connected groups from seed entity
- `network` - Analyze group network topology

**Batch/Parallel Operations:**
- `batch` - Process multiple groups sequentially
- `parallel discover` - Parallel discovery across seeds
- `parallel join` - Multi-account group joining
- `parallel archive` - Multi-account archiving

**Advanced Features:**
- `forward` - Message forwarding (with deduplication support)
- `osint` - Target tracking and intelligence gathering
- `mirror` - Group-to-group mirroring
- `sort` - File organization by type
- `schedule` - Task scheduling (cron-based)
- `migrate` - Channel migration operations
- `download-users` - User list extraction
- `accounts` - Multi-account management
- `config` - Configuration management
- `channels` - Channel access management

### TUI Interface:
**File:** `/home/user/SPECTRA/tgarchive/ui/tui.py` (1000+ lines)
- **Framework:** npyscreen (ncurses-based)
- **Components:**
  - Status messages widget with scrollable logging
  - AsyncRunner for running async operations from ncurses
  - Real-time progress display
  - Interactive command execution
  - Menu-driven operations for all major workflows

## 1.3 Frontend Frameworks
- **TUI Framework:** npyscreen 4.10+
- **Web Templates:** Jinja2 3.1.2 (for HTML templates only)
- **Web Framework:** Flask 2.3.3 + Flask-SocketIO 5.3.6 (installed but unused)
- **Static Assets:**
  - CSS/HTML in `/home/user/SPECTRA/tgarchive/osint/static/main.js`
  - No modern frontend framework (Vue, React, Angular)

---

# 2. CURRENT ARCHITECTURE

## 2.1 Entry Points & Application Start

### Bootstrap Chain:
```
./spectra (bash launcher)
├── ./bootstrap (setup + launch)
├── ./scripts/launch/spectra-launch.sh
└── python -m tgarchive

Python Entry Point Chain:
tgarchive.__main__.main()
├── setup_parser() → argparse.ArgumentParser
├── async_main(args) → Async handler
└── Command mapping → Specific handlers
```

### Main Entry File Structure:
**`/home/user/SPECTRA/tgarchive/__main__.py`**
- 1278 lines of Python
- CLI parser with 15+ command groups
- Command handlers for all 18+ operations
- Async main loop with keyboard interrupt handling

## 2.2 Configuration Management

### Configuration Files:
- **Primary:** `spectra_config.json` (JSON-based)
- **Schema:** `/home/user/SPECTRA/tgarchive/core/config_models.py`
- **Location:** `/home/user/SPECTRA/tgarchive/core/config_models.py`

### Config Structure:
```python
DEFAULT_CFG = {
    "api_id": int,
    "api_hash": str,
    "accounts": [{
        "api_id": int,
        "api_hash": str,
        "session_name": str
    }],
    "proxy": {
        "host", "user", "password", "ports": []
    },
    "entity": str,
    "db_path": "spectra.sqlite3",
    "media_dir": "media",
    "download_media": bool,
    "download_avatars": bool,
    "batch": int,
    "sleep_between_batches": float,
    "archive_topics": bool,
    "forwarding": {
        "enable_deduplication": bool,
        "secondary_unique_destination": str
    },
    "deduplication": {
        "enable_near_duplicates": bool,
        "fuzzy_hash_similarity_threshold": int,
        "perceptual_hash_distance_threshold": int
    },
    "vps": {
        "enabled": bool,
        "host": str,
        "port": int,
        "sync_options": {...}
    }
}
```

### Config Sources:
1. Environment variables (TG_API_ID, TG_API_HASH)
2. spectra_config.json file
3. gen_config.py auto-import (TELESMASHER compatible)
4. CLI argument overrides

## 2.3 Database Structure & Schema

### Database File:
**`/home/user/SPECTRA/tgarchive/db.py`** (SpectraDB class - 600+ lines)

### Database Configuration:
- **Type:** SQLite (WAL mode, foreign key integrity)
- **Path:** Configurable (default: `spectra.db`)
- **Features:**
  - WAL mode for concurrent access
  - Exponential backoff on lock contention (retry logic)
  - Application-level checksums
  - Thread-safe connections

### Core Schema Tables:

**Message & User Data:**
```sql
users (id, username, first_name, last_name, tags, avatar, last_updated)
media (id, type, url, title, description, thumb, checksum)
messages (id, type, date, edit_date, content, reply_to, user_id, media_id, checksum)
checkpoints (id, last_message_id, checkpoint_time, context)
```

**Channel Management:**
```sql
account_channel_access (account_phone_number, channel_id, channel_name, access_hash, last_seen)
channel_forward_schedule (id, channel_id, destination, schedule, last_message_id, is_enabled)
channel_forward_stats (id, schedule_id, messages_forwarded, files_forwarded, bytes_forwarded)
```

**File Operations:**
```sql
file_forward_schedule (id, source, destination, schedule, file_types, min/max_file_size)
file_forward_queue (id, schedule_id, message_id, file_id, destination, status)
channel_file_inventory (id, channel_id, file_id, message_id, topic_id)
topic_file_mapping (id, topic_id, file_id, message_id)
```

**Advanced Features:**
```sql
file_hashes (id, file_id, sha256_hash, perceptual_hash, fuzzy_hash)
category_to_group_mapping (id, category, group_id, priority)
sorting_groups (id, group_name, template, is_enabled)
migration_progress (id, source, destination, last_message_id, status)
```

## 2.4 API Endpoints & Data Flow

### Current API Structure:
**No REST API implemented** - Only CLI/TUI interfaces

### Internal Module Interfaces:

**Core Processing:**
- `runner()` - Main archiving orchestration (from `core/sync.py`)
- `GroupDiscovery` - Group discovery engine (from `utils/discovery.py`)
- `NetworkAnalyzer` - Network analysis (from `utils/discovery.py`)
- `AttachmentForwarder` - Message forwarding (from `forwarding.py`)

**Data Flow:**
```
CLI/TUI Input
├── Config Loading (config_models.py)
├── Database Init (db.py)
├── Telegram Client Init (telethon)
├── Operation Handler
│   ├── Archive Handler
│   ├── Discovery Handler
│   ├── Forward Handler
│   └── Network Handler
└── Database Output
```

### Command Handler Chain:
```python
async_main(args)
├── Command Mapping
│   ├── archive → handle_archive()
│   ├── discover → handle_discover()
│   ├── network → handle_network()
│   ├── forward → handle_attachment_forwarding() or handle_cloud_forwarding()
│   ├── parallel → handle_parallel()
│   └── ... (13 more handlers)
└── TUI Fallback (if no command)
```

---

# 3. MISSING FEATURES FOR ALL-IN-ONE INTELLIGENCE MODULE

## 3.1 Logging/Correlation Features

**Current Logging:**
- Basic Python logging to `logs/` directory
- Log files per application run with timestamps
- File: `/home/user/SPECTRA/tgarchive/core/sync.py` (lines 107-116)

**Issues - NOT IMPLEMENTED:**
- No centralized correlation dashboard
- No real-time log streaming
- No log aggregation system
- No performance metrics collection
- No security event logging

**Files with logging:**
- `/home/user/SPECTRA/tgarchive/db.py` - DB operations logging
- `/home/user/SPECTRA/tgarchive/core/sync.py` - Archive logging
- `/home/user/SPECTRA/tgarchive/ui/tui.py` - TUI status messages
- `/home/user/SPECTRA/tgarchive/services/scheduler_service.py` - Task logging

**What EXISTS:**
- StatusMessages widget in TUI for real-time output (tui.py, lines 82-92)
- Structured logging with timestamps
- Log rotation per run

## 3.2 Download/Export Functionality

**Currently Implemented:**
1. **Archive Export:**
   - Full Telegram archive downloads (messages, media, avatars)
   - Sidecar metadata JSON for each file
   - Topic/thread support

2. **Network Export:**
   - `--export` flag for discovered groups (CLI)
   - JSON format output
   - File: `utils/discovery.py` - `export_groups_to_file()` method

3. **Forwarding/Migration:**
   - `forward` command with message forwarding
   - `migrate` command for channel migration
   - `migrate-report` for migration status

4. **User Data Export:**
   - `download-users` command (line 273-279 in __main__.py)
   - Formats: CSV, JSON, SQLite
   - Server-based user extraction

**Missing - NOT IMPLEMENTED:**
- Bulk export with filtering
- Real-time export progress monitoring
- Incremental/resumable exports
- Export scheduling
- Data format conversion (e.g., to PDF, Excel)
- Encrypted archive exports
- Custom export templates

## 3.3 Search/Filter Capabilities

**Currently Limited:**
- Basic SQL queries in database
- No full-text search
- No advanced filtering UI

**Missing - NOT IMPLEMENTED:**
- Full-text message search
- Advanced filtering (by user, date range, file type)
- Search UI in web interface
- Search API endpoints
- Tag-based filtering
- Content similarity search
- Deduplication search

**Files related to search:**
- `tgarchive/db.py` - Database queries (basic only)
- `tgarchive/utils/discovery.py` - Group discovery filtering

## 3.4 Dashboard/Reporting Functionality

**Current Dashboard Elements:**
- TUI status display (basic)
- HTML templates for archive display (not real-time)
- Scheduler health check endpoint (basic HTTP)

**Missing - NOT IMPLEMENTED:**
- Real-time analytics dashboard
- System health monitoring dashboard
- Operation progress tracking
- Performance metrics visualization
- Export/forwarding statistics
- Network topology visualization (data analysis exists, but no visualization)
- User interaction heatmaps
- Archive coverage reports

**Partially Implemented:**
- Network analysis in `utils/discovery.py` (NetworkAnalyzer class)
- Graph visualization with matplotlib (commented out in some places)
- Statistics tracking in scheduler_service.py

---

# 4. SECURITY & CONFIGURATION

## 4.1 Security Mechanisms

### TEMPEST Class C Security Module:
**File:** `/home/user/SPECTRA/tgarchive/core/tempest_security.py` (600+ lines)

**Implemented Security Features:**
1. **Secure String Storage:**
   - Memory scrubbing with array.array
   - Timing-safe comparisons with hmac.compare_digest
   - Memory locking with mlock (Linux/Unix)

2. **OPSEC Features:**
   - Account rotation management
   - Proxy rotation support
   - Session persistence
   - Cooldown tracking for banned accounts

3. **Data Protection:**
   - Application-level checksums
   - Sidecar metadata encryption (prepared but not active)
   - Credential protection in memory

### Account Management:
**File:** `/home/user/SPECTRA/tgarchive/utils/group_manager.py`
- Account rotation logic
- Usage counting
- Ban detection
- Cooldown enforcement

### Error Recovery:
**File:** `/home/user/SPECTRA/tgarchive/core/error_recovery.py`
- Automatic retry with exponential backoff
- Circuit breaker pattern
- Graceful degradation

## 4.2 Authentication & Authorization

**Telegram API Authentication:**
- Telethon library handles OAuth2-like flow
- Session files per account
- No API key exposure in logs

**Application-Level Auth:**
- No user authentication system (local CLI only)
- Config-based account selection
- No role-based access control

**Missing - NOT IMPLEMENTED:**
- User authentication for web UI
- Role-based access control (RBAC)
- API key management
- Token-based API authentication

## 4.3 Configuration Management Approach

**Configuration Sources (Priority Order):**
1. CLI arguments (highest priority)
2. Environment variables
3. spectra_config.json file
4. gen_config.py (auto-import from TELESMASHER)
5. Hardcoded defaults (lowest priority)

**Configuration Validation:**
**File:** `/home/user/SPECTRA/tgarchive/core/config_validation.py`
- Input validation for config parameters
- Type checking
- Range validation

**Config Persistence:**
- JSON file-based configuration
- Auto-save of configuration changes
- Version tracking

## 4.4 Docker & Deployment Files

### Docker Setup:
**File:** `/home/user/SPECTRA/deployment/docker/Dockerfile`

**Configuration:**
- Python 3.11-slim-bookworm base image
- Non-root user (spectra:spectra)
- Multi-stage build ready
- Health check endpoint (port 8080)
- Volume mounts for data persistence

**Key Features:**
```dockerfile
# Security: Drop to non-root user
USER spectra

# Health check
HEALTHCHECK --interval=30s --timeout=10s
CMD python -c "from tgarchive.db.integrity_checker import quick_integrity_check"

# Volumes
VOLUME ["/app/data", "/app/logs", "/app/media", "/app/checkpoints"]

# Expose health check port
EXPOSE 8080
```

### Environment Configuration:
**File:** `/home/user/SPECTRA/deployment/docker/.env.example`

```bash
TG_API_ID=your_api_id_here
TG_API_HASH=your_api_hash_here
LOG_LEVEL=INFO
PROXY_HOST=rotating.proxyempire.io
SPECTRA_DB_PATH=/app/data/spectra.db
DOWNLOAD_MEDIA=true
HEALTH_CHECK_PORT=8080
SECURE_LOGGING=true
MEMORY_SCRUBBING=true
CREDENTIAL_ENCRYPTION=true
```

### Systemd Services:
**Files:**
- `/home/user/SPECTRA/deployment/systemd/spectra.service` - Main service
- `/home/user/SPECTRA/deployment/systemd/spectra-scheduler.service` - Scheduler service
- `/home/user/SPECTRA/deployment/systemd/spectra-health.service` - Health monitor

### Docker Compose:
**File:** `/home/user/SPECTRA/deployment/docker/docker-compose.yml`
- Container orchestration ready
- Volume management
- Environment variable passing

---

# 5. COMPONENT BREAKDOWN

## 5.1 Core Modules

| Module | Purpose | Status |
|--------|---------|--------|
| `core/sync.py` | Main archiving orchestration | Production |
| `core/config_models.py` | Configuration management | Production |
| `core/deduplication.py` | Message deduplication | Production |
| `core/tempest_security.py` | OPSEC/security features | Production |
| `core/production_monitor.py` | Health & resource monitoring | Ready |
| `core/error_recovery.py` | Automatic retry logic | Production |
| `core/config_validation.py` | Config validation | Production |

## 5.2 Service Modules

| Service | Purpose | Status |
|---------|---------|--------|
| `services/scheduler_service.py` | Cron-based task scheduling | Production |
| `services/file_system_watcher.py` | Directory monitoring | Production |
| `services/file_sorting_manager.py` | Automatic file organization | Production |
| `services/group_mirror.py` | Group-to-group mirroring | Production |
| `services/mass_migration.py` | Channel migration | In Development |
| `services/windows_service.py` | Windows service wrapper | Ready |

## 5.3 Utility Modules

| Utility | Purpose | Status |
|---------|---------|--------|
| `utils/discovery.py` | Group discovery & network analysis | Production |
| `utils/channel_utils.py` | Channel access management | Production |
| `utils/file_sorter.py` | File organization logic | Production |
| `utils/attribution.py` | Message source attribution | Production |
| `utils/group_manager.py` | Multi-account group operations | Production |
| `utils/user_operations.py` | User data extraction | Production |
| `utils/notifications.py` | Alert/notification system | Ready |
| `utils/progress.py` | Progress tracking | Production |
| `utils/directory_manager.py` | Directory structure management | Production |

## 5.4 Database Layer

**Primary:** `/home/user/SPECTRA/tgarchive/db.py`
- SQLite with WAL mode
- Connection pooling
- Transaction management
- Schema creation and migration

**Additional DB Modules:**
- `db/core_operations.py` - Core DB operations
- `db/forward_operations.py` - Forwarding operations
- `db/migration_operations.py` - Migration tracking
- `db/sorting_hash_operations.py` - File hash operations
- `db/vector_store.py` - Vector embeddings storage
- `db/integrity_checker.py` - Database integrity verification

---

# 6. SPECIAL FEATURES

## 6.1 Parallel & Batch Processing
**Status:** FULLY IMPLEMENTED

- Multi-account parallel discovery
- Parallel group joining
- Parallel archiving across multiple groups
- Configurable worker pool (max-workers)
- Task scheduling via `ParallelTaskScheduler`

**Files:**
- `__main__.py` - Parallel command handlers (lines 843-1040)
- `utils/discovery.py` - ParallelTaskScheduler class

## 6.2 Network Analysis
**Status:** IMPLEMENTED (Analysis) + MISSING (Visualization)

- Graph-based group relationship analysis
- Importance scoring (degree, betweenness, pagerank, combined)
- Priority targeting based on network metrics
- Export to JSON

**Missing:** Real-time visualization dashboard

## 6.3 Message Forwarding & Deduplication
**Status:** PRODUCTION

**Features:**
- SHA256-based exact deduplication
- Perceptual hashing for images
- Fuzzy hashing for near-duplicates
- Similarity thresholds (configurable)
- Secondary destination for unique messages only
- Attribution tracking

**File:** `forwarding.py` (600+ lines)

## 6.4 OSINT & Intelligence Gathering
**Status:** FUNCTIONAL

**File:** `osint/intelligence.py`

**Capabilities:**
- Target user tracking
- Channel interaction scanning
- User network visualization
- Interaction history logging

**Missing:** Real-time OSINT dashboard

## 6.5 File Organization & Sorting
**Status:** PRODUCTION

**Features:**
- Automatic file type detection
- Directory structure organization
- Template-based naming
- Category-based grouping

**Files:**
- `services/file_sorting_manager.py`
- `utils/file_sorter.py`

---

# 7. DEPENDENCIES & ENVIRONMENT

## 7.1 Critical Dependencies
```
telethon>=1.40.0          # Telegram API client
rich>=13.0.0              # Terminal formatting
tqdm>=4.66.1              # Progress bars
PyYAML>=6.0.0             # Config handling
Pillow>=11.0.0            # Image processing
npyscreen>=4.10.0         # TUI framework
networkx>=3.0             # Network analysis
matplotlib>=3.6.0         # Plotting
pandas>=2.2.0             # Data analysis
```

## 7.2 Optional but Important
```
pysocks>=1.7.1            # SOCKS proxy support
croniter>=1.3.5           # Cron expression parsing
imagehash>=4.3.0          # Image hashing
datasketch>=1.6.4         # MinHash/LSH
psutil>=5.9.0             # System monitoring
aiofiles>=23.2.1          # Async file I/O
aiosqlite>=0.20.0         # Async SQLite
```

## 7.3 Framework Dependencies (Unused in Core)
```
Flask==2.3.3              # Not currently used
Flask-SocketIO==5.3.6     # Not currently used
Jinja2==3.1.2             # For HTML templates only
```

---

# 8. MONITORING & HEALTH

## 8.1 Production Monitoring
**File:** `/home/user/SPECTRA/tgarchive/core/production_monitor.py`

**Features:**
- Health check system
- Resource monitoring (CPU, memory, disk)
- Performance metrics collection
- Graceful shutdown handlers
- Alert thresholds

**Status Levels:**
- HEALTHY - All systems operational
- DEGRADED - Some issues detected
- UNHEALTHY - Major issues
- CRITICAL - System failure imminent

## 8.2 Health Check Endpoint
**Scheduler Service:**
- HTTP server on configurable port
- Simple GET /health endpoint
- Returns 200 OK if healthy

**Docker Health Check:**
- Runs database integrity check
- Interval: 30 seconds
- Timeout: 10 seconds
- Retries: 3

---

# 9. RECOMMENDATIONS FOR ALL-IN-ONE INTELLIGENCE MODULE

## High Priority (Missing Core Features)

1. **Web Dashboard UI**
   - REST API endpoints for operations
   - Real-time operation tracking
   - System health monitoring dashboard
   - Network visualization

2. **Advanced Logging & Correlation**
   - Centralized log aggregation
   - Event correlation engine
   - Audit trail for all operations
   - Performance metrics dashboard

3. **Search & Filter System**
   - Full-text message search
   - Advanced filtering UI
   - Saved search queries
   - Real-time search API

4. **Enhanced Export/Download**
   - Incremental/resumable exports
   - Custom export templates
   - Scheduled bulk exports
   - Multiple format support (PDF, Excel, etc.)

5. **Reporting & Analytics**
   - Coverage reports
   - Statistics summaries
   - Timeline analysis
   - User interaction heatmaps

## Medium Priority (Nice to Have)

1. **Automation Improvements**
   - Workflow builder UI
   - Rule-based automation
   - Scheduled operations dashboard

2. **Advanced Security**
   - User authentication for web UI
   - API key management
   - Role-based access control

3. **Performance Optimization**
   - Caching layer for frequent queries
   - Index optimization
   - Bulk operation batching

## Low Priority (Future Enhancements)

1. **AI/ML Integration**
   - Semantic search
   - Pattern detection
   - Anomaly detection

2. **Integration Support**
   - Webhook support
   - Third-party API connectors
   - Data export to external systems

---

# 10. FILE PATHS & REFERENCES

## Key Configuration Files
- `/home/user/SPECTRA/tgarchive/core/config_models.py` - Config structure
- `/home/user/SPECTRA/spectra_config.json` - Runtime config

## Main Application Files
- `/home/user/SPECTRA/tgarchive/__main__.py` - CLI entry point
- `/home/user/SPECTRA/tgarchive/ui/tui.py` - TUI interface
- `/home/user/SPECTRA/tgarchive/db.py` - Database layer
- `/home/user/SPECTRA/tgarchive/forwarding.py` - Message forwarding

## Deployment Files
- `/home/user/SPECTRA/deployment/docker/Dockerfile` - Docker image
- `/home/user/SPECTRA/deployment/docker/docker-compose.yml` - Compose config
- `/home/user/SPECTRA/deployment/systemd/spectra.service` - Systemd service

## Core Business Logic
- `/home/user/SPECTRA/tgarchive/core/sync.py` - Archiving orchestration
- `/home/user/SPECTRA/tgarchive/utils/discovery.py` - Network discovery
- `/home/user/SPECTRA/tgarchive/services/scheduler_service.py` - Task scheduling

## Security & Monitoring
- `/home/user/SPECTRA/tgarchive/core/tempest_security.py` - Security controls
- `/home/user/SPECTRA/tgarchive/core/production_monitor.py` - Health monitoring
- `/home/user/SPECTRA/tgarchive/core/error_recovery.py` - Error handling

---

# 11. SYSTEM STATUS SUMMARY

| Component | Status | Maturity | Notes |
|-----------|--------|----------|-------|
| **CLI/TUI Interface** | ✅ COMPLETE | Production | 18+ commands, fully functional |
| **Core Archiving** | ✅ COMPLETE | Production | Multi-account, multi-threaded |
| **Database Layer** | ✅ COMPLETE | Production | SQLite with WAL, comprehensive schema |
| **Discovery/Network Analysis** | ✅ COMPLETE | Production | Graph analysis, priority targeting |
| **Message Forwarding** | ✅ COMPLETE | Production | Dedup, filtering, scheduling |
| **File Organization** | ✅ COMPLETE | Production | Automatic sorting, categorization |
| **Parallel Processing** | ✅ COMPLETE | Production | Multi-worker, configurable |
| **Security/OPSEC** | ✅ IMPLEMENTED | Production | TEMPEST Class C, account rotation |
| **Web UI/Dashboard** | ❌ MISSING | N/A | Flask in deps but not implemented |
| **REST API** | ❌ MISSING | N/A | No API endpoints implemented |
| **Full-Text Search** | ❌ MISSING | N/A | No search system |
| **Advanced Logging** | ⚠️ PARTIAL | Basic | Logging exists but no correlation |
| **Analytics/Reporting** | ❌ MISSING | N/A | No real-time dashboard |
| **Export/Download UI** | ⚠️ PARTIAL | Basic | CLI only, no progress tracking |

