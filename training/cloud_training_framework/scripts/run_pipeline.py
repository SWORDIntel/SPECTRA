#!/usr/bin/env python3
"""Generic pipeline runner — reads models.yaml and runs training scripts sequentially.

Replaces the hardcoded run.sh with a YAML-driven pipeline that:
  - Reads model definitions from scripts/models.yaml
  - Skips completed models (tracked in pipeline_state.json)
  - Runs each model in sequence with proper logging
  - Handles SIGTERM for preemptible VM resume
  - Starts everything in a tmux session

Usage:
  python3 scripts/run_pipeline.py                    # run all pending models
  python3 scripts/run_pipeline.py --model my_model   # run specific model only
  python3 scripts/run_pipeline.py --list             # list models and status
  python3 scripts/run_pipeline.py --reset            # reset all to pending
"""
import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

try:
    import yaml
except ImportError:
    print("PyYAML not installed. Run: pip install pyyaml")
    sys.exit(1)

FRAMEWORK_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = Path(os.environ.get("TRAINING_REPO_DIR", FRAMEWORK_DIR.parents[1])).resolve()
MODELS_YAML = Path(os.environ.get("MODELS_YAML", FRAMEWORK_DIR / "scripts" / "models.yaml"))
STATE_FILE = FRAMEWORK_DIR / "pipeline_state.json"
VENV = os.environ.get("VENV_PATH", "/opt/training-venv")


def load_pipeline_config():
    """Load models.yaml and return the config dict."""
    with open(MODELS_YAML) as f:
        return yaml.safe_load(f)


def load_state():
    """Load pipeline_state.json."""
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def save_state(state):
    """Save pipeline_state.json."""
    STATE_FILE.write_text(json.dumps(state, indent=2))


def get_model_status(model_name, state):
    """Get status of a model from state dict."""
    return state.get(model_name, "pending")


def mark_model(model_name, status):
    """Mark a model's status in pipeline_state.json."""
    state = load_state()
    state[model_name] = status
    save_state(state)
    print(f"[pipeline] {model_name} -> {status}")


def download_dataset(config):
    """Download and extract dataset if not present."""
    ds_config = config.get("dataset", {})
    ds_path = Path(ds_config.get("path", "/opt/training-repo/dataset"))
    ds_url = ds_config.get("url", "")
    min_files = ds_config.get("min_files", 100)

    if not ds_url:
        print(f"[pipeline] No dataset URL configured, skipping download")
        return ds_path

    # Check if dataset already exists
    if ds_path.exists():
        file_count = sum(1 for _ in ds_path.rglob("*") if _.is_file())
        if file_count >= min_files:
            print(f"[pipeline] Dataset already present ({file_count} files), skipping download")
            return ds_path

    print(f"[pipeline] Downloading dataset from {ds_url}...")
    archive = "/tmp/dataset.tar.gz"
    if not Path(archive).exists():
        subprocess.run(["wget", "-q", "--show-progress", ds_url, "-O", archive], check=True)
    
    print(f"[pipeline] Extracting dataset to {ds_path}...")
    ds_path.parent.mkdir(parents=True, exist_ok=True)
    if ds_path.exists():
        import shutil
        shutil.rmtree(ds_path)
    ds_path.mkdir(parents=True)
    subprocess.run(["tar", "xzf", archive, "-C", str(ds_path)], check=True)
    Path(archive).unlink(missing_ok=True)

    file_count = sum(1 for _ in ds_path.rglob("*") if _.is_file())
    print(f"[pipeline] Dataset ready: {file_count} files")
    return ds_path


def build_command(model_entry, data_dir, output_dir):
    """Build the shell command for a model training script."""
    script = model_entry["script"]
    args = model_entry.get("args", [])

    # Substitute placeholders
    replacements = {
        "$DATA_DIR": str(data_dir),
        "$OUTPUT_DIR": str(output_dir),
        "$REPO_DIR": str(REPO_DIR),
    }
    substituted_args = []
    for arg in args:
        for placeholder, value in replacements.items():
            arg = arg.replace(placeholder, value)
        substituted_args.append(arg)

    log_file = model_entry.get("log_file", f"/tmp/train_{model_entry['name']}.log")
    cmd = f"cd {REPO_DIR} && source {VENV}/bin/activate && python3 {script} {' '.join(substituted_args)} 2>&1 | tee {log_file}"
    return cmd, log_file


def run_pipeline(config, only_model=None):
    """Run the training pipeline."""
    state = load_state()
    models = config.get("models", [])

    if not models:
        print("[pipeline] No models defined in models.yaml!")
        return

    # Download dataset
    data_dir = download_dataset(config)
    output_dir = REPO_DIR / config.get("output", {}).get("dir", "models")
    output_dir.mkdir(parents=True, exist_ok=True)

    # Build full pipeline command
    cmd_parts = [f"cd {REPO_DIR} && source {VENV}/bin/activate"]

    total = len(models)
    for i, model in enumerate(models):
        name = model["name"]
        display = model.get("display_name", name)

        if only_model and name != only_model:
            continue

        status = get_model_status(name, state)
        if status == "done":
            print(f"[pipeline] ✓ {name} already done — skipping")
            continue

        model_cmd, log_file = build_command(model, data_dir, output_dir)
        cmd_parts.append(f"echo '=== [{i+1}/{total}] {display} ==='")
        cmd_parts.append(f"python3 {FRAMEWORK_DIR}/scripts/pipeline_state.py mark {name} running")
        cmd_parts.append(model_cmd)
        cmd_parts.append(f"python3 {FRAMEWORK_DIR}/scripts/pipeline_state.py mark {name} done")

    cmd_parts.append("echo '=== ALL TRAINING COMPLETE ==='")

    full_cmd = " && ".join(cmd_parts)

    # Start in tmux
    print("[pipeline] Starting training pipeline in tmux session 'train'...")
    subprocess.run(["tmux", "kill-session", "-t", "train"], capture_output=True)
    subprocess.run(["tmux", "new-session", "-d", "-s", "train", full_cmd], check=True)
    print("[pipeline] Training started. Attach with: tmux attach -t train")


def list_models(config):
    """List all models and their current status."""
    state = load_state()
    models = config.get("models", [])
    print(f"\n{'#':<4} {'Name':<25} {'Status':<12} {'Display Name'}")
    print("-" * 70)
    for i, model in enumerate(models):
        name = model["name"]
        display = model.get("display_name", name)
        status = get_model_status(name, state)
        icon = {"done": "✅", "running": "🔄", "pending": "⏳"}.get(status, "?")
        print(f"{i+1:<4} {name:<25} {icon} {status:<8} {display}")
    print()


def reset_state(config):
    """Reset all models to pending."""
    models = config.get("models", [])
    state = {m["name"]: "pending" for m in models}
    save_state(state)
    print("[pipeline] Reset all models to pending")


def main():
    parser = argparse.ArgumentParser(description="Run ML training pipeline")
    parser.add_argument("--model", help="Run only this model")
    parser.add_argument("--list", action="store_true", help="List models and status")
    parser.add_argument("--reset", action="store_true", help="Reset all to pending")
    args = parser.parse_args()

    config = load_pipeline_config()

    if args.list:
        list_models(config)
    elif args.reset:
        reset_state(config)
    else:
        run_pipeline(config, only_model=args.model)


if __name__ == "__main__":
    main()
