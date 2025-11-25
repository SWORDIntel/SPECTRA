"""
Secure HTTP Headers (CSNA 2.0 Compliance)
==========================================

Implements security headers to prevent common attacks:
- XSS (Content-Security-Policy)
- Clickjacking (X-Frame-Options)
- MIME type sniffing (X-Content-Type-Options)
- SSL/TLS enforcement (Strict-Transport-Security)
- Referrer policy
- etc.
"""

from flask import Flask, request, after_this_request


class SecurityHeaders:
    """Add secure headers to all responses."""

    @staticmethod
    def init_app(app: Flask):
        """Register security headers middleware."""

        @app.after_request
        def add_security_headers(response):
            """Add CSNA 2.0 compliant security headers."""

            # Prevent XSS attacks
            response.headers['X-XSS-Protection'] = '1; mode=block'
            response.headers['Content-Security-Policy'] = (
                "default-src 'self'; "
                "script-src 'self' 'wasm-unsafe-eval'; "  # For WASM in Vue
                "style-src 'self' 'unsafe-inline'; "  # For Tailwind CSS
                "img-src 'self' data: https:; "
                "font-src 'self' data:; "
                "connect-src 'self' wss: ws:; "  # For WebSocket
                "frame-ancestors 'none'; "
                "form-action 'self'; "
                "upgrade-insecure-requests"
            )

            # Prevent MIME type sniffing
            response.headers['X-Content-Type-Options'] = 'nosniff'

            # Prevent clickjacking
            response.headers['X-Frame-Options'] = 'DENY'

            # Enforce HTTPS
            if not request.environ.get('TESTING'):
                response.headers['Strict-Transport-Security'] = (
                    'max-age=31536000; includeSubDomains; preload'
                )

            # Referrer policy
            response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'

            # Permissions policy (formerly Feature-Policy)
            response.headers['Permissions-Policy'] = (
                'geolocation=(), '
                'microphone=(), '
                'camera=(), '
                'payment=(), '
                'usb=(), '
                'magnetometer=(), '
                'gyroscope=(), '
                'accelerometer=()'
            )

            # Disable caching for sensitive content
            if request.path.startswith('/api/'):
                response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
                response.headers['Pragma'] = 'no-cache'
                response.headers['Expires'] = '0'

            # Prevent tracking
            response.headers['X-Permitted-Cross-Domain-Policies'] = 'none'

            return response

        return app
