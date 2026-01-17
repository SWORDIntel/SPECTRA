"""
Cache Manager for Search Results
=================================

Redis/Memcached caching layer for search results, metadata, and anchor tables.
"""

import logging
import json
import pickle
import hashlib
from typing import Optional, Any, Dict, List
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

# Try to import Redis
try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    logger.warning("Redis not available. Caching will be disabled.")

# Try to import Memcached
try:
    import pymemcache
    MEMCACHED_AVAILABLE = True
except ImportError:
    MEMCACHED_AVAILABLE = False


class CacheManager:
    """
    Unified cache manager supporting Redis and Memcached.
    
    Provides:
    - Search result caching
    - Metadata caching
    - Anchor table serialization
    - Cache invalidation
    - Cache statistics
    """
    
    def __init__(
        self,
        redis_url: Optional[str] = "redis://localhost:6379",
        memcached_url: Optional[str] = None,
        default_ttl: int = 3600,  # 1 hour
    ):
        """
        Initialize cache manager.
        
        Args:
            redis_url: Redis connection URL (None to disable)
            memcached_url: Memcached server address (None to disable)
            default_ttl: Default TTL in seconds
        """
        self.default_ttl = default_ttl
        self.redis_client = None
        self.memcached_client = None
        
        # Initialize Redis
        if redis_url and REDIS_AVAILABLE:
            try:
                self.redis_client = redis.from_url(redis_url, decode_responses=False)
                self.redis_client.ping()
                logger.info("Redis cache initialized")
            except Exception as e:
                logger.warning(f"Failed to connect to Redis: {e}")
                self.redis_client = None
        
        # Initialize Memcached
        if memcached_url and MEMCACHED_AVAILABLE:
            try:
                host, port = memcached_url.split(':')
                self.memcached_client = pymemcache.Client((host, int(port)))
                self.memcached_client.get('test')
                logger.info("Memcached cache initialized")
            except Exception as e:
                logger.warning(f"Failed to connect to Memcached: {e}")
                self.memcached_client = None
        
        # Statistics
        self.stats = {
            'hits': 0,
            'misses': 0,
            'sets': 0,
            'deletes': 0,
        }
    
    def _make_key(self, prefix: str, *args, **kwargs) -> str:
        """Generate cache key from arguments"""
        key_data = {
            'args': args,
            'kwargs': sorted(kwargs.items()),
        }
        key_str = json.dumps(key_data, sort_keys=True)
        key_hash = hashlib.sha384(key_str.encode()).hexdigest()[:32]
        return f"spectra:{prefix}:{key_hash}"
    
    def get(self, key: str) -> Optional[Any]:
        """
        Get value from cache.
        
        Args:
            key: Cache key
        
        Returns:
            Cached value or None
        """
        # Try Redis first
        if self.redis_client:
            try:
                value = self.redis_client.get(key)
                if value:
                    self.stats['hits'] += 1
                    return pickle.loads(value)
            except Exception as e:
                logger.debug(f"Redis get failed: {e}")
        
        # Try Memcached
        if self.memcached_client:
            try:
                value = self.memcached_client.get(key)
                if value:
                    self.stats['hits'] += 1
                    return pickle.loads(value)
            except Exception as e:
                logger.debug(f"Memcached get failed: {e}")
        
        self.stats['misses'] += 1
        return None
    
    def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None
    ) -> bool:
        """
        Set value in cache.
        
        Args:
            key: Cache key
            value: Value to cache
            ttl: Time to live in seconds (None = use default)
        
        Returns:
            True if successful
        """
        ttl = ttl or self.default_ttl
        serialized = pickle.dumps(value)
        
        success = False
        
        # Set in Redis
        if self.redis_client:
            try:
                self.redis_client.setex(key, ttl, serialized)
                success = True
            except Exception as e:
                logger.debug(f"Redis set failed: {e}")
        
        # Set in Memcached
        if self.memcached_client:
            try:
                self.memcached_client.set(key, serialized, expire=ttl)
                success = True
            except Exception as e:
                logger.debug(f"Memcached set failed: {e}")
        
        if success:
            self.stats['sets'] += 1
        
        return success
    
    def delete(self, key: str) -> bool:
        """Delete key from cache"""
        success = False
        
        if self.redis_client:
            try:
                self.redis_client.delete(key)
                success = True
            except Exception as e:
                logger.debug(f"Redis delete failed: {e}")
        
        if self.memcached_client:
            try:
                self.memcached_client.delete(key)
                success = True
            except Exception as e:
                logger.debug(f"Memcached delete failed: {e}")
        
        if success:
            self.stats['deletes'] += 1
        
        return success
    
    def cache_search_result(
        self,
        query: str,
        search_type: str,
        results: List[Any],
        ttl: Optional[int] = None,
        **filters
    ) -> bool:
        """
        Cache search results.
        
        Args:
            query: Search query
            search_type: Search type
            results: Search results to cache
            ttl: Cache TTL
            **filters: Search filters (filter_channel, date_from, etc.)
        
        Returns:
            True if cached successfully
        """
        key = self._make_key("search", query, search_type, **filters)
        return self.set(key, results, ttl)
    
    def get_cached_search_result(
        self,
        query: str,
        search_type: str,
        **filters
    ) -> Optional[List[Any]]:
        """Get cached search results"""
        key = self._make_key("search", query, search_type, **filters)
        return self.get(key)
    
    def cache_anchor_table(
        self,
        workload_type: int,
        anchor_data: Any,
        ttl: Optional[int] = None
    ) -> bool:
        """Cache NOT_STISLA anchor table"""
        key = self._make_key("anchor_table", workload_type)
        return self.set(key, anchor_data, ttl or 86400)  # 24 hours default
    
    def get_cached_anchor_table(
        self,
        workload_type: int
    ) -> Optional[Any]:
        """Get cached anchor table"""
        key = self._make_key("anchor_table", workload_type)
        return self.get(key)
    
    def cache_metadata(
        self,
        message_id: int,
        metadata: Dict[str, Any],
        ttl: Optional[int] = None
    ) -> bool:
        """Cache message metadata"""
        key = self._make_key("metadata", message_id)
        return self.set(key, metadata, ttl)
    
    def get_cached_metadata(
        self,
        message_id: int
    ) -> Optional[Dict[str, Any]]:
        """Get cached metadata"""
        key = self._make_key("metadata", message_id)
        return self.get(key)
    
    def invalidate_search_cache(self, pattern: Optional[str] = None):
        """
        Invalidate search cache entries.
        
        Args:
            pattern: Optional pattern to match (None = invalidate all)
        """
        if self.redis_client:
            try:
                if pattern:
                    keys = self.redis_client.keys(f"spectra:search:{pattern}*")
                else:
                    keys = self.redis_client.keys("spectra:search:*")
                
                if keys:
                    self.redis_client.delete(*keys)
                    logger.info(f"Invalidated {len(keys)} cache entries")
            except Exception as e:
                logger.error(f"Cache invalidation failed: {e}")
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get cache statistics"""
        total_requests = self.stats['hits'] + self.stats['misses']
        hit_rate = (
            self.stats['hits'] / total_requests * 100
            if total_requests > 0 else 0.0
        )
        
        return {
            **self.stats,
            'total_requests': total_requests,
            'hit_rate_percent': hit_rate,
            'redis_available': self.redis_client is not None,
            'memcached_available': self.memcached_client is not None,
        }
    
    def clear_all(self):
        """Clear all cache entries"""
        if self.redis_client:
            try:
                keys = self.redis_client.keys("spectra:*")
                if keys:
                    self.redis_client.delete(*keys)
                    logger.info(f"Cleared {len(keys)} cache entries")
            except Exception as e:
                logger.error(f"Cache clear failed: {e}")
