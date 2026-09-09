"""
Tests for QIHSE RESP Server Ctypes Wrapper
===========================================
"""

import socket
import time
import unittest

from tgarchive.search.qihse_resp_server import (
    QIHSEResPServer,
    qihse_resp_available,
    QihseRespServerConfig,
    qihse_resp_server_config_init,
)


class TestQIHSEResPServer(unittest.TestCase):
    """Test suite for QIHSE RESP server ctypes wrapper."""

    def test_resp_server_available(self):
        """Verify native QIHSE RESP symbols are detected."""
        self.assertTrue(qihse_resp_available())

    def test_config_init(self):
        """Verify configuration initialization struct."""
        cfg = QihseRespServerConfig()
        qihse_resp_server_config_init(cfg)
        self.assertEqual(cfg.port, 6379)
        self.assertEqual(cfg.max_clients, 1024)
        self.assertTrue(cfg.enable_task_queue)

    def test_server_lifecycle_and_ping(self):
        """Verify start, is_running, port, ping, and stop lifecycle."""
        # Use dynamic port (0) to avoid any port conflicts
        server = QIHSEResPServer(host="127.0.0.1", port=0, max_clients=16, enable_task_queue=True)
        self.assertFalse(server.is_running())
        self.assertEqual(server.port(), 0)

        started = server.start(timeout=3.0)
        self.assertTrue(started, "Server failed to start")
        self.assertTrue(server.is_running())
        self.assertGreater(server.port(), 0)

        # Health ping
        self.assertTrue(server.ping(timeout=1.0))

        # Stop
        server.stop()
        self.assertFalse(server.is_running())
        self.assertEqual(server.port(), 0)
        self.assertFalse(server.ping(timeout=0.2))

    def test_context_manager(self):
        """Verify context manager lifecycle and clean teardown."""
        with QIHSEResPServer(host="127.0.0.1", port=0) as srv:
            self.assertTrue(srv.is_running())
            self.assertGreater(srv.port(), 0)
            self.assertTrue(srv.ping())

        # Once exited, should be stopped
        self.assertFalse(srv.is_running())
        self.assertEqual(srv.port(), 0)


if __name__ == "__main__":
    unittest.main()
