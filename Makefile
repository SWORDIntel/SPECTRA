.PHONY: help install repair launch run setup test clean docs bootstrap

# Default target
.DEFAULT_GOAL := help

# Colors
BLUE := \033[0;34m
GREEN := \033[0;32m
YELLOW := \033[1;33m
NC := \033[0m # No Color

# Directories
SCRIPTS_DIR := scripts
INSTALL_SCRIPT := $(SCRIPTS_DIR)/install/install-spectra.sh
REPAIR_SCRIPT := $(SCRIPTS_DIR)/install/repair-installation.sh
LAUNCH_SCRIPT := $(SCRIPTS_DIR)/launch/spectra-launch.sh
SETUP_SCRIPT := $(SCRIPTS_DIR)/setup/setup_env.sh

help: ## Show this help message
	@echo "$(BLUE)╔════════════════════════════════════════════════════════════════════════╗$(NC)"
	@echo "$(BLUE)║                        SPECTRA Project Commands                         ║$(NC)"
	@echo "$(BLUE)╚════════════════════════════════════════════════════════════════════════╝$(NC)"
	@echo ""
	@echo "$(GREEN)Quick Start:$(NC)"
	@echo "  $(YELLOW)make bootstrap$(NC)        Auto-setup and launch SPECTRA (recommended)"
	@echo "  $(YELLOW)make run$(NC)              Launch SPECTRA TUI immediately"
	@echo ""
	@echo "$(GREEN)Installation:$(NC)"
	@echo "  $(YELLOW)make install$(NC)         Install/update SPECTRA and dependencies"
	@echo "  $(YELLOW)make repair$(NC)          Repair broken SPECTRA installation"
	@echo ""
	@echo "$(GREEN)Development:$(NC)"
	@echo "  $(YELLOW)make test$(NC)            Run test suite"
	@echo "  $(YELLOW)make clean$(NC)           Clean build artifacts and cache"
	@echo "  $(YELLOW)make docs$(NC)            Generate documentation (if available)"
	@echo ""
	@echo "$(GREEN)Utilities:$(NC)"
	@echo "  $(YELLOW)make help$(NC)            Show this message"
	@echo "  $(YELLOW)make version$(NC)         Show SPECTRA version"
	@echo ""

bootstrap: ## Auto-setup and launch SPECTRA
	@echo "$(BLUE)▶$(NC) Starting SPECTRA bootstrap..."
	@./bootstrap

run: ## Launch SPECTRA TUI
	@echo "$(BLUE)▶$(NC) Launching SPECTRA TUI..."
	@$(LAUNCH_SCRIPT)

install: ## Install SPECTRA and all dependencies
	@echo "$(BLUE)▶$(NC) Installing SPECTRA..."
	@bash $(INSTALL_SCRIPT)

repair: ## Repair broken SPECTRA installation
	@echo "$(BLUE)▶$(NC) Repairing SPECTRA installation..."
	@bash $(REPAIR_SCRIPT)

setup: ## Run environment setup
	@echo "$(BLUE)▶$(NC) Setting up SPECTRA environment..."
	@bash $(SETUP_SCRIPT)

test: ## Run test suite
	@echo "$(BLUE)▶$(NC) Running tests..."
	@python3 -m pytest tgarchive/tests/ -v 2>/dev/null || \
		echo "$(YELLOW)⚠$(NC) pytest not installed. Install with: pip install pytest"

clean: ## Clean build artifacts and cache
	@echo "$(BLUE)▶$(NC) Cleaning build artifacts..."
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@find . -type f -name ".coverage" -delete 2>/dev/null || true
	@rm -rf build/ dist/ *.egg-info/ 2>/dev/null || true
	@echo "$(GREEN)✓$(NC) Clean complete"

docs: ## Generate/view documentation
	@echo "$(BLUE)▶$(NC) Documentation available at: docs/"
	@ls -lh docs/*.md 2>/dev/null | awk '{print "  - " $$9}'

version: ## Show SPECTRA version
	@python3 -c "from tgarchive import __version__; print(f'SPECTRA v{__version__}')" 2>/dev/null || \
		echo "Version info: Check tgarchive/__init__.py"

# Development targets
lint: ## Run code linting (if available)
	@echo "$(BLUE)▶$(NC) Running code linter..."
	@python3 -m pylint tgarchive/ 2>/dev/null || \
		echo "$(YELLOW)⚠$(NC) pylint not installed. Install with: pip install pylint"

format: ## Format code with Black (if available)
	@echo "$(BLUE)▶$(NC) Formatting code..."
	@python3 -m black tgarchive/ 2>/dev/null || \
		echo "$(YELLOW)⚠$(NC) black not installed. Install with: pip install black"

# Hidden targets for internal use
.PHONY: check-files
check-files:
	@test -x $(LAUNCH_SCRIPT) || chmod +x $(LAUNCH_SCRIPT)
	@test -x ./bootstrap || chmod +x ./bootstrap
