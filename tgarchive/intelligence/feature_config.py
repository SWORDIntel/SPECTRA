"""
SPECTRA Intelligence — Per-Target Feature Configuration
=======================================================
Stores and loads tunable feature-extraction parameters per persona target.

The GLM-5.2 calibration loop outputs a ````config` block with suggested
parameter changes.  This module parses, stores, and serves those configs
so feature extractors can read target-specific thresholds/weights at
extraction time without code changes.

Storage: QIHSE KV store (primary) with JSON sidecar fallback.
Key scheme: ``persona_config:<target_id>`` → JSON config blob
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Default config — mirrors the hardcoded values in the feature extractors.
# When a target has no stored config, these defaults are used (identical to
# the pre-config behavior, so existing targets are unaffected).
DEFAULT_CONFIG: Dict[str, Any] = {
    # ── Snapshot ───────────────────────────────────────────────────────────
    "vocabulary_limit": 200,
    "log_odds_alpha": 0.5,
    "knowledge_base_conf_k": 5.0,        # base_conf = n / (n + k)
    "knowledge_contradiction_scale": 0.25,  # variance / scale

    # ── Register (L7) ──────────────────────────────────────────────────────
    "register_formality_weights": {
        "word_length": 0.35,
        "cleanliness": 0.35,
        "sentence_complexity": 0.18,
        "formal_markers": 0.12,
    },
    "register_cleanliness_multiplier": 8.0,
    "register_formal_marker_multiplier": 10.0,
    "register_scream_penalty_multiplier": 4.0,
    "register_scream_penalty_cap": 0.4,
    "register_word_length_offset": 3.5,
    "register_word_length_scale": 3.0,
    "register_sentence_length_offset": 4.0,
    "register_sentence_length_scale": 20.0,

    # ── Conversation (L8) ──────────────────────────────────────────────────
    "conversation_burst_gap_seconds": 300.0,
    "conversation_double_message_seconds": 60.0,
    "conversation_idle_seconds": 1800.0,

    # ── Temporal (L9) ──────────────────────────────────────────────────────
    "temporal_session_gap_seconds": 1800.0,
    "temporal_burst_threshold_large": 5,    # when total_messages >= 10
    "temporal_burst_threshold_small": 3,    # when total_messages < 10
    "temporal_burst_window_seconds": 3600,
    "temporal_drift_windows_days": [30, 90, 365],

    # ── Conditional (L10) ──────────────────────────────────────────────────
    "conditional_max_contexts": 50,
    "conditional_length_short": 50,
    "conditional_length_long": 200,

    # ── Interaction (L11) ──────────────────────────────────────────────────
    "interaction_length_scale": 200.0,

    # ── Discourse (L3) ─────────────────────────────────────────────────────
    "discourse_compare_rate_weight": 0.6,
    "discourse_compare_dist_weight": 0.4,

    # ── Errors (L2) ────────────────────────────────────────────────────────
    "errors_max_edit_distance": 2,

    # ── Orthographic (L1) ──────────────────────────────────────────────────
    "orthographic_char_ngram_sizes": [2, 3, 4, 5, 6],
    "orthographic_char_ngram_top_k": 200,
    "orthographic_word_boundary_top_k": 100,
    "orthographic_punctuation_top_k": 50,

    # ── Notation (L6) ──────────────────────────────────────────────────────
    "notation_distribution_top_k": 50,

    # ── Layer weights for scoring (used by score_example) ──────────────────
    "layer_weights": {
        "orthographic": 1.0,
        "errors": 1.0,
        "discourse": 1.0,
        "syntax": 1.0,
        "formatting": 1.0,
        "notation": 1.0,
        "register": 1.0,
        "conversation": 1.0,
        "temporal": 1.0,
        "conditional": 1.0,
        "interaction": 1.0,
        "dialogue_acts": 1.0,
        "linguistic": 1.0,
    },
}

# Default storage paths
_DEFAULT_DIR = Path("data/qihse")
_DEFAULT_JSON = _DEFAULT_DIR / "persona_configs.json"

_lock = threading.Lock()
_cache: Dict[str, dict] = {}  # target_id -> config dict
_kv_store: Optional[object] = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_json_path(path: Optional[str | Path] = None) -> Path:
    if path is not None:
        return Path(path)
    env = os.environ.get("SPECTRA_CONFIG_JSON")
    if env:
        return Path(env)
    return _DEFAULT_JSON


def _get_kv_store():
    """Lazily get the QIHSE KV store singleton (shared with lexicon_store)."""
    global _kv_store
    if _kv_store is not None:
        return _kv_store
    try:
        from tgarchive.search.qihse_bindings import QihseKVStore
        from tgarchive.intelligence.lexicon_store import _resolve_snapshot_path
        snapshot = _resolve_snapshot_path()
        if snapshot.exists():
            store = QihseKVStore(snapshot_path=str(snapshot))
        else:
            store = QihseKVStore()
        _kv_store = store
        return _kv_store
    except Exception:
        _kv_store = None
        return None


def _kv_key(target_id: str) -> str:
    return f"persona_config:{target_id}"


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base (override wins)."""
    result = dict(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


def get_config(target_id: str, *, path: Optional[str | Path] = None) -> Dict[str, Any]:
    """Get the effective feature config for a target.

    Merges the target's stored overrides on top of DEFAULT_CONFIG.
    If the target has no stored config, returns DEFAULT_CONFIG unchanged.
    """
    with _lock:
        if target_id in _cache:
            return _cache[target_id]

        # Try QIHSE KV first
        store = _get_kv_store()
        stored = None
        if store is not None:
            try:
                raw = store.get(_kv_key(target_id))
                if raw:
                    stored = json.loads(raw)
            except Exception:
                pass

        # Fallback to JSON sidecar
        if stored is None:
            p = _resolve_json_path(path)
            try:
                if p.exists():
                    all_configs = json.loads(p.read_text(encoding="utf-8"))
                    stored = all_configs.get(target_id)
            except (json.JSONDecodeError, OSError):
                pass

        if stored is None:
            config = dict(DEFAULT_CONFIG)
        else:
            config = _deep_merge(DEFAULT_CONFIG, stored)

        _cache[target_id] = config
        return config


def set_config(
    target_id: str,
    overrides: Dict[str, Any],
    *,
    added_by: str = "glm-5.2",
    path: Optional[str | Path] = None,
) -> None:
    """Set config overrides for a target (merges with existing overrides)."""
    with _lock:
        # Load existing overrides
        existing = {}
        p = _resolve_json_path(path)
        try:
            if p.exists():
                all_configs = json.loads(p.read_text(encoding="utf-8"))
                existing = all_configs.get(target_id, {})
        except (json.JSONDecodeError, OSError):
            all_configs = {}

        # Merge new overrides
        merged = _deep_merge(existing, overrides)
        merged["__updated_by"] = added_by
        merged["__updated_at"] = _now()

        # Save to QIHSE KV
        store = _get_kv_store()
        if store is not None:
            try:
                store.set(_kv_key(target_id), json.dumps(merged))
            except Exception as exc:
                logger.warning("Failed to save config to QIHSE KV: %s", exc)

        # Save to JSON sidecar
        if not p.exists():
            all_configs = {}
        try:
            all_configs[target_id] = merged
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(all_configs, indent=2, sort_keys=True), encoding="utf-8")
        except OSError as exc:
            logger.warning("Failed to save config to JSON: %s", exc)

        # Update cache
        _cache[target_id] = _deep_merge(DEFAULT_CONFIG, merged)
        logger.info("Feature config updated for target %s (by %s)", target_id, added_by)


def reset_config(target_id: str, *, path: Optional[str | Path] = None) -> None:
    """Reset a target's config to defaults (removes all overrides)."""
    with _lock:
        store = _get_kv_store()
        if store is not None:
            try:
                store.delete(_kv_key(target_id))
            except Exception:
                pass

        p = _resolve_json_path(path)
        try:
            if p.exists():
                all_configs = json.loads(p.read_text(encoding="utf-8"))
                if target_id in all_configs:
                    del all_configs[target_id]
                    p.write_text(json.dumps(all_configs, indent=2, sort_keys=True), encoding="utf-8")
        except (json.JSONDecodeError, OSError):
            pass

        _cache.pop(target_id, None)


def parse_config_block(text: str) -> Dict[str, Any]:
    """Parse a structured config block from GLM-5.2 output.

    Expected format:
        ## Feature Config
        ```config
        vocabulary_limit: 300
        register_formality_weights.word_length: 0.40
        conversation_burst_gap_seconds: 180
        layer_weights.discourse: 1.5
        layer_weights.register: 0.8
        ```
    """
    result: Dict[str, Any] = {}
    in_block = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "```config":
            in_block = True
            continue
        if in_block and stripped == "```":
            break
        if not in_block or not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            continue
        key_part, val_part = stripped.split(":", 1)
        key = key_part.strip()
        val_str = val_part.strip()

        # Parse value type
        try:
            if val_str.lower() in ("true", "false"):
                val: Any = val_str.lower() == "true"
            elif val_str.startswith("[") and val_str.endswith("]"):
                val = json.loads(val_str)
            elif "." in val_str:
                val = float(val_str)
            else:
                val = int(val_str)
        except (ValueError, json.JSONDecodeError):
            val = val_str

        # Support dotted keys → nested dict
        parts = key.split(".")
        d = result
        for p in parts[:-1]:
            d = d.setdefault(p, {})
        d[parts[-1]] = val

    return result


def apply_config_from_text(
    text: str,
    target_id: str,
    *,
    added_by: str = "glm-5.2",
    path: Optional[str | Path] = None,
) -> Dict[str, Any]:
    """Parse GLM-5.2 output and apply any config changes.

    Returns the parsed overrides (empty dict if none found).
    """
    overrides = parse_config_block(text)
    if not overrides:
        return {}
    set_config(target_id, overrides, added_by=added_by, path=path)
    return overrides


__all__ = [
    "DEFAULT_CONFIG",
    "get_config",
    "set_config",
    "reset_config",
    "parse_config_block",
    "apply_config_from_text",
]
