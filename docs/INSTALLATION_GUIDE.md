# SPECTRA Installation Guide

## 🚀 Quick Start

### **Use the Official Installer**

```bash
./install-spectra.sh
```

This is the **only installer you need**. It provides:
- ✅ Automatic system detection (Linux, macOS, WSL)
- ✅ System dependency installation
- ✅ Virtual environment setup
- ✅ Python package installation with real-time progress
- ✅ Project structure setup
- ✅ Configuration template creation
- ✅ Installation verification

---

## 📋 Installation Steps

### **Step 1: Run the Installer**

```bash
cd ~/Documents/SPECTRA  # (or wherever you cloned it)
./install-spectra.sh
```

### **Step 2: Watch Progress**

The installer displays each dependency as it's installed:

```
▶ Installing Python dependencies...
→ Installing 8 core dependencies...
↳ Installing: telethon>=1.34.0
  ✓ telethon>=1.34.0
↳ Installing: rich>=13.0.0
  ✓ rich>=13.0.0
↳ Installing: npyscreen>=4.10.5
  ✓ npyscreen>=4.10.5
...
✓ Dependency installation complete
```

### **Step 3: Configure API Keys**

After installation, edit the configuration file:

```bash
nano spectra_config.json
```

Add your Telegram API credentials:

```json
{
  "accounts": [
    {
      "api_id": 12345678,
      "api_hash": "abcdef1234567890abcdef1234567890",
      "session_name": "account1",
      "phone_number": "+1234567890",
      "password": ""
    }
  ]
}
```

**Get API keys from:** https://my.telegram.org/auth?to=apps

### **Step 4: Activate Virtual Environment**

```bash
source .venv/bin/activate
```

### **Step 5: Test Installation**

```bash
spectra accounts --test
```

Expected output:
```
✓ account1: Connected
```

---

## ⚠️ Important Notes

### **Only One Installer Should Be Used**

- ✅ **USE:** `./install-spectra.sh` (NEW - Recommended)
- ❌ **DEPRECATED:** `./install.sh` (Old - use new installer instead)
- ❌ **DEPRECATED:** `./auto-install.sh` (Old with bugs - use new installer instead)

The new `install-spectra.sh` combines the best features of both and fixes all known issues.

### **What Gets Installed**

#### System Dependencies
- Python 3.10+ development headers
- C/C++ compiler (build-essential/gcc)
- OpenSSL and libffi development libraries

#### Python Packages (Core)
- telethon (Telegram API)
- rich (Terminal formatting)
- npyscreen (TUI framework)
- pyyaml (Configuration)
- Pillow (Image processing)
- cryptg (Encryption)

#### Python Packages (Optional)
- networkx, matplotlib, pandas (Analysis)
- aiofiles, aiosqlite (Async I/O)
- croniter, yoyo-migrations (Scheduling)
- pysocks (Proxy support)

---

## 🔧 Installation Options

### **Custom Installation**

The script has built-in options (though typically not needed):

```bash
# Verbose output
VERBOSE=true ./install-spectra.sh

# Dry run (shows what would be done)
DRY_RUN=true ./install-spectra.sh
```

### **Manual Installation** (Not Recommended)

If you need to install manually:

```bash
# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install telethon rich npyscreen pyyaml Pillow cryptg jinja2

# Optional packages
pip install networkx matplotlib pandas pysocks croniter aiofiles aiosqlite
```

---

## 🐛 Troubleshooting

### **Issue: "Python 3.10+ is required"**

```bash
# Check your Python version
python3 --version

# If too old, install Python 3.10+
sudo apt-get install python3.10  # Ubuntu/Debian
brew install python@3.10         # macOS
```

### **Issue: System Dependencies Fail**

The script continues even if some system dependencies fail (they're often already installed).

To manually install them:

**Ubuntu/Debian:**
```bash
sudo apt-get install build-essential libffi-dev libssl-dev python3-dev python3-venv
```

**CentOS/RHEL:**
```bash
sudo yum install gcc gcc-c++ make libffi-devel openssl-devel python3-devel
```

**macOS:**
```bash
brew install libffi openssl
```

### **Issue: "Failed to install" for Optional Packages**

These are non-critical. The script will skip them and continue.

### **Issue: Virtual Environment Already Exists**

The installer will reuse it. To start fresh:

```bash
rm -rf .venv
./install-spectra.sh
```

### **Issue: Permission Denied**

Make installer executable:

```bash
chmod +x install-spectra.sh
```

---

## ✅ After Installation

### **1. Configure API Keys**

Edit `spectra_config.json` with your Telegram API credentials.

See: [How to Set API Key](HOW_TO_SET_API_KEY.md)

### **2. Update Channel Database**

```bash
source .venv/bin/activate
spectra channels update-access
```

### **3. Launch SPECTRA**

```bash
# Interactive TUI
spectra

# Or use CLI
spectra forward --total-mode --destination <channel_id> --enable-deduplication
```

### **4. Test Channel Recovery**

Use the TUI Forwarding → Channel Recovery Wizard:
1. Update Channel Access Database
2. Set Recovery Destination
3. Click "START RECOVERY"

---

## 📝 Installation Log

All installation details are logged to:

```
logs/install_YYYYMMDD_HHMMSS.log
```

View the latest log:

```bash
tail -f logs/install_*.log
```

---

## 🆘 Getting Help

If installation fails:

1. **Check the log file** (see above)
2. **Check Python version:** `python3 --version` (need 3.10+)
3. **Check pip:** `pip3 --version`
4. **Run in verbose mode:** `VERBOSE=true ./install-spectra.sh`
5. **Report the error with the full log output**

---

## 📌 System Requirements

- **OS:** Linux (Ubuntu, CentOS, etc.), macOS, or Windows WSL2
- **Python:** 3.10 or higher
- **RAM:** 2GB minimum (more for large channels)
- **Disk:** 1GB+ for dependencies and data
- **Network:** Internet connection for Telegram API

---

## 🔒 Security Notes

1. **API Keys:** Keep `spectra_config.json` secure (`chmod 600`)
2. **Don't commit:** Add to `.gitignore`:
   ```
   spectra_config.json
   *.session
   ```
3. **Use env vars:** For production, use environment variables instead of config files
   ```bash
   export TG_API_ID=your_id
   export TG_API_HASH=your_hash
   ```

---

## ✨ Success Indicators

After installation, you should see:

```
✓ INSTALLATION COMPLETE!

Next Steps:
1. Configure API Keys
   Edit: spectra_config.json

2. Activate Virtual Environment
   source .venv/bin/activate

3. Test Installation
   spectra accounts --test

4. Start SPECTRA
   spectra
```

If you see this, installation was successful! 🎉
