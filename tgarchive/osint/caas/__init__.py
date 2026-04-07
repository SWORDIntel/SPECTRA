"""CAAS-focused OSINT helpers for SPECTRA.

This package contains:
- discovery_fingerprint: fast Layer 0 semantic triage for discovered channels
- profiler: slower Layer 1 message-level profiling
- worker: queue-backed processing loop for offline enrichment
"""

from .discovery_fingerprint import ChannelFingerprintEngine
from .profiler import CAASProfiler
from .aggregator import ActorDossierAggregator
from .market_intel import MarketIntelligenceEngine

__all__ = ["ChannelFingerprintEngine", "CAASProfiler", "ActorDossierAggregator", "MarketIntelligenceEngine"]
