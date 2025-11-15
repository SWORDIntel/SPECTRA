#!/bin/bash
# SPECTRA Installation Repair Script
# ===================================
#
# Fixes missing dependencies:
# - ModuleNotFoundError: No module named 'socks'
# - pandas compilation errors
#
# Use if you're getting import errors after installation

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

echo -e "\n${BOLD}${CYAN}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}${CYAN}║            SPECTRA Installation Repair                    ║${NC}"
echo -e "${BOLD}${CYAN}╚════════════════════════════════════════════════════════════╝${NC}\n"

# Check if in SPECTRA directory
if [[ ! -f "spectra_config.json" && ! -f "tgarchive/__init__.py" ]]; then
    echo -e "${RED}✗ Not in SPECTRA directory${NC}"
    echo "Usage: ./repair-installation.sh"
    echo "Run this script from your SPECTRA root directory"
    exit 1
fi

echo -e "${YELLOW}→ Checking for virtual environment...${NC}"
if [[ ! -d ".venv" ]]; then
    echo -e "${RED}✗ Virtual environment not found${NC}"
    echo -e "${YELLOW}Creating one...${NC}"
    python3 -m venv .venv
fi

echo -e "${GREEN}✓ Virtual environment found${NC}\n"

echo -e "${YELLOW}→ Activating virtual environment...${NC}"
source .venv/bin/activate
echo -e "${GREEN}✓ Activated${NC}\n"

echo -e "${YELLOW}→ Checking system dependencies...${NC}"
if command -v apt-get &> /dev/null; then
    echo -e "  Installing Ubuntu/Debian build tools..."
    sudo apt-get update -qq
    sudo apt-get install -qq -y build-essential python3-dev libffi-dev libssl-dev 2>&1 | tail -1
    echo -e "${GREEN}  ✓ System dependencies installed${NC}"
elif command -v yum &> /dev/null; then
    echo -e "  Installing CentOS/RHEL build tools..."
    sudo yum groupinstall -q -y "Development Tools" 2>&1 | tail -1
    sudo yum install -q -y python3-devel libffi-devel openssl-devel 2>&1 | tail -1
    echo -e "${GREEN}  ✓ System dependencies installed${NC}"
fi
echo

echo -e "${YELLOW}→ Upgrading pip, setuptools, wheel...${NC}"
pip install --upgrade pip setuptools wheel 2>&1 | tail -1
echo -e "${GREEN}✓ Upgraded${NC}\n"

echo -e "${YELLOW}→ Installing CRITICAL missing packages...${NC}"

echo -e "  ${CYAN}• Installing pysocks (provides 'socks' module)...${NC}"
if pip install "pysocks>=1.7.1" 2>&1 | tail -1 | grep -q "Successfully installed\|already satisfied"; then
    echo -e "    ${GREEN}✓ pysocks installed${NC}"
else
    echo -e "    ${RED}✗ Failed to install pysocks${NC}"
fi

echo -e "  ${CYAN}• Installing numpy...${NC}"
if pip install "numpy>=1.21.0" 2>&1 | tail -1 | grep -q "Successfully installed\|already satisfied"; then
    echo -e "    ${GREEN}✓ numpy installed${NC}"
else
    echo -e "    ${RED}✗ Failed to install numpy${NC}"
fi

echo -e "  ${CYAN}• Installing pandas (with compilation)...${NC}"
if pip install "pandas>=1.3.0" --no-binary pandas 2>&1 | tail -1 | grep -q "Successfully installed\|already satisfied"; then
    echo -e "    ${GREEN}✓ pandas installed${NC}"
else
    echo -e "    ${YELLOW}⚠ pandas installation attempted (may need manual retry)${NC}"
fi
echo

echo -e "${YELLOW}→ Reinstalling core dependencies...${NC}"
CORE_PACKAGES="telethon>=1.34.0 rich>=13.0.0 tqdm>=4.0.0 pyyaml>=6.0.0 Pillow>=10.0.0 npyscreen>=4.10.5 jinja2>=3.0.0 cryptg>=0.2.post4"

for pkg in $CORE_PACKAGES; do
    echo -e "  ${CYAN}• $pkg${NC}"
    if pip install "$pkg" 2>&1 | tail -1 | grep -q "Successfully installed\|already satisfied"; then
        echo -e "    ${GREEN}✓ Installed${NC}"
    else
        echo -e "    ${YELLOW}⚠ May need manual install${NC}"
    fi
done
echo

echo -e "${YELLOW}→ Verifying installation...${NC}"
echo -e "  ${CYAN}Testing imports...${NC}"

FAILED=0

python3 -c "import socks" 2>/dev/null && echo -e "    ${GREEN}✓${NC} socks (PySocks)" || { echo -e "    ${RED}✗${NC} socks"; FAILED=1; }
python3 -c "import pandas" 2>/dev/null && echo -e "    ${GREEN}✓${NC} pandas" || { echo -e "    ${RED}✗${NC} pandas"; FAILED=1; }
python3 -c "import telethon" 2>/dev/null && echo -e "    ${GREEN}✓${NC} telethon" || { echo -e "    ${RED}✗${NC} telethon"; FAILED=1; }
python3 -c "import numpy" 2>/dev/null && echo -e "    ${GREEN}✓${NC} numpy" || { echo -e "    ${RED}✗${NC} numpy"; FAILED=1; }
python3 -c "import rich" 2>/dev/null && echo -e "    ${GREEN}✓${NC} rich" || { echo -e "    ${RED}✗${NC} rich"; FAILED=1; }
python3 -c "import npyscreen" 2>/dev/null && echo -e "    ${GREEN}✓${NC} npyscreen" || { echo -e "    ${RED}✗${NC} npyscreen"; FAILED=1; }

echo

if [[ $FAILED -eq 0 ]]; then
    echo -e "${BOLD}${GREEN}╔════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}${GREEN}║           ✓ REPAIR SUCCESSFUL                              ║${NC}"
    echo -e "${BOLD}${GREEN}╚════════════════════════════════════════════════════════════╝${NC}\n"

    echo -e "${GREEN}All modules imported successfully!${NC}\n"

    echo -e "${CYAN}Test SPECTRA:${NC}"
    echo -e "  python3 -m tgarchive --help\n"

    echo -e "${CYAN}Run SPECTRA TUI:${NC}"
    echo -e "  python3 -m tgarchive\n"
else
    echo -e "${BOLD}${YELLOW}╔════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}${YELLOW}║       ⚠ SOME PACKAGES STILL FAILING - MANUAL STEPS         ║${NC}"
    echo -e "${BOLD}${YELLOW}╚════════════════════════════════════════════════════════════╝${NC}\n"

    echo -e "${YELLOW}Try these manual steps:${NC}\n"

    echo -e "1. Clean pip cache:"
    echo -e "   ${CYAN}pip cache purge${NC}\n"

    echo -e "2. Reinstall problematic packages with force:"
    echo -e "   ${CYAN}pip install --no-cache-dir --force-reinstall pysocks numpy${NC}"
    echo -e "   ${CYAN}pip install --no-cache-dir 'pandas>=1.3.0' --no-binary pandas --force-reinstall${NC}\n"

    echo -e "3. Or do a clean installation:"
    echo -e "   ${CYAN}rm -rf .venv${NC}"
    echo -e "   ${CYAN}python3 -m venv .venv${NC}"
    echo -e "   ${CYAN}source .venv/bin/activate${NC}"
    echo -e "   ${CYAN}pip install --upgrade pip setuptools wheel${NC}"
    echo -e "   ${CYAN}pip install pysocks numpy pandas telethon rich tqdm pyyaml Pillow npyscreen jinja2 cryptg${NC}\n"
fi
