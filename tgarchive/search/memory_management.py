"""
Memory-Bounded Anchor Table Management
======================================

Manages NOT_STISLA anchor tables with memory limits to prevent excessive
memory usage while maintaining optimal search performance.
"""

import logging
from typing import Dict, Optional
from pathlib import Path

from .not_stisla_bindings import (
    NotStislaSearchEngine,
    not_stisla_available,
    NOT_STISLA_MAX_ANCHORS,
)

logger = logging.getLogger(__name__)


class NotStislaMemoryManager:
    """
    Manages NOT_STISLA anchor table memory usage.
    
    Implements memory-bounded anchor tables with automatic pruning
    to prevent excessive memory consumption.
    """
    
    def __init__(self, max_memory_mb: int = 64):
        """
        Initialize memory manager.
        
        Args:
            max_memory_mb: Maximum memory budget in MB for all anchor tables
        """
        self.max_memory = max_memory_mb * 1024 * 1024  # Convert to bytes
        self.anchor_tables: Dict[int, NotStislaSearchEngine] = {}
        self.usage_counts: Dict[int, int] = {}  # Track usage for LRU pruning
    
    def get_anchor_table(self, workload_type: int) -> Optional[NotStislaSearchEngine]:
        """
        Get or create anchor table with memory limits.
        
        Args:
            workload_type: Workload type identifier
        
        Returns:
            Anchor table engine or None if unavailable
        """
        if not not_stisla_available():
            return None
        
        # Return existing table if available
        if workload_type in self.anchor_tables:
            self.usage_counts[workload_type] = self.usage_counts.get(workload_type, 0) + 1
            return self.anchor_tables[workload_type]
        
        # Check memory budget before creating new table
        current_memory = self._estimate_total_memory()
        estimated_new_memory = self._estimate_anchor_table_memory()
        
        if current_memory + estimated_new_memory > self.max_memory:
            logger.warning(f"Memory limit reached ({current_memory / 1024 / 1024:.1f}MB). Pruning anchor tables.")
            self.prune_anchor_tables()
        
        # Create new anchor table
        try:
            from .not_stisla_config import create_spectra_anchor_table
            table = create_spectra_anchor_table(workload_type)
            
            # Set memory limit per table
            if table.anchor_table:
                from .not_stisla_bindings import _lib
                if _lib:
                    _lib.not_stisla_anchor_table_set_memory_limit(
                        table.anchor_table, NOT_STISLA_MAX_ANCHORS
                    )
            
            self.anchor_tables[workload_type] = table
            self.usage_counts[workload_type] = 1
            
            logger.info(f"Created anchor table for workload {workload_type}")
            return table
            
        except Exception as e:
            logger.error(f"Failed to create anchor table for workload {workload_type}: {e}")
            return None
    
    def _estimate_anchor_table_memory(self) -> int:
        """
        Estimate memory usage for a single anchor table.
        
        Returns:
            Estimated memory in bytes
        """
        # Each anchor is ~32 bytes (int64 value + size_t index + uint32 use_count + uint64 last_used)
        # Max anchors per table is 16
        # Plus overhead for structure (~100 bytes)
        anchor_size = 32
        max_anchors = NOT_STISLA_MAX_ANCHORS
        overhead = 100
        
        return (anchor_size * max_anchors) + overhead
    
    def _estimate_total_memory(self) -> int:
        """
        Estimate total memory usage for all anchor tables.
        
        Returns:
            Total estimated memory in bytes
        """
        return len(self.anchor_tables) * self._estimate_anchor_table_memory()
    
    def prune_anchor_tables(self, prune_ratio: float = 0.25):
        """
        Prune least-used anchor tables when memory limit exceeded.
        
        Args:
            prune_ratio: Fraction of tables to prune (0.0-1.0)
        """
        if not self.anchor_tables:
            return
        
        # Sort by usage count (least used first)
        sorted_tables = sorted(
            self.usage_counts.items(),
            key=lambda x: x[1]
        )
        
        # Calculate how many to prune
        num_to_prune = max(1, int(len(sorted_tables) * prune_ratio))
        
        pruned_count = 0
        for workload_type, _ in sorted_tables[:num_to_prune]:
            if workload_type in self.anchor_tables:
                try:
                    # Reset anchor table (clear anchors but keep structure)
                    table = self.anchor_tables[workload_type]
                    table.reset()
                    
                    # Remove from tracking
                    del self.anchor_tables[workload_type]
                    del self.usage_counts[workload_type]
                    
                    pruned_count += 1
                    logger.info(f"Pruned anchor table for workload {workload_type}")
                except Exception as e:
                    logger.warning(f"Failed to prune anchor table {workload_type}: {e}")
        
        logger.info(f"Pruned {pruned_count} anchor tables to free memory")
    
    def get_memory_usage(self) -> Dict[str, float]:
        """
        Get current memory usage statistics.
        
        Returns:
            Dict with memory usage information
        """
        total_estimated = self._estimate_total_memory()
        num_tables = len(self.anchor_tables)
        
        return {
            'total_memory_mb': total_estimated / 1024 / 1024,
            'max_memory_mb': self.max_memory / 1024 / 1024,
            'memory_usage_percent': (total_estimated / self.max_memory) * 100,
            'num_anchor_tables': num_tables,
            'memory_per_table_mb': (total_estimated / num_tables / 1024 / 1024) if num_tables > 0 else 0,
        }
    
    def cleanup(self):
        """Cleanup all anchor tables"""
        for workload_type, table in list(self.anchor_tables.items()):
            try:
                del table
            except:
                pass
        
        self.anchor_tables.clear()
        self.usage_counts.clear()
        logger.info("Cleaned up all anchor tables")
