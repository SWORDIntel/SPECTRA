"""
SPECTRA Web Server & Dashboard
===============================

Main entry point for running SPECTRA as a web application.
Launches Flask server with REST API and web dashboard.

Usage:
    python -m tgarchive.web [options]

Options:
    --host HOST          Server host (default: 0.0.0.0)
    --port PORT          Server port (default: 5000)
    --debug              Enable debug mode
    --ssl                Enable HTTPS (requires cert files)
"""

import os
import sys
import logging
import argparse
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from tgarchive.api import create_app


def create_web_app():
    """Create and configure the Flask web application."""
    app = create_app({
        'JWT_SECRET': os.getenv('SPECTRA_JWT_SECRET', 'change-me-in-production'),
        'DEBUG': os.getenv('SPECTRA_DEBUG', '').lower() in ('true', '1', 'yes'),
        'CORS_ORIGINS': os.getenv('SPECTRA_CORS_ORIGINS', 'http://localhost:3000').split(','),
        'RATE_LIMIT': int(os.getenv('SPECTRA_RATE_LIMIT', '100')),
        'SESSION_TIMEOUT': int(os.getenv('SPECTRA_SESSION_TIMEOUT', '3600')),
    })

    # Register additional routes for web interface
    register_web_routes(app)

    return app


def register_web_routes(app):
    """Register web interface routes."""
    from flask import render_template, send_from_directory

    @app.route('/')
    def index():
        """Serve main dashboard."""
        return render_template('index.html')

    @app.route('/dashboard')
    def dashboard():
        """Serve dashboard."""
        return render_template('dashboard.html')

    @app.route('/login')
    def login_page():
        """Serve login page."""
        return render_template('login.html')

    @app.route('/api/docs')
    def api_docs():
        """Serve API documentation."""
        return render_template('api_docs.html')


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='SPECTRA Web Server',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument('--host', default='0.0.0.0', help='Server host')
    parser.add_argument('--port', type=int, default=5000, help='Server port')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')
    parser.add_argument('--ssl', action='store_true', help='Enable HTTPS')
    parser.add_argument('--cert', help='Path to SSL certificate')
    parser.add_argument('--key', help='Path to SSL key')

    args = parser.parse_args()

    # Create Flask app
    logger.info("Creating SPECTRA web application...")
    app = create_web_app()

    # Configure SSL if requested
    ssl_context = None
    if args.ssl:
        if not args.cert or not args.key:
            logger.error("SSL enabled but cert/key paths not provided")
            return 1

        ssl_context = (args.cert, args.key)
        logger.info(f"SSL enabled: {args.cert} / {args.key}")

    # Start server
    logger.info(f"Starting SPECTRA web server on {args.host}:{args.port}")
    logger.info(f"Dashboard: http://{args.host}:{args.port}")
    logger.info(f"API Docs: http://{args.host}:{args.port}/api/docs")
    logger.warning("⚠️  IMPORTANT: Set SPECTRA_JWT_SECRET environment variable in production!")

    try:
        app.run(
            host=args.host,
            port=args.port,
            debug=args.debug,
            ssl_context=ssl_context,
            use_reloader=args.debug
        )
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
        return 0
    except Exception as e:
        logger.error(f"Server error: {str(e)}")
        return 1


if __name__ == '__main__':
    sys.exit(main())
