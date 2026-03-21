"""
Forwarding package exports.
"""
from __future__ import annotations

from importlib import import_module

__all__ = [
    "AttachmentForwarder",
    "QueueManager",
    "Workflows",
    "EnhancedAttachmentForwarder",
    "TopicManager",
    "TopicCreationStrategy",
    "ContentClassifier",
    "OrganizationEngine",
    "OrganizationMode",
]

_EXPORTS = {
    "AttachmentForwarder": ".forwarder",
    "QueueManager": ".queue",
    "Workflows": ".workflows",
    "EnhancedAttachmentForwarder": ".enhanced_forwarder",
    "TopicManager": ".topic_manager",
    "TopicCreationStrategy": ".topic_manager",
    "ContentClassifier": ".content_classifier",
    "OrganizationEngine": ".organization_engine",
    "OrganizationMode": ".organization_engine",
}


def __getattr__(name: str):
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_name, __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value
