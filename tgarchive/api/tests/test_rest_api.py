"""
REST API Integration Tests
===========================

Tests for REST API endpoints.
"""

import unittest
import json
from flask import Flask
from pathlib import Path

from .. import create_app
from ...core.config_models import Config


class TestRESTAPI(unittest.TestCase):
    """Test REST API endpoints."""
    
    def setUp(self):
        """Set up test client."""
        config_path = Path('spectra_config.json')
        if config_path.exists():
            config = Config(config_path)
        else:
            config = Config(config_path)  # Will use defaults
        
        self.app = create_app({
            'TESTING': True,
            'JWT_SECRET': 'test-secret-key'
        })
        self.client = self.app.test_client()
    
    def test_health_endpoint(self):
        """Test health check endpoint."""
        response = self.client.get('/health')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data['status'], 'ok')
    
    def test_core_archive_endpoint(self):
        """Test archive endpoint structure."""
        # This would require authentication token
        # For now, just test endpoint exists
        response = self.client.post(
            '/api/core/archive',
            json={'entity_id': '@test_channel'},
            headers={'Authorization': 'Bearer test-token'}
        )
        # Should return 401 without valid token, but endpoint exists
        self.assertIn(response.status_code, [401, 400, 202])
    
    def test_accounts_list_endpoint(self):
        """Test accounts list endpoint."""
        response = self.client.get(
            '/api/accounts',
            headers={'Authorization': 'Bearer test-token'}
        )
        self.assertIn(response.status_code, [401, 200])


if __name__ == '__main__':
    unittest.main()
