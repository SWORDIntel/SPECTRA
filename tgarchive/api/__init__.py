"""
SPECTRA REST API
================

Full-featured REST API for SPECTRA with CSNA 2.0 security compliance.
"""

from flask import Flask
from flask_cors import CORS
from pathlib import Path

from .security import TokenManager, RateLimiter, SecurityHeaders
from .routes import (
    auth_bp, channels_bp, messages_bp, search_bp, export_bp, admin_bp,
    core_bp, accounts_bp, forwarding_bp, threat_bp, analytics_bp, ml_bp,
    crypto_bp, database_bp, osint_bp, services_bp, cli_bp
)
from .services import TaskManager
from .middleware import register_error_handlers
from ..core.config_models import Config

import logging
logger = logging.getLogger(__name__)


def create_app(config=None):
    """
    Create and configure the Flask application.

    Args:
        config: Configuration dictionary or path

    Returns:
        Configured Flask app
    """
    app = Flask(__name__, template_folder='../../templates', static_folder='../../static')

    # Configuration
    if config:
        app.config.from_mapping(config)
    else:
        # Load from environment
        app.config['JWT_SECRET'] = app.config.get('SPECTRA_JWT_SECRET', 'dev-secret-key')
        app.config['DEBUG'] = app.config.get('SPECTRA_DEBUG', False)
        app.config['TESTING'] = app.config.get('SPECTRA_TESTING', False)

    # Initialize security
    SecurityHeaders.init_app(app)

    # Initialize rate limiter
    app.rate_limiter = RateLimiter(
        default_limit=int(app.config.get('RATE_LIMIT', 100)),
        window_seconds=int(app.config.get('RATE_LIMIT_WINDOW', 60))
    )

    # Initialize token manager
    app.token_manager = TokenManager(secret_key=app.config.get('JWT_SECRET'))

    # Enable CORS with security restrictions
    CORS(
        app,
        origins=app.config.get('CORS_ORIGINS', ['http://localhost:3000']),
        allow_headers=['Content-Type', 'Authorization'],
        expose_headers=['X-RateLimit-Limit', 'X-RateLimit-Remaining', 'X-RateLimit-Reset'],
        supports_credentials=True,
        max_age=3600
    )

    # Initialize task manager
    task_manager = TaskManager()
    
    # Load config if not provided
    if not config:
        config_path = Path('spectra_config.json')
        if config_path.exists():
            config = Config(config_path)
        else:
            config = Config(config_path)  # Will use defaults
    
    # Register blueprints
    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    
    # Initialize and register route modules
    try:
        from .routes import core, accounts, forwarding, threat, analytics, ml, crypto, database, osint, services, channels, messages
        
        # Initialize routes with dependencies
        core.init_core_routes(app, config, task_manager)
        accounts.init_accounts_routes(app, config)
        forwarding.init_forwarding_routes(app, config, task_manager)
        threat.init_threat_routes(app)
        analytics.init_analytics_routes(app)
        ml.init_ml_routes(app)
        crypto.init_crypto_routes(app)
        database.init_database_routes(app, config)
        osint.init_osint_routes(app, config)
        services.init_services_routes(app, config)
        channels.init_channels_routes(app, config)
        messages.init_messages_routes(app, config)
    except Exception as e:
        logger.warning(f"Some route modules failed to initialize: {e}")
    
    # Register existing blueprints (these may be registered by init functions above)
    # Only register if not already registered
    try:
        if 'channels' not in [bp.name for bp in app.blueprints.values()]:
            app.register_blueprint(channels_bp, url_prefix='/api/channels')
        if 'messages' not in [bp.name for bp in app.blueprints.values()]:
            app.register_blueprint(messages_bp, url_prefix='/api/messages')
        if 'search' not in [bp.name for bp in app.blueprints.values()]:
            app.register_blueprint(search_bp, url_prefix='/api/search')
        if 'export' not in [bp.name for bp in app.blueprints.values()]:
            app.register_blueprint(export_bp, url_prefix='/api/export')
        if 'admin' not in [bp.name for bp in app.blueprints.values()]:
            app.register_blueprint(admin_bp, url_prefix='/api/admin')
    except Exception as e:
        logger.warning(f"Some blueprints failed to register: {e}")
    
    # Register error handlers
    register_error_handlers(app)
    
    # Initialize WebSocket
    try:
        from .websocket import WebSocketManager, init_websocket_routes
        ws_manager = WebSocketManager(app)
        init_websocket_routes(app, ws_manager)
        app.ws_manager = ws_manager
    except Exception as e:
        logger.warning(f"WebSocket initialization failed: {e}")
        app.ws_manager = None
    
    # Initialize GraphQL
    try:
        from .graphql import init_graphql_routes
        init_graphql_routes(app)
    except Exception as e:
        logger.warning(f"GraphQL initialization failed: {e}")
    
    # Initialize CLI API
    try:
        from .cli.routes import init_cli_routes
        init_cli_routes(app, task_manager)
    except Exception as e:
        logger.warning(f"CLI API initialization failed: {e}")

    # Health check endpoint
    @app.route('/health')
    def health():
        return {'status': 'ok', 'service': 'spectra-api'}, 200

    return app
