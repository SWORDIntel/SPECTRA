"""
Tests for Step 7 (Config Fields), Step 8 (systemd Service), and Step 9 (MSNET Key Generation).
"""

import configparser
import os
import stat
import tempfile
import unittest
from pathlib import Path
from click.testing import CliRunner

from tgarchive.core.config_models import Config, DEFAULT_CFG
from tgarchive.cli.app import cli


class TestStep7ConfigFields(unittest.TestCase):
    """Verify Step 7: Config fields and properties."""

    def test_default_cfg_fields(self):
        """Verify DEFAULT_CFG has all requested resp, msnet, and swarm fields."""
        # resp
        self.assertIn("resp", DEFAULT_CFG)
        self.assertEqual(DEFAULT_CFG["resp"]["port"], 6379)
        self.assertIsInstance(DEFAULT_CFG["resp"]["port"], int)
        self.assertEqual(DEFAULT_CFG["resp"]["bind_address"], "127.0.0.1")
        self.assertIsInstance(DEFAULT_CFG["resp"]["bind_address"], str)
        self.assertEqual(DEFAULT_CFG["resp"]["lan_cidr"], "192.168.1.0/24")
        self.assertIsInstance(DEFAULT_CFG["resp"]["lan_cidr"], str)
        self.assertEqual(DEFAULT_CFG["resp"]["auto_start"], True)
        self.assertIsInstance(DEFAULT_CFG["resp"]["auto_start"], bool)
        self.assertEqual(DEFAULT_CFG["resp"]["max_clients"], 64)
        self.assertIsInstance(DEFAULT_CFG["resp"]["max_clients"], int)

        # msnet
        self.assertIn("msnet", DEFAULT_CFG)
        self.assertEqual(DEFAULT_CFG["msnet"]["port"], 8899)
        self.assertIsInstance(DEFAULT_CFG["msnet"]["port"], int)
        self.assertEqual(DEFAULT_CFG["msnet"]["cluster_name"], "SPECTRA")
        self.assertIsInstance(DEFAULT_CFG["msnet"]["cluster_name"], str)
        self.assertEqual(DEFAULT_CFG["msnet"]["heartbeat_interval"], 30)
        self.assertIsInstance(DEFAULT_CFG["msnet"]["heartbeat_interval"], int)
        self.assertEqual(DEFAULT_CFG["msnet"]["node_timeout"], 90)
        self.assertIsInstance(DEFAULT_CFG["msnet"]["node_timeout"], int)

        # swarm
        self.assertIn("swarm", DEFAULT_CFG)
        self.assertEqual(DEFAULT_CFG["swarm"]["enabled"], True)
        self.assertIsInstance(DEFAULT_CFG["swarm"]["enabled"], bool)
        self.assertEqual(DEFAULT_CFG["swarm"]["node_id"], "")
        self.assertIsInstance(DEFAULT_CFG["swarm"]["node_id"], str)
        self.assertEqual(DEFAULT_CFG["swarm"]["bootstrap_peers"], [])
        self.assertIsInstance(DEFAULT_CFG["swarm"]["bootstrap_peers"], list)

    def test_config_instance_properties(self):
        """Verify Config class properties for resp_conf, msnet_conf, and swarm_conf."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = Path(tmpdir) / "spectra_config.json"
            cfg = Config(path=cfg_path)

            self.assertEqual(cfg.resp_conf["port"], 6379)
            self.assertEqual(cfg.resp_conf["bind_address"], "127.0.0.1")
            self.assertEqual(cfg.resp_conf["lan_cidr"], "192.168.1.0/24")
            self.assertEqual(cfg.resp_conf["auto_start"], True)
            self.assertEqual(cfg.resp_conf["max_clients"], 64)

            self.assertEqual(cfg.msnet_conf["port"], 8899)
            self.assertEqual(cfg.msnet_conf["cluster_name"], "SPECTRA")
            self.assertEqual(cfg.msnet_conf["heartbeat_interval"], 30)
            self.assertEqual(cfg.msnet_conf["node_timeout"], 90)

            self.assertEqual(cfg.swarm_conf["enabled"], True)
            self.assertEqual(cfg.swarm_conf["node_id"], "")
            self.assertEqual(cfg.swarm_conf["bootstrap_peers"], [])


class TestStep8SystemdService(unittest.TestCase):
    """Verify Step 8: systemd user service file."""

    def test_service_file_contents(self):
        """Verify scripts/systemd/qihse-resp.service exists and meets requirements."""
        service_path = Path("/fast/home/john/SPECTRA/scripts/systemd/qihse-resp.service")
        self.assertTrue(service_path.exists(), f"{service_path} does not exist")

        content = service_path.read_text(encoding="utf-8")
        self.assertIn("WorkingDirectory=/fast/home/john/SPECTRA", content)
        self.assertIn("Environment=\"SPECTRA_DB=/fast/home/john/SPECTRA/spectra.db\"", content)
        self.assertIn("Environment=\"KEYSTONE_FORCE_SCALAR=1\"", content)
        self.assertIn("spectra index resp start --foreground", content)
        self.assertIn("Restart=on-failure", content)
        self.assertIn("RestartSec=5", content)
        self.assertIn("WantedBy=default.target", content)

        # Validate with configparser (strict=False to allow multiple Environment= lines in systemd units)
        parser = configparser.ConfigParser(strict=False)
        parser.read_string(content)
        self.assertTrue(parser.has_section("Unit"))
        self.assertTrue(parser.has_section("Service"))
        self.assertTrue(parser.has_section("Install"))
        self.assertEqual(parser.get("Service", "Restart"), "on-failure")
        self.assertEqual(parser.get("Service", "RestartSec"), "5")
        self.assertEqual(parser.get("Install", "WantedBy"), "default.target")


class TestStep9KeyGeneration(unittest.TestCase):
    """Verify Step 9: crypto generate-msnet-keys CLI command."""

    def test_generate_msnet_keys(self):
        """Verify key generation, file permissions (600 for private key), and output."""
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            target_dir = Path(tmpdir) / "msnet_keys"
            result = runner.invoke(cli, ["crypto", "generate-msnet-keys", "--output-dir", str(target_dir)])
            self.assertEqual(result.exit_code, 0, f"Command failed: {result.output}")

            private_key = target_dir / "private_key.bin"
            public_key = target_dir / "public_key.bin"

            self.assertTrue(private_key.exists())
            self.assertTrue(public_key.exists())

            # Check file sizes
            self.assertGreaterEqual(len(private_key.read_bytes()), 32)
            self.assertGreaterEqual(len(public_key.read_bytes()), 32)

            # Check permissions (private key must be 0600)
            priv_mode = stat.S_IMODE(private_key.stat().st_mode)
            self.assertEqual(priv_mode, 0o600, f"Private key mode is {oct(priv_mode)}, expected 0o600")

            # Check public key path printed
            self.assertIn(str(public_key), result.output)

            # Refuse overwrite without --force
            result_conflict = runner.invoke(cli, ["crypto", "generate-msnet-keys", "--output-dir", str(target_dir)])
            self.assertNotEqual(result_conflict.exit_code, 0)
            self.assertIn("already exist", (result_conflict.output + str(result_conflict.exception)).lower())

            # Overwrite with --force
            result_force = runner.invoke(cli, ["crypto", "generate-msnet-keys", "--output-dir", str(target_dir), "--force"])
            self.assertEqual(result_force.exit_code, 0)


if __name__ == "__main__":
    unittest.main()
