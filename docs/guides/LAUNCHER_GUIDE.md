# SPECTRA Auto-Launcher System
## Comprehensive Setup and Usage Guide

🚀 **Professional Auto-Launching System for SPECTRA** - Zero-configuration, cross-platform, production-ready

---

## 📋 Quick Start

### One-Click Launch
```bash
# Linux/macOS - Just run this:
./spectra.sh

# Windows - Just run this:
spectra.bat

# Or use the Python launcher directly:
python3 scripts/spectra_launch.py
```

### First-Time Setup
```bash
# Automatic setup (recommended):
./auto-install.sh

# Or step-by-step:
python3 scripts/spectra_launch.py --setup
```

---

## 🎯 What This System Provides

### ✅ **Automatic Dependency Management**
- Creates and manages Python virtual environment
- Installs all required dependencies with fallbacks
- Handles version conflicts and compatibility issues
- Cross-platform dependency resolution

### ✅ **Professional User Experience**
- Animated splash screen with progress indication
- Interactive setup wizard for first-time users
- Comprehensive error messages with solutions
- One-click launch to TUI interface

### ✅ **Cross-Platform Compatibility**
- **Linux**: Full support (Ubuntu, CentOS, Arch, etc.)
- **macOS**: Native support with Homebrew integration
- **Windows**: PowerShell, Command Prompt, Git Bash
- **WSL**: Windows Subsystem for Linux support

### ✅ **Intelligent Error Recovery**
- Automatic detection and repair of broken installations
- Fallback dependency installation strategies
- System dependency verification and installation
- Configuration validation and recovery

### ✅ **Zero Configuration Required**
- Automatic account import from `gen_config.py`
- Smart system detection and optimization
- Automatic directory structure creation
- Self-healing installation system

---

## 📦 System Components

### Core Launcher Scripts
| Script | Platform | Purpose |
|--------|----------|---------|
| `scripts/spectra_launch.py` | Universal | Main Python launcher with full functionality |
| `spectra.sh` | Linux/macOS | Bash wrapper with auto-detection |
| `spectra.bat` | Windows | Batch file for Windows environments |
| `auto-install.sh` | Linux/macOS | Enhanced installation with system deps |

### Support Components
| Component | Purpose |
|-----------|---------|
| `scripts/spectra_splash.py` | Animated startup screens and progress |
| `requirements.txt` | Enhanced dependencies with fallbacks |
| `spectra_config.json` | Auto-generated configuration |

---

## 🚀 Launch Options

### Interactive Mode (Recommended for New Users)
```bash
./spectra.sh --interactive        # Linux/macOS
spectra.bat --interactive         # Windows
python3 scripts/spectra_launch.py --setup # Universal
```

**Features:**
- Guided setup process
- System status overview
- Auto-repair options
- User-friendly choices

### Direct TUI Launch
```bash
./spectra.sh                      # Linux/macOS
spectra.bat                       # Windows
python3 scripts/spectra_launch.py         # Universal
```

**Features:**
- Immediate TUI startup
- Automatic dependency checking
- Progress indication
- Error recovery

### CLI Mode
```bash
./spectra.sh cli                  # Show CLI commands
python3 scripts/spectra_launch.py --cli   # Universal CLI help
```

### System Diagnostics
```bash
./spectra.sh check                # Quick system check
./spectra.sh --status             # Detailed status
python3 scripts/spectra_launch.py --check # Universal check
```

---

## 🔧 Installation Methods

### Method 1: Enhanced Auto-Installer (Recommended)
```bash
# Clone repository
git clone https://github.com/SWORDIntel/SPECTRA.git
cd SPECTRA

# Run enhanced installer
./auto-install.sh

# Optional: Create desktop shortcuts
./auto-install.sh --desktop

# Force clean installation
./auto-install.sh --force
```

**Features:**
- Automatic system dependency detection and installation
- Virtual environment creation with latest pip
- Comprehensive dependency installation with fallbacks
- Desktop integration (optional)
- Cross-platform compatibility

### Method 2: Python Launcher Setup
```bash
# Basic setup
python3 scripts/spectra_launch.py --setup

# With system repair
python3 scripts/spectra_launch.py --repair

# Check system status
python3 scripts/spectra_launch.py --check
```

### Method 3: Manual Installation
```bash
# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate  # Linux/macOS
.venv\Scripts\activate     # Windows

# Install dependencies
pip install -e .

# Launch SPECTRA
python -m tgarchive
```

---

## 🛠️ Configuration

### Automatic Configuration Discovery

The launcher automatically detects and imports configuration from:

1. **`gen_config.py`** - TELESMASHER-compatible account file
2. **`spectra_config.json`** - Main configuration file
3. **Environment variables** - API credentials
4. **Interactive setup** - Step-by-step configuration

### Manual Configuration

Edit `spectra_config.json`:
```json
{
  "accounts": [
    {
      "api_id": 12345,
      "api_hash": "your_api_hash",
      "session_name": "main"
    }
  ],
  "discovery": {
    "default_depth": 2,
    "max_messages": 1000
  },
  "parallel": {
    "max_workers": 4
  }
}
```

### First-Time Setup Wizard

Run the interactive setup:
```bash
python3 scripts/spectra_launch.py --setup
```

The wizard will:
- Import accounts from `gen_config.py` if available
- Guide you through manual account setup
- Validate API credentials
- Test Telegram connectivity
- Save configuration automatically

---

## 🎨 User Experience Features

### Animated Splash Screen
```bash
# Show splash with progress
python3 scripts/spectra_splash.py --progress

# Interactive startup with choices
python3 scripts/spectra_splash.py --interactive

# Quick system check
python3 scripts/spectra_splash.py --check
```

### Progress Indicators
- **Spinner animations** during long operations
- **Progress bars** for installation steps
- **Status indicators** for system health
- **Color-coded messages** for different status levels

### Error Recovery Assistant
- **Automatic problem detection** with clear explanations
- **Suggested solutions** for common issues
- **One-click repair** for broken installations
- **Fallback strategies** for dependency conflicts

---

## 🔍 Troubleshooting

### Common Issues and Solutions

#### Python Version Issues
```bash
# Problem: Python 3.10+ not found
# Solution: Install Python 3.10+
sudo apt-get install python3.11  # Ubuntu/Debian
brew install python@3.11         # macOS
# Download from python.org       # Windows
```

#### Virtual Environment Problems
```bash
# Problem: Virtual environment creation failed
# Solution: Install python3-venv
sudo apt-get install python3-venv  # Ubuntu/Debian

# Or recreate virtual environment
rm -rf .venv
python3 scripts/spectra_launch.py --repair
```

#### Dependency Installation Failures
```bash
# Problem: Some packages fail to install
# Solution: Install system dependencies
sudo apt-get install build-essential libffi-dev libssl-dev  # Ubuntu
sudo yum groupinstall "Development Tools"                   # CentOS
xcode-select --install                                       # macOS

# Or use minimal installation
python3 scripts/spectra_launch.py --setup
# Choose "core dependencies only" when prompted
```

#### Permission Issues
```bash
# Problem: Permission denied errors
# Solution: Fix permissions
chmod +x scripts/spectra_launch.py
chmod +x spectra.sh
chmod +x auto-install.sh

# Or run without execution permission
python3 scripts/spectra_launch.py
bash spectra.sh
```

#### Configuration Problems
```bash
# Problem: No Telegram accounts configured
# Solution: Run setup wizard
python3 scripts/spectra_launch.py --setup

# Or manually edit config
nano spectra_config.json

# Get API credentials from:
# https://my.telegram.org/apps
```

### Advanced Troubleshooting

#### System Diagnostics
```bash
# Comprehensive system check
python3 scripts/spectra_launch.py --check

# Detailed status with debugging
./spectra.sh --status

# Check installation logs
cat logs/install_*.log
cat logs/launcher_*.log
```

#### Repair and Recovery
```bash
# Automatic repair
python3 scripts/spectra_launch.py --repair

# Force clean reinstallation
./auto-install.sh --force

# Reset configuration
rm spectra_config.json
python3 scripts/spectra_launch.py --setup
```

#### Manual Debugging
```bash
# Activate virtual environment
source .venv/bin/activate

# Test Python imports
python -c "import tgarchive; print('OK')"
python -c "import telethon; print('Telethon OK')"
python -c "import rich; print('Rich OK')"

# Test SPECTRA directly
python -m tgarchive --help
```

---

## 📊 System Requirements

### Minimum Requirements
- **Python**: 3.10 or later
- **RAM**: 2GB available
- **Storage**: 500MB for installation
- **Network**: Internet connection for initial setup

### Recommended Requirements
- **Python**: 3.11 or later
- **RAM**: 4GB available
- **Storage**: 2GB for data and logs
- **Network**: Stable broadband connection

### Platform-Specific Requirements

#### Linux
- **Distributions**: Ubuntu 20.04+, CentOS 8+, Arch Linux, Debian 11+
- **Packages**: `python3-venv`, `python3-dev`, `build-essential`
- **Optional**: `git`, `curl`, desktop environment for shortcuts

#### macOS
- **Version**: macOS 10.15 (Catalina) or later
- **Tools**: Xcode Command Line Tools
- **Package Manager**: Homebrew (recommended)

#### Windows
- **Version**: Windows 10 or later
- **Python**: From python.org or Microsoft Store
- **Terminal**: PowerShell, Command Prompt, or Git Bash

---

## 🌍 Cross-Platform Usage

### Linux Usage
```bash
# Standard installation
git clone https://github.com/SWORDIntel/SPECTRA.git
cd SPECTRA
./auto-install.sh

# Launch
./spectra.sh

# Create desktop shortcut
./auto-install.sh --desktop
```

### macOS Usage
```bash
# Install system dependencies
brew install python@3.11 git

# Install SPECTRA
git clone https://github.com/SWORDIntel/SPECTRA.git
cd SPECTRA
./auto-install.sh

# Launch
./spectra.sh

# Create app bundle
./auto-install.sh --desktop
```

### Windows Usage
```batch
REM Clone repository (using Git for Windows)
git clone https://github.com/SWORDIntel/SPECTRA.git
cd SPECTRA

REM Setup using Python launcher
python scripts/spectra_launch.py --setup

REM Launch
spectra.bat

REM Or use PowerShell
powershell -ExecutionPolicy Bypass -File spectra.ps1
```

### Windows Subsystem for Linux (WSL)
```bash
# Works exactly like Linux
./auto-install.sh
./spectra.sh

# Can access Windows filesystem
cd /mnt/c/Users/YourName/Downloads/SPECTRA
./spectra.sh
```

---

## 📈 Performance Optimizations

### Virtual Environment Optimization
- **Isolated dependencies** prevent conflicts
- **Pip caching** speeds up reinstallation
- **Optimized package selection** reduces installation time
- **Automatic cleanup** prevents bloat

### Dependency Management
- **Frozen versions** ensure compatibility
- **Fallback strategies** handle installation failures
- **Optional dependencies** reduce core requirements
- **Platform-specific packages** optimize performance

### Startup Performance
- **Cached system checks** reduce startup time
- **Lazy imports** speed up initial load
- **Progress indication** improves perceived performance
- **Background initialization** for responsive UI

---

## 🔧 Advanced Configuration

### Environment Variables
```bash
# Override Python command
export SPECTRA_PYTHON=python3.11

# Override virtual environment path
export SPECTRA_VENV_PATH=/path/to/custom/venv

# Enable debug mode
export SPECTRA_DEBUG=1

# Specify config file
export SPECTRA_CONFIG=/path/to/config.json
```

### Custom Installation Paths
```bash
# Install to custom directory
./auto-install.sh --prefix=/opt/spectra

# Use existing virtual environment
SPECTRA_VENV_PATH=/path/to/venv ./spectra.sh
```

### Proxy Configuration
```bash
# HTTP proxy
export http_proxy=http://proxy.example.com:8080
export https_proxy=http://proxy.example.com:8080

# SOCKS proxy
export ALL_PROXY=socks5://proxy.example.com:1080
```

---

## 🎯 Production Deployment

### System Service Installation
```bash
# Install as systemd service (Linux)
sudo cp deploy/spectra-scheduler.service /etc/systemd/system/
sudo systemctl enable spectra-scheduler
sudo systemctl start spectra-scheduler

# Install as launchd service (macOS)
cp com.swordint.spectra.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.swordint.spectra.plist
```

### Docker Deployment
```bash
# Build Docker image
docker build -t spectra:latest .

# Run container
docker run -d --name spectra \
  -v $(pwd)/data:/app/spectra_data \
  -v $(pwd)/config:/app/config \
  spectra:latest
```

### Multi-User Installation
```bash
# System-wide installation
sudo ./auto-install.sh --system
sudo chmod 755 /opt/spectra/spectra.sh

# User access via symlink
ln -s /opt/spectra/spectra.sh ~/.local/bin/spectra
```

---

## 📚 Development and Contribution

### Development Setup
```bash
# Clone for development
git clone https://github.com/SWORDIntel/SPECTRA.git
cd SPECTRA

# Install in development mode
./auto-install.sh --force
source .venv/bin/activate
pip install -e .[dev]

# Run tests
python -m pytest
```

### Adding New Features
1. **Extend launcher scripts** for new functionality
2. **Update requirements.txt** for new dependencies
3. **Add configuration options** to config schema
4. **Update documentation** and help text
5. **Test cross-platform compatibility**

### Contributing Guidelines
- **Follow existing code style** and patterns
- **Test on multiple platforms** (Linux, macOS, Windows)
- **Update documentation** for new features
- **Maintain backward compatibility** when possible
- **Add comprehensive error handling**

---

## 📞 Support and Resources

### Getting Help
- **GitHub Issues**: https://github.com/SWORDIntel/SPECTRA/issues
- **Documentation**: See `docs/` directory
- **System Check**: `python3 scripts/spectra_launch.py --check`
- **Verbose Logs**: Check `logs/` directory

### Useful Commands
```bash
# System information
python3 scripts/spectra_launch.py --check

# Repair installation
python3 scripts/spectra_launch.py --repair

# Reset configuration
rm spectra_config.json && python3 scripts/spectra_launch.py --setup

# View logs
tail -f logs/launcher_*.log
```

### Community Resources
- **Example Configurations**: See `examples/` directory
- **Video Tutorials**: Links in main README
- **Community Scripts**: User-contributed automation
- **Best Practices**: Production deployment guides

---

## 📋 Summary

The SPECTRA Auto-Launcher System provides:

✅ **Zero-configuration startup** with automatic dependency management
✅ **Cross-platform compatibility** (Linux, macOS, Windows)
✅ **Professional user experience** with progress indication
✅ **Intelligent error recovery** and system repair
✅ **Production-ready deployment** with comprehensive testing
✅ **Extensive documentation** and troubleshooting guides

**Start using SPECTRA in 30 seconds:**
```bash
git clone https://github.com/SWORDIntel/SPECTRA.git
cd SPECTRA
./spectra.sh
```

That's it! The launcher handles everything else automatically.

---

*For technical support, feature requests, or contributions, please visit the [SPECTRA GitHub repository](https://github.com/SWORDIntel/SPECTRA).*