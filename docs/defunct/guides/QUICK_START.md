# SPECTRA Quick Start Guide
## Get Running in 30 Seconds

🚀 **Professional Auto-Launching System** - Zero configuration required!

---

## 🎯 One-Click Launch

### Option 1: Cross-Platform Launcher (Recommended)
```bash
# Linux/macOS:
./spectra.sh

# Windows:
spectra.bat

# Any platform with Python:
python3 scripts/spectra_launch.py
```

### Option 2: Enhanced Auto-Installer
```bash
# Full automatic setup:
./auto-install.sh

# With desktop shortcuts:
./auto-install.sh --desktop

# Force clean installation:
./auto-install.sh --force
```

---

## 🚀 What Happens Automatically

✅ **System Detection** - Automatically detects your OS and Python version
✅ **Virtual Environment** - Creates and manages Python virtual environment
✅ **Dependencies** - Installs all required packages with fallback options
✅ **Configuration** - Auto-imports accounts from `gen_config.py` if available
✅ **Directory Setup** - Creates all necessary data and log directories
✅ **Error Recovery** - Automatically fixes common installation issues
✅ **Progress Display** - Shows animated progress with status updates
✅ **TUI Launch** - Starts SPECTRA TUI interface immediately

---

## 🔧 First-Time Setup

### If You Have `gen_config.py` (TELESMASHER users):
```bash
# Everything is automatic!
./spectra.sh
# Accounts will be imported automatically
```

### If You Need to Configure Accounts:
```bash
# Run setup wizard:
python3 scripts/spectra_launch.py --setup

# Follow the prompts to:
# 1. Get API credentials from https://my.telegram.org/apps
# 2. Enter your API ID and Hash
# 3. Choose a session name
# 4. Test the connection
```

---

## 📱 Quick Commands

### Launch Options
```bash
./spectra.sh                    # Start TUI (default)
./spectra.sh cli               # Show CLI commands
./spectra.sh setup             # Run setup wizard
./spectra.sh check             # Check system status
./spectra.sh --interactive     # Interactive mode with choices
```

### System Management
```bash
python3 scripts/spectra_launch.py --check    # Detailed system check
python3 scripts/spectra_launch.py --repair   # Repair broken installation
python3 tests/test_launcher.py       # Test all components
```

### Help and Status
```bash
./spectra.sh --help            # Show all options
./spectra.sh --status          # Quick status check
python3 scripts/spectra_splash.py --interactive  # Interactive startup
```

---

## 🎨 Features

### Professional User Experience
- **Animated splash screen** with SPECTRA logo
- **Progress indicators** for all operations
- **Color-coded status messages** with icons
- **Interactive setup wizard** for beginners
- **One-click error recovery** for common issues

### Cross-Platform Support
- **Linux**: Ubuntu, CentOS, Arch, Debian, and more
- **macOS**: Native support with Homebrew integration
- **Windows**: PowerShell, Command Prompt, Git Bash
- **WSL**: Windows Subsystem for Linux compatibility

### Automatic Error Recovery
- **Dependency conflicts** - Multiple installation strategies
- **Version mismatches** - Automatic compatibility detection
- **Missing system packages** - Auto-installation on supported systems
- **Broken virtual environment** - Automatic recreation and repair
- **Configuration issues** - Interactive wizard for fixing problems

---

## 🛠️ System Requirements

### Minimum Requirements
- **Python 3.10+** (automatically detected)
- **2GB RAM** available
- **500MB storage** for installation
- **Internet connection** for initial setup

### Supported Platforms
- **Linux**: Any modern distribution with Python 3.10+
- **macOS**: 10.15 (Catalina) or later
- **Windows**: Windows 10 or later
- **WSL**: Windows Subsystem for Linux (any version)

---

## 🔍 Troubleshooting

### Common Issues

#### "Python 3.10+ not found"
```bash
# Ubuntu/Debian:
sudo apt-get install python3.11

# CentOS/RHEL:
sudo dnf install python3.11

# macOS:
brew install python@3.11

# Windows: Download from python.org
```

#### "Virtual environment creation failed"
```bash
# Install venv module:
sudo apt-get install python3-venv  # Linux
# Usually included with Python on macOS/Windows

# Or repair automatically:
python3 scripts/spectra_launch.py --repair
```

#### "Dependencies failed to install"
```bash
# Install build tools:
sudo apt-get install build-essential  # Ubuntu/Debian
sudo yum groupinstall "Development Tools"  # CentOS
xcode-select --install  # macOS

# Or use automatic repair:
./auto-install.sh --force
```

#### "No Telegram accounts configured"
```bash
# Run setup wizard:
python3 scripts/spectra_launch.py --setup

# Get API credentials:
# 1. Go to https://my.telegram.org/apps
# 2. Create a new application
# 3. Copy API ID and Hash
# 4. Enter in setup wizard
```

### Getting Help
```bash
# System diagnostics:
python3 scripts/spectra_launch.py --check

# Comprehensive repair:
python3 scripts/spectra_launch.py --repair

# Interactive troubleshooting:
./spectra.sh --interactive

# View logs:
cat logs/launcher_*.log
cat logs/install_*.log
```

---

## 📊 Quick Test

Verify everything is working:
```bash
# Run test suite:
python3 tests/test_launcher.py

# Check system status:
python3 scripts/spectra_launch.py --check

# Test splash screen:
python3 scripts/spectra_splash.py --check

# Try interactive mode:
./spectra.sh --interactive
```

---

## 🎯 Next Steps

Once SPECTRA is running:

1. **Import or configure accounts** via the setup wizard
2. **Explore the TUI interface** - all major features accessible
3. **Try discovery operations** - start with a seed channel
4. **Set up network analysis** - visualize Telegram networks
5. **Configure archiving** - download and archive content
6. **Use parallel processing** - leverage multiple accounts

### Advanced Usage
- **CLI commands**: `./spectra.sh cli` for command-line reference
- **Batch operations**: Process multiple channels automatically
- **Scheduled tasks**: Set up automated archiving
- **API integration**: Use SPECTRA modules in your own scripts

---

## 📞 Support

- **System Check**: `python3 scripts/spectra_launch.py --check`
- **Comprehensive Guide**: See [`LAUNCHER_GUIDE.md`](./LAUNCHER_GUIDE.md)
- **Project Documentation**: See `README.md`
- **GitHub Issues**: https://github.com/SWORDIntel/SPECTRA/issues

---

**🎉 That's it! SPECTRA should now be ready to use. The auto-launcher handles all the complexity automatically.**
