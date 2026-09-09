"""Core operations route stubs.

The full web API is being phased out in favor of CLI-only architecture.
This stub provides the blueprint registration so the api package imports
cleanly without a hard dependency on the removed core routes.
"""

from . import core_bp

# Placeholder routes — CLI is the primary interface now.
@core_bp.route('/api/core/status', methods=['GET'])
def core_status():
    """Health check stub — CLI is the primary interface."""
    return {"status": "ok", "interface": "cli"}
