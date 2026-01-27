"""
GraphQL Routes
==============

GraphQL endpoint and playground.
"""

import logging
from flask import request, jsonify

logger = logging.getLogger(__name__)

try:
    from graphene import Schema, ObjectType, String, Int, List, Field, Mutation
    from flask_graphql import GraphQLView
    GRAPHQL_AVAILABLE = True
except ImportError:
    GRAPHQL_AVAILABLE = False
    logger.warning("GraphQL not available - install graphene and flask-graphql")


def init_graphql_routes(app):
    """Initialize GraphQL routes."""
    if not GRAPHQL_AVAILABLE:
        logger.warning("GraphQL routes not initialized - dependencies not available")
        return
    
    try:
        from .schema import create_schema
        
        schema = create_schema()
        
        # GraphQL endpoint
        app.add_url_rule(
            '/api/graphql',
            view_func=GraphQLView.as_view(
                'graphql',
                schema=schema,
                graphiql=app.config.get('DEBUG', False)  # Enable playground in debug mode
            )
        )
        
        logger.info("GraphQL endpoint initialized at /api/graphql")
    except Exception as e:
        logger.error(f"Failed to initialize GraphQL: {e}", exc_info=True)
        # Fallback endpoint
        @app.route('/api/graphql', methods=['POST', 'GET'])
        def graphql_fallback():
            return jsonify({
                'error': 'GraphQL not available',
                'message': 'Install graphene and flask-graphql to enable GraphQL API'
            }), 503
