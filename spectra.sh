#!/bin/bash
# SPECTRA Cross-Platform Launcher Wrapper
# ========================================
# Universal startup script that works on Linux, macOS, and Windows (WSL/Git Bash)
# Automatically detects system configuration and launches appropriate components

set -e

# Color definitions with fallback for non-color terminals
if [[ -t 1 ]] && command -v tput >/dev/null 2>&1; then
    BLUE=$(tput setaf 4)
    GREEN=$(tput setaf 2)
    RED=$(tput setaf 1)
    YELLOW=$(tput setaf 3)
    CYAN=$(tput setaf 6)
    WHITE=$(tput setaf 7)
    NC=$(tput sgr0)
else
    BLUE='\033[0;34m'
    GREEN='\033[0;32m'
    RED='\033[0;31m'
    YELLOW='\033[0;33m'
    CYAN='\033[0;36m'
    WHITE='\033[1;37m'
    NC='\033[0m'
fi

# Script directory detection (works with symlinks)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR"

# Platform detection
detect_platform() {
    case "$OSTYPE" in
        linux-gnu*)   PLATFORM="linux" ;;
        darwin*)      PLATFORM="macos" ;;
        msys*|cygwin*) PLATFORM="windows" ;;
        *)            PLATFORM="unknown" ;;
    esac
}

# Python detection with version checking
detect_python() {
    local python_candidates=("python3.12" "python3.11" "python3.10" "python3.9" "python3" "python")

    for cmd in "${python_candidates[@]}"; do
        if command -v "$cmd" >/dev/null 2>&1; then
            local version_output=$($cmd --version 2>&1)
            local version=$(echo "$version_output" | grep -oE '[0-9]+\.[0-9]+' | head -1)
            local major=$(echo "$version" | cut -d. -f1)
            local minor=$(echo "$version" | cut -d. -f2)

            if [[ "$major" -eq 3 ]] && [[ "$minor" -ge 10 ]]; then
                PYTHON_CMD="$cmd"
                return 0
            fi
        fi
    done

    return 1
}

# Virtual environment path detection
get_venv_python() {
    local venv_path="$PROJECT_ROOT/.venv"

    if [[ "$PLATFORM" == "windows" ]]; then
        echo "$venv_path/Scripts/python.exe"
    else
        echo "$venv_path/bin/python"
    fi
}

# Check if virtual environment exists and is functional
check_venv() {
    local venv_python=$(get_venv_python)

    if [[ -f "$venv_python" ]]; then
        # Test if virtual environment works
        if "$venv_python" -c "import sys; print('OK')" >/dev/null 2>&1; then
            return 0
        fi
    fi

    return 1
}

# Check if SPECTRA is installed in virtual environment
check_spectra_installation() {
    local venv_python=$(get_venv_python)

    if [[ -f "$venv_python" ]]; then
        if "$venv_python" -c "import tgarchive; print('SPECTRA OK')" >/dev/null 2>&1; then
            return 0
        fi
    fi

    return 1
}

# Auto-launch with appropriate method
auto_launch() {
    local mode="$1"

    echo -e "${CYAN}🚀 SPECTRA Auto-Launcher${NC}"
    echo -e "${WHITE}Platform: $PLATFORM${NC}"

    # Check Python
    if ! detect_python; then
        echo -e "${RED}✗ Python 3.10+ not found${NC}"
        echo -e "${YELLOW}Please install Python 3.10 or later${NC}"
        return 1
    fi

    echo -e "${GREEN}✓ Python: $PYTHON_CMD${NC}"

    # Check virtual environment
    if ! check_venv; then
        echo -e "${YELLOW}⚠ Virtual environment not found or broken${NC}"
        echo -e "${CYAN}→ Running auto-setup...${NC}"

        if [[ -f "$PROJECT_ROOT/auto-install.sh" ]]; then
            bash "$PROJECT_ROOT/auto-install.sh" "$@"
        elif [[ -f "$PROJECT_ROOT/spectra-launch.py" ]]; then
            "$PYTHON_CMD" "$PROJECT_ROOT/spectra-launch.py" --setup
        else
            echo -e "${RED}✗ Setup scripts not found${NC}"
            return 1
        fi
    fi

    # Check SPECTRA installation
    if ! check_spectra_installation; then
        echo -e "${YELLOW}⚠ SPECTRA not properly installed${NC}"
        echo -e "${CYAN}→ Running installation repair...${NC}"

        if [[ -f "$PROJECT_ROOT/spectra-launch.py" ]]; then
            "$PYTHON_CMD" "$PROJECT_ROOT/spectra-launch.py" --repair
        else
            echo -e "${RED}✗ Cannot repair installation${NC}"
            return 1
        fi
    fi

    echo -e "${GREEN}✓ SPECTRA installation verified${NC}"

    # Launch appropriate mode
    local venv_python=$(get_venv_python)

    case "$mode" in
        "tui"|"")
            echo -e "${CYAN}→ Launching SPECTRA TUI...${NC}"
            # Show splash screen if available
            if [[ -f "$PROJECT_ROOT/spectra-splash.py" ]]; then
                "$venv_python" "$PROJECT_ROOT/spectra-splash.py" --progress
            fi
            cd "$PROJECT_ROOT"
            exec "$venv_python" -m tgarchive
            ;;
        "cli")
            echo -e "${CYAN}→ SPECTRA CLI Commands:${NC}"
            "$venv_python" "$PROJECT_ROOT/spectra-launch.py" --cli
            ;;
        "setup")
            echo -e "${CYAN}→ Running setup wizard...${NC}"
            "$venv_python" "$PROJECT_ROOT/spectra-launch.py" --setup
            ;;
        "check")
            echo -e "${CYAN}→ Running system check...${NC}"
            "$venv_python" "$PROJECT_ROOT/spectra-launch.py" --check
            ;;
        "repair")
            echo -e "${CYAN}→ Repairing installation...${NC}"
            "$venv_python" "$PROJECT_ROOT/spectra-launch.py" --repair
            ;;
        *)
            echo -e "${RED}✗ Unknown mode: $mode${NC}"
            show_usage
            return 1
            ;;
    esac
}

# Show usage information
show_usage() {
    echo -e "${WHITE}SPECTRA Cross-Platform Launcher${NC}"
    echo -e "${CYAN}Usage:${NC} $0 [mode] [options]"
    echo ""
    echo -e "${CYAN}Modes:${NC}"
    echo -e "  ${WHITE}tui${NC}      Launch SPECTRA TUI (default)"
    echo -e "  ${WHITE}cli${NC}      Show CLI commands"
    echo -e "  ${WHITE}setup${NC}    Run configuration wizard"
    echo -e "  ${WHITE}check${NC}    Check system status"
    echo -e "  ${WHITE}repair${NC}   Repair installation"
    echo ""
    echo -e "${CYAN}Options:${NC}"
    echo -e "  ${WHITE}--help, -h${NC}     Show this help"
    echo -e "  ${WHITE}--interactive${NC}  Interactive startup mode"
    echo -e "  ${WHITE}--quick${NC}        Quick launch without checks"
    echo -e "  ${WHITE}--verbose${NC}      Verbose output"
    echo ""
    echo -e "${CYAN}Examples:${NC}"
    echo -e "  $0                  # Launch TUI"
    echo -e "  $0 setup            # Run setup wizard"
    echo -e "  $0 cli              # Show CLI commands"
    echo -e "  $0 --interactive    # Interactive mode"
}

# Quick status check
quick_status() {
    echo -e "${CYAN}SPECTRA Quick Status${NC}"
    echo "===================="

    detect_platform
    echo "Platform: $PLATFORM"

    if detect_python; then
        echo -e "${GREEN}✓${NC} Python: $PYTHON_CMD"
    else
        echo -e "${RED}✗${NC} Python 3.10+ not found"
    fi

    if check_venv; then
        echo -e "${GREEN}✓${NC} Virtual environment: OK"
    else
        echo -e "${YELLOW}⚠${NC} Virtual environment: Missing/Broken"
    fi

    if check_spectra_installation; then
        echo -e "${GREEN}✓${NC} SPECTRA: Installed"
    else
        echo -e "${YELLOW}⚠${NC} SPECTRA: Not installed"
    fi

    if [[ -f "$PROJECT_ROOT/spectra_config.json" ]]; then
        echo -e "${GREEN}✓${NC} Configuration: Found"
    else
        echo -e "${YELLOW}⚠${NC} Configuration: Missing"
    fi
}

# Interactive startup mode
interactive_mode() {
    # Use splash screen if available
    if [[ -f "$PROJECT_ROOT/spectra-splash.py" ]]; then
        if detect_python; then
            "$PYTHON_CMD" "$PROJECT_ROOT/spectra-splash.py" --interactive
            return $?
        fi
    fi

    # Fallback interactive mode
    echo -e "${CYAN}SPECTRA Interactive Mode${NC}"
    echo "========================"

    quick_status

    echo ""
    echo "What would you like to do?"
    echo "1. Launch SPECTRA TUI"
    echo "2. Run setup wizard"
    echo "3. Show CLI commands"
    echo "4. Check system status"
    echo "5. Repair installation"
    echo "6. Exit"

    read -p "Enter choice (1-6): " choice

    case "$choice" in
        1) auto_launch "tui" ;;
        2) auto_launch "setup" ;;
        3) auto_launch "cli" ;;
        4) auto_launch "check" ;;
        5) auto_launch "repair" ;;
        6|"") echo "Goodbye!"; exit 0 ;;
        *) echo -e "${RED}Invalid choice${NC}"; exit 1 ;;
    esac
}

# Main function
main() {
    # Initialize platform detection
    detect_platform

    # Parse arguments
    case "$1" in
        ""|"tui")
            auto_launch "tui" "${@:2}"
            ;;
        "cli")
            auto_launch "cli" "${@:2}"
            ;;
        "setup")
            auto_launch "setup" "${@:2}"
            ;;
        "check")
            auto_launch "check" "${@:2}"
            ;;
        "repair")
            auto_launch "repair" "${@:2}"
            ;;
        "--status")
            quick_status
            ;;
        "--interactive")
            interactive_mode
            ;;
        "--quick")
            # Quick launch without extensive checks
            local venv_python=$(get_venv_python)
            if [[ -f "$venv_python" ]] && check_spectra_installation; then
                cd "$PROJECT_ROOT"
                exec "$venv_python" -m tgarchive
            else
                echo -e "${RED}✗ Quick launch failed - system not ready${NC}"
                echo -e "${CYAN}→ Try: $0 setup${NC}"
                exit 1
            fi
            ;;
        "--help"|"-h")
            show_usage
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            show_usage
            exit 1
            ;;
    esac
}

# Error handling
trap 'echo -e "\n${YELLOW}Interrupted by user${NC}"; exit 130' INT TERM

# Run main function
main "$@"