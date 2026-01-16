"""
NOT_STISLA Configuration for SPECTRA Workloads
===============================================

Workload-specific configuration for NOT_STISLA search optimizations.
"""

from typing import Dict, Any
from .not_stisla_bindings import (
    NOT_STISLA_WORKLOAD_TELEMETRY,
    NOT_STISLA_WORKLOAD_IDS,
    NOT_STISLA_WORKLOAD_OFFSETS,
    NOT_STISLA_WORKLOAD_EVENTS,
    NOT_STISLA_MAX_ANCHORS,
    NotStislaSearchEngine,
)


# SPECTRA workload type mappings
SPECTRA_WORKLOAD_TELEMETRY = NOT_STISLA_WORKLOAD_TELEMETRY
SPECTRA_WORKLOAD_IDS = NOT_STISLA_WORKLOAD_IDS
SPECTRA_WORKLOAD_OFFSETS = NOT_STISLA_WORKLOAD_OFFSETS
SPECTRA_WORKLOAD_EVENTS = NOT_STISLA_WORKLOAD_EVENTS


# Workload-specific tolerance recommendations
WORKLOAD_TOLERANCES = {
    NOT_STISLA_WORKLOAD_TELEMETRY: 8,   # Timestamps with variable gaps
    NOT_STISLA_WORKLOAD_IDS: 8,          # Uniform ID distributions
    NOT_STISLA_WORKLOAD_OFFSETS: 16,     # Exponential offset patterns
    NOT_STISLA_WORKLOAD_EVENTS: 12,      # Burst event patterns
}


def get_optimal_tolerance(workload_type: int) -> int:
    """Get optimal tolerance for workload type"""
    return WORKLOAD_TOLERANCES.get(workload_type, 8)


def configure_not_stisla_for_spectra(anchor_table: NotStislaSearchEngine, 
                                     workload_type: int) -> bool:
    """
    Configure anchor table for SPECTRA workload
    
    Args:
        anchor_table: NOT_STISLA anchor table instance
        workload_type: SPECTRA workload type
    
    Returns:
        True if configuration successful
    """
    try:
        # Set memory limit (max 16 anchors per table)
        anchor_table._lib.not_stisla_anchor_table_set_memory_limit(
            anchor_table.anchor_table, NOT_STISLA_MAX_ANCHORS
        )
        
        # Optimize for workload
        result = anchor_table._lib.not_stisla_anchor_table_optimize_for_workload(
            anchor_table.anchor_table, workload_type
        )
        
        return result == 0
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Failed to configure NOT_STISLA: {e}")
        return False


def create_spectra_anchor_table(workload_type: int) -> NotStislaSearchEngine:
    """
    Create and configure anchor table for SPECTRA workload
    
    Args:
        workload_type: SPECTRA workload type
    
    Returns:
        Configured NOT_STISLA search engine
    """
    engine = NotStislaSearchEngine(workload_type)
    configure_not_stisla_for_spectra(engine, workload_type)
    return engine


# Workload detection helpers
def detect_workload_from_data(data: list, data_type: str = "auto") -> int:
    """
    Detect workload type from data characteristics
    
    Args:
        data: Sample data array
        data_type: Data type hint ("timestamp", "id", "offset", "event", "auto")
    
    Returns:
        Detected workload type
    """
    if data_type != "auto":
        type_map = {
            "timestamp": NOT_STISLA_WORKLOAD_TELEMETRY,
            "id": NOT_STISLA_WORKLOAD_IDS,
            "offset": NOT_STISLA_WORKLOAD_OFFSETS,
            "event": NOT_STISLA_WORKLOAD_EVENTS,
        }
        return type_map.get(data_type, NOT_STISLA_WORKLOAD_TELEMETRY)
    
    # Auto-detect based on data patterns
    if len(data) < 10:
        return NOT_STISLA_WORKLOAD_TELEMETRY  # Default
    
    # Calculate gaps
    gaps = [data[i+1] - data[i] for i in range(len(data)-1)]
    if not gaps:
        return NOT_STISLA_WORKLOAD_TELEMETRY
    
    avg_gap = sum(gaps) / len(gaps)
    gap_variance = sum((g - avg_gap) ** 2 for g in gaps) / len(gaps)
    cv = (gap_variance ** 0.5) / avg_gap if avg_gap > 0 else 0
    
    # High variance = telemetry/events (variable gaps)
    if cv > 0.5:
        # Check for burst patterns (events)
        if any(g == 0 for g in gaps[:min(100, len(gaps))]):
            return NOT_STISLA_WORKLOAD_EVENTS
        return NOT_STISLA_WORKLOAD_TELEMETRY
    
    # Low variance = uniform (IDs)
    if cv < 0.1:
        return NOT_STISLA_WORKLOAD_IDS
    
    # Exponential growth = offsets
    if data[-1] / data[0] > 100 and len(data) > 100:
        return NOT_STISLA_WORKLOAD_OFFSETS
    
    return NOT_STISLA_WORKLOAD_TELEMETRY  # Default
