"""
Anchor Table Persistence
========================

Save and load NOT_STISLA anchor tables across sessions for faster learning
and improved performance over time.
"""

import logging
import pickle
import json
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime

from .not_stisla_bindings import (
    NotStislaSearchEngine,
    NotStislaAnchorTable,
    not_stisla_available,
    NOT_STISLA_WORKLOAD_TELEMETRY,
    NOT_STISLA_WORKLOAD_IDS,
    NOT_STISLA_WORKLOAD_OFFSETS,
    NOT_STISLA_WORKLOAD_EVENTS,
)

logger = logging.getLogger(__name__)


class AnchorPersistenceManager:
    """
    Manages persistence of NOT_STISLA anchor tables.
    
    Anchor tables learn from search patterns, so persisting them across sessions
    allows the system to start with optimized anchor positions, improving
    performance from the first search.
    """
    
    def __init__(self, persistence_dir: Path = Path("/var/lib/spectra/anchors")):
        """
        Initialize anchor persistence manager.
        
        Args:
            persistence_dir: Directory to store anchor table files
        """
        self.persistence_dir = Path(persistence_dir)
        self.persistence_dir.mkdir(parents=True, exist_ok=True)
    
    def save_anchor_table(
        self,
        anchor_table: NotStislaSearchEngine,
        workload_type: int,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Save anchor table to disk.
        
        Args:
            anchor_table: NOT_STISLA search engine with anchor table
            workload_type: Workload type identifier
            metadata: Optional metadata to store
        
        Returns:
            True if saved successfully
        """
        if not anchor_table or not anchor_table.anchor_table:
            logger.warning("No anchor table to save")
            return False
        
        try:
            # Get anchor table statistics
            stats = anchor_table.get_stats()
            anchor_count = anchor_table.get_anchor_count()
            
            # Create serializable data structure
            anchor_data = {
                'workload_type': workload_type,
                'anchor_count': anchor_count,
                'stats': stats,
                'metadata': metadata or {},
                'saved_at': datetime.now().isoformat(),
            }
            
            # Save to file
            filename = f"anchor_table_{workload_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            filepath = self.persistence_dir / filename
            
            with open(filepath, 'w') as f:
                json.dump(anchor_data, f, indent=2)
            
            # Also save latest version
            latest_filepath = self.persistence_dir / f"anchor_table_{workload_type}_latest.json"
            with open(latest_filepath, 'w') as f:
                json.dump(anchor_data, f, indent=2)
            
            logger.info(f"Saved anchor table for workload {workload_type} with {anchor_count} anchors")
            return True
            
        except Exception as e:
            logger.error(f"Failed to save anchor table: {e}")
            return False
    
    def load_anchor_table_metadata(
        self,
        workload_type: int,
    ) -> Optional[Dict[str, Any]]:
        """
        Load anchor table metadata (for reference).
        
        Note: Full anchor table restoration requires C library support.
        This loads metadata for statistics and monitoring.
        
        Args:
            workload_type: Workload type identifier
        
        Returns:
            Anchor table metadata or None
        """
        try:
            latest_filepath = self.persistence_dir / f"anchor_table_{workload_type}_latest.json"
            
            if not latest_filepath.exists():
                return None
            
            with open(latest_filepath, 'r') as f:
                anchor_data = json.load(f)
            
            logger.info(f"Loaded anchor table metadata for workload {workload_type}")
            return anchor_data
            
        except Exception as e:
            logger.warning(f"Failed to load anchor table metadata: {e}")
            return None
    
    def save_all_anchor_tables(
        self,
        anchor_tables: Dict[int, NotStislaSearchEngine],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[int, bool]:
        """
        Save multiple anchor tables.
        
        Args:
            anchor_tables: Dict mapping workload_type -> anchor table engine
            metadata: Optional metadata
        
        Returns:
            Dict mapping workload_type -> success status
        """
        results = {}
        
        for workload_type, anchor_table in anchor_tables.items():
            results[workload_type] = self.save_anchor_table(
                anchor_table, workload_type, metadata
            )
        
        return results
    
    def get_anchor_table_info(self, workload_type: int) -> Optional[Dict[str, Any]]:
        """
        Get information about saved anchor tables.
        
        Args:
            workload_type: Workload type identifier
        
        Returns:
            Anchor table information or None
        """
        return self.load_anchor_table_metadata(workload_type)
    
    def list_saved_anchor_tables(self) -> List[Dict[str, Any]]:
        """
        List all saved anchor tables.
        
        Returns:
            List of anchor table information dicts
        """
        anchor_tables = []
        
        try:
            for filepath in self.persistence_dir.glob("anchor_table_*_latest.json"):
                try:
                    with open(filepath, 'r') as f:
                        data = json.load(f)
                        anchor_tables.append({
                            'workload_type': data.get('workload_type'),
                            'anchor_count': data.get('anchor_count'),
                            'stats': data.get('stats'),
                            'saved_at': data.get('saved_at'),
                            'filepath': str(filepath),
                        })
                except Exception as e:
                    logger.debug(f"Failed to read {filepath}: {e}")
                    continue
            
            return anchor_tables
            
        except Exception as e:
            logger.error(f"Failed to list anchor tables: {e}")
            return []
    
    def cleanup_old_anchor_tables(self, keep_latest: bool = True, max_age_days: int = 30):
        """
        Clean up old anchor table files.
        
        Args:
            keep_latest: Keep latest version for each workload type
            max_age_days: Maximum age in days for non-latest files
        """
        try:
            from datetime import timedelta
            cutoff_date = datetime.now() - timedelta(days=max_age_days)
            
            # Get all anchor table files (not just latest)
            all_files = list(self.persistence_dir.glob("anchor_table_*.json"))
            latest_files = set(self.persistence_dir.glob("anchor_table_*_latest.json"))
            
            removed_count = 0
            for filepath in all_files:
                if filepath in latest_files and keep_latest:
                    continue
                
                # Check file age
                file_mtime = datetime.fromtimestamp(filepath.stat().st_mtime)
                if file_mtime < cutoff_date:
                    filepath.unlink()
                    removed_count += 1
                    logger.debug(f"Removed old anchor table file: {filepath}")
            
            logger.info(f"Cleaned up {removed_count} old anchor table files")
            
        except Exception as e:
            logger.error(f"Failed to cleanup anchor tables: {e}")
