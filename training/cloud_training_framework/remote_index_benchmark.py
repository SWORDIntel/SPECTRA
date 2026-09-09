#!/usr/bin/env python3
"""Run a bounded SPECTRA index benchmark on an explicit SSH target."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence


RESULT_SCHEMA = "spectra.remote-index-benchmark.v1"
STAGE_MARKER = "SPECTRA_REMOTE_RESULT="
DEFAULT_CONNECT_TIMEOUT = 10
DEFAULT_STAGE_TIMEOUT = 900
MAX_CONNECT_TIMEOUT = 120
MAX_STAGE_TIMEOUT = 86_400
MAX_DIAGNOSTIC_LENGTH = 4_096

Executor = Callable[..., subprocess.CompletedProcess[str]]

_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?hash|api[_-]?key|authorization|password|secret|session|token)\b"
    r"(\s*[:=]\s*)([^\s,;]+)"
)
_PEM_BLOCK = re.compile(
    r"-----BEGIN [^-]+ PRIVATE KEY-----.*?-----END [^-]+ PRIVATE KEY-----",
    re.DOTALL,
)
_SSH_TARGET = re.compile(r"^[A-Za-z0-9_.@:\-\[\]]+$")


class LauncherError(RuntimeError):
    """A controlled remote benchmark launcher failure."""


@dataclass(frozen=True)
class BenchmarkConfig:
    target: str
    identity_file: Path | None = None
    port: int = 22
    remote_dir: str = "/opt/training-repo"
    spectra_bin: str = "spectra"
    events: int = 1_000
    writers: int = 16
    lookups: int = 10
    batch_size: int = 1_000
    connect_timeout: int = DEFAULT_CONNECT_TIMEOUT
    stage_timeout: int = DEFAULT_STAGE_TIMEOUT
    strict_host_key_checking: str = "yes"

    def validate(self) -> None:
        _validate_target(self.target)
        _validate_text("remote directory", self.remote_dir)
        _validate_text("SPECTRA executable", self.spectra_bin)
        _validate_range("port", self.port, 1, 65_535)
        _validate_range("events", self.events, 10, 1_000_000)
        _validate_range("writers", self.writers, 1, 256)
        _validate_range("lookups", self.lookups, 1, 10_000)
        _validate_range("batch size", self.batch_size, 1, 100_000)
        _validate_range("connect timeout", self.connect_timeout, 1, MAX_CONNECT_TIMEOUT)
        _validate_range("stage timeout", self.stage_timeout, 1, MAX_STAGE_TIMEOUT)
        if self.strict_host_key_checking not in {"yes", "accept-new"}:
            raise ValueError("strict host key checking must be 'yes' or 'accept-new'")


def _validate_target(target: str) -> None:
    _validate_text("SSH target", target)
    if target.startswith("-") or not _SSH_TARGET.fullmatch(target):
        raise ValueError("SSH target contains unsupported characters")
    if target.count("@") > 1:
        raise ValueError("SSH target must contain at most one '@'")
    if "@" in target and ":" in target.split("@", 1)[0]:
        raise ValueError("SSH target must not contain inline credentials")


def _validate_text(label: str, value: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty string")
    if "\x00" in value or "\n" in value or "\r" in value:
        raise ValueError(f"{label} contains an invalid control character")


def _validate_range(label: str, value: int, minimum: int, maximum: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{label} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{label} must be between {minimum} and {maximum}")


def build_ssh_command(config: BenchmarkConfig) -> list[str]:
    """Build the exact argv used for each bounded remote Python stage."""
    config.validate()
    command = [
        "ssh",
        "-T",
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={config.connect_timeout}",
        "-o",
        "ConnectionAttempts=1",
        "-o",
        "ServerAliveInterval=15",
        "-o",
        "ServerAliveCountMax=2",
        "-o",
        f"StrictHostKeyChecking={config.strict_host_key_checking}",
        "-p",
        str(config.port),
    ]
    if config.identity_file is not None:
        command.extend(["-i", str(config.identity_file.expanduser())])
    command.extend(["--", config.target, "python3", "-"])
    return command


def public_ssh_command(config: BenchmarkConfig) -> list[str]:
    """Return a log-safe representation of the SSH argv."""
    command = build_ssh_command(config)
    if "-i" in command:
        identity_index = command.index("-i") + 1
        command[identity_index] = "<redacted-identity-file>"
    return command


def _script_config(config: BenchmarkConfig) -> dict[str, Any]:
    return {
        "remote_dir": config.remote_dir,
        "spectra_bin": config.spectra_bin,
        "events": config.events,
        "writers": config.writers,
        "lookups": config.lookups,
        "batch_size": config.batch_size,
        "command_timeout": max(1, config.stage_timeout - 5),
    }


def _remote_preflight_script(config: BenchmarkConfig) -> str:
    encoded = repr(json.dumps(_script_config(config), separators=(",", ":")))
    return f"""\
import json
import os
import shutil
import subprocess
import sys

CONFIG = json.loads({encoded})
MARKER = {STAGE_MARKER!r}
PROBE = r'''
import json

result = {{"qihse": {{"available": False, "operational": False}},
          "keystone": {{"available": False, "operational": False}}}}
try:
    from tgarchive.search.qihse_bindings import (
        QihseSearchEngine,
        get_qihse_version,
        qihse_available,
    )
    available = bool(qihse_available())
    if available:
        QihseSearchEngine(array_size=16)
    result["qihse"] = {{
        "available": available,
        "operational": available,
        "version": get_qihse_version(),
    }}
except BaseException as error:
    result["qihse"]["error"] = type(error).__name__

try:
    from tgarchive.search.keystone_bindings import (
        KEYSTONE_WORKLOAD_IDS,
        KeystoneSearchEngine,
        get_version as get_keystone_version,
        keystone_available,
    )
    available = bool(keystone_available())
    found = False
    if available:
        engine = KeystoneSearchEngine(KEYSTONE_WORKLOAD_IDS)
        found = engine.search([1, 3, 5], 3) == 1
    result["keystone"] = {{
        "available": available,
        "operational": available and found,
        "version": get_keystone_version(),
    }}
except BaseException as error:
    result["keystone"]["error"] = type(error).__name__

result["ok"] = all(
    capability.get("available") and capability.get("operational")
    for capability in (result["qihse"], result["keystone"])
)
print(json.dumps(result, sort_keys=True))
'''

def emit(payload):
    print(MARKER + json.dumps(payload, sort_keys=True), flush=True)

remote_dir = CONFIG["remote_dir"]
if not os.path.isdir(remote_dir):
    emit({{"ok": False, "stage": "preflight", "error": "remote_directory_unavailable"}})
    raise SystemExit(0)

configured_spectra = CONFIG["spectra_bin"]
if os.path.isabs(configured_spectra):
    spectra_path = configured_spectra
elif os.path.sep in configured_spectra:
    spectra_path = os.path.abspath(os.path.join(remote_dir, configured_spectra))
else:
    spectra_path = shutil.which(configured_spectra)
if not spectra_path or not os.path.isfile(spectra_path) or not os.access(spectra_path, os.X_OK):
    emit({{"ok": False, "stage": "preflight", "error": "spectra_executable_unavailable"}})
    raise SystemExit(0)

environment_python = os.path.join(os.path.dirname(spectra_path), "python")
probe_python = (
    environment_python
    if os.path.isfile(environment_python) and os.access(environment_python, os.X_OK)
    else sys.executable
)
try:
    completed = subprocess.run(
        [probe_python, "-c", PROBE],
        cwd=remote_dir,
        capture_output=True,
        text=True,
        timeout=CONFIG["command_timeout"],
        check=False,
    )
except subprocess.TimeoutExpired:
    emit({{"ok": False, "stage": "preflight", "error": "native_probe_timeout"}})
    raise SystemExit(0)
except OSError as error:
    emit({{"ok": False, "stage": "preflight", "error": "native_probe_start_failed",
          "error_type": type(error).__name__}})
    raise SystemExit(0)

try:
    capabilities = json.loads(completed.stdout.strip())
except (json.JSONDecodeError, TypeError):
    emit({{"ok": False, "stage": "preflight", "error": "invalid_native_probe_output",
          "returncode": completed.returncode}})
    raise SystemExit(0)

ok = completed.returncode == 0 and capabilities.get("ok") is True
emit({{"ok": ok, "stage": "preflight", "returncode": completed.returncode,
      "capabilities": capabilities}})
"""


def _remote_benchmark_script(config: BenchmarkConfig) -> str:
    encoded = repr(json.dumps(_script_config(config), separators=(",", ":")))
    return f"""\
import json
import os
import subprocess

CONFIG = json.loads({encoded})
MARKER = {STAGE_MARKER!r}

def emit(payload):
    print(MARKER + json.dumps(payload, sort_keys=True), flush=True)

def parse_json_output(value):
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else None
    except (json.JSONDecodeError, TypeError):
        decoder = json.JSONDecoder()
        candidate = None
        for position, character in enumerate(value):
            if character != "{{":
                continue
            try:
                parsed, _ = decoder.raw_decode(value[position:])
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                candidate = parsed
        return candidate

command = [
    CONFIG["spectra_bin"],
    "index",
    "benchmark",
    "--events", str(CONFIG["events"]),
    "--writers", str(CONFIG["writers"]),
    "--lookups", str(CONFIG["lookups"]),
    "--batch-size", str(CONFIG["batch_size"]),
    "--output", "json",
]
try:
    completed = subprocess.run(
        command,
        cwd=CONFIG["remote_dir"],
        capture_output=True,
        text=True,
        timeout=CONFIG["command_timeout"],
        check=False,
    )
except subprocess.TimeoutExpired:
    emit({{"ok": False, "stage": "benchmark", "error": "benchmark_timeout"}})
    raise SystemExit(0)
except OSError as error:
    emit({{"ok": False, "stage": "benchmark", "error": "benchmark_start_failed",
          "error_type": type(error).__name__}})
    raise SystemExit(0)

benchmark = parse_json_output(completed.stdout)
ok = completed.returncode == 0 and benchmark is not None
payload = {{"ok": ok, "stage": "benchmark", "returncode": completed.returncode}}
if benchmark is not None:
    payload["benchmark"] = benchmark
else:
    payload["error"] = "invalid_benchmark_output"
if completed.stderr:
    payload["diagnostic"] = completed.stderr[-{MAX_DIAGNOSTIC_LENGTH}:]
emit(payload)
"""


def _redact_text(value: str) -> str:
    value = _PEM_BLOCK.sub("<redacted-private-key>", value)
    return _SENSITIVE_ASSIGNMENT.sub(
        lambda match: f"{match.group(1)}{match.group(2)}<redacted>",
        value,
    )


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "<redacted>" if _is_sensitive_key(str(key)) else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        return _redact_text(value)[:MAX_DIAGNOSTIC_LENGTH]
    return value


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(
        marker in normalized
        for marker in ("api_key", "api_hash", "authorization", "password", "secret", "session", "token")
    )


def _parse_stage_output(stdout: str) -> dict[str, Any]:
    for line in reversed(stdout.splitlines()):
        if not line.startswith(STAGE_MARKER):
            continue
        try:
            payload = json.loads(line[len(STAGE_MARKER) :])
        except json.JSONDecodeError as error:
            raise LauncherError("remote stage returned malformed JSON") from error
        if not isinstance(payload, dict):
            raise LauncherError("remote stage returned a non-object JSON result")
        return payload
    raise LauncherError("remote stage did not return a structured result")


def _run_stage(
    config: BenchmarkConfig,
    script: str,
    *,
    executor: Executor,
) -> tuple[dict[str, Any], float]:
    started = time.monotonic()
    try:
        completed = executor(
            build_ssh_command(config),
            input=script,
            capture_output=True,
            text=True,
            timeout=config.stage_timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise LauncherError("SSH stage exceeded its bounded timeout") from error
    except OSError as error:
        raise LauncherError(f"unable to start SSH: {type(error).__name__}") from error
    elapsed = time.monotonic() - started
    if completed.returncode != 0:
        diagnostic = _redact_text(completed.stderr or "")
        suffix = f": {diagnostic}" if diagnostic else ""
        raise LauncherError(f"SSH stage failed with exit code {completed.returncode}{suffix}")
    return _parse_stage_output(completed.stdout), elapsed


def run_remote_benchmark(
    config: BenchmarkConfig,
    *,
    dry_run: bool = False,
    executor: Executor = subprocess.run,
) -> dict[str, Any]:
    """Preflight native libraries and run the benchmark when they are usable."""
    config.validate()
    base: dict[str, Any] = {
        "schema": RESULT_SCHEMA,
        "target": config.target,
        "dry_run": dry_run,
        "parameters": {
            "events": config.events,
            "writers": config.writers,
            "lookups": config.lookups,
            "batch_size": config.batch_size,
            "connect_timeout_seconds": config.connect_timeout,
            "stage_timeout_seconds": config.stage_timeout,
        },
    }
    if dry_run:
        return {
            **base,
            "ok": True,
            "ssh_command": public_ssh_command(config),
            "stages": ["native_capability_preflight", "index_benchmark"],
        }

    preflight, preflight_seconds = _run_stage(
        config,
        _remote_preflight_script(config),
        executor=executor,
    )
    base["preflight"] = preflight
    base["timings_seconds"] = {"preflight": round(preflight_seconds, 6)}
    if preflight.get("ok") is not True:
        return _redact({**base, "ok": False, "error": "native_capability_preflight_failed"})

    benchmark, benchmark_seconds = _run_stage(
        config,
        _remote_benchmark_script(config),
        executor=executor,
    )
    base["timings_seconds"]["benchmark"] = round(benchmark_seconds, 6)
    return _redact({
        **base,
        "ok": benchmark.get("ok") is True,
        "benchmark": benchmark,
    })


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a bounded SPECTRA index benchmark on an explicit SSH target."
    )
    parser.add_argument("--target", required=True, help="Explicit SSH destination, such as ubuntu@host.")
    parser.add_argument("--identity-file", type=Path, help="SSH private key path; never emitted in output.")
    parser.add_argument("--port", type=int, default=22)
    parser.add_argument("--remote-dir", default="/opt/training-repo")
    parser.add_argument("--spectra-bin", default="spectra")
    parser.add_argument("--events", type=int, default=1_000)
    parser.add_argument("--writers", type=int, default=16)
    parser.add_argument("--lookups", type=int, default=10)
    parser.add_argument("--batch-size", type=int, default=1_000)
    parser.add_argument("--connect-timeout", type=int, default=DEFAULT_CONNECT_TIMEOUT)
    parser.add_argument("--stage-timeout", type=int, default=DEFAULT_STAGE_TIMEOUT)
    parser.add_argument(
        "--strict-host-key-checking",
        choices=("yes", "accept-new"),
        default="yes",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser


def _config_from_args(arguments: argparse.Namespace) -> BenchmarkConfig:
    return BenchmarkConfig(
        target=arguments.target,
        identity_file=arguments.identity_file,
        port=arguments.port,
        remote_dir=arguments.remote_dir,
        spectra_bin=arguments.spectra_bin,
        events=arguments.events,
        writers=arguments.writers,
        lookups=arguments.lookups,
        batch_size=arguments.batch_size,
        connect_timeout=arguments.connect_timeout,
        stage_timeout=arguments.stage_timeout,
        strict_host_key_checking=arguments.strict_host_key_checking,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    arguments = parser.parse_args(argv)
    try:
        result = run_remote_benchmark(_config_from_args(arguments), dry_run=arguments.dry_run)
    except (LauncherError, ValueError) as error:
        result = {
            "schema": RESULT_SCHEMA,
            "ok": False,
            "error": type(error).__name__,
            "message": _redact_text(str(error)),
        }
    print(json.dumps(result, sort_keys=True))
    return 0 if result.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
