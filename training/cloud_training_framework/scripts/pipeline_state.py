#!/usr/bin/env python3
"""Pipeline state tracker for preemptible VM resume.

Tracks which models have completed training in pipeline_state.json.
Called by run_pipeline.py to check/mark model status.

Usage:
  python3 scripts/pipeline_state.py check <model>   # exit 0 if done, 1 if not
  python3 scripts/pipeline_state.py mark <model> <status>  # set status
  python3 scripts/pipeline_state.py show             # print state
  python3 scripts/pipeline_state.py reset            # reset all to pending
"""
import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

STATE_FILE = Path(__file__).parent.parent / "pipeline_state.json"
MODELS_YAML = Path(__file__).parent / "models.yaml"


def get_model_names():
    """Get model names from models.yaml."""
    if not MODELS_YAML.exists() or yaml is None:
        return []
    with open(MODELS_YAML) as f:
        config = yaml.safe_load(f)
    return [m["name"] for m in config.get("models", [])]


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def main():
    if len(sys.argv) < 2:
        print("Usage: pipeline_state.py [check|mark|show|reset] ...")
        sys.exit(2)

    cmd = sys.argv[1]

    if cmd == "check":
        model = sys.argv[2]
        state = load_state()
        sys.exit(0 if state.get(model) == "done" else 1)

    elif cmd == "mark":
        model = sys.argv[2]
        status = sys.argv[3]  # "running", "done", "pending"
        state = load_state()
        state[model] = status
        save_state(state)
        print(f"[pipeline] {model} -> {status}")

    elif cmd == "show":
        state = load_state()
        print(json.dumps(state, indent=2))

    elif cmd == "reset":
        names = get_model_names()
        if names:
            save_state({n: "pending" for n in names})
        else:
            save_state({})
        print("[pipeline] Reset all models to pending")

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(2)


if __name__ == "__main__":
    main()
