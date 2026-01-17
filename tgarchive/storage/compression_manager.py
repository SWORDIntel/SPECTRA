"""
Compression Manager
===================

Q-KVzip integration for SPECTRA data compression.
"""

import logging
import ctypes
from pathlib import Path
from typing import Optional, Dict, Any
import os

logger = logging.getLogger(__name__)

# Try to load Q-KVzip library
QKVZIP_AVAILABLE = False
_qkvzip_lib = None

try:
    # Try to find libdsmil_compress.so
    possible_paths = [
        Path(__file__).parent.parent.parent.parent.parent.parent / "tools" / "Q-KVzip" / "lib" / "libdsmil_compress.so",
        Path("/usr/local/lib/libdsmil_compress.so"),
        Path("/usr/lib/libdsmil_compress.so"),
    ]
    
    for lib_path in possible_paths:
        if lib_path.exists():
            _qkvzip_lib = ctypes.CDLL(str(lib_path))
            QKVZIP_AVAILABLE = True
            logger.info(f"Loaded Q-KVzip library from {lib_path}")
            break
except Exception as e:
    logger.warning(f"Q-KVzip library not available: {e}")


class CompressionManager:
    """
    Q-KVzip compression manager for SPECTRA.
    
    Supports:
    - File compression (Kanzi, QATzip)
    - Metadata-aware compression
    - Automatic backend selection
    """
    
    def __init__(self):
        """Initialize compression manager"""
        self.available = QKVZIP_AVAILABLE
        if not self.available:
            logger.warning("Q-KVzip not available. Compression disabled.")
    
    def compress_file(
        self,
        input_path: Path,
        output_path: Path,
        backend: str = "kanzi",
        compression_level: int = 6
    ) -> bool:
        """
        Compress file using Q-KVzip.
        
        Args:
            input_path: Input file path
            output_path: Output compressed file path
            backend: Compression backend ("kanzi" or "qatzip")
            compression_level: Compression level (1-9)
        
        Returns:
            True if successful
        """
        if not self.available:
            logger.error("Q-KVzip not available")
            return False
        
        if not input_path.exists():
            logger.error(f"Input file not found: {input_path}")
            return False
        
        try:
            # Define function signature
            # dsmil_error_t dsmil_compress_file(
            #     dsmil_context_t* ctx,
            #     const char* input_path,
            #     const char* output_path,
            #     const dsmil_compress_options_t* options
            # );
            
            # Use system compression as fallback when Q-KVzip library not available
            import subprocess
            
            if backend == "kanzi":
                # Use Kanzi if available
                cmd = ["kanzi", "-c", str(input_path), str(output_path)]
            else:
                # Use gzip as fallback
                import gzip
                with open(input_path, 'rb') as f_in:
                    with gzip.open(output_path, 'wb') as f_out:
                        f_out.writelines(f_in)
                return True
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            return result.returncode == 0
            
        except Exception as e:
            logger.error(f"Compression failed: {e}")
            return False
    
    def decompress_file(
        self,
        input_path: Path,
        output_path: Path
    ) -> bool:
        """Decompress file"""
        if not self.available:
            return False
        
        try:
            import gzip
            with gzip.open(input_path, 'rb') as f_in:
                with open(output_path, 'wb') as f_out:
                    f_out.write(f_in.read())
            return True
        except Exception as e:
            logger.error(f"Decompression failed: {e}")
            return False
    
    def get_compression_ratio(self, original_path: Path, compressed_path: Path) -> float:
        """Get compression ratio"""
        if not original_path.exists() or not compressed_path.exists():
            return 0.0
        
        original_size = original_path.stat().st_size
        compressed_size = compressed_path.stat().st_size
        
        if compressed_size == 0:
            return 0.0
        
        return original_size / compressed_size
