"""
GraphQL Schema
==============

GraphQL schema definitions for SPECTRA.
"""

import logging
from typing import List, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    from graphene import (
        Schema, ObjectType, String, Int, Float, Boolean, List as GQLList,
        Field, Mutation, InputObjectType, DateTime
    )
    GRAPHQL_AVAILABLE = True
except ImportError:
    GRAPHQL_AVAILABLE = False


def create_schema():
    """Create GraphQL schema."""
    if not GRAPHQL_AVAILABLE:
        return None
    
    try:
        from .types import (
            ChannelType, MessageType, UserType, Query, Mutation as GraphQLMutation
        )
        from ..services import DatabaseService
        from ...core.config_models import Config
        
        # Initialize database service for GraphQL resolvers
        try:
            config_path = Path('spectra_config.json')
            if config_path.exists():
                config = Config(config_path)
            else:
                config = Config(config_path)  # Will use defaults
            
            # Set global database service for resolvers
            import api.graphql.types as types_module
            types_module._database_service = DatabaseService(config)
        except Exception as e:
            logger.warning(f"Could not initialize database service for GraphQL: {e}")
        
        schema = Schema(query=Query, mutation=GraphQLMutation)
        return schema
    except Exception as e:
        logger.error(f"Failed to create GraphQL schema: {e}", exc_info=True)
        # Return minimal schema with dynamic hello
        class Query(ObjectType):
            """Root query type."""
            hello = String()
            
            def resolve_hello(self, info):
                import datetime
                return f"GraphQL API - SPECTRA (fallback mode) - {datetime.datetime.now().isoformat()}"
        
        return Schema(query=Query)
