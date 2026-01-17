"""
Advanced Search System for SPECTRA TUI
=======================================

Multi-criteria search with saved filters, search history, and integration
with hybrid search (SQLite FTS5, Qdrant, NOT_STISLA, QIHSE).
"""

import json
import logging
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    from ..search.hybrid_search import HybridSearchEngine
    HYBRID_SEARCH_AVAILABLE = True
except ImportError:
    HYBRID_SEARCH_AVAILABLE = False
    logger.debug("Hybrid search not available")


@dataclass
class SearchFilter:
    """Search filter criteria"""
    name: str
    criteria: Dict[str, Any]
    created_at: float = 0.0
    
    def __post_init__(self):
        if self.created_at == 0.0:
            self.created_at = time.time()
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SearchFilter':
        return cls(**data)


@dataclass
class SearchHistoryEntry:
    """Search history entry"""
    query: str
    filters: Dict[str, Any]
    results_count: int
    timestamp: float = 0.0
    
    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SearchHistoryEntry':
        return cls(**data)


class AdvancedSearch:
    """Advanced search with filters and history"""
    
    def __init__(self, db_instance=None, search_dir: Optional[Path] = None):
        self.db = db_instance
        if search_dir is None:
            search_dir = Path("data/search")
        self.search_dir = search_dir
        self.search_dir.mkdir(parents=True, exist_ok=True)
        
        self.saved_filters: Dict[str, SearchFilter] = {}
        self.search_history: List[SearchHistoryEntry] = []
        self.hybrid_engine = None
        
        if HYBRID_SEARCH_AVAILABLE and self.db:
            try:
                self.hybrid_engine = HybridSearchEngine(self.db)
            except Exception as e:
                logger.debug(f"Hybrid search engine not available: {e}")
        
        self._load_filters()
        self._load_history()
    
    def _load_filters(self):
        """Load saved filters"""
        filters_file = self.search_dir / "filters.json"
        if filters_file.exists():
            try:
                with open(filters_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for name, filter_data in data.items():
                        self.saved_filters[name] = SearchFilter.from_dict(filter_data)
            except Exception as e:
                logger.warning(f"Failed to load filters: {e}")
    
    def _save_filters(self):
        """Save filters to file"""
        filters_file = self.search_dir / "filters.json"
        try:
            data = {name: f.to_dict() for name, f in self.saved_filters.items()}
            with open(filters_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save filters: {e}")
    
    def _load_history(self):
        """Load search history"""
        history_file = self.search_dir / "history.json"
        if history_file.exists():
            try:
                with open(history_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.search_history = [SearchHistoryEntry.from_dict(e) for e in data]
            except Exception as e:
                logger.warning(f"Failed to load history: {e}")
    
    def _save_history(self):
        """Save search history"""
        history_file = self.search_dir / "history.json"
        try:
            data = [e.to_dict() for e in self.search_history[-100:]]  # Keep last 100
            with open(history_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save history: {e}")
    
    def search(
        self,
        query: str,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Perform advanced search.
        
        Args:
            query: Search query string
            filters: Optional filter criteria
            limit: Maximum results
            
        Returns:
            List of search results
        """
        if not self.hybrid_engine:
            logger.warning("Hybrid search engine not available")
            return []
        
        try:
            # Apply filters
            search_params = {"query": query, "limit": limit}
            if filters:
                search_params.update(filters)
            
            # Perform search
            results = self.hybrid_engine.search(**search_params)
            
            # Record in history
            entry = SearchHistoryEntry(
                query=query,
                filters=filters or {},
                results_count=len(results)
            )
            self.search_history.append(entry)
            self._save_history()
            
            return results
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return []
    
    def save_filter(self, name: str, criteria: Dict[str, Any]):
        """Save a search filter"""
        filter_obj = SearchFilter(name=name, criteria=criteria)
        self.saved_filters[name] = filter_obj
        self._save_filters()
    
    def get_filter(self, name: str) -> Optional[SearchFilter]:
        """Get a saved filter"""
        return self.saved_filters.get(name)
    
    def list_filters(self) -> List[str]:
        """List all saved filter names"""
        return list(self.saved_filters.keys())
    
    def delete_filter(self, name: str) -> bool:
        """Delete a saved filter"""
        if name in self.saved_filters:
            del self.saved_filters[name]
            self._save_filters()
            return True
        return False
    
    def get_recent_searches(self, limit: int = 10) -> List[SearchHistoryEntry]:
        """Get recent search history"""
        return self.search_history[-limit:][::-1]
