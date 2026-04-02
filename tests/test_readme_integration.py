#!/usr/bin/env python3
"""
Test script for README integration with SPECTRA GUI launcher
Tests the Flask routes and template rendering for README functionality
"""

import sys
import asyncio
import json
import logging
import tempfile
from pathlib import Path
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Import the main launcher
from spectra_app.spectra_gui_launcher import SpectraGUILauncher, create_default_config, SystemMode


class _StubWebAuthnBackend:
    available = True
    backend_name = "stub"
    unavailable_reason = ""

    def begin_registration(self, operator, rp_id=None, rp_name=None, origin=None):
        return ({"challenge": "register-challenge", "rpId": rp_id or "localhost"}, {"operator_id": operator.operator_id})

    def register_complete(self, state, request_data):
        return {
            "credential_id": "cred-1",
            "attested_credential_data": "Y3JlZC1kYXRh",
            "aaguid": None,
            "public_key": None,
        }

    def begin_authentication(self, operators=None, rp_id=None, origin=None):
        return ({"challenge": "auth-challenge", "rpId": rp_id or "localhost"}, {"operator_id": operators[0].operator_id if operators else None})

    def authenticate_complete(self, state, credentials, request_data):
        return {"credential_id": "cred-1"}

def test_readme_integration():
    """Test the README integration functionality"""
    print("🧪 Testing README Integration...")
    failures = []

    # Create test configuration
    config = create_default_config()
    config.mode = SystemMode.DEMO
    config.debug = True
    config.port = 5555  # Use different port for testing
    config.bootstrap_secret = "bootstrap-admin-key"
    auth_dir = Path(tempfile.mkdtemp(prefix="spectra-auth-"))
    config.auth_store_path = str(auth_dir / "operators.json")

    # Initialize launcher
    launcher = SpectraGUILauncher(config)
    launcher.auth_service.backend = _StubWebAuthnBackend()
    client = launcher.app.test_client()

    # Test README content processing
    print("\n📄 Testing README content processing...")
    try:
        readme_content = launcher._get_readme_content()
        assert readme_content, "No README content loaded"
        print(f"✅ README content loaded successfully ({len(readme_content)} characters)")

        # Check for key sections
        assert "SPECTRA" in readme_content, "Main title missing from README"
        print("✅ Main title found")
        assert "Installation" in readme_content, "Installation section missing from README"
        print("✅ Installation section found")
        assert "Features" in readme_content, "Features section missing from README"
        print("✅ Features section found")

    except Exception as e:
        failures.append(f"README content processing: {e}")
        print(f"❌ Error loading README content: {e}")

    # Test markdown fallback
    print("\n🔄 Testing markdown fallback...")
    try:
        test_markdown = """
# Test Header
This is a test of the **markdown** fallback.

## Subheader
- List item 1
- List item 2

```bash
echo "test code block"
```

[Link test](https://example.com)
        """

        fallback_html = launcher._markdown_to_html_fallback(test_markdown)
        assert "<h1>Test Header</h1>" in fallback_html, "Header conversion failed"
        print("✅ Header conversion working")
        assert "<h2>Subheader</h2>" in fallback_html, "Subheader conversion failed"
        print("✅ Subheader conversion working")
        assert "<pre><code>" in fallback_html, "Code block conversion failed"
        print("✅ Code block conversion working")
        assert '<a href="https://example.com">Link test</a>' in fallback_html, "Link conversion failed"
        print("✅ Link conversion working")

    except Exception as e:
        failures.append(f"Markdown fallback: {e}")
        print(f"❌ Error testing markdown fallback: {e}")

    # Test Flask app setup
    print("\n🌐 Testing Flask app setup...")
    try:
        app = launcher.app
        assert app, "Flask app not initialized"
        print("✅ Flask app initialized")

        # Check routes
        routes = [rule.rule for rule in app.url_map.iter_rules()]
        assert '/readme' in routes, "README route not registered"
        print("✅ README route registered")
        assert '/help' in routes, "Help route not registered"
        print("✅ Help route registered")
        assert '/documentation' in routes, "Documentation route not registered"
        print("✅ Documentation route registered")
        assert '/api/system/status' in routes, "API routes not registered"
        print("✅ API routes registered")

    except Exception as e:
        failures.append(f"Flask app setup: {e}")
        print(f"❌ Error testing Flask app: {e}")

    # Test template existence
    print("\n📋 Testing template files...")
    try:
        templates_dir = ROOT_DIR / "templates"
        assert templates_dir.exists(), "Templates directory not found"
        print("✅ Templates directory exists")

        readme_template = templates_dir / "readme.html"
        assert readme_template.exists(), "README template not found"
        print("✅ README template exists")

        # Check template content
        template_content = readme_template.read_text()
        assert "{{ readme_content|safe }}" in template_content, "Jinja2 content placeholder missing"
        print("✅ Template has proper Jinja2 integration")
        assert "system_status" in template_content, "System status integration missing"
        print("✅ Template has system status integration")

    except Exception as e:
        failures.append(f"Template files: {e}")
        print(f"❌ Error testing templates: {e}")

    # Test system status integration
    print("\n📊 Testing system status integration...")
    try:
        with launcher.app.test_request_context("/"):
            status = launcher.get_system_status()
        assert status, "No system status available"
        print("✅ System status available")
        print(f"   Mode: {status.get('mode', 'Unknown')}")
        print(f"   Running: {status.get('system_running', False)}")
        print(f"   Agents: {status.get('total_agents', 0)}")

    except Exception as e:
        failures.append(f"System status: {e}")
        print(f"❌ Error getting system status: {e}")

    print("\n🔐 Testing browser auth gates...")
    try:
        redirect_response = client.get("/readme", follow_redirects=False)
        assert redirect_response.status_code in (301, 302), "Unauthenticated README access should redirect"
        assert "/login" in redirect_response.headers["Location"], "Redirect should point to /login"

        login_page = client.get("/login")
        login_html = login_page.get_data(as_text=True)
        assert "Bootstrap admin enrollment" in login_html, "Bootstrap login copy missing"
        assert "YubiKey" in login_html, "Passkey-first copy missing"

        bootstrap_status = client.get("/api/auth/bootstrap/status")
        assert bootstrap_status.status_code == 200

        register_response = client.post(
            "/api/auth/webauthn/register/options",
            json={"bootstrap_secret": "bootstrap-admin-key", "username": "admin", "display_name": "Admin"},
        )
        assert register_response.status_code == 200, "Bootstrap registration should succeed"

        verify_response = client.post(
            "/api/auth/webauthn/register/verify",
            json={"id": "cred-1", "type": "public-key", "response": {}},
        )
        assert verify_response.status_code == 200, "Bootstrap verification should succeed"

        with client.session_transaction() as sess:
            assert sess.get("spectra_operator_id") is not None

        readme_response = client.get("/readme")
        assert readme_response.status_code == 200, "Authenticated README access should succeed"
        assert "SPECTRA Documentation" in readme_response.get_data(as_text=True)

        logout_response = client.post("/logout")
        assert logout_response.status_code == 200, "Logout should succeed"
        assert logout_response.get_json()["success"] is True
    except Exception as e:
        failures.append(f"Auth gate flow: {e}")
        print(f"❌ Error testing auth gates: {e}")

    print("\n🎯 README Integration Test Summary:")
    print("=" * 50)
    print("✅ All core functionality tested")
    print("✅ Flask routes configured")
    print("✅ Template integration ready")
    print("✅ Markdown processing available")
    print("✅ System status integration working")
    if failures:
        raise AssertionError("; ".join(failures))

    print("\n🚀 Ready for deployment!")

if __name__ == "__main__":
    # Set up basic logging
    logging.basicConfig(level=logging.INFO)

    try:
        test_readme_integration()
        print("\n🚀 Creating demo launcher...")
        create_demo_launcher()
        print("\n✅ README integration is ready!")
        print("\nTo test the GUI:")
        print("1. python3 examples/demo_readme_gui.py")
        print("2. Open http://localhost:5000/readme")
    except KeyboardInterrupt:
        print("\n🛑 Test interrupted by user")
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        sys.exit(1)
