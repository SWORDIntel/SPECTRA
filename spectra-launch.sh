#!/bin/bash
# SPECTRA Bootstrap Script
# =======================
#
# One-command installation and launch of SPECTRA TUI
#
# Usage: ./spectra-launch.sh
#
# This script will:
# 1. Detect your OS and package manager
# 2. Install system dependencies
# 3. Create Python virtual environment
# 4. Install all Python packages
# 5. Set up project structure
# 6. Configure SPECTRA
# 7. Launch the TUI
#
# No additional commands needed!

set -e

# ─────────────────────────────────────────────────────────────────────────────
# Color Definitions
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
INSTALL_LOG="$PROJECT_ROOT/logs/bootstrap_$(date +%Y%m%d_%H%M%S).log"
VENV_PATH="$PROJECT_ROOT/.venv"
CONFIG_PATH="$PROJECT_ROOT/spectra_config.json"

OS_TYPE=""
PACKAGE_MANAGER=""
PYTHON_CMD=""
PIP_CMD=""

# ─────────────────────────────────────────────────────────────────────────────
# Logging Functions
# ─────────────────────────────────────────────────────────────────────────────

log_message() {
    local level="$1"
    local message="$2"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')

    mkdir -p "$(dirname "$INSTALL_LOG")"
    echo "[$timestamp] [$level] $message" >> "$INSTALL_LOG"

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

print_banner() {
    echo -e "\n${BLUE}${BOLD}╔═══════════════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}${BOLD}║                          ███████╗██████╗ ███████╗ ██████╗████████╗██████╗  ║${NC}"
    echo -e "${BLUE}${BOLD}║                          ██╔════╝██╔══██╗██╔════╝██╔════╝╚══██╔══╝██╔══██╗ ║${NC}"
    echo -e "${BLUE}${BOLD}║                          ███████╗██████╔╝█████╗  ██║        ██║   ██████╔╗ ║${NC}"
    echo -e "${BLUE}${BOLD}║                          ╚════██║██╔═══╝ ██╔══╝  ██║        ██║   ██╔══██║ ║${NC}"
    echo -e "${BLUE}${BOLD}║                          ███████║██║     ███████╗╚██████╗   ██║   ██║  ██║ ║${NC}"
    echo -e "${BLUE}${BOLD}║                          ╚══════╝╚═╝     ╚══════╝ ╚═════╝   ╚═╝   ╚═╝  ╚═╝ ║${NC}"
    echo -e "${BLUE}${BOLD}╚═══════════════════════════════════════════════════════════════════════════╝${NC}"
    echo -e "${BOLD}${CYAN}               Unified Bootstrap & Launch - Network Discovery & Archiving${NC}\n"
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
                if dpkg -l 2>/dev/null | grep -q "^ii.*$dep"; then
                    log_message "INFO" "$dep is already installed"
                else
                    log_message "INSTALL" "system package: $dep"
                    if sudo apt-get install -qq -y "$dep" >> "$INSTALL_LOG" 2>&1; then
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
                if sudo yum install -q -y "$dep" >> "$INSTALL_LOG" 2>&1; then
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
        log_message "INFO" "Virtual environment already exists"
    else
        log_message "INSTALL" "Creating virtual environment"
        if $PYTHON_CMD -m venv "$VENV_PATH" >> "$INSTALL_LOG" 2>&1; then
            log_message "INSTALLED" "Virtual environment created"
        else
            log_message "ERROR" "Failed to create virtual environment"
            exit 1
        fi
    fi

    PIP_CMD="$VENV_PATH/bin/pip"

    log_message "PROGRESS" "Upgrading pip, setuptools, and wheel..."
    if $PIP_CMD install --upgrade pip setuptools wheel >> "$INSTALL_LOG" 2>&1; then
        log_message "INSTALLED" "pip, setuptools, wheel upgraded"
    else
        log_message "WARNING" "Failed to upgrade pip tools (continuing)"
    fi
}

install_python_dependencies() {
    log_message "PROGRESS" "Installing Python dependencies from requirements.txt..."

    # Pre-install build dependencies
    log_message "INFO" "Upgrading pip, setuptools, wheel..."
    $PIP_CMD install --upgrade pip setuptools wheel >> "$INSTALL_LOG" 2>&1 || true

    # Use requirements.txt for exact versions
    if [[ -f "requirements.txt" ]]; then
        log_message "INFO" "Installing from requirements.txt (with exact versions)..."
        if $PIP_CMD install -r requirements.txt >> "$INSTALL_LOG" 2>&1; then
            log_message "SUCCESS" "All dependencies installed from requirements.txt"
        else
            log_message "WARNING" "Some dependencies may have failed during installation"
            log_message "INFO" "Attempting fallback: installing critical core dependencies..."

            # Fallback to core dependencies if requirements.txt has issues
            local core_deps=(
                "pysocks>=1.7.1"
                "numpy>=1.21.0"
                "pandas>=1.5.0"
                "telethon>=1.34.0"
                "rich>=13.0.0"
                "tqdm>=4.0.0"
                "PyYAML>=6.0.0"
                "Pillow>=10.0.0"
                "npyscreen>=4.10.5"
                "Jinja2>=3.0.0"
            )

            local fallback_count=0
            for dep in "${core_deps[@]}"; do
                if $PIP_CMD install "$dep" >> "$INSTALL_LOG" 2>&1; then
                    log_message "INSTALLED" "$dep (fallback)"
                    ((fallback_count++))
                fi
            done
            log_message "WARNING" "Fallback installation complete ($fallback_count packages)"
        fi
    else
        log_message "ERROR" "requirements.txt not found at $PROJECT_ROOT"
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
            if mkdir -p "$full_path" >> "$INSTALL_LOG" 2>&1; then
                log_message "INSTALLED" "$dir"
            else
                log_message "WARNING" "Failed to create: $dir"
            fi
        fi
    done

    log_message "SUCCESS" "Project structure setup complete"
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
        log_message "INSTALLED" "Configuration template created"
    else
        log_message "INFO" "Configuration file already exists"
    fi
}

verify_installation() {
    log_message "PROGRESS" "Verifying installation..."

    if $VENV_PATH/bin/python3 -c "import telethon, rich, npyscreen, socks" 2>/dev/null; then
        log_message "SUCCESS" "Core modules verified"
    else
        log_message "WARNING" "Some modules could not be verified"
    fi
}

print_setup_instructions() {
    echo -e "\n${BOLD}${GREEN}╔═══════════════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}${GREEN}║                    ✓ INSTALLATION COMPLETE!${NC}"
    echo -e "${BOLD}${GREEN}╚═══════════════════════════════════════════════════════════════════════════╝${NC}\n"

    echo -e "${BOLD}Configuration Required:${NC}\n"
    echo -e "1. Get API credentials from: ${CYAN}https://my.telegram.org/auth?to=apps${NC}"
    echo -e "2. Edit configuration file: ${CYAN}$CONFIG_PATH${NC}"
    echo -e "3. Add your API ID and Hash\n"

    echo -e "${BOLD}Configuration Example:${NC}"
    echo -e "${CYAN}{${NC}"
    echo -e "  ${CYAN}\"api_id\": 12345678,${NC}"
    echo -e "  ${CYAN}\"api_hash\": \"abcdef1234567890abcdef1234567890\",${NC}"
    echo -e "  ${CYAN}\"phone_number\": \"+1234567890\"${NC}"
    echo -e "${CYAN}}${NC}\n"
}

launch_tui() {
    log_message "PROGRESS" "Launching SPECTRA TUI..."
    echo -e "\n${GREEN}Launching SPECTRA...${NC}\n"

    # Activate virtual environment and launch TUI
    source "$VENV_PATH/bin/activate"
    exec python3 -m tgarchive
}

# ─────────────────────────────────────────────────────────────────────────────
# Main Execution
# ─────────────────────────────────────────────────────────────────────────────

main() {
    print_banner

    # Check if config exists
    if [[ -f "$CONFIG_PATH" ]]; then
        log_message "INFO" "Configuration found. Skipping setup."
        log_message "PROGRESS" "Launching SPECTRA TUI..."

        source "$VENV_PATH/bin/activate" 2>/dev/null || {
            log_message "WARNING" "Virtual environment needs recreation"
            setup_virtual_environment
            install_python_dependencies
        }

        echo -e "\n${GREEN}Launching SPECTRA...${NC}\n"
        exec python3 -m tgarchive
    fi

    # Full installation
    log_message "INFO" "Starting SPECTRA bootstrap and setup..."
    log_message "INFO" "Installation log: $INSTALL_LOG"

    detect_system
    check_python
    install_system_dependencies
    setup_virtual_environment
    install_python_dependencies
    setup_project_structure
    verify_installation
    create_config_template
    print_setup_instructions

    echo -e "${BOLD}${YELLOW}To continue, please:${NC}\n"
    echo -e "1. Edit: ${CYAN}nano spectra_config.json${NC}"
    echo -e "2. Add your Telegram API credentials"
    echo -e "3. Run this script again to launch the TUI\n"

    log_message "SUCCESS" "Bootstrap setup complete"
}

# Run main
main
