"""
Performance Benchmarks for Search Algorithms
============================================

Comprehensive benchmark suite for validating performance improvements
from NOT_STISLA and QIHSE integrations.
"""

import time
import logging
from typing import List, Tuple
from datetime import datetime, timedelta
import bisect

logger = logging.getLogger(__name__)


def benchmark_not_stisla_vs_binary(
    timestamps: List[int],
    target: int,
    anchor_table=None,
    tolerance: int = 8,
) -> Tuple[float, float, float]:
    """
    Benchmark NOT_STISLA vs Python binary search.
    
    Args:
        timestamps: Sorted list of timestamps
        target: Target timestamp to find
        anchor_table: Optional NOT_STISLA anchor table
        tolerance: Search tolerance
    
    Returns:
        Tuple of (binary_time, not_stisla_time, speedup)
    """
    # Binary search
    start = time.perf_counter_ns()
    idx_binary = bisect.bisect_left(timestamps, target)
    if idx_binary < len(timestamps) and timestamps[idx_binary] == target:
        found_binary = True
    else:
        found_binary = False
    time_binary = time.perf_counter_ns() - start
    
    # NOT_STISLA search
    time_not_stisla = None
    found_not_stisla = False
    
    try:
        from ..search.not_stisla_bindings import search_timestamps
        
        start = time.perf_counter_ns()
        idx_not_stisla = search_timestamps(timestamps, target, anchor_table, tolerance)
        time_not_stisla = time.perf_counter_ns() - start
        
        found_not_stisla = idx_not_stisla is not None
    except ImportError:
        logger.warning("NOT_STISLA not available for benchmarking")
        return time_binary / 1e9, None, None
    
    if time_not_stisla:
        speedup = time_binary / time_not_stisla if time_not_stisla > 0 else 0
        return time_binary / 1e9, time_not_stisla / 1e9, speedup
    
    return time_binary / 1e9, None, None


def benchmark_qihse_vs_qdrant(
    vectors,
    query_vector,
    qdrant_client=None,
    qihse_engine=None,
) -> Tuple[float, float, float]:
    """
    Benchmark QIHSE vs Qdrant semantic search.
    
    Args:
        vectors: Array of vectors
        query_vector: Query vector
        qdrant_client: Qdrant client
        qihse_engine: QIHSE search engine
    
    Returns:
        Tuple of (qdrant_time, qihse_time, speedup)
    """
    # Qdrant search
    time_qdrant = None
    if qdrant_client:
        try:
            start = time.perf_counter_ns()
            results = qdrant_client.search(
                collection_name="spectra_messages",
                query_vector=query_vector.tolist(),
                limit=20,
            )
            time_qdrant = time.perf_counter_ns() - start
        except Exception as e:
            logger.warning(f"Qdrant benchmark failed: {e}")
    
    # QIHSE search
    time_qihse = None
    if qihse_engine:
        try:
            import numpy as np
            vectors_array = np.array(vectors, dtype=np.float64)
            query_array = np.array(query_vector, dtype=np.float64)
            
            start = time.perf_counter_ns()
            results = qihse_engine.search_vectors(vectors_array, query_array)
            time_qihse = time.perf_counter_ns() - start
        except Exception as e:
            logger.warning(f"QIHSE benchmark failed: {e}")
    
    if time_qdrant and time_qihse:
        speedup = time_qdrant / time_qihse if time_qihse > 0 else 0
        return time_qdrant / 1e9, time_qihse / 1e9, speedup
    
    return time_qdrant / 1e9 if time_qdrant else None, time_qihse / 1e9 if time_qihse else None, None


def run_comprehensive_benchmarks():
    """Run comprehensive benchmark suite"""
    results = {
        'not_stisla': {},
        'qihse': {},
        'hybrid': {},
    }
    
    # Generate test data
    print("Generating test data...")
    timestamps = sorted([int((datetime.now() - timedelta(days=i)).timestamp()) for i in range(1000000)])
    target = timestamps[500000]
    
    # Benchmark NOT_STISLA
    print("Benchmarking NOT_STISLA vs binary search...")
    binary_time, not_stisla_time, speedup = benchmark_not_stisla_vs_binary(timestamps, target)
    
    results['not_stisla'] = {
        'binary_time_ns': binary_time * 1e9,
        'not_stisla_time_ns': not_stisla_time * 1e9 if not_stisla_time else None,
        'speedup': speedup,
        'array_size': len(timestamps),
    }
    
    print(f"NOT_STISLA Results:")
    print(f"  Binary search: {binary_time*1e6:.2f} μs")
    if not_stisla_time:
        print(f"  NOT_STISLA: {not_stisla_time*1e6:.2f} μs")
        print(f"  Speedup: {speedup:.2f}x")
    
    return results


if __name__ == "__main__":
    results = run_comprehensive_benchmarks()
    print("\nBenchmark Results:")
    print(results)
