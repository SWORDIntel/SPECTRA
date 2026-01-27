"""
SPECTRA API Service Layer
==========================

Service abstractions that wrap SPECTRA core modules for API access.
"""

from .tasks import TaskManager, TaskStatus
from .archive_service import ArchiveService
from .discovery_service import DiscoveryService
from .forwarding_service import ForwardingService
from .threat_service import ThreatService
from .analytics_service import AnalyticsService
from .ml_service import MLService
from .crypto_service import CryptoService
from .database_service import DatabaseService

__all__ = [
    'TaskManager',
    'TaskStatus',
    'ArchiveService',
    'DiscoveryService',
    'ForwardingService',
    'ThreatService',
    'AnalyticsService',
    'MLService',
    'CryptoService',
    'DatabaseService',
]
