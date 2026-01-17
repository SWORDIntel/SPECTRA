"""Auto-completion system with QIHSE and ML enhancements for SPECTRA TUI"""

import logging
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    from ..search.qihse_bindings import QihseStore, qihse_available
    QIHSE_ENABLED = qihse_available()
except ImportError:
    QIHSE_ENABLED = False

try:
    from ..ai.semantic_search import SemanticSearch
    SEMANTIC_ENABLED = True
except ImportError:
    SEMANTIC_ENABLED = False


class AutoCompleter:
    """Auto-completion engine with QIHSE and ML enhancements"""
    
    def __init__(self, db_instance=None, command_history=None):
        self.db = db_instance
        self.command_history = command_history
        self.qihse_store = None
        self.semantic_search = None
        
        if QIHSE_ENABLED:
            try:
                self.qihse_store = QihseStore()
            except Exception as e:
                logger.debug(f"QIHSE not available: {e}")
        
        if SEMANTIC_ENABLED:
            try:
                self.semantic_search = SemanticSearch()
            except Exception as e:
                logger.debug(f"Semantic search not available: {e}")
    
    def complete_channel_name(self, prefix: str, limit: int = 10) -> List[str]:
        """Complete channel name using database and QIHSE"""
        if not self.db:
            return []
        
        try:
            channels = self.db.get_all_unique_channels()
            # Filter and sort by prefix match
            matches = [name for _, name in channels if name.lower().startswith(prefix.lower())]
            return sorted(matches)[:limit]
        except Exception:
            return []
    
    def complete_command(self, prefix: str, limit: int = 10) -> List[str]:
        """Complete command using command history"""
        if not self.command_history:
            return []
        
        # Get recent operations
        recent = self.command_history.get_recent(limit=100)
        operations = {entry.operation_type for entry in recent}
        matches = [op for op in operations if op.lower().startswith(prefix.lower())]
        return sorted(matches)[:limit]
    
    def suggest_semantic(self, query: str, limit: int = 5) -> List[Tuple[str, float]]:
        """Get semantic suggestions using QIHSE/ML"""
        if not self.semantic_search or not self.qihse_store:
            return []
        
        try:
            results = self.semantic_search.search(query, limit=limit)
            return [(r['text'], r.get('score', 0.0)) for r in results]
        except Exception:
            return []
