#!/bin/bash
# SPECTRA Unified Installer
# ========================
#
# Comprehensive installation script with:
# - Cross-platform support (Linux, macOS, Windows WSL)
# - Virtual environment management
# - Dependency resolution with progress display
# - Error recovery and system compatibility checks
# - Single installer (no conflicts with other installers)

set -e  # Exit on error

# ─────────────────────────────────────────────────────────────────────────────
# Color definitions
# ─────────────────────────────────────────────────────────────────────────────
if [[ -t 1 ]] && command -v tput >/dev/null 2>&1; then
    BLUE=$(tput setaf 4)
    GREEN=$(tput setaf 2)
    RED=$(tput setaf 1)
    YELLOW=$(tput setaf 3)
    CYAN=$(tput setaf 6)
    PURPLE=$(tput setaf 5)
    BOLD=$(tput bold)
    NC=$(tput sgr0)
else
    BLUE='\033[0;34m'
    GREEN='\033[0;32m'
    RED='\033[0;31m'
    YELLOW='\033[0;33m'
    CYAN='\033[0;36m'
    PURPLE='\033[0;35m'
    BOLD='\033[1m'
    NC='\033[0m'
fi

# ─────────────────────────────────────────────────────────────────────────────
# Global Variables
# ─────────────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR"
INSTALL_LOG="$PROJECT_ROOT/logs/install_$(date +%Y%m%d_%H%M%S).log"
VENV_PATH="$PROJECT_ROOT/.venv"
CONFIG_PATH="$PROJECT_ROOT/spectra_config.json"

OS_TYPE=""
PACKAGE_MANAGER=""
PYTHON_CMD=""
PIP_CMD=""

VERBOSE=false
DRY_RUN=false

# ─────────────────────────────────────────────────────────────────────────────
# Utility Functions
# ─────────────────────────────────────────────────────────────────────────────

print_banner() {
    echo -e "\n${BLUE}${BOLD}╔═══════════════════════════════════════════════════════════════════════════╗"
    echo "║                          ███████╗██████╗ ███████╗ ██████╗████████╗██████╗  ║"
    echo "║                          ██╔════╝██╔══██╗██╔════╝██╔════╝╚══██╔══╝██╔══██╗ ║"
    echo "║                          ███████╗██████╔╝█████╗  ██║        ██║   ██████╔╗ ║"
    echo "║                          ╚════██║██╔═══╝ ██╔══╝  ██║        ██║   ██╔══██║ ║"
    echo "║                          ███████║██║     ███████╗╚██████╗   ██║   ██║  ██║ ║"
    echo "║                          ╚══════╝╚═╝     ╚══════╝ ╚═════╝   ╚═╝   ╚═╝  ╚═╝ ║"
    echo "╚═══════════════════════════════════════════════════════════════════════════╝${NC}"
    echo -e "${BOLD}               Unified Installation Script - Network Discovery & Archiving${NC}\n"
}

log_message() {
    local level="$1"
    local message="$2"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')

    # Create logs directory if it doesn't exist
    mkdir -p "$(dirname "$INSTALL_LOG")"

    # Write to log file
    echo "[$timestamp] [$level] $message" >> "$INSTALL_LOG"

    # Print to console with colors
    case "$level" in
        "INFO")
            echo -e "${CYAN}→${NC} $message"
            ;;
        "SUCCESS")
            echo -e "${GREEN}✓${NC} $message"
            ;;
        "INSTALL")
            echo -e "${PURPLE}↳${NC} Installing: ${BOLD}$message${NC}"
            ;;
        "INSTALLED")
            echo -e "  ${GREEN}✓${NC} $message"
            ;;
        "WARNING")
            echo -e "${YELLOW}⚠${NC} $message"
            ;;
        "ERROR")
            echo -e "${RED}✗${NC} $message"
            ;;
        "PROGRESS")
            echo -e "${PURPLE}▶${NC} $message"
            ;;
        *)
            echo -e "$message"
            ;;
    esac
}

# ─────────────────────────────────────────────────────────────────────────────
# System Detection
# ─────────────────────────────────────────────────────────────────────────────

detect_system() {
    log_message "PROGRESS" "Detecting system..."

    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        OS_TYPE="Linux"
        if command -v apt-get &> /dev/null; then
            PACKAGE_MANAGER="apt"
        elif command -v yum &> /dev/null; then
            PACKAGE_MANAGER="yum"
        elif command -v pacman &> /dev/null; then
            PACKAGE_MANAGER="pacman"
        else
            log_message "ERROR" "Unsupported package manager"
            exit 1
        fi
    elif [[ "$OSTYPE" == "darwin"* ]]; then
        OS_TYPE="macOS"
        if command -v brew &> /dev/null; then
            PACKAGE_MANAGER="brew"
        else
            log_message "ERROR" "Homebrew is required on macOS. Install from https://brew.sh"
            exit 1
        fi
    else
        log_message "ERROR" "Unsupported operating system: $OSTYPE"
        exit 1
    fi

    log_message "SUCCESS" "System detected: $OS_TYPE ($PACKAGE_MANAGER)"
}

check_python() {
    log_message "PROGRESS" "Checking Python installation..."

    if ! command -v python3 &> /dev/null; then
        log_message "ERROR" "Python 3 is not installed"
        exit 1
    fi

    local python_version=$(python3 --version 2>&1 | awk '{print $2}')
    local python_major=$(echo $python_version | cut -d. -f1)
    local python_minor=$(echo $python_version | cut -d. -f2)

    if [ "$python_major" -lt 3 ] || ([ "$python_major" -eq 3 ] && [ "$python_minor" -lt 10 ]); then
        log_message "ERROR" "Python 3.10+ is required (found $python_version)"
        exit 1
    fi

    PYTHON_CMD="python3"
    log_message "SUCCESS" "Python $python_version detected"
}

install_system_dependencies() {
    log_message "PROGRESS" "Installing system dependencies..."

    case "$PACKAGE_MANAGER" in
        "apt")
            local deps=("build-essential" "libffi-dev" "libssl-dev" "python3-dev" "python3-venv")
            for dep in "${deps[@]}"; do
                if dpkg -l | grep -q "^ii.*$dep"; then
                    log_message "INFO" "$dep is already installed"
                else
                    log_message "INSTALL" "system package: $dep"
                    if sudo apt-get install -y "$dep" >> "$INSTALL_LOG" 2>&1; then
                        log_message "INSTALLED" "$dep"
                    else
                        log_message "WARNING" "Failed to install $dep (non-critical)"
                    fi
                fi
            done
            ;;
        "yum")
            local deps=("gcc" "gcc-c++" "make" "libffi-devel" "openssl-devel" "python3-devel")
            for dep in "${deps[@]}"; do
                log_message "INSTALL" "system package: $dep"
                if sudo yum install -y "$dep" >> "$INSTALL_LOG" 2>&1; then
                    log_message "INSTALLED" "$dep"
                else
                    log_message "WARNING" "Failed to install $dep (non-critical)"
                fi
            done
            ;;
        "pacman")
            local deps=("base-devel" "libffi" "openssl")
            for dep in "${deps[@]}"; do
                log_message "INSTALL" "system package: $dep"
                if sudo pacman -S --noconfirm "$dep" >> "$INSTALL_LOG" 2>&1; then
                    log_message "INSTALLED" "$dep"
                else
                    log_message "WARNING" "Failed to install $dep (non-critical)"
                fi
            done
            ;;
        "brew")
            local deps=("libffi" "openssl")
            for dep in "${deps[@]}"; do
                if brew list "$dep" &> /dev/null; then
                    log_message "INFO" "$dep is already installed"
                else
                    log_message "INSTALL" "system package: $dep"
                    if brew install "$dep" >> "$INSTALL_LOG" 2>&1; then
                        log_message "INSTALLED" "$dep"
                    else
                        log_message "WARNING" "Failed to install $dep (non-critical)"
                    fi
                fi
            done
            ;;
    esac

    log_message "SUCCESS" "System dependencies installation complete"
}

setup_virtual_environment() {
    log_message "PROGRESS" "Setting up Python virtual environment..."

    if [[ -d "$VENV_PATH" ]]; then
        log_message "INFO" "Virtual environment already exists at $VENV_PATH"
    else
        log_message "INSTALL" "Creating virtual environment"
        if $PYTHON_CMD -m venv "$VENV_PATH" >> "$INSTALL_LOG" 2>&1; then
            log_message "INSTALLED" "Virtual environment created"
        else
            log_message "ERROR" "Failed to create virtual environment"
            exit 1
        fi
    fi

    # Set pip command
    PIP_CMD="$VENV_PATH/bin/pip"

    log_message "PROGRESS" "Upgrading pip..."
    if $PIP_CMD install --upgrade pip >> "$INSTALL_LOG" 2>&1; then
        log_message "INSTALLED" "pip upgraded"
    else
        log_message "WARNING" "Failed to upgrade pip (continuing anyway)"
    fi
}

install_python_dependencies() {
    log_message "PROGRESS" "Installing Python dependencies..."

    # Core dependencies
    local core_deps=(
        "telethon>=1.34.0"
        "rich>=13.0.0"
        "tqdm>=4.0.0"
        "pyyaml>=6.0.0"
        "Pillow>=10.0.0"
        "npyscreen>=4.10.5"
        "jinja2>=3.0.0"
        "cryptg>=0.2.post4"
    )

    # Optional dependencies
    local optional_deps=(
        "networkx>=3.0"
        "matplotlib>=3.6.0"
        "pandas>=1.5.0"
        "python-magic>=0.4.27"
        "pysocks>=1.7.1"
        "croniter>=1.3.5"
        "yoyo-migrations>=8.2.0"
        "aiofiles>=23.2.1"
        "aiosqlite>=0.20.0"
    )

    local installed_count=0
    local failed_count=0
    local skipped_count=0

    # Install core dependencies
    log_message "INFO" "Installing ${#core_deps[@]} core dependencies..."
    for dep in "${core_deps[@]}"; do
        log_message "INSTALL" "$dep"
        if $PIP_CMD install "$dep" >> "$INSTALL_LOG" 2>&1; then
            log_message "INSTALLED" "$dep"
            ((installed_count++))
        else
            log_message "ERROR" "Failed to install core dependency: $dep"
            ((failed_count++))
        fi
    done

    # Install optional dependencies (don't fail if they don't install)
    log_message "INFO" "Installing ${#optional_deps[@]} optional dependencies..."
    for dep in "${optional_deps[@]}"; do
        log_message "INSTALL" "$dep (optional)"
        if $PIP_CMD install "$dep" >> "$INSTALL_LOG" 2>&1; then
            log_message "INSTALLED" "$dep"
            ((installed_count++))
        else
            log_message "WARNING" "Skipped optional dependency: $dep"
            ((skipped_count++))
        fi
    done

    log_message "INFO" "Dependency installation summary: $installed_count installed, $failed_count failed, $skipped_count skipped"

    if [[ $failed_count -gt 3 ]]; then
        log_message "ERROR" "Too many core dependencies failed. Installation cannot continue."
        exit 1
    fi

    log_message "SUCCESS" "Python dependencies installation complete"
}

setup_project_structure() {
    log_message "PROGRESS" "Setting up project structure..."

    local directories=(
        "spectra_data"
        "spectra_data/media"
        "logs"
        "migrations"
    )

    for dir in "${directories[@]}"; do
        local full_path="$PROJECT_ROOT/$dir"
        if [[ ! -d "$full_path" ]]; then
            log_message "INSTALL" "directory: $dir"
            if mkdir -p "$full_path" >> "$INSTALL_LOG" 2>&1; then
                log_message "INSTALLED" "$dir"
            else
                log_message "WARNING" "Failed to create directory: $dir"
            fi
        else
            log_message "INFO" "Directory already exists: $dir"
        fi
    done

    log_message "SUCCESS" "Project structure setup complete"
}

verify_installation() {
    log_message "PROGRESS" "Verifying installation..."

    # Check if required modules can be imported
    if $VENV_PATH/bin/python3 -c "import telethon; import rich; import npyscreen" 2>/dev/null; then
        log_message "SUCCESS" "Core modules verified"
    else
        log_message "WARNING" "Some modules could not be verified (may require runtime imports)"
    fi

    log_message "SUCCESS" "Installation verification complete"
}

create_config_template() {
    if [[ ! -f "$CONFIG_PATH" ]]; then
        log_message "PROGRESS" "Creating configuration template..."
        cat > "$CONFIG_PATH" << 'EOF'
{
  "accounts": [
    {
      "api_id": 0,
      "api_hash": "YOUR_API_HASH_HERE",
      "session_name": "account1",
      "phone_number": "+1234567890",
      "password": ""
    }
  ],
  "default_forwarding_destination_id": null,
  "forwarding": {
    "enable_deduplication": true,
    "secondary_unique_destination": null,
    "auto_invite_accounts": true
  },
  "db": {
    "path": "spectra.db"
  },
  "logging": {
    "level": "INFO",
    "file": "spectra.log"
  }
}
EOF
        log_message "INSTALLED" "Configuration template created at $CONFIG_PATH"
        log_message "INFO" "Please edit $CONFIG_PATH and add your Telegram API credentials"
    else
        log_message "INFO" "Configuration file already exists at $CONFIG_PATH"
    fi
}

print_next_steps() {
    echo -e "\n${BOLD}${GREEN}╔═══════════════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}${GREEN}║                    ✓ INSTALLATION COMPLETE!${NC}"
    echo -e "${BOLD}${GREEN}╚═══════════════════════════════════════════════════════════════════════════╝${NC}\n"

    echo -e "${BOLD}Next Steps:${NC}\n"

    echo -e "1. ${BOLD}Configure API Keys${NC}"
    echo -e "   Edit: ${CYAN}$CONFIG_PATH${NC}"
    echo -e "   Get API credentials from: ${CYAN}https://my.telegram.org/auth?to=apps${NC}\n"

    echo -e "2. ${BOLD}Activate Virtual Environment${NC}"
    echo -e "   ${CYAN}source $VENV_PATH/bin/activate${NC}\n"

    echo -e "3. ${BOLD}Test Installation${NC}"
    echo -e "   ${CYAN}spectra accounts --test${NC}\n"

    echo -e "4. ${BOLD}Start SPECTRA${NC}"
    echo -e "   ${CYAN}spectra${NC} (or run TUI directly)\n"

    echo -e "${BOLD}Documentation:${NC}"
    echo -e "  • API Setup: See the comprehensive API key guide above"
    echo -e "  • Channel Recovery: Use the TUI Forwarding → Channel Recovery Wizard"
    echo -e "  • CLI Usage: Run ${CYAN}spectra --help${NC}\n"

    echo -e "${BOLD}Installation Log:${NC}"
    echo -e "  ${CYAN}$INSTALL_LOG${NC}\n"
}

# ─────────────────────────────────────────────────────────────────────────────
# Main Installation Flow
# ─────────────────────────────────────────────────────────────────────────────

main() {
    print_banner

    log_message "INFO" "Starting SPECTRA installation..."
    log_message "INFO" "Installation log: $INSTALL_LOG"

    # Run installation steps
    detect_system
    check_python
    install_system_dependencies
    setup_virtual_environment
    install_python_dependencies
    setup_project_structure
    verify_installation
    create_config_template

    # Print summary
    print_next_steps

    log_message "SUCCESS" "SPECTRA installation completed successfully"
}

# ─────────────────────────────────────────────────────────────────────────────
# Run Main Installation
# ─────────────────────────────────────────────────────────────────────────────

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main
fi
