#!/usr/bin/env python3
"""
SPECTRA Splash Screen & Progress Indicator
==========================================

Enhanced startup experience with:
- Animated splash screen
- Progress tracking
- System status indicators
- Error recovery assistance
- Professional startup experience
"""

import sys
import time
import threading
import itertools
from typing import Optional, Callable, Any
from pathlib import Path

# Ensure repository root is available when executed directly
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Color constants
class Colors:
    BLUE = '\033[0;34m'
    GREEN = '\033[0;32m'
    RED = '\033[0;31m'
    YELLOW = '\033[0;33m'
    CYAN = '\033[0;36m'
    PURPLE = '\033[0;35m'
    WHITE = '\033[1;37m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    NC = '\033[0m'  # No Color

class ProgressSpinner:
    """Animated progress spinner for terminal"""

    def __init__(self, message: str = "Loading...", style: str = "dots"):
        self.message = message
        self.running = False
        self.thread = None

        # Different spinner styles
        self.styles = {
            "dots": ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"],
            "bars": ["▁", "▃", "▄", "▅", "▆", "▇", "█", "▇", "▆", "▅", "▄", "▃"],
            "arrows": ["←", "↖", "↑", "↗", "→", "↘", "↓", "↙"],
            "clock": ["🕐", "🕑", "🕒", "🕓", "🕔", "🕕", "🕖", "🕗", "🕘", "🕙", "🕚", "🕛"],
            "pulse": ["●", "○", "●", "○"],
            "wave": ["▁", "▂", "▃", "▄", "▅", "▆", "▇", "█", "▇", "▆", "▅", "▄", "▃", "▂"]
        }

        self.spinner_chars = self.styles.get(style, self.styles["dots"])
        self.spinner = itertools.cycle(self.spinner_chars)

    def _spin(self):
        """Internal spinner animation"""
        while self.running:
            sys.stdout.write(f"\r{Colors.CYAN}{next(self.spinner)} {self.message}{Colors.NC}")
            sys.stdout.flush()
            time.sleep(0.1)

    def start(self):
        """Start the spinner"""
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self._spin)
            self.thread.daemon = True
            self.thread.start()

    def stop(self, success_message: Optional[str] = None, error_message: Optional[str] = None):
        """Stop the spinner with optional message"""
        if self.running:
            self.running = False
            if self.thread:
                self.thread.join()

            # Clear the line
            sys.stdout.write("\r" + " " * 80 + "\r")

            if success_message:
                sys.stdout.write(f"{Colors.GREEN}✓ {success_message}{Colors.NC}\n")
            elif error_message:
                sys.stdout.write(f"{Colors.RED}✗ {error_message}{Colors.NC}\n")

            sys.stdout.flush()

    def update_message(self, new_message: str):
        """Update spinner message"""
        self.message = new_message

class ProgressBar:
    """ASCII progress bar with customizable styling"""

    def __init__(self, total: int = 100, width: int = 50, fill_char: str = "█", empty_char: str = "░"):
        self.total = total
        self.width = width
        self.fill_char = fill_char
        self.empty_char = empty_char
        self.current = 0

    def update(self, progress: int, message: str = ""):
        """Update progress bar"""
        self.current = min(progress, self.total)
        percentage = (self.current / self.total) * 100
        filled_width = int((self.current / self.total) * self.width)

        bar = self.fill_char * filled_width + self.empty_char * (self.width - filled_width)

        sys.stdout.write(f"\r{Colors.CYAN}[{bar}] {percentage:6.1f}% {message}{Colors.NC}")
        sys.stdout.flush()

    def finish(self, message: str = "Complete"):
        """Finish progress bar"""
        self.update(self.total, message)
        sys.stdout.write("\n")
        sys.stdout.flush()

class SplashScreen:
    """SPECTRA splash screen with animation and status"""

    def __init__(self):
        self.width = 80
        self.banner_lines = [
            "╔═══════════════════════════════════════════════════════════════════════════╗",
            "║                          ███████╗██████╗ ███████╗ ██████╗████████╗██████╗  ║",
            "║                          ██╔════╝██╔══██╗██╔════╝██╔════╝╚══██╔══╝██╔══██╗ ║",
            "║                          ███████╗██████╔╝█████╗  ██║        ██║   ██████╔╗ ║",
            "║                          ╚════██║██╔═══╝ ██╔══╝  ██║        ██║   ██╔══██║ ║",
            "║                          ███████║██║     ███████╗╚██████╗   ██║   ██║  ██║ ║",
            "║                          ╚══════╝╚═╝     ╚══════╝ ╚═════╝   ╚═╝   ╚═╝  ╚═╝ ║",
            "╚═══════════════════════════════════════════════════════════════════════════╝"
        ]

        self.subtitle = "Telegram Network Discovery & Archiving System"
        self.version = "v3.0 Auto-Launcher"

    def clear_screen(self):
        """Clear terminal screen"""
        import os
        os.system('cls' if os.name == 'nt' else 'clear')

    def show_banner(self, animated: bool = True):
        """Display the main banner"""
        self.clear_screen()

        if animated:
            # Animate banner appearance
            for i, line in enumerate(self.banner_lines):
                print(f"{Colors.BLUE}{line}{Colors.NC}")
                time.sleep(0.1)
        else:
            for line in self.banner_lines:
                print(f"{Colors.BLUE}{line}{Colors.NC}")

        # Show subtitle and version
        print(f"{Colors.WHITE}{self.subtitle:^{self.width}}{Colors.NC}")
        print(f"{Colors.CYAN}{self.version:^{self.width}}{Colors.NC}")
        print()

    def show_system_info(self, system_info: dict):
        """Display system information"""
        print(f"{Colors.YELLOW}System Information:{Colors.NC}")
        print(f"  Platform: {system_info.get('platform', 'Unknown')}")
        print(f"  Python: {system_info.get('python_version', 'Unknown')}")
        print(f"  Architecture: {system_info.get('architecture', 'Unknown')}")
        print()

    def show_startup_sequence(self, steps: list, step_delay: float = 0.8):
        """Show animated startup sequence"""
        print(f"{Colors.CYAN}Initializing SPECTRA...{Colors.NC}\n")

        progress = ProgressBar(total=len(steps), width=60)

        for i, step in enumerate(steps):
            spinner = ProgressSpinner(step, "pulse")
            spinner.start()

            # Simulate work
            time.sleep(step_delay)

            spinner.stop(success_message=step)
            progress.update(i + 1)
            time.sleep(0.2)

        progress.finish("Initialization complete")
        print()

def run_startup_checks(progress_callback: Optional[Callable] = None) -> dict:
    """Run system checks with progress updates"""
    import platform
    import sys
    from pathlib import Path

    checks = {
        "python_version": False,
        "venv_exists": False,
        "config_exists": False,
        "dependencies": False,
        "system_info": {}
    }

    # Collect system info
    checks["system_info"] = {
        "platform": platform.system(),
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "architecture": platform.architecture()[0],
        "machine": platform.machine()
    }

    if progress_callback:
        progress_callback("Checking Python version...")
    time.sleep(0.3)
    checks["python_version"] = sys.version_info >= (3, 10)

    if progress_callback:
        progress_callback("Checking virtual environment...")
    time.sleep(0.3)
    venv_path = Path(__file__).parent / ".venv"
    checks["venv_exists"] = venv_path.exists()

    if progress_callback:
        progress_callback("Checking configuration...")
    time.sleep(0.3)
    config_path = Path(__file__).parent / "spectra_config.json"
    checks["config_exists"] = config_path.exists()

    if progress_callback:
        progress_callback("Verifying dependencies...")
    time.sleep(0.5)
    try:
        import telethon
        import rich
        import npyscreen
        checks["dependencies"] = True
    except ImportError:
        checks["dependencies"] = False

    return checks

def show_status_summary(checks: dict):
    """Show system status summary"""
    print(f"{Colors.WHITE}System Status:{Colors.NC}")
    print("=" * 50)

    status_items = [
        ("Python 3.10+", checks["python_version"]),
        ("Virtual Environment", checks["venv_exists"]),
        ("Configuration File", checks["config_exists"]),
        ("Dependencies Installed", checks["dependencies"])
    ]

    all_good = True
    for item, status in status_items:
        icon = "✓" if status else "✗"
        color = Colors.GREEN if status else Colors.RED
        print(f"  {color}{icon} {item}{Colors.NC}")
        if not status:
            all_good = False

    print()

    if all_good:
        print(f"{Colors.GREEN}🎉 System is ready! Starting SPECTRA...{Colors.NC}")
    else:
        print(f"{Colors.YELLOW}⚠  Setup required. Run: python3 scripts/spectra_launch.py --setup{Colors.NC}")

    return all_good

def show_quick_help():
    """Show quick help and usage"""
    print(f"{Colors.CYAN}Quick Start Commands:{Colors.NC}")
    print("=" * 50)

    commands = [
        ("Launch TUI", "python3 scripts/spectra_launch.py"),
        ("Setup wizard", "python3 scripts/spectra_launch.py --setup"),
        ("CLI commands", "python3 scripts/spectra_launch.py --cli"),
        ("System check", "python3 scripts/spectra_launch.py --check"),
        ("Repair install", "python3 scripts/spectra_launch.py --repair")
    ]

    for desc, cmd in commands:
        print(f"  {Colors.WHITE}{desc}:{Colors.NC} {cmd}")

    print()

def interactive_mode():
    """Interactive startup mode with user choices"""
    splash = SplashScreen()
    splash.show_banner(animated=True)

    # Run startup checks
    message_spinner = ProgressSpinner("Running system checks...", "dots")
    message_spinner.start()

    checks = run_startup_checks()
    message_spinner.stop()

    # Show system info
    splash.show_system_info(checks["system_info"])

    # Show status
    system_ready = show_status_summary(checks)

    if not system_ready:
        print(f"\n{Colors.YELLOW}System setup is required. What would you like to do?{Colors.NC}")
        print("1. Run auto-setup now")
        print("2. Show installation instructions")
        print("3. Exit")

        try:
            choice = input(f"\n{Colors.CYAN}Enter choice (1-3): {Colors.NC}").strip()

            if choice == "1":
                print(f"\n{Colors.INFO}Running auto-setup...{Colors.NC}")
                return "setup"
            elif choice == "2":
                show_quick_help()
                return "help"
            else:
                return "exit"
        except KeyboardInterrupt:
            print(f"\n{Colors.YELLOW}Cancelled by user{Colors.NC}")
            return "exit"
    else:
        print(f"\n{Colors.GREEN}Starting SPECTRA TUI in 3 seconds...{Colors.NC}")
        print(f"{Colors.DIM}(Press Ctrl+C to cancel){Colors.NC}")

        try:
            for i in range(3, 0, -1):
                sys.stdout.write(f"\rStarting in {i}...")
                sys.stdout.flush()
                time.sleep(1)
            print(f"\r{' ' * 20}\r", end="")  # Clear the countdown
            return "launch"
        except KeyboardInterrupt:
            print(f"\n{Colors.YELLOW}Startup cancelled{Colors.NC}")
            return "exit"

def launch_with_progress():
    """Launch SPECTRA with full progress indication"""
    splash = SplashScreen()
    splash.show_banner(animated=False)

    startup_steps = [
        "Loading configuration...",
        "Initializing database...",
        "Setting up TUI components...",
        "Preparing network modules...",
        "Starting SPECTRA interface..."
    ]

    splash.show_startup_sequence(startup_steps, step_delay=0.6)

    print(f"{Colors.GREEN}🚀 SPECTRA is ready!{Colors.NC}\n")

def main():
    """Main entry point for splash screen"""
    import argparse

    parser = argparse.ArgumentParser(description="SPECTRA Splash Screen & Progress")
    parser.add_argument("--interactive", action="store_true", help="Show interactive startup")
    parser.add_argument("--progress", action="store_true", help="Show launch progress")
    parser.add_argument("--check", action="store_true", help="Run system checks only")
    parser.add_argument("--quick", action="store_true", help="Quick launch without animation")

    args = parser.parse_args()

    try:
        if args.check:
            # Just run checks and show status
            splash = SplashScreen()
            splash.show_banner(animated=False)
            checks = run_startup_checks()
            splash.show_system_info(checks["system_info"])
            show_status_summary(checks)

        elif args.interactive:
            # Interactive mode with user choices
            result = interactive_mode()
            return 0 if result in ["launch", "setup"] else 1

        elif args.progress:
            # Show launch progress
            launch_with_progress()

        elif args.quick:
            # Quick startup without delays
            splash = SplashScreen()
            splash.show_banner(animated=False)
            print(f"{Colors.GREEN}SPECTRA ready to launch{Colors.NC}")

        else:
            # Default: show banner and basic info
            splash = SplashScreen()
            splash.show_banner(animated=True)
            checks = run_startup_checks()
            show_status_summary(checks)

        return 0

    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Interrupted by user{Colors.NC}")
        return 130
    except Exception as e:
        print(f"\n{Colors.RED}Error: {e}{Colors.NC}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
