"""
Archive Compressor
==================

Automatic compression policies for SPECTRA archives.
"""

import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

from .compression_manager import CompressionManager

logger = logging.getLogger(__name__)


class ArchiveCompressor:
    """
    Automatic compression for archived data.
    
    Policies:
    - Compress old messages (>30 days)
    - Compress large media files
    - Compress database backups
    """
    
    def __init__(self, compression_manager: CompressionManager):
        """Initialize archive compressor"""
        self.compression = compression_manager
        self.compression_age_days = 30
        self.large_file_threshold_mb = 10
    
    def compress_old_archives(
        self,
        archive_dir: Path,
        age_days: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Compress archives older than specified age.
        
        Args:
            archive_dir: Directory containing archives
            age_days: Age threshold in days (default: 30)
        
        Returns:
            List of compression results
        """
        age_days = age_days or self.compression_age_days
        cutoff_date = datetime.now() - timedelta(days=age_days)
        
        results = []
        
        for archive_file in archive_dir.glob("*.json"):
            try:
                file_mtime = datetime.fromtimestamp(archive_file.stat().st_mtime)
                
                if file_mtime < cutoff_date:
                    compressed_path = archive_file.with_suffix('.json.gz')
                    
                    if self.compression.compress_file(archive_file, compressed_path):
                        # Remove original after successful compression
                        archive_file.unlink()
                        
                        ratio = self.compression.get_compression_ratio(archive_file, compressed_path)
                        results.append({
                            'file': str(archive_file),
                            'compressed': str(compressed_path),
                            'ratio': ratio,
                            'status': 'success',
                        })
                    else:
                        results.append({
                            'file': str(archive_file),
                            'status': 'failed',
                        })
            except Exception as e:
                logger.error(f"Failed to compress {archive_file}: {e}")
                results.append({
                    'file': str(archive_file),
                    'status': 'error',
                    'error': str(e),
                })
        
        return results
    
    def compress_large_files(
        self,
        file_dir: Path,
        threshold_mb: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Compress large files.
        
        Args:
            file_dir: Directory containing files
            threshold_mb: Size threshold in MB
        
        Returns:
            List of compression results
        """
        threshold_mb = threshold_mb or self.large_file_threshold_mb
        threshold_bytes = threshold_mb * 1024 * 1024
        
        results = []
        
        for file_path in file_dir.rglob("*"):
            if file_path.is_file() and file_path.suffix not in ['.gz', '.zip', '.compressed']:
                try:
                    file_size = file_path.stat().st_size
                    
                    if file_size > threshold_bytes:
                        compressed_path = file_path.with_suffix(file_path.suffix + '.gz')
                        
                        if self.compression.compress_file(file_path, compressed_path):
                            file_path.unlink()
                            
                            ratio = self.compression.get_compression_ratio(file_path, compressed_path)
                            results.append({
                                'file': str(file_path),
                                'compressed': str(compressed_path),
                                'ratio': ratio,
                                'original_size_mb': file_size / (1024 * 1024),
                                'status': 'success',
                            })
                except Exception as e:
                    logger.error(f"Failed to compress {file_path}: {e}")
        
        return results
    
    def compress_database_backup(self, backup_path: Path) -> bool:
        """Compress database backup"""
        if not backup_path.exists():
            return False
        
        compressed_path = backup_path.with_suffix(backup_path.suffix + '.gz')
        
        if self.compression.compress_file(backup_path, compressed_path):
            backup_path.unlink()
            return True
        
        return False
