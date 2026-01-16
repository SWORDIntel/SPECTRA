"""
QIHSE Configuration for SPECTRA
================================

Configuration management for QIHSE search operations.
"""

from typing import Dict, Any, Optional
from .qihse_bindings import (
    QihseConfig,
    QihseAmplificationConfig,
    QihseVerifyConfig,
    QIHSE_TYPE_DOUBLE,
    QIHSE_VERIFY_WINDOW,
    QIHSE_PIPELINE_BALANCED,
    qihse_available,
    _qihse_lib,
    byref,
)


def create_qihse_config(data_type: int = QIHSE_TYPE_DOUBLE, 
                       array_size: int = 1000,
                       confidence_threshold: float = 0.95,
                       use_heterogeneous: bool = True) -> Optional[QihseConfig]:
    """
    Create and configure QIHSE config for SPECTRA
    
    Args:
        data_type: QIHSE data type
        array_size: Size of array to search
        confidence_threshold: Minimum confidence threshold
        use_heterogeneous: Enable heterogeneous parallel computing
    
    Returns:
        Configured QIHSE config or None if QIHSE unavailable
    """
    if not qihse_available():
        return None
    
    config = QihseConfig()
    result = _qihse_lib.qihse_config_init(byref(config), data_type, array_size)
    
    if result != 0:
        return None
    
    # Configure for SPECTRA use case
    config.use_heterogeneous = use_heterogeneous
    config.enable_acceleration = True
    config.verification.mode = QIHSE_VERIFY_WINDOW
    config.verification.min_confidence = confidence_threshold
    config.verification.fallback_to_classical = True
    config.anchor_config.enable_anchor_learning = True
    config.anchor_config.max_anchors = 16
    config.enable_profiling = True
    
    return config


def configure_qihse_for_semantic_search(config: QihseConfig, 
                                        embedding_dim: int = 384,
                                        confidence_threshold: float = 0.95):
    """
    Configure QIHSE for semantic/vector search operations
    
    Args:
        config: QIHSE config to configure
        embedding_dim: Embedding dimension (typically 384 for sentence-transformers)
        confidence_threshold: Minimum confidence threshold
    """
    config.data_type = QIHSE_TYPE_DOUBLE
    config.fixed_dimensions = embedding_dim
    config.auto_dimensions = False
    config.verification.min_confidence = confidence_threshold
    config.use_heterogeneous = True
    config.enable_acceleration = True


def configure_qihse_for_clustering(config: QihseConfig, num_clusters: int = 10):
    """
    Configure QIHSE for clustering operations
    
    Args:
        config: QIHSE config to configure
        num_clusters: Number of clusters
    """
    config.use_parallel_pipelines = True
    config.max_parallel_pipelines = min(num_clusters, 8)
    config.enable_profiling = True
