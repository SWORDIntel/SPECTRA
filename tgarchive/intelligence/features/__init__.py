"""
SPECTRA Intelligence Feature Extractors
=======================================
Feature extraction and comparison modules for identity resolution and attribution.

Modules:
- linguistic: Stylometric, lexical, punctuation, and structural feature extractors
- temporal: Circadian, weekday/weekend, latency, and burst feature extractors
- formatting: Markdown, lists, code, and layout structure extractors (L5)
- notation: Numeric, currency, date/time, unit, and version notation extractors (L6)
- register: Formality score, slang, profanity, jargon, and social register extractors (L7)
"""
from __future__ import annotations

from .conditional import (
    compare_conditional_features,
    extract_conditional_features,
)
from .dialogue_acts import (
    compare_dialogue_acts_features,
    extract_dialogue_acts_features,
)
from .formatting import extract_formatting_features
from .interaction import (
    compare_interaction_features,
    extract_interaction_features,
)
from .linguistic import (
    compare_linguistic_features,
    extract_linguistic_features,
)
from .notation import extract_notation_features
from .register import extract_register_features
from .temporal import (
    compare_temporal_features,
    extract_temporal_features,
)

__all__ = [
    "extract_conditional_features",
    "compare_conditional_features",
    "extract_interaction_features",
    "compare_interaction_features",
    "extract_dialogue_acts_features",
    "compare_dialogue_acts_features",
    "extract_linguistic_features",
    "compare_linguistic_features",
    "extract_temporal_features",
    "compare_temporal_features",
    "extract_formatting_features",
    "extract_notation_features",
    "extract_register_features",
]

