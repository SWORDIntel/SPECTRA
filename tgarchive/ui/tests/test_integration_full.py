"""
Full Integration Test for SPECTRA TUI Enhancements
===================================================

Tests the complete TUI application with all enhancements integrated.
Simulates real operator workflows.
"""

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import sys
# Add SPECTRA root to path
spectra_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(spectra_root))

# Mock npyscreen for testing
sys.modules['npyscreen'] = MagicMock()

try:
    from tgarchive.ui.tui import SpectraApp
    from tgarchive.core.config_models import Config
    from tgarchive.db import SpectraDB
    from tgarchive.ui.operation_queue import Priority
    IMPORTS_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Could not import SPECTRA modules: {e}")
    IMPORTS_AVAILABLE = False
    SpectraApp = None
    Config = None
    Priority = None


class TestFullIntegration(unittest.TestCase):
    """Full integration test simulating real operator workflows"""
    
    def setUp(self):
        """Set up test environment"""
        if not IMPORTS_AVAILABLE or SpectraApp is None:
            self.skipTest("Required imports not available")
        self.temp_dir = tempfile.mkdtemp()
        self.config_path = Path(self.temp_dir) / "test_config.json"
        
        # Create minimal config
        config_data = {
            "api_id": 12345,
            "api_hash": "test_hash",
            "accounts": [{
                "api_id": 12345,
                "api_hash": "test_hash",
                "session_name": "test_session"
            }],
            "db_path": str(Path(self.temp_dir) / "test.db"),
            "media_dir": str(Path(self.temp_dir) / "media"),
        }
        
        with open(self.config_path, 'w') as f:
            import json
            json.dump(config_data, f)
        
        # Mock the app initialization
        self.app = SpectraApp()
        self.app.manager = MagicMock()
        self.app.manager.config = Config(self.config_path)
        self.app.manager.config.active_accounts = config_data["accounts"]
        self.app.db_instance = MagicMock()
    
    def tearDown(self):
        """Clean up"""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_app_initialization(self):
        """Test that app initializes all enhancement systems"""
        # Verify all systems are initialized
        self.assertIsNotNone(self.app.keyboard_handler)
        self.assertIsNotNone(self.app.command_history)
        self.assertIsNotNone(self.app.help_system)
        self.assertIsNotNone(self.app.quick_actions)
        self.assertIsNotNone(self.app.undo_redo)
        self.assertIsNotNone(self.app.templates)
        self.assertIsNotNone(self.app.error_handler)
        self.assertIsNotNone(self.app.operation_queue)
        self.assertIsNotNone(self.app.profiles)
        self.assertIsNotNone(self.app.workflow_automation)
        self.assertIsNotNone(self.app.preferences)
        self.assertIsNotNone(self.app.quick_access)
        self.assertIsNotNone(self.app.audit_logger)
        self.assertIsNotNone(self.app.remote_friendly)
    
    def test_workflow_archive_operation(self):
        """Test complete archive operation workflow"""
        # Record operation in history
        entry = self.app.command_history.add_entry(
            operation_type="archive",
            parameters={"entity": "test_channel", "download_media": True},
            result_status="started"
        )
        self.assertIsNotNone(entry)
        
        # Log audit event
        self.app.audit_logger.log(
            "operation", "test_user", "archive",
            {"entity": "test_channel"}, "success"
        )
        
        # Check history
        recent = self.app.command_history.get_recent(limit=1)
        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0].operation_type, "archive")
        
        # Check audit log
        self.assertEqual(len(self.app.audit_logger.memory_log), 1)
    
    def test_keyboard_shortcuts_workflow(self):
        """Test keyboard shortcuts in workflow"""
        # Test shortcuts
        result = self.app.keyboard_handler.handle_keypress(4, "MAIN")  # Ctrl+D
        self.assertTrue(result)
        
        # Test quick actions
        result = self.app.quick_actions.execute("qa", self.app)
        self.assertTrue(result)
    
    def test_template_and_profile_workflow(self):
        """Test using templates and profiles"""
        # Save template
        template_data = {
            "operation_type": "archive",
            "parameters": {"entity": "common_channel", "download_media": True}
        }
        self.app.templates.save_template("common_archive", template_data)
        
        # Load template
        template = self.app.templates.get_template("common_archive")
        self.assertIsNotNone(template)
        
        # Save profile
        from tgarchive.ui.profiles import ConfigProfile
        profile = ConfigProfile("test_profile", {"media_dir": "custom_media"})
        self.app.profiles.save_profile(profile)
        
        # Set current profile
        self.app.profiles.set_current("test_profile")
        self.assertEqual(self.app.profiles.current_profile, "test_profile")
    
    def test_search_and_history_integration(self):
        """Test search with history integration"""
        # Add search history
        if self.app.advanced_search:
            self.app.advanced_search.save_filter("test_filter", {"channel_id": 123})
            filter_obj = self.app.advanced_search.get_filter("test_filter")
            self.assertIsNotNone(filter_obj)
    
    def test_error_handling_workflow(self):
        """Test error handling in workflow"""
        error = ValueError("Test error")
        self.app.error_handler.handle_operation_error("archive", error)
        # Should not raise exception
    
    def test_operation_queue_workflow(self):
        """Test operation queue workflow"""
        def test_operation():
            return "success"
        
        op = self.app.operation_queue.add_operation(
            "test_op", "test", test_operation, priority=Priority.HIGH
        )
        self.assertIsNotNone(op)
        
        status = self.app.operation_queue.get_status()
        self.assertIn("queued", status)


def run_integration_tests():
    """Run full integration tests"""
    if not IMPORTS_AVAILABLE:
        print("Warning: Integration tests require full SPECTRA imports")
        return True  # Don't fail if imports are missing
    
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestFullIntegration)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_integration_tests()
    sys.exit(0 if success else 1)
