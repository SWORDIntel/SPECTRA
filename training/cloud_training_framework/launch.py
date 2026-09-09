#!/usr/bin/env python3
"""Cloud GPU Training Launcher — TUI dashboard with VM creation and pre-seeding.

Creates a preemptible GPU VM on Nebius, pre-seeds the repo via rsync,
then drops into a rich TUI dashboard showing live training progress.

Usage:
  python3 launch.py                          # create + pre-seed + monitor
  python3 launch.py --monitor                # just monitor existing VM
  python3 launch.py --status                 # just check VM status
  python3 launch.py --ssh                    # just SSH in
  python3 launch.py --stop                   # stop the VM
  python3 launch.py --start                  # start a stopped VM
  python3 launch.py --delete                 # delete the VM
  python3 launch.py --seed                   # just pre-seed repo to VM
  python3 launch.py --download               # download trained models from VM

Requires: nebius CLI, jq, ssh, rsync, Python rich

Features:
  - Auto-resume: if VM is preempted (SIGTERM), waits for reboot, re-seeds, resumes pipeline
  - Auto-download: when all models complete, rsyncs models to local ./models/
  - SIGTERM-safe: launcher exits cleanly if local machine shuts down
"""
import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import urllib.request
import ast
import re

# --- Local venv bootstrap ---
LAUNCHER_VENV = Path(__file__).resolve().parent / ".venv-launcher"

def _ensure_venv():
    """Ensure a local venv with rich exists. Re-exec into it if needed."""
    needs_rich = False
    try:
        import rich  # noqa: F401
        return
    except ImportError:
        needs_rich = True

    if needs_rich:
        if not LAUNCHER_VENV.exists():
            print(f"Creating launcher venv at {LAUNCHER_VENV} ...")
            subprocess.check_call([sys.executable, "-m", "venv", str(LAUNCHER_VENV)])
            subprocess.check_call([str(LAUNCHER_VENV / "bin" / "pip"), "install", "--upgrade", "pip", "wheel"])

        r = subprocess.run(
            [str(LAUNCHER_VENV / "bin" / "python"), "-c", "import rich"],
            capture_output=True,
        )
        if r.returncode != 0:
            print("Installing rich into launcher venv ...")
            subprocess.check_call([str(LAUNCHER_VENV / "bin" / "pip"), "install", "rich"])

        os.execv(str(LAUNCHER_VENV / "bin" / "python"), [str(LAUNCHER_VENV / "bin" / "python"), __file__] + sys.argv[1:])

_ensure_venv()

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.layout import Layout
from rich.live import Live
from rich.text import Text
from rich.align import Align
from rich import box

console = Console()

# Ensure nebius CLI is on PATH
_nebius_bin = os.path.expanduser("~/.nebius/bin")
if os.path.isdir(_nebius_bin) and _nebius_bin not in os.environ.get("PATH", ""):
    os.environ["PATH"] = _nebius_bin + os.pathsep + os.environ["PATH"]

# SIGTERM handler
_sigterm_flag = False

def _sigterm_handler(signum, frame):
    global _sigterm_flag
    _sigterm_flag = True

signal.signal(signal.SIGTERM, _sigterm_handler)

# --- Config (override via env vars) ---
env_file = Path(__file__).parent.resolve() / ".env"
if env_file.exists():
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                k, v = line.split('=', 1)
                os.environ[k] = v.strip('"\'')

VM_NAME = os.environ.get("VM_NAME", "ml-training")
PROJECT_ID = os.environ.get("PROJECT_ID", "")
PLATFORM = os.environ.get("PLATFORM", "gpu-l40s-a")
PRESET = os.environ.get("PRESET", "1gpu-40vcpu-160gb")
SUBNET_ID = os.environ.get("SUBNET_ID", "")
DISK_SIZE_GIB = os.environ.get("DISK_SIZE_GIB", "250")
DISK_TYPE = os.environ.get("DISK_TYPE", "network_ssd")
IMAGE_ID = os.environ.get("IMAGE_ID", "")  # Ubuntu 24.04 + CUDA image
SSH_USER = os.environ.get("SSH_USER", "ubuntu")
SSH_KEY = os.environ.get("SSH_KEY", os.path.expanduser("~/.ssh/id_rsa"))
SSH_HOST = os.environ.get("SSH_HOST", "")
SSH_PUB_KEY = os.environ.get("SSH_PUB_KEY", "~/.ssh/id_rsa.pub")
FRAMEWORK_DIR = Path(__file__).parent.resolve()
REPO_DIR = Path(os.environ.get("TRAINING_REPO_DIR", FRAMEWORK_DIR.parents[1])).resolve()
CLOUD_INIT_FILE = FRAMEWORK_DIR / "cloud-init.yaml"
REMOTE_DIR = "/opt/training-repo"

# Use generic tracking based on whatever the VM outputs
MODEL_ICONS = {"done": "✅", "running": "🔄", "pending": "⏳"}
MODEL_ICONS = {"done": "✅", "running": "🔄", "pending": "⏳"}


# --- Helpers ---

def run(cmd, capture=True, check=False, timeout=30):
    """Run a shell command."""
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=capture, text=True, timeout=timeout
        )
        if check and r.returncode != 0:
            console.print(f"[red]Command failed: {cmd}[/red]")
            if r.stderr:
                console.print(r.stderr)
        return r
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, 124, "", "timeout")


def check_deps():
    missing = []
    for dep in ["nebius", "jq", "ssh", "rsync"]:
        if run(f"command -v {dep}").returncode != 0:
            missing.append(dep)
    if missing:
        console.print(f"[red]Missing: {', '.join(missing)}[/red]")
        sys.exit(1)

def preflight_check():
    """Run local validations to prevent wasting cloud resources on typos."""
    console.print("[cyan]Running pre-flight checks...[/cyan]")
    
    # 1. Syntax check all Python files
    py_files = list(REPO_DIR.rglob("*.py"))
    for py_file in py_files:
        if ".venv" in str(py_file): continue
        try:
            ast.parse(py_file.read_bytes(), filename=str(py_file))
        except SyntaxError as e:
            console.print(f"[red]Pre-flight failed! Syntax error in {py_file.name}: {e}[/red]")
            sys.exit(1)
            
    # 2. Validate package names in requirements exist on PyPI
    req_files = [
        FRAMEWORK_DIR / "requirements-gpu.txt",
        REPO_DIR / "training" / "spectra_operator" / "requirements-gpu.txt",
    ]
    for req_file in req_files:
        if req_file.exists():
            console.print(f"Validating package names in {req_file.name}...")
            lines = req_file.read_text().splitlines()
            for line in lines:
                line = line.split('#')[0].strip()
                if not line: continue
                
                # Extract base package name (ignore versions, extras, env markers)
                pkg_match = re.match(r'^([a-zA-Z0-9_\-]+)', line)
                if pkg_match:
                    pkg_name = pkg_match.group(1)
                    # Simple HTTP HEAD to PyPI to check if it's a real package
                    try:
                        req = urllib.request.Request(f"https://pypi.org/pypi/{pkg_name}/json", method="HEAD")
                        urllib.request.urlopen(req, timeout=5)
                    except urllib.error.HTTPError as e:
                        if e.code == 404:
                            console.print(f"[red]Pre-flight failed! Package '{pkg_name}' does not exist on PyPI (Typo?).[/red]")
                            sys.exit(1)
                    except Exception:
                        pass # Ignore network errors to PyPI

    # 3. Validate Ubuntu packages in cloud-init.yaml
    if CLOUD_INIT_FILE.exists():
        console.print("Validating apt packages in cloud-init.yaml against Ubuntu Noble (24.04)...")
        content = CLOUD_INIT_FILE.read_text()
        packages_to_check = set()
        
        in_apt_cmd = False
        for line in content.splitlines():
            line = line.strip()
            if "apt-get install" in line or "apt install" in line:
                in_apt_cmd = True
                
            if in_apt_cmd:
                # Remove bash operators and quotes
                clean_line = re.sub(r'[\\|{};\'"]', ' ', line)
                words = clean_line.split()
                
                for w in words:
                    if w in ("apt-get", "apt", "install", "sudo", "echo", "exit", "true", "false", "then", "fi", "do", "done"):
                        continue
                    if w.startswith("-") or w.startswith("$") or w.startswith(">"):
                        continue
                    packages_to_check.add(w)
                    
                if not line.endswith('\\'):
                    in_apt_cmd = False
                    
        for pkg in packages_to_check:
            try:
                url = f"https://packages.ubuntu.com/noble/{pkg}"
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                resp = urllib.request.urlopen(req, timeout=5)
                html = resp.read().decode('utf-8')
                if "No such package." in html or "Error" in html and "not found" in html.lower():
                    console.print(f"[red]Pre-flight failed! APT package '{pkg}' does not exist in Ubuntu Noble repos (Typo?).[/red]")
                    sys.exit(1)
            except Exception as e:
                pass # Ignore network errors or 404s if the site is down

    console.print("[green]Pre-flight passed![/green]")


def get_vm_json():
    r = run(f"nebius compute instance get-by-name --name {VM_NAME} --parent-id {PROJECT_ID} --format json")
    try:
        return json.loads(r.stdout) if r.stdout.strip() else {}
    except json.JSONDecodeError:
        return {}


def get_vm_status():
    j = get_vm_json()
    return j.get("status", {}).get("state", "not_found")


def get_vm_ip():
    j = get_vm_json()
    addr = j.get("status", {}).get("network_interfaces", [{}])[0].get("public_ip_address", {}).get("address", "")
    return addr.split("/")[0] if addr else ""


def get_vm_id():
    j = get_vm_json()
    return j.get("metadata", {}).get("id", "")


def wait_for_ip(timeout=150):
    console.print("[cyan]Waiting for public IP...[/cyan]")
    for i in range(timeout // 5):
        ip = get_vm_ip()
        if ip:
            console.print(f"[green]Public IP: {ip}[/green]")
            return ip
        time.sleep(5)
    console.print("[red]Timed out waiting for IP[/red]")
    return None


def wait_for_ssh(ip, timeout=600):
    console.print(f"[cyan]Waiting for SSH at {ip}...[/cyan]")
    for i in range(timeout // 5):
        r = run(
            f"ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no -o BatchMode=yes "
            f"-i {SSH_KEY} {SSH_USER}@{ip} echo ready"
        )
        if r.returncode == 0:
            console.print("[green]SSH is up![/green]")
            return True
        time.sleep(5)
    console.print("[red]SSH never came up[/red]")
    return False


def ssh_cmd(ip, remote_cmd, timeout=15):
    """Run a command on the VM via SSH."""
    return subprocess.run(
        ["ssh", "-o", "ConnectTimeout=5", "-o", "StrictHostKeyChecking=no",
         "-o", "BatchMode=yes", "-i", SSH_KEY, f"{SSH_USER}@{ip}", remote_cmd],
        capture_output=True, text=True, timeout=timeout,
    )


# --- Pre-seed ---

def preseed_vm(ip):
    """Rsync the repo to the VM, install deps if needed, then kick off the pipeline."""
    console.print("[cyan]Pre-seeding repo to VM via rsync...[/cyan]")

    ssh_cmd(ip, f"sudo mkdir -p {REMOTE_DIR} && sudo chown {SSH_USER}:{SSH_USER} {REMOTE_DIR}")

    excludes = [
        "--exclude=.git",
        "--exclude=.env",
        "--exclude=.env.*",
        "--exclude=*.session",
        "--exclude=*.session-journal",
        "--exclude=*.db",
        "--exclude=*.sqlite",
        "--exclude=*.sqlite3",
        "--exclude=.learn/",
        "--exclude=.qlearn/",
        "--exclude=memory-bank/",
        "--exclude=logs/",
        "--exclude=dataset/",
        "--exclude=models/",
        "--exclude=reports/",
        "--exclude=pipeline_state.json",
        "--exclude=training/cloud_training_framework/models/",
        "--exclude=training/cloud_training_framework/reports/",
        "--exclude=training/cloud_training_framework/dataset/",
        "--exclude=training/cloud_training_framework/pipeline_state.json",
        "--exclude=training/spectra_operator/data/*.jsonl",
        "--exclude=training/spectra_operator/models/",
        "--exclude=training/spectra_operator/checkpoints/",
        "--exclude=__pycache__/",
        "--exclude=*.pyc",
        "--exclude=*.log",
        "--exclude=*.tar.gz",
        "--exclude=.venv-launcher/",
        "--exclude=.venv/",
    ]
    rsync_cmd = (
        f"rsync -azP --delete {' '.join(excludes)} "
        f"-e 'ssh -o StrictHostKeyChecking=no -i {SSH_KEY}' "
        f"{REPO_DIR}/ {SSH_USER}@{ip}:{REMOTE_DIR}/"
    )
    r = run(rsync_cmd, timeout=120)
    if r.returncode != 0:
        console.print(f"[red]rsync failed: {r.stderr}[/red]")
        return False
    console.print("[green]Repo synced![/green]")

    # Check if venv exists
    r = ssh_cmd(ip, "test -d /opt/training-venv/bin && echo yes || echo no")
    venv_exists = "yes" in (r.stdout or "")

    if not venv_exists:
        console.print("[yellow]Venv not found — running setup.sh on VM...[/yellow]")
        ssh_cmd(ip, f"sudo bash /opt/setup.sh", timeout=600)
    else:
        console.print("[green]Venv already exists — skipping setup[/green]")

    ssh_cmd(ip, f"chmod +x {REMOTE_DIR}/training/cloud_training_framework/scripts/*.py {REMOTE_DIR}/training/cloud_training_framework/scripts/*.sh")

    # Check if pipeline is already running
    r = ssh_cmd(ip, "tmux has-session -t train 2>/dev/null && echo running || echo stopped")
    tmux_running = "running" in (r.stdout or "")

    if tmux_running:
        console.print("[green]Training pipeline already running — skipping launch[/green]")
    else:
        console.print("[cyan]Starting training pipeline...[/cyan]")
        ssh_cmd(ip, f"sudo bash /opt/run-pipeline.sh", timeout=30)
        console.print("[green]Pipeline started![/green]")

    return True


# --- VM actions ---

def do_create():
    preflight_check()
    
    if not PROJECT_ID:
        console.print("[red]PROJECT_ID not set. export PROJECT_ID=<id>[/red]")
        sys.exit(1)
    if not PLATFORM or not PRESET:
        console.print("[yellow]PLATFORM/PRESET not set. Listing options...[/yellow]")
        r = run("nebius compute platform list --format json")
        try:
            for p in json.loads(r.stdout).get("items", []):
                console.print(f"  {p['name']} (id: {p['id']})")
        except Exception:
            console.print("  (could not list)")
        r = run("nebius compute preset list --format json")
        try:
            for p in json.loads(r.stdout).get("items", []):
                console.print(f"  {p['name']} — {p.get('description', '')}")
        except Exception:
            console.print("  (could not list)")
        sys.exit(1)
    if not SUBNET_ID:
        console.print("[yellow]SUBNET_ID not set. Listing subnets...[/yellow]")
        r = run("nebius vpc subnet list --format json")
        try:
            for s in json.loads(r.stdout).get("items", []):
                console.print(f"  {s['name']} (id: {s['id']})")
        except Exception:
            console.print("  (could not list)")
        sys.exit(1)
    if not IMAGE_ID:
        console.print("[red]IMAGE_ID not set. Find a CUDA image:[/red]")
        r = run("nebius compute image list --format json")
        try:
            for img in json.loads(r.stdout).get("items", []):
                console.print(f"  {img['name']} (id: {img['id']})")
        except Exception:
            console.print("  (could not list)")
        sys.exit(1)

    if not CLOUD_INIT_FILE.exists():
        console.print(f"[red]cloud-init.yaml not found at {CLOUD_INIT_FILE}[/red]")
        sys.exit(1)

    existing = get_vm_status()
    if existing != "not_found":
        console.print(f"[yellow]VM '{VM_NAME}' already exists (status: {existing})[/yellow]")
        resp = input("Delete and recreate? [y/N] ").strip().lower()
        if resp != "y":
            console.print("[green]Keeping existing VM.[/green]")
            return
        do_delete()

    console.print(f"[cyan]Creating preemptible VM '{VM_NAME}'...[/cyan]")
    console.print(f"  Platform: {PLATFORM}")
    console.print(f"  Preset:   {PRESET}")
    console.print(f"  Disk:     {DISK_SIZE_GIB}GiB {DISK_TYPE}")
    console.print(f"  Image ID: {IMAGE_ID}")
    console.print(f"  Subnet:   {SUBNET_ID}")

    cloud_init = CLOUD_INIT_FILE.read_text()
    try:
        pub_key = Path(os.path.expanduser(SSH_PUB_KEY)).read_text().strip()
        cloud_init = cloud_init.replace("__SSH_PUB_KEY__", pub_key)
    except Exception as e:
        console.print(f"[yellow]Warning: Could not read SSH pub key from {SSH_PUB_KEY}: {e}[/yellow]")
    net_json = json.dumps([{
        "name": "eth0",
        "subnet_id": SUBNET_ID,
        "ip_address": {},
        "public_ip_address": {},
    }])

    cmd_args = [
        "nebius", "compute", "instance", "create",
        "--name", VM_NAME,
        "--parent-id", PROJECT_ID,
        "--resources-platform", PLATFORM,
        "--resources-preset", PRESET,
        "--boot-disk-managed-disk-name", f"{VM_NAME}-boot-disk",
        "--boot-disk-managed-disk-size-gibibytes", DISK_SIZE_GIB,
        "--boot-disk-managed-disk-type", DISK_TYPE,
        "--boot-disk-managed-disk-source-image-id", IMAGE_ID,
        "--boot-disk-attach-mode", "READ_WRITE",
        "--preemptible-on-preemption", "stop",
        "--recovery-policy", "fail",
        "--cloud-init-user-data", cloud_init,
        "--network-interfaces", net_json,
    ]
    try:
        r = subprocess.run(cmd_args, capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            console.print(f"[red]VM creation failed:[/red]")
            if r.stderr:
                console.print(r.stderr[:2000])
            if r.stdout:
                console.print(r.stdout[:2000])
            return False
        else:
            console.print("[green]VM created![/green]")
            return True
    except subprocess.TimeoutExpired:
        console.print("[red]VM creation timed out[/red]")
        return False


def do_create_and_monitor():
    if not do_create():
        sys.exit(1)
    ip = wait_for_ip()
    if not ip:
        sys.exit(1)
    if not wait_for_ssh(ip):
        sys.exit(1)
    preseed_vm(ip)
    run_tui(ip)


def do_delete():
    console.print(f"[cyan]Deleting VM '{VM_NAME}'...[/cyan]")
    vm_id = get_vm_id()
    if not vm_id:
        console.print("[red]VM not found.[/red]")
        return
    run(f"nebius compute instance delete {vm_id}", timeout=120)
    console.print("[green]VM deleted.[/green]")


def do_stop():
    console.print(f"[cyan]Stopping VM '{VM_NAME}'...[/cyan]")
    vm_id = get_vm_id()
    if not vm_id:
        console.print("[red]VM not found.[/red]")
        return
    run(f"nebius compute instance stop {vm_id}", timeout=60)
    console.print("[green]VM stopped.[/green]")


def do_start():
    console.print(f"[cyan]Starting VM '{VM_NAME}'...[/cyan]")
    vm_id = get_vm_id()
    if not vm_id:
        console.print("[red]VM not found.[/red]")
        return
    run(f"nebius compute instance start {vm_id}", timeout=60)
    console.print("[green]VM starting. Pipeline will auto-resume via cloud-init.[/green]")


def do_ssh():
    ip = SSH_HOST or get_vm_ip()
    if not ip:
        console.print("[red]No VM found or no public IP.[/red]")
        sys.exit(1)
    console.print(f"[cyan]SSH to {SSH_USER}@{ip}[/cyan]")
    os.execvp("ssh", ["ssh", "-o", "StrictHostKeyChecking=no", "-i", SSH_KEY, f"{SSH_USER}@{ip}"])


def do_status():
    status = get_vm_status()
    ip = get_vm_ip()
    console.print(f"VM:        {VM_NAME}")
    console.print(f"Status:    {status}")
    console.print(f"Public IP: {ip or 'none'}")
    if ip and status == "running":
        console.print("[cyan]Checking pipeline state on VM...[/cyan]")
        r = ssh_cmd(ip, f"python3 {REMOTE_DIR}/training/cloud_training_framework/scripts/pipeline_state.py show 2>/dev/null || echo '(not started)'")
        if r.stdout:
            console.print(r.stdout.strip())


# --- TUI Dashboard ---

def fetch_vm_state(ip):
    """Fetch all state from VM in a single SSH call."""
    r = ssh_cmd(ip, """
        echo '===STATE==='
        cat /opt/training-repo/training/cloud_training_framework/pipeline_state.json 2>/dev/null || echo '{}'
        echo ''
        echo '===GPU==='
        nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu --format=csv,noheader,nounits 2>/dev/null || echo 'none'
        echo '===TMUX==='
        tmux has-session -t train 2>/dev/null && echo running || echo stopped
        echo '===LOG==='
        for f in /tmp/train_*.log /tmp/train.log; do
            if [ -f "$f" ]; then tail -12 "$f"; break; fi
        done
        echo '===UPTIME==='
        uptime 2>/dev/null || echo 'unknown'
        echo '===DISK==='
        df -h /opt 2>/dev/null | tail -1 || echo 'unknown'
        echo '===DONE==='
    """, timeout=15)

    sections = {}
    current = None
    for line in (r.stdout or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("===") and stripped.endswith("===") and len(stripped) > 6:
            current = stripped.strip("= ")
            sections[current] = []
        elif current:
            sections[current].append(line)

    return sections


def build_dashboard(data, ip):
    """Build the rich TUI layout from VM state."""
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="body"),
        Layout(name="footer", size=14),
    )
    layout["body"].split_row(
        Layout(name="left"),
        Layout(name="right"),
    )

    header = Panel(
        Align.center(
            Text("ML Training Pipeline", style="bold cyan", justify="center")
            + Text(f"  |  {SSH_USER}@{ip}  |  {time.strftime('%H:%M:%S')}", style="dim", justify="center")
        ),
        border_style="cyan",
    )
    layout["header"].update(header)

    state_lines = data.get("STATE", [])
    state_json = "\n".join(state_lines).strip()
    try:
        state = json.loads(state_json) if state_json else {}
    except json.JSONDecodeError:
        state = {}

    table = Table(title="Pipeline State", box=box.ROUNDED, border_style="blue", expand=True, show_lines=False)
    table.add_column("Model", style="bold", ratio=3)
    table.add_column("Status", justify="center", ratio=2)
    table.add_column("Progress", ratio=2)

    total_done = 0
    total_tasks = len(state) if state else 1
    for task_key, status in state.items():
        icon = MODEL_ICONS.get(status, "?")
        if status == "done":
            total_done += 1
            bar = "[green]████████████[/green]"
        elif status == "running":
            bar = "[yellow]█████░░░░░░░░[/yellow]"
        else:
            bar = "[dim]░░░░░░░░░░░░░░[/dim]"
        table.add_row(f"{icon} {task_key}", str(status), bar)

    if total_tasks > 0:
        progress_pct = total_done * 100 // total_tasks
        table.add_row("", "", "")
        table.add_row("[bold]Overall[/bold]", f"{total_done}/{total_tasks}", f"[bold green]{progress_pct}%[/bold green]")

    layout["left"].update(table)

    gpu_lines = data.get("GPU", [])
    gpu_text = ""
    if gpu_lines and gpu_lines[0] != "none":
        parts = [p.strip() for p in gpu_lines[0].split(",")]
        if len(parts) >= 4:
            util, mem_used, mem_total, temp = parts[:4]
            gpu_text = (
                f"[bold]GPU Utilization:[/bold]  {util}%\n"
                f"[bold]GPU Memory:[/bold]      {mem_used} / {mem_total} MiB\n"
                f"[bold]GPU Temp:[/bold]        {temp}°C\n"
            )
        else:
            gpu_text = "GPU data unavailable\n"
    else:
        gpu_text = "[dim]GPU not available[/dim]\n"

    tmux_lines = data.get("TMUX", [])
    tmux_status = tmux_lines[0] if tmux_lines else "unknown"
    tmux_text = f"[bold]tmux [train]:[/bold] {'🟢 running' if tmux_status == 'running' else '🔴 stopped'}\n"

    uptime_lines = data.get("UPTIME", [])
    uptime_text = f"[bold]Uptime:[/bold] {uptime_lines[0] if uptime_lines else 'unknown'}\n"

    disk_lines = data.get("DISK", [])
    disk_text = f"[bold]Disk /opt:[/bold] {disk_lines[0] if disk_lines else 'unknown'}\n"

    sys_content = f"{gpu_text}\n{tmux_text}\n{uptime_text}\n{disk_text}"
    sys_panel = Panel(sys_content, title="System", border_style="green", box=box.ROUNDED)
    layout["right"].update(sys_panel)

    log_lines = data.get("LOG", [])
    log_text = "\n".join(log_lines[-10:]) if log_lines else "[dim](no training logs yet)[/dim]"
    log_panel = Panel(log_text, title="Recent Log Output", border_style="yellow", box=box.ROUNDED)
    layout["footer"].update(log_panel)

    return layout


def build_dashboard_with_banner(data, ip, banner_msg):
    layout = build_dashboard(data, ip)
    header = Panel(
        Align.center(
            Text(banner_msg, style="bold yellow", justify="center")
            + Text(f"  |  {SSH_USER}@{ip}  |  {time.strftime('%H:%M:%S')}", style="dim", justify="center")
        ),
        border_style="yellow",
    )
    layout["header"].update(header)
    return layout


def download_models(ip):
    """Rsync trained models from VM to local repo."""
    local_models = FRAMEWORK_DIR / "models"
    local_models.mkdir(exist_ok=True)
    console.print("[cyan]Downloading trained models from VM...[/cyan]")
    r = run(
        f"rsync -azP --progress "
        f"-e 'ssh -o StrictHostKeyChecking=no -i {SSH_KEY}' "
        f"{SSH_USER}@{ip}:{REMOTE_DIR}/training/cloud_training_framework/models/ {local_models}/",
        timeout=300,
    )
    if r.returncode == 0:
        run(
            f"rsync -azP "
            f"-e 'ssh -o StrictHostKeyChecking=no -i {SSH_KEY}' "
            f"{SSH_USER}@{ip}:{REMOTE_DIR}/training/cloud_training_framework/reports/ {FRAMEWORK_DIR / 'reports'}/ 2>/dev/null",
            timeout=60,
        )
        console.print(f"[green]Models downloaded to {local_models}/[/green]")
        for root, dirs, files in os.walk(local_models):
            for f in files:
                p = Path(root) / f
                size_mb = p.stat().st_size / (1024 * 1024)
                console.print(f"  {p.relative_to(local_models)} ({size_mb:.1f} MB)")
        return True
    else:
        console.print(f"[red]Model download failed: {r.stderr}[/red]")
        return False


def check_all_done(ip):
    """Check if all models are done training."""
    data = fetch_vm_state(ip)
    state_lines = data.get("STATE", [])
    state_json = "\n".join(state_lines).strip()
    try:
        state = json.loads(state_json) if state_json else {}
    except json.JSONDecodeError:
        return False
    return all(v == "done" for v in state.values()) if state else False


def run_tui(ip):
    """Run the live TUI dashboard with auto-resume and auto-download."""
    console.print(f"[cyan]Starting TUI dashboard (Ctrl+C to exit, VM keeps running)...[/cyan]")
    console.print(f"[dim]Connect manually: ssh -i {SSH_KEY} {SSH_USER}@{ip}[/dim]")
    console.print(f"[dim]Auto-resume: if VM is preempted, will wait for reboot and re-seed[/dim]")
    console.print(f"[dim]Auto-download: models pulled locally when all complete[/dim]\n")

    models_downloaded = False
    vm_was_down = False
    current_ip = ip

    try:
        with Live(build_dashboard({}, current_ip), console=console, refresh_per_second=0.6, screen=True) as live:
            while True:
                if _sigterm_flag:
                    live.stop()
                    console.print("\n[yellow]SIGTERM received — exiting launcher. VM keeps running.[/yellow]")
                    return

                vm_status = get_vm_status()

                if vm_status in ("stopped", "stopping", "not_found"):
                    if not vm_was_down:
                        vm_was_down = True
                        models_downloaded = False
                        live.update(build_dashboard_with_banner(
                            {}, current_ip,
                            f"⚠ VM {vm_status.upper()} — waiting for reboot... (auto-resumes when back up)"
                        ))
                    if vm_status == "stopped":
                        vm_id = get_vm_id()
                        if vm_id:
                            run(f"nebius compute instance start {vm_id}", timeout=60)
                            live.update(build_dashboard_with_banner(
                                {}, current_ip,
                                "🚀 VM was preempted. Re-start command sent to Nebius!"
                            ))
                    time.sleep(15)
                    continue

                if vm_was_down and vm_status == "running":
                    live.update(build_dashboard_with_banner(
                        {}, current_ip,
                        "🔄 VM back up — waiting for SSH..."
                    ))
                    new_ip = wait_for_ip(timeout=60)
                    if new_ip:
                        current_ip = new_ip
                        if wait_for_ssh(current_ip, timeout=120):
                            live.update(build_dashboard_with_banner(
                                {}, current_ip,
                                "🔄 SSH up — re-seeding repo..."
                            ))
                            preseed_vm(current_ip)
                            vm_was_down = False
                            live.update(build_dashboard_with_banner(
                                {}, current_ip,
                                "✅ Pipeline resumed!"
                            ))
                            time.sleep(3)
                    continue

                try:
                    data = fetch_vm_state(current_ip)
                    live.update(build_dashboard(data, current_ip))

                    if not models_downloaded and check_all_done(current_ip):
                        models_downloaded = True
                        live.update(build_dashboard_with_banner(
                            data, current_ip,
                            "🎉 All models complete! Downloading models..."
                        ))
                        download_models(current_ip)
                        live.update(build_dashboard_with_banner(
                            data, current_ip,
                            "✅ Models downloaded! Check ./models/ directory. Ctrl+C to exit."
                        ))
                except Exception:
                    live.update(build_dashboard({}, current_ip))

                time.sleep(5)
    except KeyboardInterrupt:
        console.print("\n[yellow]Exited monitor. VM is still running.[/yellow]")
        console.print(f"[dim]Reconnect: python3 launch.py --monitor[/dim]")
        console.print(f"[dim]SSH:       ssh -i {SSH_KEY} {SSH_USER}@{current_ip}[/dim]")
        if not models_downloaded:
            console.print(f"[dim]Download models: python3 launch.py --download[/dim]")


# --- Main ---

def main():
    check_deps()

    parser = argparse.ArgumentParser(description="Cloud GPU Training Launcher")
    parser.add_argument("--monitor", "-m", action="store_true", help="Monitor existing VM")
    parser.add_argument("--status", "-s", action="store_true", help="Show VM status")
    parser.add_argument("--ssh", action="store_true", help="SSH into VM")
    parser.add_argument("--stop", action="store_true", help="Stop VM")
    parser.add_argument("--start", action="store_true", help="Start VM")
    parser.add_argument("--delete", "-d", action="store_true", help="Delete VM")
    parser.add_argument("--seed", action="store_true", help="Pre-seed repo to VM only")
    parser.add_argument("--download", action="store_true", help="Download trained models from VM")
    parser.add_argument("--create", "-c", action="store_true", help="Create VM only")
    args = parser.parse_args()

    if args.status:
        do_status()
    elif args.ssh:
        do_ssh()
    elif args.stop:
        do_stop()
    elif args.start:
        do_start()
    elif args.delete:
        do_delete()
    elif args.seed:
        ip = SSH_HOST or get_vm_ip()
        if not ip:
            console.print("[red]No VM found.[/red]")
            sys.exit(1)
        preseed_vm(ip)
    elif args.download:
        ip = SSH_HOST or get_vm_ip()
        if not ip:
            console.print("[red]No VM found or no public IP.[/red]")
            sys.exit(1)
        download_models(ip)
    elif args.create:
        do_create()
    elif args.monitor:
        ip = SSH_HOST or get_vm_ip()
        if not ip:
            console.print("[red]No VM found or no public IP.[/red]")
            sys.exit(1)
        run_tui(ip)
    else:
        do_create_and_monitor()


if __name__ == "__main__":
    main()
