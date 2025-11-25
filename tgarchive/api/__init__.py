"""
SPECTRA REST API
================

Full-featured REST API for SPECTRA with CSNA 2.0 security compliance.
"""

from flask import Flask
from flask_cors import CORS

from .security import TokenManager, RateLimiter, SecurityHeaders
from .routes import auth_bp, channels_bp, messages_bp, search_bp, export_bp, admin_bp


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

    # Register blueprints
    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    app.register_blueprint(channels_bp, url_prefix='/api/channels')
    app.register_blueprint(messages_bp, url_prefix='/api/messages')
    app.register_blueprint(search_bp, url_prefix='/api/search')
    app.register_blueprint(export_bp, url_prefix='/api/export')
    app.register_blueprint(admin_bp, url_prefix='/api/admin')

    # Health check endpoint
    @app.route('/health')
    def health():
        return {'status': 'ok', 'service': 'spectra-api'}, 200

    return app
