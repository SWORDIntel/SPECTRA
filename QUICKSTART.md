# SPECTRA Quick Start Guide

## Prerequisites

Before running SPECTRA, you need to install Python dependencies. This project has been reorganized with multiple ways to get started:

## Installation Methods

### Option 1: Bootstrap (Recommended)
The bootstrap script handles everything automatically:

```bash
cd /home/user/SPECTRA
./bootstrap
```

This script will:
- Detect your OS
- Install system dependencies
- Create a Python virtual environment
- Install all Python packages
- Generate configuration templates
- Launch the TUI

### Option 2: Using Make
```bash
make bootstrap    # Full setup + launch
make install      # Just install dependencies
make run          # Launch TUI (after setup)
make help         # See all available commands
```

### Option 3: Manual Setup (For Advanced Users)

```bash
# 1. Create virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Launch the application
python3 -m tgarchive        # TUI mode
python3 -m tgarchive --no-tui  # CLI mode
```

## Required Dependencies

### Core (Required)
- `telethon` - Telegram API client
- `rich` - Terminal formatting

### Optional
- `npyscreen` - Terminal UI (required for TUI mode)
- `pysocks` - Proxy support
- `pillow` - Image processing
- `pandas` - Data processing
- `networkx` - Network analysis
- `matplotlib` - Graph visualization

## Configuration

The first time you run SPECTRA, it will prompt you to:
1. Add Telegram API credentials (from https://my.telegram.org/apps)
2. Select which accounts to use
3. Choose archiving options

Configuration is saved to: `data/config/spectra_config.json`

## Troubleshooting

### Missing Dependencies Error
```
ERROR: rich library is required. Install with: pip install rich
```

**Solution**: Run the bootstrap script:
```bash
./bootstrap
```

Or install manually:
```bash
pip install -r requirements.txt
```

### No TUI Mode
If `npyscreen` isn't installed, use CLI mode:
```bash
python3 -m tgarchive --no-tui --entity @yourchannel
```

Or install npyscreen:
```bash
pip install npyscreen
```

## Usage

### TUI Mode (Interactive)
```bash
python3 -m tgarchive
```
Navigate using arrow keys, press Enter to select.

### CLI Mode (Command Line)
```bash
# Archive a channel
python3 -m tgarchive --entity @channelname

# With options
python3 -m tgarchive --entity @channel --download-media

# Auto mode (no interaction)
python3 -m tgarchive --auto
```

## Project Structure

```
SPECTRA/
├── scripts/          # Installation and launch scripts
├── docs/             # Documentation and guides
├── data/             # Runtime data (config, logs, cache)
├── tgarchive/        # Main Python package
├── tests/            # Test suite
├── bootstrap         # Auto-setup script (recommended)
├── Makefile          # Common commands
├── README.md         # Full documentation
└── spectra           # Command launcher
```

## Getting Help

- `./bootstrap --help`  - Show bootstrap help
- `make help` - Show all available commands
- `python3 -m tgarchive --help` - Show CLI help
- `docs/INSTALLATION_GUIDE.md` - Detailed installation guide
- `docs/HOW_TO_SET_API_KEY.md` - API key setup guide

## Next Steps

1. Run `./bootstrap` to set up the environment
2. Follow the prompts to add your Telegram API credentials
3. Select accounts and channels to archive
4. Start archiving!

---

For detailed instructions, see:
- [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md) - Project organization
- [docs/INSTALLATION_GUIDE.md](docs/INSTALLATION_GUIDE.md) - Detailed setup
- [docs/HOW_TO_SET_API_KEY.md](docs/HOW_TO_SET_API_KEY.md) - API key configuration
