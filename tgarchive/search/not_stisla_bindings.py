"""
NOT_STISLA Python FFI Bindings
==============================

Python ctypes wrapper for NOT_STISLA C library providing:
- 22.28x speedup over binary search for sorted arrays
- Anchor-based interpolation search with learning
- Memory-bounded anchor tables
- Workload-specific optimizations
- Runtime CPU feature detection (AVX2/AVX-512/AMX)
"""

import ctypes
import os
import sys
from ctypes import (
    c_int64, c_size_t, c_void_p, c_uint32, c_uint64, c_double,
    POINTER, Structure, c_int, c_bool, byref
)
from pathlib import Path
from typing import List, Optional, Tuple
import logging

logger = logging.getLogger(__name__)

# Constants from not_stisla.h
NOT_STISLA_NOT_FOUND = 0xFFFFFFFFFFFFFFFF
NOT_STISLA_MAX_ANCHORS = 16
NOT_STISLA_CHUNK_SIZE = 4
NOT_STISLA_MIN_ANCHORS = 2

# Workload types
NOT_STISLA_WORKLOAD_TELEMETRY = 0
NOT_STISLA_WORKLOAD_IDS = 1
NOT_STISLA_WORKLOAD_OFFSETS = 2
NOT_STISLA_WORKLOAD_EVENTS = 3

# Error codes
NOT_STISLA_SUCCESS = 0
NOT_STISLA_ERROR_INVALID_PARAM = -1
NOT_STISLA_ERROR_MEMORY = -2
NOT_STISLA_ERROR_NOT_FOUND = -3


class NotStislaAnchor(Structure):
    """Anchor structure for interpolation search"""
    _fields_ = [
        ("v", c_int64),           # value
        ("i", c_size_t),          # index
        ("use_count", c_uint32),  # usage frequency
        ("last_used", c_uint64),  # timestamp for LRU
    ]


class NotStislaStats(Structure):
    """Statistics structure"""
    _fields_ = [
        ("searches_total", c_uint64),
        ("searches_successful", c_uint64),
        ("anchors_learned", c_uint64),
        ("anchors_pruned", c_uint64),
        ("memory_reallocations", c_uint64),
        ("avg_search_time_ns", c_double),
        ("avg_interpolation_error", c_double),
        ("cpu_features_detected", c_uint32),
    ]


class NotStislaAnchorTable(Structure):
    """Anchor table structure"""
    _fields_ = [
        ("anchors", POINTER(NotStislaAnchor)),
        ("capacity", c_size_t),
        ("size", c_size_t),
        ("max_capacity", c_size_t),
        ("searches_performed", c_size_t),
        ("workload_type", c_int),
        ("stats", NotStislaStats),
        ("creation_time", c_uint64),
    ]


class NotStislaConfig(Structure):
    """Configuration structure"""
    _fields_ = [
        ("tol", c_size_t),
        ("enable_anchor_learning", c_int),
        ("enable_profiling", c_int),
        ("strict_mode", c_int),
    ]


class NotStislaBatchItem(Structure):
    """Batch search item"""
    _fields_ = [
        ("key", c_int64),
        ("result", c_size_t),
        ("ordinal", c_size_t),
    ]


class NotStislaParallelConfig(Structure):
    """Parallel search configuration"""
    _fields_ = [
        ("num_threads", c_int),
        ("use_thread_pool", c_int),
        ("batch_chunk", c_size_t),
    ]


# Load NOT_STISLA library
def _load_not_stisla_library():
    """Load NOT_STISLA shared library"""
    # Try multiple possible locations
    possible_paths = [
        # Relative to SPECTRA root
        Path(__file__).parent.parent.parent.parent.parent / "libs" / "search_algorithms" / "not_stisla" / "libnot_stisla.so",
        Path(__file__).parent.parent.parent.parent.parent / "libs" / "search_algorithms" / "not_stisla" / "libnot_stisla.a",
        # System library paths
        Path("/usr/local/lib/libnot_stisla.so"),
        Path("/usr/lib/libnot_stisla.so"),
        # Current directory
        Path("libnot_stisla.so"),
    ]
    
    for lib_path in possible_paths:
        if lib_path.exists():
            try:
                lib = ctypes.CDLL(str(lib_path))
                logger.info(f"Loaded NOT_STISLA library from {lib_path}")
                return lib
            except OSError as e:
                logger.debug(f"Failed to load {lib_path}: {e}")
                continue
    
    # Try loading by name (if in LD_LIBRARY_PATH)
    try:
        lib = ctypes.CDLL("libnot_stisla.so")
        logger.info("Loaded NOT_STISLA library from system path")
        return lib
    except OSError:
        logger.warning("NOT_STISLA library not found. Some features will be unavailable.")
        return None


_lib = _load_not_stisla_library()

if _lib is not None:
    # Define function signatures
    _lib.not_stisla_anchor_table_create.argtypes = []
    _lib.not_stisla_anchor_table_create.restype = POINTER(NotStislaAnchorTable)
    
    _lib.not_stisla_anchor_table_destroy.argtypes = [POINTER(NotStislaAnchorTable)]
    _lib.not_stisla_anchor_table_destroy.restype = None
    
    _lib.not_stisla_anchor_table_size.argtypes = [POINTER(NotStislaAnchorTable)]
    _lib.not_stisla_anchor_table_size.restype = c_size_t
    
    _lib.not_stisla_anchor_table_reset.argtypes = [POINTER(NotStislaAnchorTable)]
    _lib.not_stisla_anchor_table_reset.restype = None
    
    _lib.not_stisla_anchor_table_set_memory_limit.argtypes = [POINTER(NotStislaAnchorTable), c_size_t]
    _lib.not_stisla_anchor_table_set_memory_limit.restype = c_int
    
    _lib.not_stisla_anchor_table_optimize_for_workload.argtypes = [POINTER(NotStislaAnchorTable), c_int]
    _lib.not_stisla_anchor_table_optimize_for_workload.restype = c_int
    
    _lib.not_stisla_detect_cpu_features.argtypes = []
    _lib.not_stisla_detect_cpu_features.restype = c_uint32
    
    _lib.not_stisla_search.argtypes = [
        POINTER(c_int64),  # arr
        c_size_t,          # n
        c_int64,           # key
        POINTER(NotStislaAnchorTable),  # table
        c_size_t           # tol
    ]
    _lib.not_stisla_search.restype = c_size_t
    
    _lib.not_stisla_search_enhanced.argtypes = [
        POINTER(c_int64),  # arr
        c_size_t,          # n
        c_int64,           # key
        POINTER(NotStislaAnchorTable),  # table
        POINTER(NotStislaConfig)       # config
    ]
    _lib.not_stisla_search_enhanced.restype = c_size_t
    
    _lib.not_stisla_search_batch.argtypes = [
        POINTER(c_int64),              # arr
        c_size_t,                      # n
        POINTER(NotStislaBatchItem),   # items
        c_size_t,                      # num_items
        POINTER(NotStislaAnchorTable), # table
        c_size_t                       # tol
    ]
    _lib.not_stisla_search_batch.restype = c_size_t
    
    _lib.not_stisla_search_parallel.argtypes = [
        POINTER(c_int64),                  # arr
        c_size_t,                          # n
        POINTER(NotStislaBatchItem),       # items
        c_size_t,                          # num_items
        POINTER(NotStislaAnchorTable),     # table
        c_size_t,                          # tol
        POINTER(NotStislaParallelConfig)   # config
    ]
    _lib.not_stisla_search_parallel.restype = c_size_t
    
    _lib.not_stisla_anchor_table_get_stats.argtypes = [POINTER(NotStislaAnchorTable)]
    _lib.not_stisla_anchor_table_get_stats.restype = POINTER(NotStislaStats)
    
    _lib.not_stisla_version.argtypes = []
    _lib.not_stisla_version.restype = ctypes.c_char_p
    
    _lib.not_stisla_build_info.argtypes = []
    _lib.not_stisla_build_info.restype = ctypes.c_char_p


def not_stisla_available() -> bool:
    """Check if NOT_STISLA library is available"""
    return _lib is not None


class NotStislaSearchEngine:
    """Python interface for NOT_STISLA search operations"""
    
    def __init__(self, workload_type: int = NOT_STISLA_WORKLOAD_TELEMETRY):
        """Initialize NOT_STISLA search engine"""
        if not not_stisla_available():
            raise RuntimeError("NOT_STISLA library not available")
        
        self.workload_type = workload_type
        self.anchor_table = None
        self._create_anchor_table()
    
    def _create_anchor_table(self):
        """Create and configure anchor table"""
        if _lib is None:
            return
        
        self.anchor_table = _lib.not_stisla_anchor_table_create()
        if not self.anchor_table:
            raise RuntimeError("Failed to create NOT_STISLA anchor table")
        
        # Set memory limit
        _lib.not_stisla_anchor_table_set_memory_limit(self.anchor_table, NOT_STISLA_MAX_ANCHORS)
        
        # Optimize for workload
        _lib.not_stisla_anchor_table_optimize_for_workload(self.anchor_table, self.workload_type)
    
    def __del__(self):
        """Cleanup anchor table"""
        if self.anchor_table and _lib:
            _lib.not_stisla_anchor_table_destroy(self.anchor_table)
    
    def search(self, arr: List[int], key: int, tolerance: int = 8) -> Optional[int]:
        """
        Search for key in sorted array using NOT_STISLA
        
        Args:
            arr: Sorted array of integers
            key: Value to search for
            tolerance: Search tolerance (8-16 recommended)
        
        Returns:
            Index of found element, or None if not found
        """
        if not arr or not self.anchor_table:
            return None
        
        # Convert Python list to C array
        n = len(arr)
        c_arr = (c_int64 * n)(*arr)
        
        # Perform search
        result = _lib.not_stisla_search(
            c_arr, n, c_int64(key), self.anchor_table, c_size_t(tolerance)
        )
        
        if result == NOT_STISLA_NOT_FOUND:
            return None
        
        return int(result)
    
    def search_enhanced(self, arr: List[int], key: int, config: Optional[dict] = None) -> Optional[int]:
        """
        Enhanced search with configuration
        
        Args:
            arr: Sorted array of integers
            key: Value to search for
            config: Optional configuration dict
        
        Returns:
            Index of found element, or None if not found
        """
        if not arr or not self.anchor_table:
            return None
        
        # Create config structure
        not_stisla_config = NotStislaConfig()
        if config:
            not_stisla_config.tol = config.get('tolerance', 8)
            not_stisla_config.enable_anchor_learning = 1 if config.get('enable_learning', True) else 0
        else:
            not_stisla_config.tol = 8
            not_stisla_config.enable_anchor_learning = 1
        
        n = len(arr)
        c_arr = (c_int64 * n)(*arr)
        
        result = _lib.not_stisla_search_enhanced(
            c_arr, n, c_int64(key), self.anchor_table, byref(not_stisla_config)
        )
        
        if result == NOT_STISLA_NOT_FOUND:
            return None
        
        return int(result)
    
    def search_batch(self, arr: List[int], keys: List[int], tolerance: int = 8) -> List[Optional[int]]:
        """
        Batch search for multiple keys
        
        Args:
            arr: Sorted array of integers
            keys: List of keys to search for
            tolerance: Search tolerance
        
        Returns:
            List of indices (None if not found)
        """
        if not arr or not keys or not self.anchor_table:
            return [None] * len(keys)
        
        n = len(arr)
        num_keys = len(keys)
        
        # Create C array for data
        c_arr = (c_int64 * n)(*arr)
        
        # Create batch items
        batch_items = (NotStislaBatchItem * num_keys)()
        for i, key in enumerate(keys):
            batch_items[i].key = c_int64(key)
            batch_items[i].ordinal = c_size_t(i)
        
        # Perform batch search
        found_count = _lib.not_stisla_search_batch(
            c_arr, n, batch_items, num_keys, self.anchor_table, c_size_t(tolerance)
        )
        
        # Extract results
        results = []
        for i in range(num_keys):
            if batch_items[i].result == NOT_STISLA_NOT_FOUND:
                results.append(None)
            else:
                results.append(int(batch_items[i].result))
        
        return results
    
    def search_parallel(self, arr: List[int], keys: List[int], 
                       num_threads: int = 0, tolerance: int = 8) -> List[Optional[int]]:
        """
        Parallel batch search across multiple threads
        
        Args:
            arr: Sorted array of integers
            keys: List of keys to search for
            num_threads: Number of threads (0 = auto-detect)
            tolerance: Search tolerance
        
        Returns:
            List of indices (None if not found)
        """
        if not arr or not keys or not self.anchor_table:
            return [None] * len(keys)
        
        n = len(arr)
        num_keys = len(keys)
        
        # Create C array for data
        c_arr = (c_int64 * n)(*arr)
        
        # Create batch items
        batch_items = (NotStislaBatchItem * num_keys)()
        for i, key in enumerate(keys):
            batch_items[i].key = c_int64(key)
            batch_items[i].ordinal = c_size_t(i)
        
        # Create parallel config
        parallel_config = NotStislaParallelConfig()
        parallel_config.num_threads = c_int(num_threads)
        parallel_config.use_thread_pool = c_int(0)
        parallel_config.batch_chunk = c_size_t(max(1, num_keys // (num_threads or 4)))
        
        # Perform parallel search
        found_count = _lib.not_stisla_search_parallel(
            c_arr, n, batch_items, num_keys, self.anchor_table, 
            c_size_t(tolerance), byref(parallel_config)
        )
        
        # Extract results
        results = []
        for i in range(num_keys):
            if batch_items[i].result == NOT_STISLA_NOT_FOUND:
                results.append(None)
            else:
                results.append(int(batch_items[i].result))
        
        return results
    
    def get_stats(self) -> dict:
        """Get search statistics"""
        if not self.anchor_table:
            return {}
        
        stats_ptr = _lib.not_stisla_anchor_table_get_stats(self.anchor_table)
        if not stats_ptr:
            return {}
        
        stats = stats_ptr.contents
        return {
            'searches_total': stats.searches_total,
            'searches_successful': stats.searches_successful,
            'anchors_learned': stats.anchors_learned,
            'anchors_pruned': stats.anchors_pruned,
            'memory_reallocations': stats.memory_reallocations,
            'avg_search_time_ns': stats.avg_search_time_ns,
            'avg_interpolation_error': stats.avg_interpolation_error,
            'cpu_features_detected': stats.cpu_features_detected,
        }
    
    def reset(self):
        """Reset anchor table (clear learned anchors)"""
        if self.anchor_table:
            _lib.not_stisla_anchor_table_reset(self.anchor_table)
    
    def get_anchor_count(self) -> int:
        """Get number of anchors in table"""
        if not self.anchor_table:
            return 0
        return int(_lib.not_stisla_anchor_table_size(self.anchor_table))


def detect_cpu_features() -> dict:
    """Detect available CPU features"""
    if not _lib:
        return {}
    
    features = _lib.not_stisla_detect_cpu_features()
    return {
        'AVX2': bool(features & 0x01),
        'AVX512': bool(features & 0x02),
        'AMX': bool(features & 0x04),
        'VNNI': bool(features & 0x08),
    }


def get_version() -> str:
    """Get NOT_STISLA version string"""
    if not _lib:
        return "NOT_STISLA not available"
    
    version_ptr = _lib.not_stisla_version()
    if version_ptr:
        return version_ptr.decode('utf-8')
    return "unknown"


def get_build_info() -> str:
    """Get NOT_STISLA build information"""
    if not _lib:
        return "NOT_STISLA not available"
    
    info_ptr = _lib.not_stisla_build_info()
    if info_ptr:
        return info_ptr.decode('utf-8')
    return "unknown"


# Convenience functions for common operations
def search_timestamps(timestamps: List[int], target: int, 
                     anchor_table: Optional[NotStislaSearchEngine] = None,
                     tolerance: int = 8) -> Optional[int]:
    """
    Search sorted timestamp array using NOT_STISLA
    
    Args:
        timestamps: Sorted list of Unix timestamps
        target: Target timestamp to find
        anchor_table: Optional anchor table (creates new if None)
        tolerance: Search tolerance
    
    Returns:
        Index of found timestamp, or None if not found
    """
    if not not_stisla_available():
        # Fallback to binary search
        import bisect
        idx = bisect.bisect_left(timestamps, target)
        if idx < len(timestamps) and timestamps[idx] == target:
            return idx
        return None
    
    if anchor_table is None:
        engine = NotStislaSearchEngine(NOT_STISLA_WORKLOAD_TELEMETRY)
        result = engine.search(timestamps, target, tolerance)
        del engine
        return result
    else:
        return anchor_table.search(timestamps, target, tolerance)


def search_message_ids(message_ids: List[int], target_id: int,
                      anchor_table: Optional[NotStislaSearchEngine] = None,
                      tolerance: int = 8) -> Optional[int]:
    """
    Search sorted message ID array using NOT_STISLA
    
    Args:
        message_ids: Sorted list of message IDs
        target_id: Target message ID to find
        anchor_table: Optional anchor table
        tolerance: Search tolerance
    
    Returns:
        Index of found message ID, or None if not found
    """
    if not not_stisla_available():
        import bisect
        idx = bisect.bisect_left(message_ids, target_id)
        if idx < len(message_ids) and message_ids[idx] == target_id:
            return idx
        return None
    
    if anchor_table is None:
        engine = NotStislaSearchEngine(NOT_STISLA_WORKLOAD_IDS)
        result = engine.search(message_ids, target_id, tolerance)
        del engine
        return result
    else:
        return anchor_table.search(message_ids, target_id, tolerance)


def search_offsets(offsets: List[int], target_offset: int,
                  anchor_table: Optional[NotStislaSearchEngine] = None,
                  tolerance: int = 16) -> Optional[int]:
    """
    Search sorted file offset array using NOT_STISLA
    
    Args:
        offsets: Sorted list of file offsets
        target_offset: Target offset to find
        anchor_table: Optional anchor table
        tolerance: Search tolerance (higher for exponential patterns)
    
    Returns:
        Index of found offset, or None if not found
    """
    if not not_stisla_available():
        import bisect
        idx = bisect.bisect_left(offsets, target_offset)
        if idx < len(offsets) and offsets[idx] == target_offset:
            return idx
        return None
    
    if anchor_table is None:
        engine = NotStislaSearchEngine(NOT_STISLA_WORKLOAD_OFFSETS)
        result = engine.search(offsets, target_offset, tolerance)
        del engine
        return result
    else:
        return anchor_table.search(offsets, target_offset, tolerance)
