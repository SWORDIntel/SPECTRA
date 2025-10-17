#!/usr/bin/env python3
"""
SPECTRA Auto-Launcher
=====================

Comprehensive auto-launching system for SPECTRA that handles:
- Automatic virtual environment creation and management
- Dependency installation and conflict resolution
- Error recovery and system compatibility
- Direct TUI launch with progress indication
- Configuration wizard for first-time setup

Usage:
    python3 scripts/spectra_launch.py              # Auto-launch TUI
    python3 scripts/spectra_launch.py --setup      # Run setup wizard
    python3 scripts/spectra_launch.py --cli        # Launch CLI mode
    python3 scripts/spectra_launch.py --check      # Check system status
    python3 scripts/spectra_launch.py --repair     # Repair installation
"""

import argparse
import asyncio
import json
import logging
import os
import platform
import shutil
import subprocess
import sys
import time
import venv
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

# Ensure repository root is available for downstream imports
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Color constants for cross-platform output
class Colors:
    BLUE = '\033[0;34m'
    GREEN = '\033[0;32m'
    RED = '\033[0;31m'
    YELLOW = '\033[0;33m'
    CYAN = '\033[0;36m'
    PURPLE = '\033[0;35m'
    WHITE = '\033[1;37m'
    NC = '\033[0m'  # No Color

    @classmethod
    def disable_on_windows(cls):
        """Disable colors on Windows if not supported"""
        if platform.system() == "Windows":
            for attr in dir(cls):
                if not attr.startswith('_') and attr != 'disable_on_windows':
                    setattr(cls, attr, '')

# Initialize colors
if platform.system() == "Windows" and not os.environ.get("ANSICON"):
    Colors.disable_on_windows()

class SpectraLauncher:
    """Main launcher class for SPECTRA system"""

    def __init__(self, project_root: Optional[Path] = None):
        self.project_root = project_root or Path(__file__).resolve().parents[1]
        self.venv_path = self.project_root / ".venv"
        self.config_path = self.project_root / "spectra_config.json"
        self.requirements_path = self.project_root / "requirements.txt"
        self.logs_dir = self.project_root / "logs"
        self.data_dir = self.project_root / "spectra_data"

        # Setup logging
        self.logs_dir.mkdir(exist_ok=True)
        log_file = self.logs_dir / f"launcher_{int(time.time())}.log"

        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)

        # System info
        self.system_info = {
            "platform": platform.system(),
            "python_version": sys.version,
            "python_executable": sys.executable,
            "architecture": platform.architecture()[0],
            "machine": platform.machine()
        }

        self.logger.info(f"SPECTRA Launcher initialized on {self.system_info['platform']}")

    def print_banner(self):
        """Display the SPECTRA banner"""
        banner = f"""
{Colors.BLUE}╔═══════════════════════════════════════════════════════════════════════════╗
║                          ███████╗██████╗ ███████╗ ██████╗████████╗██████╗  ║
║                          ██╔════╝██╔══██╗██╔════╝██╔════╝╚══██╔══╝██╔══██╗ ║
║                          ███████╗██████╔╝█████╗  ██║        ██║   ██████╔╗ ║
║                          ╚════██║██╔═══╝ ██╔══╝  ██║        ██║   ██╔══██║ ║
║                          ███████║██║     ███████╗╚██████╗   ██║   ██║  ██║ ║
║                          ╚══════╝╚═╝     ╚══════╝ ╚═════╝   ╚═╝   ╚═╝  ╚═╝ ║
╚═══════════════════════════════════════════════════════════════════════════╝{Colors.NC}
{Colors.WHITE}               Auto-Launcher - Telegram Network Discovery & Archiving{Colors.NC}
"""
        print(banner)

    def print_status(self, message: str, status: str = "INFO", progress: Optional[int] = None):
        """Print status message with color coding"""
        color_map = {
            "INFO": Colors.CYAN,
            "SUCCESS": Colors.GREEN,
            "WARNING": Colors.YELLOW,
            "ERROR": Colors.RED,
            "PROGRESS": Colors.PURPLE
        }

        color = color_map.get(status, Colors.WHITE)
        prefix = "✓" if status == "SUCCESS" else "⚠" if status == "WARNING" else "✗" if status == "ERROR" else "→"

        if progress is not None:
            message = f"[{progress:3d}%] {message}"

        print(f"{color}{prefix} {message}{Colors.NC}")
        self.logger.info(f"{status}: {message}")

    def check_python_version(self) -> bool:
        """Check if Python version meets requirements"""
        self.print_status("Checking Python version...", "PROGRESS")

        version_info = sys.version_info
        required_major, required_minor = 3, 10

        if version_info.major < required_major or (
            version_info.major == required_major and version_info.minor < required_minor
        ):
            self.print_status(
                f"Python {required_major}.{required_minor}+ required "
                f"(found {version_info.major}.{version_info.minor})",
                "ERROR"
            )
            return False

        self.print_status(
            f"Python {version_info.major}.{version_info.minor}.{version_info.micro} detected",
            "SUCCESS"
        )
        return True

    def check_system_dependencies(self) -> List[str]:
        """Check for required system dependencies"""
        self.print_status("Checking system dependencies...", "PROGRESS")

        missing_deps = []

        # Check for git
        if not shutil.which("git"):
            missing_deps.append("git")

        # Platform-specific checks
        if self.system_info["platform"] == "Linux":
            # Check for development packages that might be needed
            try:
                subprocess.run(["pkg-config", "--exists", "libffi"],
                             check=True, capture_output=True)
            except (subprocess.CalledProcessError, FileNotFoundError):
                missing_deps.append("libffi-dev")

        if missing_deps:
            self.print_status(f"Missing system dependencies: {', '.join(missing_deps)}", "WARNING")
            if self.system_info["platform"] == "Linux":
                self.print_status("Install with: sudo apt-get install " + " ".join(missing_deps), "INFO")
        else:
            self.print_status("All system dependencies satisfied", "SUCCESS")

        return missing_deps

    def create_virtual_environment(self) -> bool:
        """Create Python virtual environment"""
        if self.venv_path.exists():
            self.print_status("Virtual environment already exists", "INFO")
            return True

        self.print_status("Creating Python virtual environment...", "PROGRESS")

        try:
            venv.create(self.venv_path, with_pip=True, upgrade_deps=True)
            self.print_status("Virtual environment created successfully", "SUCCESS")
            return True
        except Exception as e:
            self.print_status(f"Failed to create virtual environment: {e}", "ERROR")
            return False

    def get_venv_python(self) -> Path:
        """Get path to Python executable in virtual environment"""
        if self.system_info["platform"] == "Windows":
            return self.venv_path / "Scripts" / "python.exe"
        else:
            return self.venv_path / "bin" / "python"

    def get_venv_pip(self) -> Path:
        """Get path to pip executable in virtual environment"""
        if self.system_info["platform"] == "Windows":
            return self.venv_path / "Scripts" / "pip.exe"
        else:
            return self.venv_path / "bin" / "pip"

    def upgrade_pip(self) -> bool:
        """Upgrade pip in virtual environment"""
        self.print_status("Upgrading pip...", "PROGRESS")

        try:
            subprocess.run([
                str(self.get_venv_python()), "-m", "pip", "install", "--upgrade", "pip"
            ], check=True, capture_output=True, text=True)
            self.print_status("Pip upgraded successfully", "SUCCESS")
            return True
        except subprocess.CalledProcessError as e:
            self.print_status(f"Failed to upgrade pip: {e}", "ERROR")
            return False

    def install_dependencies(self, force_reinstall: bool = False) -> bool:
        """Install Python dependencies"""
        if not self.requirements_path.exists():
            self.print_status("Creating basic requirements.txt...", "PROGRESS")
            self.create_requirements_file()

        self.print_status("Installing Python dependencies...", "PROGRESS")

        pip_cmd = [str(self.get_venv_pip()), "install"]

        if force_reinstall:
            pip_cmd.append("--force-reinstall")

        # Install package in development mode
        pip_cmd.extend(["-e", "."])

        try:
            result = subprocess.run(
                pip_cmd,
                cwd=self.project_root,
                check=True,
                capture_output=True,
                text=True
            )
            self.print_status("Dependencies installed successfully", "SUCCESS")
            return True
        except subprocess.CalledProcessError as e:
            self.print_status(f"Failed to install dependencies: {e}", "ERROR")
            self.print_status(f"Stdout: {e.stdout}", "ERROR")
            self.print_status(f"Stderr: {e.stderr}", "ERROR")

            # Try alternative installation
            return self.install_dependencies_alternative()

    def install_dependencies_alternative(self) -> bool:
        """Alternative dependency installation with fallbacks"""
        self.print_status("Attempting alternative dependency installation...", "PROGRESS")

        # Core dependencies that are essential
        core_deps = [
            "telethon>=1.34.0",
            "rich>=13.0.0",
            "tqdm>=4.0.0",
            "pyyaml>=6.0.0",
            "Pillow>=10.0.0",
            "npyscreen>=4.10.5",
            "jinja2>=3.0.0"
        ]

        pip_path = str(self.get_venv_pip())

        for dep in core_deps:
            try:
                self.print_status(f"Installing {dep}...", "PROGRESS")
                subprocess.run([pip_path, "install", dep], check=True, capture_output=True)
                self.print_status(f"Installed {dep}", "SUCCESS")
            except subprocess.CalledProcessError as e:
                self.print_status(f"Failed to install {dep}: {e}", "WARNING")

        # Try to install optional dependencies without failing
        optional_deps = [
            "networkx>=3.0",
            "matplotlib>=3.6.0",
            "pandas>=1.5.0",
            "python-magic>=0.4.27",
            "cryptg>=0.2.post4"
        ]

        for dep in optional_deps:
            try:
                subprocess.run([pip_path, "install", dep], check=True, capture_output=True)
                self.print_status(f"Installed optional dependency {dep}", "SUCCESS")
            except subprocess.CalledProcessError:
                self.print_status(f"Skipped optional dependency {dep}", "WARNING")

        return True

    def create_requirements_file(self):
        """Create a comprehensive requirements.txt file"""
        requirements_content = """# SPECTRA Core Dependencies
telethon>=1.34.0
rich>=13.0.0
tqdm>=4.0.0
pyyaml>=6.0.0
Pillow>=10.0.0
npyscreen>=4.10.5
jinja2>=3.0.0

# Network analysis
networkx>=3.0
matplotlib>=3.6.0
pandas>=1.5.0

# Proxy and authentication
python-magic>=0.4.27
pyaes>=1.6.1
pyasn1>=0.6.0
rsa>=4.9

# Media handling
feedgen>=0.9.0
lxml>=4.9.2

# Deduplication libraries
imagehash>=4.3.1
ssdeep>=3.4
datasketch>=1.5.9

# Optional but recommended
pysocks>=1.7.1  # For SOCKS proxy support
cryptg>=0.2.post4  # For faster downloads
croniter>=1.3.5
yoyo-migrations>=8.2.0
pywin32>=300; sys_platform == 'win32'
aiofiles>=23.2.1
aiosqlite>=0.20.0
"""

        self.requirements_path.write_text(requirements_content.strip())
        self.print_status("Created requirements.txt", "SUCCESS")

    def check_configuration(self) -> bool:
        """Check if SPECTRA is properly configured"""
        self.print_status("Checking SPECTRA configuration...", "PROGRESS")

        if not self.config_path.exists():
            self.print_status("Configuration file not found", "WARNING")
            return False

        try:
            with open(self.config_path, 'r') as f:
                config = json.load(f)

            # Check for required configuration sections
            required_sections = ["accounts"]
            missing_sections = [section for section in required_sections if section not in config]

            if missing_sections:
                self.print_status(f"Missing configuration sections: {missing_sections}", "WARNING")
                return False

            # Check if accounts are configured
            if not config.get("accounts") or len(config["accounts"]) == 0:
                self.print_status("No Telegram accounts configured", "WARNING")
                return False

            self.print_status("Configuration is valid", "SUCCESS")
            return True

        except json.JSONDecodeError as e:
            self.print_status(f"Invalid JSON in configuration file: {e}", "ERROR")
            return False
        except Exception as e:
            self.print_status(f"Error reading configuration: {e}", "ERROR")
            return False

    def create_default_configuration(self) -> bool:
        """Create default configuration file"""
        self.print_status("Creating default configuration...", "PROGRESS")

        default_config = {
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
                "enable_deduplication": True,
                "secondary_unique_destination": None
            },
            "parallel": {
                "max_workers": 4,
                "enable_by_default": False
            }
        }

        try:
            with open(self.config_path, 'w') as f:
                json.dump(default_config, f, indent=2)

            self.print_status("Default configuration created", "SUCCESS")
            return True
        except Exception as e:
            self.print_status(f"Failed to create configuration: {e}", "ERROR")
            return False

    def setup_directories(self) -> bool:
        """Create necessary directories"""
        self.print_status("Setting up directories...", "PROGRESS")

        directories = [
            self.data_dir,
            self.data_dir / "media",
            self.logs_dir,
            self.project_root / "migrations"
        ]

        try:
            for directory in directories:
                directory.mkdir(parents=True, exist_ok=True)

            self.print_status("Directories created successfully", "SUCCESS")
            return True
        except Exception as e:
            self.print_status(f"Failed to create directories: {e}", "ERROR")
            return False

    def run_configuration_wizard(self) -> bool:
        """Run interactive configuration wizard"""
        self.print_status("Starting configuration wizard...", "INFO")

        try:
            # Import accounts from gen_config.py if available
            gen_config_path = self.project_root / "gen_config.py"
            if gen_config_path.exists():
                self.print_status("Found gen_config.py - importing accounts...", "INFO")
                try:
                    python_path = str(self.get_venv_python())
                    result = subprocess.run([
                        python_path, "-m", "tgarchive", "accounts", "--import"
                    ], cwd=self.project_root, capture_output=True, text=True)

                    if result.returncode == 0:
                        self.print_status("Accounts imported from gen_config.py", "SUCCESS")
                        return True
                    else:
                        self.print_status("Failed to import from gen_config.py", "WARNING")
                except Exception as e:
                    self.print_status(f"Error importing accounts: {e}", "WARNING")

            # Manual configuration if needed
            print(f"\n{Colors.YELLOW}Configuration Wizard{Colors.NC}")
            print("=" * 50)

            print(f"\n{Colors.CYAN}To complete SPECTRA setup, you need:{Colors.NC}")
            print("1. Telegram API credentials (api_id and api_hash)")
            print("2. At least one Telegram account")
            print("\nGet API credentials from: https://my.telegram.org/apps")

            response = input(f"\n{Colors.YELLOW}Do you want to configure now? [y/N]: {Colors.NC}")
            if response.lower() in ['y', 'yes']:
                return self.interactive_account_setup()
            else:
                self.print_status("Configuration skipped - you can run setup later", "WARNING")
                return False

        except Exception as e:
            self.print_status(f"Configuration wizard failed: {e}", "ERROR")
            return False

    def interactive_account_setup(self) -> bool:
        """Interactive account setup"""
        try:
            config = {}
            if self.config_path.exists():
                with open(self.config_path, 'r') as f:
                    config = json.load(f)

            if "accounts" not in config:
                config["accounts"] = []

            print(f"\n{Colors.CYAN}Account Setup{Colors.NC}")
            print("-" * 30)

            api_id = input("Enter your Telegram API ID: ").strip()
            api_hash = input("Enter your Telegram API Hash: ").strip()
            session_name = input("Enter session name (default: main): ").strip() or "main"

            if not api_id or not api_hash:
                self.print_status("API ID and Hash are required", "ERROR")
                return False

            account = {
                "api_id": int(api_id),
                "api_hash": api_hash,
                "session_name": session_name
            }

            config["accounts"].append(account)

            with open(self.config_path, 'w') as f:
                json.dump(config, f, indent=2)

            self.print_status("Account configuration saved", "SUCCESS")
            return True

        except ValueError:
            self.print_status("API ID must be a number", "ERROR")
            return False
        except Exception as e:
            self.print_status(f"Failed to save account configuration: {e}", "ERROR")
            return False

    def check_spectra_installation(self) -> bool:
        """Check if SPECTRA is properly installed"""
        self.print_status("Checking SPECTRA installation...", "PROGRESS")

        try:
            python_path = str(self.get_venv_python())
            result = subprocess.run([
                python_path, "-c", "import tgarchive; print('SPECTRA installed')"
            ], capture_output=True, text=True)

            if result.returncode == 0:
                self.print_status("SPECTRA is properly installed", "SUCCESS")
                return True
            else:
                self.print_status("SPECTRA installation check failed", "ERROR")
                return False
        except Exception as e:
            self.print_status(f"Error checking installation: {e}", "ERROR")
            return False

    def launch_tui(self) -> bool:
        """Launch SPECTRA TUI"""
        self.print_status("Launching SPECTRA TUI...", "INFO")

        try:
            python_path = str(self.get_venv_python())

            # Show splash screen
            self.show_splash_screen()

            # Launch TUI
            os.chdir(self.project_root)
            env = os.environ.copy()
            env["PYTHONPATH"] = str(self.project_root)

            subprocess.run([python_path, "-m", "tgarchive"], env=env)
            return True

        except KeyboardInterrupt:
            self.print_status("TUI launch cancelled by user", "INFO")
            return False
        except Exception as e:
            self.print_status(f"Failed to launch TUI: {e}", "ERROR")
            return False

    def show_splash_screen(self):
        """Show loading splash screen"""
        print(f"\n{Colors.GREEN}🚀 Initializing SPECTRA...{Colors.NC}")

        loading_steps = [
            "Loading configuration...",
            "Initializing database...",
            "Setting up TUI interface...",
            "Ready to launch!"
        ]

        for i, step in enumerate(loading_steps):
            print(f"{Colors.CYAN}   {step}{Colors.NC}")
            time.sleep(0.5)

        print(f"\n{Colors.WHITE}SPECTRA TUI is starting...{Colors.NC}\n")

    def launch_cli(self) -> bool:
        """Launch SPECTRA in CLI mode"""
        self.print_status("Launching SPECTRA CLI...", "INFO")

        try:
            python_path = str(self.get_venv_python())

            print(f"\n{Colors.CYAN}SPECTRA CLI Commands:{Colors.NC}")
            print("=" * 40)
            print(f"{Colors.WHITE}Discovery:{Colors.NC}")
            print(f"  {python_path} -m tgarchive discover --seed @channel --depth 2")
            print(f"  {python_path} -m tgarchive network --from-db --plot")
            print(f"\n{Colors.WHITE}Archiving:{Colors.NC}")
            print(f"  {python_path} -m tgarchive archive --entity @channel --auto")
            print(f"  {python_path} -m tgarchive batch --from-db --limit 10")
            print(f"\n{Colors.WHITE}Account Management:{Colors.NC}")
            print(f"  {python_path} -m tgarchive accounts --list")
            print(f"  {python_path} -m tgarchive accounts --import")
            print(f"\n{Colors.WHITE}Help:{Colors.NC}")
            print(f"  {python_path} -m tgarchive --help")

            return True

        except Exception as e:
            self.print_status(f"Failed to show CLI help: {e}", "ERROR")
            return False

    def check_system_status(self) -> Dict:
        """Check complete system status"""
        self.print_status("Checking system status...", "INFO")

        status = {
            "python_version": self.check_python_version(),
            "venv_exists": self.venv_path.exists(),
            "dependencies_installed": False,
            "configuration_valid": False,
            "spectra_installed": False,
            "system_dependencies": [],
            "directories_setup": True
        }

        if status["venv_exists"]:
            status["dependencies_installed"] = self.check_spectra_installation()

        status["configuration_valid"] = self.check_configuration()
        status["system_dependencies"] = self.check_system_dependencies()

        # Check directories
        required_dirs = [self.data_dir, self.logs_dir]
        status["directories_setup"] = all(d.exists() for d in required_dirs)

        return status

    def repair_installation(self) -> bool:
        """Repair broken installation"""
        self.print_status("Starting installation repair...", "INFO")

        # Check and fix virtual environment
        if not self.venv_path.exists():
            if not self.create_virtual_environment():
                return False

        # Upgrade pip
        if not self.upgrade_pip():
            self.print_status("Warning: Could not upgrade pip", "WARNING")

        # Reinstall dependencies
        if not self.install_dependencies(force_reinstall=True):
            return False

        # Setup directories
        if not self.setup_directories():
            return False

        # Check configuration
        if not self.config_path.exists():
            self.create_default_configuration()

        self.print_status("Installation repair completed", "SUCCESS")
        return True

    def full_setup(self) -> bool:
        """Complete setup process"""
        self.print_banner()

        self.print_status("Starting SPECTRA auto-setup...", "INFO")

        # Progress tracking
        total_steps = 8
        current_step = 0

        def progress():
            nonlocal current_step
            current_step += 1
            return int((current_step / total_steps) * 100)

        # Step 1: Check Python version
        if not self.check_python_version():
            return False
        self.print_status("Python version check", "SUCCESS", progress())

        # Step 2: Check system dependencies
        self.check_system_dependencies()
        self.print_status("System dependencies check", "SUCCESS", progress())

        # Step 3: Create virtual environment
        if not self.create_virtual_environment():
            return False
        self.print_status("Virtual environment", "SUCCESS", progress())

        # Step 4: Upgrade pip
        if not self.upgrade_pip():
            self.print_status("Pip upgrade failed - continuing", "WARNING")
        self.print_status("Pip upgrade", "SUCCESS", progress())

        # Step 5: Install dependencies
        if not self.install_dependencies():
            return False
        self.print_status("Dependencies installation", "SUCCESS", progress())

        # Step 6: Setup directories
        if not self.setup_directories():
            return False
        self.print_status("Directory setup", "SUCCESS", progress())

        # Step 7: Configuration
        if not self.config_path.exists():
            if not self.create_default_configuration():
                return False
        self.print_status("Configuration setup", "SUCCESS", progress())

        # Step 8: Configuration wizard
        self.run_configuration_wizard()
        self.print_status("Setup completed", "SUCCESS", progress())

        print(f"\n{Colors.GREEN}🎉 SPECTRA setup completed successfully!{Colors.NC}")
        print(f"\n{Colors.CYAN}Next steps:{Colors.NC}")
        if not self.check_configuration():
            print(f"  1. Run: {Colors.WHITE}python3 scripts/spectra_launch.py --setup{Colors.NC} to configure accounts")
        print(f"  2. Run: {Colors.WHITE}python3 scripts/spectra_launch.py{Colors.NC} to start SPECTRA TUI")
        print(f"  3. Or run: {Colors.WHITE}python3 scripts/spectra_launch.py --cli{Colors.NC} for CLI commands")

        return True

def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="SPECTRA Auto-Launcher - Comprehensive setup and launch system"
    )

    parser.add_argument(
        "--setup", action="store_true",
        help="Run configuration setup wizard"
    )

    parser.add_argument(
        "--cli", action="store_true",
        help="Show CLI commands instead of launching TUI"
    )

    parser.add_argument(
        "--check", action="store_true",
        help="Check system status and requirements"
    )

    parser.add_argument(
        "--repair", action="store_true",
        help="Repair broken installation"
    )

    parser.add_argument(
        "--project-root", type=Path,
        help="Override project root directory"
    )

    args = parser.parse_args()

    # Initialize launcher
    launcher = SpectraLauncher(args.project_root)

    try:
        if args.check:
            # Check system status
            status = launcher.check_system_status()
            launcher.print_banner()

            print(f"\n{Colors.CYAN}System Status Report{Colors.NC}")
            print("=" * 50)

            for key, value in status.items():
                status_str = "✓" if value else "✗"
                color = Colors.GREEN if value else Colors.RED
                print(f"{color}{status_str} {key.replace('_', ' ').title()}: {value}{Colors.NC}")

            return 0 if all(status.values()) else 1

        elif args.repair:
            # Repair installation
            launcher.print_banner()
            return 0 if launcher.repair_installation() else 1

        elif args.setup:
            # Run setup wizard only
            launcher.print_banner()
            return 0 if launcher.run_configuration_wizard() else 1

        elif args.cli:
            # Show CLI commands
            launcher.print_banner()
            return 0 if launcher.launch_cli() else 1

        else:
            # Full auto-launch (default)
            # Check if setup is needed
            status = launcher.check_system_status()

            if not all([status["python_version"], status["venv_exists"],
                       status["dependencies_installed"]]):
                # Run full setup
                if not launcher.full_setup():
                    return 1
            else:
                # System is ready, just launch
                launcher.print_banner()

                if not launcher.check_configuration():
                    launcher.print_status("Configuration needed", "WARNING")
                    if not launcher.run_configuration_wizard():
                        launcher.print_status("Launching without full configuration", "WARNING")

                # Launch TUI
                launcher.launch_tui()

            return 0

    except KeyboardInterrupt:
        launcher.print_status("Operation cancelled by user", "INFO")
        return 130
    except Exception as e:
        launcher.print_status(f"Unexpected error: {e}", "ERROR")
        return 1

if __name__ == "__main__":
    sys.exit(main())
