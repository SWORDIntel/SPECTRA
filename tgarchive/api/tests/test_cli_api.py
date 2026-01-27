"""
CLI API Tests
=============

Tests for CLI command execution API.
"""

import unittest
import json
from flask import Flask

from .. import create_app


class TestCLIAPI(unittest.TestCase):
    """Test CLI API endpoints."""
    
    def setUp(self):
        """Set up test client."""
        self.app = create_app({'TESTING': True})
        self.client = self.app.test_client()
    
    def test_list_commands(self):
        """Test listing available commands."""
        response = self.client.get(
            '/api/cli/commands',
            headers={'Authorization': 'Bearer test-token'}
        )
        self.assertIn(response.status_code, [401, 200])
        if response.status_code == 200:
            data = json.loads(response.data)
            self.assertIn('commands', data)
    
    def test_execute_command_structure(self):
        """Test command execution endpoint structure."""
        response = self.client.post(
            '/api/cli/execute',
            json={
                'command': 'archive',
                'args': ['--entity', '@test']
            },
            headers={'Authorization': 'Bearer test-token'}
        )
        # Should return 401 without valid token, but endpoint exists
        self.assertIn(response.status_code, [401, 403, 202])


if __name__ == '__main__':
    unittest.main()
