"""LRU Cache implementation for session metadata."""

from __future__ import annotations

import logging
import time
from collections import OrderedDict
from threading import Lock
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class SessionMetadataCache:
    """Thread-safe LRU cache for session metadata.
    
    This cache helps reduce MongoDB queries for frequently accessed sessions
    by keeping metadata in memory with automatic eviction of least recently used items.
    """
    
    def __init__(self, max_size: int = 1000, ttl_seconds: int = 300) -> None:
        """Initialize the LRU cache.
        
        Args:
            max_size: Maximum number of items to cache
            ttl_seconds: Time-to-live for cached items in seconds
        """
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self._cache: OrderedDict[str, Tuple[Dict[str, Any], float]] = OrderedDict()
        self._lock = Lock()
        self._hits = 0
        self._misses = 0
        
        logger.info(f"Initialized session metadata cache - max_size: {max_size}, ttl: {ttl_seconds}s")
    
    def get(self, key: str) -> Optional[Dict[str, Any]]:
        """Get a value from the cache.
        
        Args:
            key: The cache key (session_id)
            
        Returns:
            The cached value or None if not found/expired
        """
        with self._lock:
            if key not in self._cache:
                self._misses += 1
                return None
            
            # Check if expired
            value, timestamp = self._cache[key]
            if time.time() - timestamp > self.ttl_seconds:
                # Expired - remove it
                del self._cache[key]
                self._misses += 1
                return None
            
            # Move to end (most recently used)
            self._cache.move_to_end(key)
            self._hits += 1
            return value.copy()  # Return a copy to prevent external modifications
    
    def put(self, key: str, value: Dict[str, Any]) -> None:
        """Put a value in the cache.
        
        Args:
            key: The cache key (session_id)
            value: The value to cache
        """
        with self._lock:
            # Remove if already exists to update position
            if key in self._cache:
                del self._cache[key]
            
            # Add to end (most recently used)
            self._cache[key] = (value.copy(), time.time())
            
            # Evict oldest if over capacity
            if len(self._cache) > self.max_size:
                # Remove first (least recently used)
                self._cache.popitem(last=False)
    
    def invalidate(self, key: str) -> None:
        """Remove a specific item from the cache.
        
        Args:
            key: The cache key to invalidate
        """
        with self._lock:
            self._cache.pop(key, None)
    
    def clear(self) -> None:
        """Clear all items from the cache."""
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics.
        
        Returns:
            Dictionary with cache statistics
        """
        with self._lock:
            total_requests = self._hits + self._misses
            hit_rate = self._hits / total_requests if total_requests > 0 else 0
            
            return {
                "size": len(self._cache),
                "max_size": self.max_size,
                "ttl_seconds": self.ttl_seconds,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": hit_rate,
                "total_requests": total_requests
            }


class CachedMongoDBSessionManager:
    """Wrapper for MongoDBSessionManager with metadata caching.
    
    This class adds a caching layer on top of the standard session manager
    to optimize metadata lookups in high-traffic scenarios.
    """
    
    def __init__(
        self,
        session_manager: Any,  # MongoDBSessionManager instance
        cache: Optional[SessionMetadataCache] = None
    ) -> None:
        """Initialize the cached session manager.
        
        Args:
            session_manager: The underlying MongoDB session manager
            cache: Optional shared cache instance (creates new if not provided)
        """
        self.session_manager = session_manager
        self.cache = cache or SessionMetadataCache()
        
        # Delegate all attributes to the underlying manager
        self._delegate_attributes()
    
    def _delegate_attributes(self) -> None:
        """Set up attribute delegation to the underlying session manager."""
        # List of methods/attributes to delegate
        delegated = [
            'session_id', 'append_message', 'sync_agent', 'start_timing',
            'set_token_counts', 'get_metrics_summary', 'close',
            'session_repository', '_start_time', '_last_input_tokens',
            '_last_output_tokens', '_agent_configs', '_latest_agent_message'
        ]
        
        for attr in delegated:
            if hasattr(self.session_manager, attr):
                setattr(self, attr, getattr(self.session_manager, attr))
    
    def check_session_exists(self, agent_id: Optional[str] = None) -> Dict[str, Any]:
        """Check if session exists with caching.
        
        Args:
            agent_id: Optional specific agent ID to check
            
        Returns:
            Session existence and metadata information
        """
        # Create cache key
        cache_key = f"{self.session_manager.session_id}:{agent_id or 'all'}"
        
        # Try cache first
        cached_result = self.cache.get(cache_key)
        if cached_result is not None:
            logger.debug(f"Cache hit for session check: {cache_key}")
            return cached_result
        
        # Cache miss - get from database
        logger.debug(f"Cache miss for session check: {cache_key}")
        result = self.session_manager.check_session_exists(agent_id)
        
        # Cache the result if session exists
        if result['exists']:
            self.cache.put(cache_key, result)
        
        return result
    
    def invalidate_cache(self) -> None:
        """Invalidate all cache entries for this session."""
        # Invalidate all possible cache keys for this session
        session_id = self.session_manager.session_id
        self.cache.invalidate(f"{session_id}:all")
        
        # Also invalidate any agent-specific entries
        # This is a simple approach - in production you might track which keys exist
        if hasattr(self.session_manager, '_agent_configs'):
            for agent_id in self.session_manager._agent_configs:
                self.cache.invalidate(f"{session_id}:{agent_id}")


# Global cache instance for sharing across session managers
_global_metadata_cache: Optional[SessionMetadataCache] = None


def get_global_metadata_cache(
    max_size: int = 1000,
    ttl_seconds: int = 300
) -> SessionMetadataCache:
    """Get or create the global metadata cache.
    
    Args:
        max_size: Maximum cache size (only used on first call)
        ttl_seconds: Cache TTL (only used on first call)
        
    Returns:
        The global cache instance
    """
    global _global_metadata_cache
    
    if _global_metadata_cache is None:
        _global_metadata_cache = SessionMetadataCache(
            max_size=max_size,
            ttl_seconds=ttl_seconds
        )
    
    return _global_metadata_cache