# SPECTRA Project Structure

## Overview
This document describes the organized project structure after refactoring.

## Root Directory Structure

```
SPECTRA/
├── scripts/                    # All executable scripts
│   ├── install/               # Installation scripts
│   │   ├── install-spectra.sh (modern unified installer)
│   │   ├── repair-installation.sh (fix broken installations)
│   │   ├── auto-install.sh (deprecated)
│   │   └── install.sh (deprecated)
│   ├── launch/                # Launch and execution scripts
│   │   ├── spectra-launch.sh (unified bootstrap & launch)
│   │   ├── spectra.sh (linux launcher)
│   │   └── spectra.bat (windows launcher)
│   └── setup/                 # Setup and configuration scripts
│       ├── setup_env.sh
│       ├── gen_config.py
│       └── yoyo.ini (database migrations config)
│
├── data/                      # Runtime data (NOT tracked in git)
│   ├── logs/                  # Application logs
│   ├── cache/                 # Database and temporary files
│   └── config/                # Runtime configuration files
│
├── docs/                      # Documentation
│   ├── migrations/            # Database migration docs
│   ├── guides/
│   ├── design/
│   ├── reference/
│   ├── INSTALLATION_GUIDE.md
│   ├── HOW_TO_SET_API_KEY.md
│   └── DEPRECATION.md
│
├── src/                       # Archived/deprecated code
│   ├── spectra_app/           # Old app implementation
│   ├── deploy/                # Deployment configs
│   └── Telepathy-Community/   # Community fork
│
├── tgarchive/                 # Main Python package
│   ├── core/                  # Core functionality
│   │   ├── sync.py            # Archive logic
│   │   ├── config_models.py   # Configuration
│   │   └── deduplication.py   # Dedup logic
│   │
│   ├── ui/                    # User interfaces
│   │   └── tui.py             # TUI (Terminal UI)
│   │
│   ├── services/              # Background services
│   │   ├── scheduler_service.py
│   │   ├── file_system_watcher.py
│   │   ├── file_sorting_manager.py
│   │   ├── group_mirror.py
│   │   ├── mass_migration.py
│   │   └── windows_service.py
│   │
│   ├── utils/                 # Utility functions
│   │   ├── discovery.py       # Network discovery
│   │   ├── channel_utils.py   # Channel utilities
│   │   ├── file_sorter.py     # File organization
│   │   ├── attribution.py     # Message attribution
│   │   ├── group_manager.py   # Group management
│   │   ├── user_operations.py
│   │   ├── directory_manager.py
│   │   ├── sorting_forwarder.py
│   │   ├── notifications.py
│   │   └── cli_extensions.py
│   │
│   ├── db/                    # Database layer
│   │   ├── spectra_db.py      # Main DB interface
│   │   ├── models.py          # Data models
│   │   ├── schema.py          # DB schema
│   │   ├── core_operations.py
│   │   ├── forward_operations.py
│   │   └── ... (other db modules)
│   │
│   ├── forwarding/            # Message forwarding
│   │   ├── forwarder.py
│   │   ├── enhanced_forwarder.py
│   │   ├── organization_engine.py
│   │   └── topic_manager.py
│   │
│   ├── osint/                 # Intelligence gathering
│   │   ├── intelligence.py
│   │   ├── media/
│   │   └── static/
│   │
│   ├── __main__.py            # CLI entry point
│   ├── __init__.py            # Package init
│   ├── db.py                  # Legacy DB module (deprecated)
│   ├── forwarding.py          # Legacy forwarding (deprecated)
│   └── ... (other root modules)
│
├── tests/                     # Test suite
├── static/                    # Web assets
├── templates/                 # Web templates
├── examples/                  # Example code
├── logs/                      # Legacy logs directory (use data/logs/)
│
├── setup.py                   # Python package setup
├── requirements.txt           # Frozen dependencies
├── MANIFEST.in                # Package manifest
├── .gitignore                 # Git ignore rules
├── README.md
└── LICENSE

```

## Import Patterns

### Relative Imports (within tgarchive)
```python
# From core modules
from .core.sync import Config, runner, logger
from .core.config_models import Config
from .core.deduplication import get_sha256_hash

# From utils
from .utils.discovery import GroupDiscovery
from .utils.channel_utils import populate_account_channel_access

# From services
from .services.scheduler_service import SchedulerDaemon
from .services.group_mirror import GroupMirrorManager

# From UI
from .ui.tui import main as tui_main

# From db/forwarding (packages)
from .db import SpectraDB
from .forwarding import AttachmentForwarder
```

### Absolute Imports (external usage)
```python
from tgarchive import archive_channel, ArchCfg
from tgarchive.core.sync import Config
from tgarchive.utils.discovery import GroupDiscovery
from tgarchive.services.scheduler_service import SchedulerDaemon
```

## Module Organization Principles

1. **core/**: Core business logic
   - Archive functionality
   - Configuration management
   - Deduplication algorithms

2. **services/**: Background processes and daemons
   - Scheduling
   - File watching
   - Group management
   - Database operations

3. **ui/**: User interaction layers
   - TUI (npyscreen-based terminal interface)
   - Forms and input handling

4. **utils/**: Reusable utility functions
   - Network discovery
   - Channel operations
   - File management
   - Data formatting

5. **db/**: Data persistence layer
   - Database models
   - CRUD operations
   - Schema management

6. **forwarding/**: Message forwarding logic
   - Attachment handling
   - Topic organization
   - Advanced forwarding features

7. **osint/**: Intelligence gathering
   - Metadata analysis
   - Network analysis

## Data Directory Structure

The `data/` directory is **NOT** tracked in git and contains:
- Logs: Application and system logs
- Cache: Database files and temporary data
- Config: Runtime configuration JSON/INI files

## Migration from Old Structure

### Old Structure Issues
- Scattered Python modules in root of tgarchive/
- Mixed concerns (UI, services, utils) at same level
- Unclear module organization
- Difficult to maintain and extend

### Benefits of New Structure
- **Clear separation of concerns**: Core logic, Services, UI, Utilities
- **Easier navigation**: Related modules grouped together
- **Better imports**: Clearer import paths
- **Scalability**: Easy to add new services or UI modules
- **Maintainability**: Self-documenting structure

## Scripts Directory

All executable scripts are now organized under `scripts/`:

### Installation
- `install-spectra.sh`: Modern unified installer with full dependency management
- `repair-installation.sh`: Fix broken installations
- Deprecated: `auto-install.sh`, `install.sh`

### Launch
- `spectra-launch.sh`: One-command bootstrap and launch
- `spectra.sh`: Linux launcher
- `spectra.bat`: Windows launcher

### Setup
- `setup_env.sh`: Environment setup
- `gen_config.py`: Generate configuration
- `yoyo.ini`: Database migration configuration

## Git Ignore Updates

The `.gitignore` file has been updated to:
- Ignore all content in `data/logs/`, `data/cache/`
- Ignore runtime config files in `data/config/`
- Track the directory structure but not runtime data
- Ignore legacy config/database files in root
