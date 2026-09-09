from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import remote_index_benchmark as launcher


def _completed(payload: dict[str, Any], *, returncode: int = 0) -> subprocess.CompletedProcess[str]:
    stdout = launcher.STAGE_MARKER + json.dumps(payload) + "\n"
    return subprocess.CompletedProcess(["ssh"], returncode, stdout, "")


class RemoteIndexBenchmarkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = launcher.BenchmarkConfig(
            target="ubuntu@benchmark.example",
            identity_file=Path("/private/keys/cloud.pem"),
            events=200,
            writers=8,
            lookups=5,
            batch_size=100,
            connect_timeout=7,
            stage_timeout=60,
        )

    def test_build_ssh_command_is_an_argument_list_with_bounded_options(self) -> None:
        command = launcher.build_ssh_command(self.config)

        self.assertIsInstance(command, list)
        self.assertEqual(command[0], "ssh")
        self.assertIn("BatchMode=yes", command)
        self.assertIn("ConnectTimeout=7", command)
        self.assertIn("ConnectionAttempts=1", command)
        self.assertIn("ServerAliveCountMax=2", command)
        self.assertEqual(command[-4:], ["--", "ubuntu@benchmark.example", "python3", "-"])

    def test_target_cannot_be_ssh_option_or_contain_whitespace(self) -> None:
        for target in (
            "-oProxyCommand=bad",
            "ubuntu@host command",
            "ubuntu@host;command",
            "ubuntu:password@host",
        ):
            with self.subTest(target=target), self.assertRaises(ValueError):
                launcher.BenchmarkConfig(target=target).validate()

    def test_generated_remote_stages_are_valid_python(self) -> None:
        compile(launcher._remote_preflight_script(self.config), "<preflight>", "exec")
        benchmark_script = launcher._remote_benchmark_script(self.config)
        compile(benchmark_script, "<benchmark>", "exec")

        self.assertIn('"index",', benchmark_script)
        self.assertIn('"benchmark",', benchmark_script)
        self.assertNotIn("shell=True", benchmark_script)

    def test_generated_benchmark_stage_executes_expected_argv(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            executable = Path(temporary_dir) / "spectra"
            executable.write_text(
                "#!/usr/bin/env python3\n"
                "import json\n"
                "import sys\n"
                "print(json.dumps({'argv': sys.argv[1:], 'ok': True}))\n",
                encoding="utf-8",
            )
            os.chmod(executable, 0o700)
            config = launcher.BenchmarkConfig(
                target="benchmark.example",
                remote_dir=temporary_dir,
                spectra_bin=str(executable),
                events=200,
                writers=8,
                lookups=5,
                batch_size=100,
                stage_timeout=30,
            )

            completed = subprocess.run(
                ["python3", "-"],
                input=launcher._remote_benchmark_script(config),
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            payload = launcher._parse_stage_output(completed.stdout)

        self.assertEqual(completed.returncode, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(
            payload["benchmark"]["argv"],
            [
                "index",
                "benchmark",
                "--events",
                "200",
                "--writers",
                "8",
                "--lookups",
                "5",
                "--batch-size",
                "100",
                "--output",
                "json",
            ],
        )

    def test_dry_run_does_not_execute_and_redacts_identity_path(self) -> None:
        executor = Mock(side_effect=AssertionError("executor must not run"))

        result = launcher.run_remote_benchmark(self.config, dry_run=True, executor=executor)

        self.assertTrue(result["ok"])
        self.assertTrue(result["dry_run"])
        self.assertIn("<redacted-identity-file>", result["ssh_command"])
        self.assertNotIn(str(self.config.identity_file), result["ssh_command"])
        executor.assert_not_called()

    def test_success_runs_preflight_then_benchmark(self) -> None:
        preflight = {
            "ok": True,
            "stage": "preflight",
            "capabilities": {
                "qihse": {"available": True, "operational": True},
                "keystone": {"available": True, "operational": True},
            },
        }
        benchmark = {
            "ok": True,
            "stage": "benchmark",
            "benchmark": {"events": 200, "write_events_per_second": 1234.5},
        }
        executor = Mock(side_effect=[_completed(preflight), _completed(benchmark)])

        result = launcher.run_remote_benchmark(self.config, executor=executor)

        self.assertTrue(result["ok"])
        self.assertEqual(result["preflight"], preflight)
        self.assertEqual(result["benchmark"], benchmark)
        self.assertEqual(executor.call_count, 2)
        for call in executor.call_args_list:
            self.assertIsInstance(call.args[0], list)
            self.assertNotIn("shell", call.kwargs)
            self.assertEqual(call.kwargs["timeout"], 60)

    def test_failed_preflight_prevents_benchmark(self) -> None:
        preflight = {
            "ok": False,
            "stage": "preflight",
            "capabilities": {
                "qihse": {"available": True, "operational": True},
                "keystone": {"available": False, "operational": False},
            },
        }
        executor = Mock(return_value=_completed(preflight))

        result = launcher.run_remote_benchmark(self.config, executor=executor)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "native_capability_preflight_failed")
        executor.assert_called_once()

    def test_malformed_stage_output_is_a_controlled_error(self) -> None:
        executor = Mock(
            return_value=subprocess.CompletedProcess(["ssh"], 0, "ordinary remote output\n", "")
        )

        with self.assertRaisesRegex(launcher.LauncherError, "structured result"):
            launcher.run_remote_benchmark(self.config, executor=executor)

    def test_diagnostics_and_sensitive_keys_are_redacted(self) -> None:
        preflight = {
            "ok": True,
            "stage": "preflight",
            "capabilities": {
                "qihse": {"available": True, "operational": True},
                "keystone": {"available": True, "operational": True},
            },
        }
        benchmark = {
            "ok": False,
            "stage": "benchmark",
            "diagnostic": "api_hash=do-not-print token: also-private",
            "metadata": {"session_token": "third-private"},
        }
        executor = Mock(side_effect=[_completed(preflight), _completed(benchmark)])

        serialized = json.dumps(launcher.run_remote_benchmark(self.config, executor=executor))

        self.assertNotIn("do-not-print", serialized)
        self.assertNotIn("also-private", serialized)
        self.assertNotIn("third-private", serialized)
        self.assertIn("<redacted>", serialized)

    def test_ssh_timeout_is_reported_without_command_or_key_material(self) -> None:
        executor = Mock(side_effect=subprocess.TimeoutExpired(["ssh"], 60))

        with self.assertRaisesRegex(launcher.LauncherError, "bounded timeout") as caught:
            launcher.run_remote_benchmark(self.config, executor=executor)

        self.assertNotIn(str(self.config.identity_file), str(caught.exception))


if __name__ == "__main__":
    unittest.main()
