#!/bin/bash
# SPECTRA Enhanced Auto-Installer
# ================================
#
# Comprehensive installation script with:
# - Cross-platform support (Linux, macOS, Windows WSL)
# - Virtual environment management
# - Dependency resolution and conflict handling
# - Error recovery and system compatibility checks
# - Desktop integration (optional)
# - Automatic configuration discovery

set -e  # Exit on error

# Color definitions for cross-platform compatibility
if [[ -t 1 ]] && command -v tput >/dev/null 2>&1; then
    BLUE=$(tput setaf 4)
    GREEN=$(tput setaf 2)
    RED=$(tput setaf 1)
    YELLOW=$(tput setaf 3)
    CYAN=$(tput setaf 6)
    PURPLE=$(tput setaf 5)
    WHITE=$(tput setaf 7)
    BOLD=$(tput bold)
    NC=$(tput sgr0) # No Color
else
    BLUE='\033[0;34m'
    GREEN='\033[0;32m'
    RED='\033[0;31m'
    YELLOW='\033[0;33m'
    CYAN='\033[0;36m'
    PURPLE='\033[0;35m'
    WHITE='\033[1;37m'
    BOLD='\033[1m'
    NC='\033[0m'
fi

# Global variables
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR"
INSTALL_LOG="$PROJECT_ROOT/logs/install_$(date +%Y%m%d_%H%M%S).log"
VENV_PATH="$PROJECT_ROOT/.venv"
CONFIG_PATH="$PROJECT_ROOT/spectra_config.json"

# Detection variables
OS_TYPE=""
DISTRO=""
PACKAGE_MANAGER=""
PYTHON_CMD=""
PIP_CMD=""

# Options
INSTALL_DESKTOP_SHORTCUTS=false
FORCE_REINSTALL=false
SKIP_SYSTEM_DEPS=false
VERBOSE=false
DRY_RUN=false

# Function definitions
print_banner() {
    echo -e "\n${BLUE}╔═══════════════════════════════════════════════════════════════════════════╗"
    echo -e "║                          ███████╗██████╗ ███████╗ ██████╗████████╗██████╗  ║"
    echo -e "║                          ██╔════╝██╔══██╗██╔════╝██╔════╝╚══██╔══╝██╔══██╗ ║"
    echo -e "║                          ███████╗██████╔╝█████╗  ██║        ██║   ██████╔╗ ║"
    echo -e "║                          ╚════██║██╔═══╝ ██╔══╝  ██║        ██║   ██╔══██║ ║"
    echo -e "║                          ███████║██║     ███████╗╚██████╗   ██║   ██║  ██║ ║"
    echo -e "║                          ╚══════╝╚═╝     ╚══════╝ ╚═════╝   ╚═╝   ╚═╝  ╚═╝ ║"
    echo -e "╚═══════════════════════════════════════════════════════════════════════════╝${NC}"
    echo -e "${BOLD}${WHITE}               Enhanced Auto-Installer - Network Discovery & Archiving${NC}\n"
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
            echo -e "${CYAN}→ $message${NC}"
            ;;
        "SUCCESS")
            echo -e "${GREEN}✓ $message${NC}"
            ;;
        "WARNING")
            echo -e "${YELLOW}⚠ $message${NC}"
            ;;
        "ERROR")
            echo -e "${RED}✗ $message${NC}"
            ;;
        "PROGRESS")
            echo -e "${PURPLE}▶ $message${NC}"
            ;;
        *)
            echo -e "${WHITE}  $message${NC}"
            ;;
    esac
}

detect_system() {
    log_message "PROGRESS" "Detecting system configuration..."

    # Detect OS
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        OS_TYPE="linux"
    elif [[ "$OSTYPE" == "darwin"* ]]; then
        OS_TYPE="macos"
    elif [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "cygwin" ]]; then
        OS_TYPE="windows"
    else
        OS_TYPE="unknown"
    fi

    # Detect Linux distribution
    if [[ "$OS_TYPE" == "linux" ]]; then
        if command -v lsb_release >/dev/null 2>&1; then
            DISTRO=$(lsb_release -si | tr '[:upper:]' '[:lower:]')
        elif [[ -f /etc/os-release ]]; then
            DISTRO=$(grep "^ID=" /etc/os-release | cut -d'=' -f2 | tr -d '"' | tr '[:upper:]' '[:lower:]')
        elif [[ -f /etc/redhat-release ]]; then
            DISTRO="redhat"
        elif [[ -f /etc/debian_version ]]; then
            DISTRO="debian"
        else
            DISTRO="unknown"
        fi

        # Detect package manager
        if command -v apt-get >/dev/null 2>&1; then
            PACKAGE_MANAGER="apt"
        elif command -v yum >/dev/null 2>&1; then
            PACKAGE_MANAGER="yum"
        elif command -v dnf >/dev/null 2>&1; then
            PACKAGE_MANAGER="dnf"
        elif command -v pacman >/dev/null 2>&1; then
            PACKAGE_MANAGER="pacman"
        elif command -v zypper >/dev/null 2>&1; then
            PACKAGE_MANAGER="zypper"
        else
            PACKAGE_MANAGER="unknown"
        fi
    elif [[ "$OS_TYPE" == "macos" ]]; then
        PACKAGE_MANAGER="brew"
    fi

    log_message "SUCCESS" "System detected: $OS_TYPE ($DISTRO) with $PACKAGE_MANAGER"
}

detect_python() {
    log_message "PROGRESS" "Detecting Python installation..."

    # List of possible Python commands to try
    local python_candidates=("python3.12" "python3.11" "python3.10" "python3.9" "python3" "python")

    for cmd in "${python_candidates[@]}"; do
        if command -v "$cmd" >/dev/null 2>&1; then
            local version_output=$($cmd --version 2>&1)
            local version=$(echo "$version_output" | grep -oE '[0-9]+\.[0-9]+' | head -1)
            local major=$(echo "$version" | cut -d. -f1)
            local minor=$(echo "$version" | cut -d. -f2)

            if [[ "$major" -eq 3 ]] && [[ "$minor" -ge 10 ]]; then
                PYTHON_CMD="$cmd"
                log_message "SUCCESS" "Found suitable Python: $cmd (version $version)"
                return 0
            else
                log_message "WARNING" "Found $cmd but version $version is too old (need 3.10+)"
            fi
        fi
    done

    log_message "ERROR" "No suitable Python 3.10+ installation found"
    return 1
}

install_system_dependencies() {
    if [[ "$SKIP_SYSTEM_DEPS" == "true" ]]; then
        log_message "INFO" "Skipping system dependencies installation"
        return 0
    fi

    log_message "PROGRESS" "Installing system dependencies..."

    local deps_installed=0

    case "$PACKAGE_MANAGER" in
        "apt")
            local packages=("python3-venv" "python3-dev" "python3-pip" "git" "build-essential" "libffi-dev" "libssl-dev")

            if [[ "$DRY_RUN" == "true" ]]; then
                log_message "INFO" "Would install: ${packages[*]}"
                return 0
            fi

            # Update package list
            sudo apt-get update -q

            for package in "${packages[@]}"; do
                if ! dpkg -l | grep -q "^ii.*$package "; then
                    log_message "INFO" "Installing $package..."
                    if sudo apt-get install -y "$package" >> "$INSTALL_LOG" 2>&1; then
                        log_message "SUCCESS" "Installed $package"
                        ((deps_installed++))
                    else
                        log_message "WARNING" "Failed to install $package"
                    fi
                else
                    log_message "INFO" "$package is already installed"
                fi
            done
            ;;

        "dnf"|"yum")
            local packages=("python3-venv" "python3-devel" "python3-pip" "git" "gcc" "openssl-devel" "libffi-devel")

            if [[ "$DRY_RUN" == "true" ]]; then
                log_message "INFO" "Would install: ${packages[*]}"
                return 0
            fi

            for package in "${packages[@]}"; do
                if ! rpm -q "$package" >/dev/null 2>&1; then
                    log_message "INFO" "Installing $package..."
                    if sudo "$PACKAGE_MANAGER" install -y "$package" >> "$INSTALL_LOG" 2>&1; then
                        log_message "SUCCESS" "Installed $package"
                        ((deps_installed++))
                    else
                        log_message "WARNING" "Failed to install $package"
                    fi
                else
                    log_message "INFO" "$package is already installed"
                fi
            done
            ;;

        "pacman")
            local packages=("python" "python-pip" "git" "base-devel" "openssl" "libffi")

            if [[ "$DRY_RUN" == "true" ]]; then
                log_message "INFO" "Would install: ${packages[*]}"
                return 0
            fi

            for package in "${packages[@]}"; do
                if ! pacman -Q "$package" >/dev/null 2>&1; then
                    log_message "INFO" "Installing $package..."
                    if sudo pacman -S --noconfirm "$package" >> "$INSTALL_LOG" 2>&1; then
                        log_message "SUCCESS" "Installed $package"
                        ((deps_installed++))
                    else
                        log_message "WARNING" "Failed to install $package"
                    fi
                else
                    log_message "INFO" "$package is already installed"
                fi
            done
            ;;

        "brew")
            local packages=("python@3.11" "git" "openssl" "libffi")

            if [[ "$DRY_RUN" == "true" ]]; then
                log_message "INFO" "Would install: ${packages[*]}"
                return 0
            fi

            for package in "${packages[@]}"; do
                if ! brew list "$package" >/dev/null 2>&1; then
                    log_message "INFO" "Installing $package..."
                    if brew install "$package" >> "$INSTALL_LOG" 2>&1; then
                        log_message "SUCCESS" "Installed $package"
                        ((deps_installed++))
                    else
                        log_message "WARNING" "Failed to install $package"
                    fi
                else
                    log_message "INFO" "$package is already installed"
                fi
            done
            ;;

        *)
            log_message "WARNING" "Unknown package manager: $PACKAGE_MANAGER"
            log_message "INFO" "Please install Python 3.10+, git, and development tools manually"
            ;;
    esac

    if [[ $deps_installed -gt 0 ]]; then
        log_message "SUCCESS" "Installed $deps_installed system dependencies"
    else
        log_message "INFO" "All required system dependencies are already installed"
    fi
}

create_virtual_environment() {
    log_message "PROGRESS" "Setting up Python virtual environment..."

    if [[ -d "$VENV_PATH" ]]; then
        if [[ "$FORCE_REINSTALL" == "true" ]]; then
            log_message "INFO" "Removing existing virtual environment..."
            rm -rf "$VENV_PATH"
        else
            log_message "INFO" "Using existing virtual environment"
            return 0
        fi
    fi

    if [[ "$DRY_RUN" == "true" ]]; then
        log_message "INFO" "Would create virtual environment at: $VENV_PATH"
        return 0
    fi

    # Create virtual environment
    if "$PYTHON_CMD" -m venv "$VENV_PATH" >> "$INSTALL_LOG" 2>&1; then
        log_message "SUCCESS" "Virtual environment created"
    else
        log_message "ERROR" "Failed to create virtual environment"
        return 1
    fi

    # Activate virtual environment and get pip path
    if [[ "$OS_TYPE" == "windows" ]]; then
        PIP_CMD="$VENV_PATH/Scripts/pip"
    else
        PIP_CMD="$VENV_PATH/bin/pip"
    fi

    # Upgrade pip
    log_message "INFO" "Upgrading pip..."
    if "$PIP_CMD" install --upgrade pip >> "$INSTALL_LOG" 2>&1; then
        log_message "SUCCESS" "Pip upgraded"
    else
        log_message "WARNING" "Failed to upgrade pip"
    fi
}

install_python_dependencies() {
    log_message "PROGRESS" "Installing Python dependencies..."

    if [[ "$DRY_RUN" == "true" ]]; then
        log_message "INFO" "Would install Python dependencies"
        return 0
    fi

    # Install in development mode
    local install_cmd=("$PIP_CMD" "install")

    if [[ "$FORCE_REINSTALL" == "true" ]]; then
        install_cmd+=("--force-reinstall")
    fi

    install_cmd+=("-e" ".")

    cd "$PROJECT_ROOT"

    if "${install_cmd[@]}" >> "$INSTALL_LOG" 2>&1; then
        log_message "SUCCESS" "Python dependencies installed successfully"
        return 0
    else
        log_message "WARNING" "Standard installation failed, trying alternative method..."
        return install_dependencies_alternative
    fi
}

install_dependencies_alternative() {
    log_message "PROGRESS" "Installing dependencies with alternative method..."

    # Core dependencies
    local core_deps=(
        "telethon>=1.34.0"
        "rich>=13.0.0"
        "tqdm>=4.0.0"
        "pyyaml>=6.0.0"
        "Pillow>=10.0.0"
        "npyscreen>=4.10.5"
        "jinja2>=3.0.0"
    )

    # Optional dependencies
    local optional_deps=(
        "networkx>=3.0"
        "matplotlib>=3.6.0"
        "pandas>=1.5.0"
        "python-magic>=0.4.27"
        "cryptg>=0.2.post4"
        "pysocks>=1.7.1"
        "croniter>=1.3.5"
        "yoyo-migrations>=8.2.0"
        "aiofiles>=23.2.1"
        "aiosqlite>=0.20.0"
    )

    local installed_count=0
    local failed_count=0

    # Install core dependencies
    for dep in "${core_deps[@]}"; do
        log_message "INFO" "Installing core dependency: $dep"
        if "$PIP_CMD" install "$dep" >> "$INSTALL_LOG" 2>&1; then
            log_message "SUCCESS" "Installed $dep"
            ((installed_count++))
        else
            log_message "ERROR" "Failed to install core dependency: $dep"
            ((failed_count++))
        fi
    done

    # Install optional dependencies (don't fail if they don't install)
    for dep in "${optional_deps[@]}"; do
        log_message "INFO" "Installing optional dependency: $dep"
        if "$PIP_CMD" install "$dep" >> "$INSTALL_LOG" 2>&1; then
            log_message "SUCCESS" "Installed optional dependency: $dep"
            ((installed_count++))
        else
            log_message "WARNING" "Skipped optional dependency: $dep"
        fi
    done

    log_message "INFO" "Installed $installed_count dependencies, $failed_count failures"

    if [[ $failed_count -gt 0 ]] && [[ $failed_count -gt 3 ]]; then
        log_message "ERROR" "Too many core dependencies failed to install"
        return 1
    fi

    return 0
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
            if [[ "$DRY_RUN" == "true" ]]; then
                log_message "INFO" "Would create directory: $full_path"
            else
                mkdir -p "$full_path"
                log_message "SUCCESS" "Created directory: $dir"
            fi
        else
            log_message "INFO" "Directory already exists: $dir"
        fi
    done
}

create_default_config() {
    log_message "PROGRESS" "Setting up configuration..."

    if [[ -f "$CONFIG_PATH" ]]; then
        log_message "INFO" "Configuration file already exists"
        return 0
    fi

    if [[ "$DRY_RUN" == "true" ]]; then
        log_message "INFO" "Would create default configuration"
        return 0
    fi

    # Create default configuration
    cat > "$CONFIG_PATH" << 'EOF'
{
  "accounts": [],
  "db": {
    "path": "spectra.db"
  },
  "data_dir": "spectra_data",
  "logging": {
    "level": "INFO",
    "file": "logs/spectra.log"
  },
  "discovery": {
    "default_depth": 2,
    "max_messages": 1000,
    "delay_between_requests": 1
  },
  "forwarding": {
    "enable_deduplication": true,
    "secondary_unique_destination": null
  },
  "parallel": {
    "max_workers": 4,
    "enable_by_default": false
  }
}
EOF

    log_message "SUCCESS" "Default configuration created"
}

check_for_existing_config() {
    log_message "PROGRESS" "Checking for existing configuration..."

    # Check for gen_config.py
    if [[ -f "$PROJECT_ROOT/gen_config.py" ]]; then
        log_message "SUCCESS" "Found gen_config.py - accounts can be imported"
        return 0
    fi

    # Check if config has accounts
    if [[ -f "$CONFIG_PATH" ]]; then
        if command -v jq >/dev/null 2>&1; then
            local account_count=$(jq '.accounts | length' "$CONFIG_PATH" 2>/dev/null || echo "0")
            if [[ "$account_count" -gt 0 ]]; then
                log_message "SUCCESS" "Found $account_count configured accounts"
                return 0
            fi
        fi
    fi

    log_message "WARNING" "No Telegram accounts configured"
    log_message "INFO" "You'll need to configure accounts after installation"
    return 1
}

create_desktop_shortcuts() {
    if [[ "$INSTALL_DESKTOP_SHORTCUTS" != "true" ]]; then
        return 0
    fi

    log_message "PROGRESS" "Creating desktop shortcuts..."

    case "$OS_TYPE" in
        "linux")
            create_linux_desktop_shortcuts
            ;;
        "macos")
            create_macos_shortcuts
            ;;
        *)
            log_message "WARNING" "Desktop shortcuts not supported on $OS_TYPE"
            ;;
    esac
}

create_linux_desktop_shortcuts() {
    local desktop_dir="$HOME/.local/share/applications"
    mkdir -p "$desktop_dir"

    # SPECTRA TUI shortcut
    cat > "$desktop_dir/spectra-tui.desktop" << EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=SPECTRA TUI
Comment=Telegram Network Discovery & Archiving System
Exec=$PROJECT_ROOT/scripts/spectra_launch.py
Icon=$PROJECT_ROOT/SPECTRA.png
Terminal=true
Categories=Network;Utility;
StartupNotify=true
EOF

    # SPECTRA CLI shortcut
    cat > "$desktop_dir/spectra-cli.desktop" << EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=SPECTRA CLI
Comment=SPECTRA Command Line Interface
Exec=$PROJECT_ROOT/scripts/spectra_launch.py --cli
Icon=$PROJECT_ROOT/SPECTRA.png
Terminal=true
Categories=Network;Utility;
StartupNotify=true
EOF

    chmod +x "$desktop_dir/spectra-tui.desktop"
    chmod +x "$desktop_dir/spectra-cli.desktop"

    log_message "SUCCESS" "Desktop shortcuts created"
}

create_macos_shortcuts() {
    # Create app bundles for macOS
    local apps_dir="$HOME/Applications"
    mkdir -p "$apps_dir"

    # SPECTRA TUI app
    local app_path="$apps_dir/SPECTRA.app"
    mkdir -p "$app_path/Contents/MacOS"

    cat > "$app_path/Contents/MacOS/SPECTRA" << EOF
#!/bin/bash
cd "$PROJECT_ROOT"
exec "$PROJECT_ROOT/scripts/spectra_launch.py"
EOF

    chmod +x "$app_path/Contents/MacOS/SPECTRA"

    cat > "$app_path/Contents/Info.plist" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>SPECTRA</string>
    <key>CFBundleExecutable</key>
    <string>SPECTRA</string>
    <key>CFBundleIdentifier</key>
    <string>com.swordint.spectra</string>
    <key>CFBundleVersion</key>
    <string>1.0</string>
    <key>LSUIElement</key>
    <true/>
</dict>
</plist>
EOF

    log_message "SUCCESS" "macOS app bundle created"
}

run_post_install_checks() {
    log_message "PROGRESS" "Running post-installation checks..."

    local python_path
    if [[ "$OS_TYPE" == "windows" ]]; then
        python_path="$VENV_PATH/Scripts/python"
    else
        python_path="$VENV_PATH/bin/python"
    fi

    # Test SPECTRA import
    if "$python_path" -c "import tgarchive; print('SPECTRA import successful')" >> "$INSTALL_LOG" 2>&1; then
        log_message "SUCCESS" "SPECTRA installation verified"
    else
        log_message "ERROR" "SPECTRA installation verification failed"
        return 1
    fi

    # Check configuration
    check_for_existing_config

    return 0
}

show_completion_message() {
    echo -e "\n${GREEN}╔═══════════════════════════════════════════════════════════════════════════╗"
    echo -e "║                          🎉 INSTALLATION COMPLETE! 🎉                       ║"
    echo -e "╚═══════════════════════════════════════════════════════════════════════════╝${NC}\n"

    log_message "SUCCESS" "SPECTRA auto-installation completed successfully!"

    echo -e "${CYAN}Quick Start:${NC}"
    echo -e "  ${WHITE}Launch TUI:${NC}     python3 scripts/spectra_launch.py"
    echo -e "  ${WHITE}Setup wizard:${NC}   python3 scripts/spectra_launch.py --setup"
    echo -e "  ${WHITE}CLI commands:${NC}   python3 scripts/spectra_launch.py --cli"
    echo -e "  ${WHITE}System check:${NC}   python3 scripts/spectra_launch.py --check"

    echo -e "\n${CYAN}Configuration:${NC}"
    if [[ -f "$PROJECT_ROOT/gen_config.py" ]]; then
        echo -e "  ${WHITE}Import accounts:${NC} python3 scripts/spectra_launch.py --setup"
    else
        echo -e "  ${WHITE}Configure accounts:${NC} Edit $CONFIG_PATH or run setup wizard"
        echo -e "  ${WHITE}Get API keys:${NC} https://my.telegram.org/apps"
    fi

    echo -e "\n${CYAN}Documentation:${NC}"
    echo -e "  ${WHITE}Project root:${NC}  $PROJECT_ROOT"
    echo -e "  ${WHITE}Config file:${NC}   $CONFIG_PATH"
    echo -e "  ${WHITE}Install log:${NC}   $INSTALL_LOG"

    if [[ "$INSTALL_DESKTOP_SHORTCUTS" == "true" ]]; then
        echo -e "\n${CYAN}Desktop shortcuts created for easy access!${NC}"
    fi
}

# Parse command line arguments
parse_arguments() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --force)
                FORCE_REINSTALL=true
                log_message "INFO" "Force reinstall enabled"
                shift
                ;;
            --desktop)
                INSTALL_DESKTOP_SHORTCUTS=true
                log_message "INFO" "Desktop shortcuts will be created"
                shift
                ;;
            --skip-system)
                SKIP_SYSTEM_DEPS=true
                log_message "INFO" "Skipping system dependencies"
                shift
                ;;
            --verbose)
                VERBOSE=true
                log_message "INFO" "Verbose mode enabled"
                shift
                ;;
            --dry-run)
                DRY_RUN=true
                log_message "INFO" "Dry run mode - no changes will be made"
                shift
                ;;
            --help|-h)
                show_help
                exit 0
                ;;
            *)
                log_message "ERROR" "Unknown option: $1"
                show_help
                exit 1
                ;;
        esac
    done
}

show_help() {
    echo -e "${BOLD}SPECTRA Enhanced Auto-Installer${NC}"
    echo -e "${CYAN}Usage:${NC} $0 [options]"
    echo ""
    echo -e "${CYAN}Options:${NC}"
    echo -e "  ${WHITE}--force${NC}        Force reinstall (remove existing venv)"
    echo -e "  ${WHITE}--desktop${NC}      Create desktop shortcuts"
    echo -e "  ${WHITE}--skip-system${NC}  Skip system dependency installation"
    echo -e "  ${WHITE}--verbose${NC}      Enable verbose output"
    echo -e "  ${WHITE}--dry-run${NC}      Show what would be done without making changes"
    echo -e "  ${WHITE}--help, -h${NC}     Show this help message"
    echo ""
    echo -e "${CYAN}Examples:${NC}"
    echo -e "  $0                    # Standard installation"
    echo -e "  $0 --force --desktop  # Force reinstall with desktop shortcuts"
    echo -e "  $0 --dry-run          # Preview installation steps"
}

# Main installation function
main() {
    # Create logs directory
    mkdir -p "$(dirname "$INSTALL_LOG")"

    # Parse arguments
    parse_arguments "$@"

    # Show banner
    print_banner

    log_message "INFO" "Starting SPECTRA enhanced auto-installation"
    log_message "INFO" "Installation log: $INSTALL_LOG"

    if [[ "$DRY_RUN" == "true" ]]; then
        log_message "INFO" "DRY RUN MODE - No changes will be made"
    fi

    # Step 1: System detection
    detect_system || {
        log_message "ERROR" "System detection failed"
        exit 1
    }

    # Step 2: Python detection
    detect_python || {
        log_message "ERROR" "Python detection failed"
        log_message "INFO" "Please install Python 3.10+ and try again"
        exit 1
    }

    # Step 3: Install system dependencies
    install_system_dependencies || {
        log_message "WARNING" "Some system dependencies may be missing"
    }

    # Step 4: Create virtual environment
    create_virtual_environment || {
        log_message "ERROR" "Virtual environment creation failed"
        exit 1
    }

    # Step 5: Install Python dependencies
    install_python_dependencies || {
        log_message "ERROR" "Python dependency installation failed"
        exit 1
    }

    # Step 6: Setup project structure
    setup_project_structure

    # Step 7: Create default configuration
    create_default_config

    # Step 8: Create desktop shortcuts (if requested)
    create_desktop_shortcuts

    # Step 9: Post-installation checks
    run_post_install_checks || {
        log_message "ERROR" "Post-installation checks failed"
        exit 1
    }

    # Step 10: Show completion message
    show_completion_message

    log_message "SUCCESS" "Installation completed successfully!"
}

# Error handling
trap 'log_message "ERROR" "Installation interrupted"; exit 1' INT TERM

# Run main function
main "$@"