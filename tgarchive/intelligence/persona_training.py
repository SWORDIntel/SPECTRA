"""Longitudinal persona training-data model for authorized targets.

This module builds a consent-based persona corpus and knowledge profile:

* Positive examples: target-authored or target-approved text.
* Negative examples: counterexamples, other authors, copied content, or
  otherwise unsuitable data. Negatives are temporally matched to positives
  where practical so a downstream model learns what the target *does not* say.
* Review examples: uncertain material — never treated as positive by default.
* Domain knowledge observations: ``score`` (measurement) is kept distinct from
  ``confidence`` (trust in the measurement). Both are normalized to [0, 1].
* Longitudinal snapshots: vocabulary, distinctive vocabulary (positive relative
  to negatives via smoothed log-odds), bigrams, linguistic features, and
  knowledge estimates — preserved over time rather than overwritten.

The model does **not** train or invoke a language model. It builds a
high-quality, auditable corpus/profile suitable for local training under
SPECTRA's air-gapped policy. Export is gated behind explicit authorization and
refuses with ``PermissionError`` unless the target is authorized.

Persistence is handled by ``tgarchive.db.persona_store.PersonaStore``; this
module focuses on analysis and is duck-typed against the store so it can be
unit-tested with fakes.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

# Reuse existing stylometric infrastructure.
from .features.linguistic import extract_linguistic_features

# V2 behavioral feature extractors (standard library only).
try:
    from .features.orthographic import extract_orthographic_features
except ImportError:
    extract_orthographic_features = None
try:
    from .features.errors import extract_error_features
except ImportError:
    extract_error_features = None
try:
    from .features.discourse import extract_discourse_features
except ImportError:
    extract_discourse_features = None
try:
    from .features.formatting import extract_formatting_features
except ImportError:
    extract_formatting_features = None
try:
    from .features.notation import extract_notation_features
except ImportError:
    extract_notation_features = None
try:
    from .features.register import extract_register_features
except ImportError:
    extract_register_features = None
try:
    from .features.conversation import extract_conversation_features
except ImportError:
    extract_conversation_features = None
try:
    from .features.syntax import extract_syntax_features
except ImportError:
    extract_syntax_features = None
try:
    from .features.temporal import extract_temporal_features
except ImportError:
    extract_temporal_features = None
try:
    from .features.conditional import extract_conditional_features
except ImportError:
    extract_conditional_features = None
try:
    from .features.interaction import extract_interaction_features
except ImportError:
    extract_interaction_features = None
try:
    from .features.dialogue_acts import extract_dialogue_acts_features
except ImportError:
    extract_dialogue_acts_features = None
try:
    from .features.boilerplate import filter_messages as _filter_boilerplate
except ImportError:
    _filter_boilerplate = None

_WORD_RE = re.compile(r"\b\w+\b")
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")

# Default domain lexicons for inferred knowledge observations.
# Conservative term lists — a single hit is weak evidence; the estimator
# calibrates score by hit density and confidence by sample size.
DEFAULT_DOMAIN_LEXICONS: Dict[str, frozenset[str]] = {
    "computers": frozenset({
        "code", "script", "server", "client", "kernel", "linux", "windows",
        "python", "javascript", "rust", "c++", "java", "git", "docker",
        "compiler", "binary", "hex", "debug", "patch", "repo", "api",
        "database", "sql", "tcp", "udp", "dns", "ssh", "shell", "bash",
        "regex", "thread", "process", "memory", "cpu", "gpu", "buffer",
        "overflow", "exploit", "vulnerability", "encryption", "cipher",
        "hash", "sha", "aes", "rsa", "tls", "ssl", "http", "https",
        "program", "function", "variable", "class", "object", "pointer",
        "array", "loop", "syntax", "runtime", "bytecode", "opcode",
    }),
    "biology": frozenset({
        "cell", "dna", "rna", "protein", "enzyme", "gene", "genome",
        "membrane", "mitochondria", "nucleus", "ribosome", "chromosome",
        "organism", "tissue", "organ", "neuron", "synapse", "hormone",
        "metabolism", "photosynthesis", "evolution", "species", "genus",
        "bacteria", "virus", "antibody", "immune", "pathogen", "infection",
        "membrane", "cytoplasm", "ecosystem", "habitat", "taxonomy",
        "anatomy", "physiology", "molecule", "lipid", "carbohydrate",
        "amino", "acid", "polymerase", "replication", "transcription",
    }),
    "finance": frozenset({
        "money", "dollar", "euro", "currency", "bank", "account", "loan",
        "credit", "debit", "interest", "principal", "bond", "stock",
        "share", "equity", "dividend", "portfolio", "asset", "liability",
        "revenue", "profit", "loss", "income", "expense", "budget",
        "tax", "audit", "invoice", "transaction", "transfer", "deposit",
        "withdrawal", "forex", "exchange", "inflation", "deflation",
        "market", "trade", "broker", "commodity", "derivative", "option",
    }),
    "security": frozenset({
        "attack", "defend", "threat", "vulnerability", "exploit", "payload",
        "malware", "trojan", "worm", "rootkit", "backdoor", "firewall",
        "ids", "ips", "siem", "soc", "pentest", "redteam", "blueteam",
        "zero-day", "cve", "patch", "hardening", "sandbox", "honeypot",
        "phishing", "spearphishing", "social", "reconnaissance", "foothold",
        "lateral", "exfiltration", "c2", "command", "control", "apt",
        "ransomware", "encryption", "decryption", "forensics", "triage",
    }),
    "medicine": frozenset({
        "patient", "diagnosis", "symptom", "treatment", "therapy", "dose",
        "medication", "drug", "prescription", "clinical", "trial", "study",
        "disease", "syndrome", "chronic", "acute", "infection", "inflammation",
        "surgery", "procedure", "prognosis", "epidemiology", "vaccine",
        "immunization", "antibiotic", "antiviral", "pathology", "radiology",
        "mri", "ct", "ultrasound", "biopsy", "blood", "pressure", "heart",
        "cardiac", "pulmonary", "respiratory", "neurological", "oncology",
    }),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tokenize(text: str) -> List[str]:
    return [t.lower() for t in _WORD_RE.findall(text)]


def _bigrams(tokens: Sequence[str]) -> List[str]:
    return [f"{tokens[i]} {tokens[i+1]}" for i in range(len(tokens) - 1)]


def _smoothed_log_odds(pos_count: int, neg_count: int,
                       alpha: float = 0.5) -> float:
    """Smoothed log-odds ratio for distinctive vocabulary.

    Positive values indicate the word is more characteristic of positives.
    """
    return math.log((pos_count + alpha) / (neg_count + alpha))


def _simple_numeric_similarity(feat_a: Dict[str, Any], feat_b: Dict[str, Any]) -> float:
    """Cosine similarity over shared numeric scalar keys between two feature dicts."""
    import math as _math
    shared = set()
    for k, v in feat_a.items():
        if isinstance(v, (int, float)) and isinstance(feat_b.get(k), (int, float)):
            shared.add(k)
    if not shared:
        return 0.0
    dot = sum(float(feat_a[k]) * float(feat_b[k]) for k in shared)
    norm_a = _math.sqrt(sum(float(feat_a[k]) ** 2 for k in shared))
    norm_b = _math.sqrt(sum(float(feat_b[k]) ** 2 for k in shared))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return max(0.0, min(1.0, dot / (norm_a * norm_b)))


def _import_compare_module(layer_name: str):
    """Lazily import a feature module for its compare function."""
    import importlib
    mod_map = {
        "linguistic": "tgarchive.intelligence.features.linguistic",
        "orthographic": "tgarchive.intelligence.features.orthographic",
        "errors": "tgarchive.intelligence.features.errors",
        "discourse": "tgarchive.intelligence.features.discourse",
        "syntax": "tgarchive.intelligence.features.syntax",
        "conditional": "tgarchive.intelligence.features.conditional",
        "interaction": "tgarchive.intelligence.features.interaction",
        "dialogue_acts": "tgarchive.intelligence.features.dialogue_acts",
    }
    mod_path = mod_map.get(layer_name)
    if mod_path is None:
        return None
    try:
        return importlib.import_module(mod_path)
    except ImportError:
        return None


class PersonaTrainingModel:
    """Analytical model for building, scoring, and exporting persona corpora.

    This class is pure analysis — it does not touch the database directly.
    Persistence is delegated to ``PersonaStore`` (or any duck-typed store).
    """

    MODEL_NAME = "persona-v2"
    MODEL_VERSION = "2.0"

    # ── Example construction ────────────────────────────────────────────

    @staticmethod
    def build_example(
        target_id: str,
        label: str,
        text: str,
        *,
        source_type: str = "message",
        source_message_id: Optional[int] = None,
        source_channel_id: Optional[int] = None,
        source_user_id: Optional[int] = None,
        observed_at: Optional[str] = None,
        weight: float = 1.0,
        notes: str = "",
    ) -> Dict[str, Any]:
        """Build an example dict ready for ``PersonaStore.add_example``."""
        if label not in ("positive", "negative", "review"):
            raise ValueError(f"label must be positive/negative/review, got {label!r}")
        if not text or not isinstance(text, str):
            raise ValueError("text must be a non-empty string")
        if not isinstance(weight, (int, float)) or isinstance(weight, bool) or weight <= 0:
            raise ValueError("weight must be a positive number")
        return {
            "target_id": target_id,
            "label": label,
            "text": text,
            "source_type": source_type,
            "source_message_id": source_message_id,
            "source_channel_id": source_channel_id,
            "source_user_id": source_user_id,
            "observed_at": observed_at,
            "weight": float(weight),
            "notes": notes,
        }

    @staticmethod
    def build_knowledge_observation(
        target_id: str,
        domain: str,
        score: float,
        confidence: float,
        *,
        evidence_source: Optional[str] = None,
        evaluator: str = "manual",
        evaluator_version: str = "1.0",
        observed_at: Optional[str] = None,
        notes: str = "",
    ) -> Dict[str, Any]:
        """Build a knowledge observation dict."""
        for name, value in (("score", score), ("confidence", confidence)):
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise TypeError(f"{name} must be a number")
            if not (0.0 <= float(value) <= 1.0):
                raise ValueError(f"{name} must be in [0.0, 1.0], got {value}")
        if not domain or not isinstance(domain, str):
            raise ValueError("domain must be a non-empty string")
        return {
            "target_id": target_id,
            "domain": domain,
            "score": float(score),
            "confidence": float(confidence),
            "evidence_source": evidence_source,
            "evaluator": evaluator,
            "evaluator_version": evaluator_version,
            "observed_at": observed_at,
            "notes": notes,
        }

    # ── Knowledge estimation ────────────────────────────────────────────

    @staticmethod
    def estimate_knowledge(
        observations: Sequence[Dict[str, Any]],
        *,
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Dict[str, float]]:
        """Aggregate knowledge observations into per-domain estimates.

        Returns ``{domain: {"score": float, "confidence": float, "n": int}}``.

        Score is a confidence-weighted mean (so high-trust observations count
        more). Confidence rises with independent evidence but is bounded [0,1]
        and is reduced by contradictory evidence (high-variance scores).

        config: Optional per-target feature config for tunable k and contradiction scale.
        """
        cfg = config or {}
        base_conf_k = cfg.get("knowledge_base_conf_k", 5.0)
        contradiction_scale = cfg.get("knowledge_contradiction_scale", 0.25)
        by_domain: Dict[str, List[Dict[str, Any]]] = {}
        for obs in observations:
            domain = obs.get("domain")
            if not domain:
                continue
            by_domain.setdefault(domain, []).append(obs)
        estimates: Dict[str, Dict[str, float]] = {}
        for domain, obs_list in by_domain.items():
            n = len(obs_list)
            scores = [float(o.get("score", 0.0)) for o in obs_list]
            confs = [float(o.get("confidence", 0.0)) for o in obs_list]
            total_conf = sum(confidence) if (confidence := confs) else 0.0
            if total_conf > 0:
                weighted_score = sum(s * c for s, c in zip(scores, confs)) / total_conf
            else:
                weighted_score = sum(scores) / n if n else 0.0
            # Confidence: rises with sample size, bounded [0,1].
            # Use a Beta-inspired aggregation: prior Beta(1,1), posterior
            # strength grows with n. Reduce by variance (contradiction).
            base_conf = n / (n + base_conf_k)  # saturates toward 1.0
            if n > 1:
                mean = sum(scores) / n
                variance = sum((s - mean) ** 2 for s in scores) / n
                # Normalize variance to [0,1] (max variance for [0,1] is 0.25)
                contradiction_penalty = min(1.0, variance / contradiction_scale)
                base_conf *= (1.0 - 0.5 * contradiction_penalty)
            # Also factor in average observation confidence.
            avg_obs_conf = (sum(confs) / n) if n else 0.0
            final_conf = base_conf * (0.5 + 0.5 * avg_obs_conf)
            final_conf = max(0.0, min(1.0, final_conf))
            estimates[domain] = {
                "score": round(weighted_score, 4),
                "confidence": round(final_conf, 4),
                "n": n,
            }
        return estimates

    # ── Snapshot building ───────────────────────────────────────────────

    @classmethod
    def build_snapshot(
        cls,
        target_id: str,
        examples: Sequence[Dict[str, Any]],
        observations: Sequence[Dict[str, Any]],
        *,
        as_of: Optional[str] = None,
        vocabulary_limit: int = 200,
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Build a longitudinal persona profile snapshot.

        Only examples with ``observed_at <= as_of`` (or null observed_at) are
        used. Positives drive persona vocabulary/style; negatives are retained
        for counts and contrast.

        config: Optional per-target feature config (from feature_config.get_config).
                When provided, config-driven thresholds/weights override defaults.
        """
        if as_of is None:
            as_of = _now()
        cfg = config or {}
        # Allow config to override vocabulary_limit if not explicitly passed
        if config and vocabulary_limit == 200:
            vocabulary_limit = cfg.get("vocabulary_limit", 200)
        alpha = cfg.get("log_odds_alpha", 0.5)
        # Filter examples by temporal cutoff.
        relevant: List[Dict[str, Any]] = []
        for ex in examples:
            obs = ex.get("observed_at")
            if obs is None or obs <= as_of:
                relevant.append(ex)
        positives = [e for e in relevant if e.get("label") == "positive"]
        negatives = [e for e in relevant if e.get("label") == "negative"]
        reviews = [e for e in relevant if e.get("label") == "review"]

        # Vocabulary from positives.
        pos_tokens: List[str] = []
        for ex in positives:
            pos_tokens.extend(_tokenize(ex.get("text", "")))
        pos_word_counts = Counter(pos_tokens)
        pos_total = len(pos_tokens)

        neg_tokens: List[str] = []
        for ex in negatives:
            neg_tokens.extend(_tokenize(ex.get("text", "")))
        neg_word_counts = Counter(neg_tokens)
        neg_total = len(neg_tokens)

        # Common word frequencies (positives).
        vocabulary: Dict[str, float] = {}
        if pos_total > 0:
            for word, count in pos_word_counts.most_common(vocabulary_limit):
                vocabulary[word] = round(count / pos_total, 6)

        # Distinctive vocabulary: smoothed log-odds (positive vs negative).
        # When there are no negatives, log-odds is degenerate (every positive
        # word appears infinitely more characteristic).  In that case we fall
        # back to raw positive frequency as a weak distinctive signal.
        distinctive: Dict[str, float] = {}
        if pos_total > 0:
            candidates = set(pos_word_counts.keys())
            if neg_total > 0:
                # Standard smoothed log-odds with negative contrast.
                for word in sorted(candidates,
                                   key=lambda w: pos_word_counts[w],
                                   reverse=True)[:vocabulary_limit]:
                    pc = pos_word_counts[word]
                    nc = neg_word_counts.get(word, 0)
                    lo = _smoothed_log_odds(pc, nc, alpha=alpha)
                    distinctive[word] = round(lo, 4)
            else:
                # No negatives — use positive frequency as a fallback.
                # Mark with a flag so downstream consumers know this is
                # not a true contrastive signal.
                for word in sorted(candidates,
                                   key=lambda w: pos_word_counts[w],
                                   reverse=True)[:vocabulary_limit]:
                    pc = pos_word_counts[word]
                    distinctive[word] = round(pc / pos_total, 6)

        # Bigrams from positives.
        pos_bigrams: List[str] = []
        for ex in positives:
            tokens = _tokenize(ex.get("text", ""))
            pos_bigrams.extend(_bigrams(tokens))
        bigram_counts = Counter(pos_bigrams)
        bigrams: Dict[str, float] = {}
        pos_bigram_total = len(pos_bigrams)
        if pos_bigram_total > 0:
            for bg, count in bigram_counts.most_common(vocabulary_limit):
                bigrams[bg] = round(count / pos_bigram_total, 6)

        # Linguistic features from positives (V1 — preserved for backward compat).
        pos_messages = [{"content": ex.get("text", "")} for ex in positives]

        # Apply boilerplate filter to strip forwarding footers, link-only
        # messages, and other platform-injected noise before feature extraction.
        if _filter_boilerplate is not None:
            pos_messages = _filter_boilerplate(pos_messages)
        linguistic_features = extract_linguistic_features(pos_messages)

        # ── V2 behavioral feature layers ──────────────────────────────────
        # Each extractor is optional (graceful degradation if module missing).
        # All extractors receive positive examples as message dicts.
        # Conversation/temporal extractors also use timestamps and metadata.
        orthographic_features = (
            extract_orthographic_features(pos_messages)
            if extract_orthographic_features else {}
        )
        error_features = (
            extract_error_features(pos_messages)
            if extract_error_features else {}
        )
        discourse_features = (
            extract_discourse_features(pos_messages)
            if extract_discourse_features else {}
        )
        formatting_features = (
            extract_formatting_features(pos_messages)
            if extract_formatting_features else {}
        )
        notation_features = (
            extract_notation_features(pos_messages)
            if extract_notation_features else {}
        )
        register_features = (
            extract_register_features(pos_messages, config=cfg)
            if extract_register_features else {}
        )
        syntax_features = (
            extract_syntax_features(pos_messages)
            if extract_syntax_features else {}
        )

        # Conversation and temporal features need full message metadata.
        # Build enriched message dicts from positive examples.
        pos_msgs_meta = []
        for ex in positives:
            msg = {"content": ex.get("text", "")}
            if ex.get("observed_at"):
                msg["date"] = ex["observed_at"]
            if ex.get("source_user_id") is not None:
                msg["user_id"] = ex["source_user_id"]
            if ex.get("source_channel_id") is not None:
                msg["channel_id"] = ex["source_channel_id"]
            if ex.get("source_message_id") is not None:
                msg["id"] = ex["source_message_id"]
            pos_msgs_meta.append(msg)

        conversation_features = (
            extract_conversation_features(pos_msgs_meta, config=cfg)
            if extract_conversation_features else {}
        )
        temporal_features = (
            extract_temporal_features(pos_msgs_meta)
            if extract_temporal_features else {}
        )

        # V2 Phase 2: conditional, interaction, dialogue/affective.
        # These need full message metadata (channel, reply_to, timestamps).
        # Guard against degenerate cases:
        #   - conditional_features: meaningless without negatives to contrast
        #     against (P(feature|context) for a single actor with no baseline
        #     produces all-1.0 conditionals that add noise).
        #   - interaction_features: meaningless with a single channel (no
        #     cross-channel style variation can be measured).
        unique_channels: Set = set()
        for m in pos_msgs_meta:
            ch = m.get("channel_id")
            if ch is not None:
                unique_channels.add(ch)

        if extract_conditional_features and len(negatives) > 0:
            conditional_features = extract_conditional_features(pos_msgs_meta)
        else:
            conditional_features = {}

        if extract_interaction_features and len(unique_channels) > 1:
            interaction_features = extract_interaction_features(pos_msgs_meta)
        else:
            interaction_features = {}

        dialogue_acts_features = (
            extract_dialogue_acts_features(pos_msgs_meta)
            if extract_dialogue_acts_features else {}
        )

        # Knowledge estimates.
        knowledge_estimates = cls.estimate_knowledge(observations, config=cfg)

        return {
            "target_id": target_id,
            "as_of": as_of,
            "positive_count": len(positives),
            "negative_count": len(negatives),
            "review_count": len(reviews),
            "vocabulary": vocabulary,
            "distinctive_vocab": distinctive,
            "bigrams": bigrams,
            "linguistic_features": linguistic_features,
            "knowledge_estimates": knowledge_estimates,
            # V2 behavioral layers
            "orthographic_features": orthographic_features,
            "error_features": error_features,
            "discourse_features": discourse_features,
            "formatting_features": formatting_features,
            "notation_features": notation_features,
            "register_features": register_features,
            "conversation_features": conversation_features,
            "syntax_features": syntax_features,
            "temporal_features": temporal_features,
            # V2 Phase 2
            "conditional_features": conditional_features,
            "interaction_features": interaction_features,
            "dialogue_acts_features": dialogue_acts_features,
            "model": cls.MODEL_NAME,
            "model_version": cls.MODEL_VERSION,
        }

    # ── Per-example scoring (contribution breakdown) ───────────────────

    @classmethod
    def score_example(
        cls,
        snapshot: Dict[str, Any],
        text: str,
        *,
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Score a single text against a persona snapshot.

        Returns a per-feature-layer contribution breakdown showing which
        layers match the persona and which don't.  This is intended for
        the GLM-5.2 calibration loop so it can see *why* an example looks
        like (or unlike) the target.

        Returns:
            {
                "overall_similarity": float,   # weighted mean [0,1]
                "layer_scores": {layer: {"similarity": float, "confidence": float}},
                "weighted_layer_scores": {layer: float},
                "dominant_layers": [str, ...],  # top 3 by weighted score
                "weak_layers": [str, ...],      # bottom 3 by weighted score
                "extracted_features": {...},    # features extracted from the text
            }
        """
        cfg = config or {}
        layer_weights = cfg.get("layer_weights", {})

        # Extract features from the input text as a single-message corpus.
        msg = [{"content": text}]
        if _filter_boilerplate is not None:
            msg = _filter_boilerplate(msg)

        extracted: Dict[str, Dict[str, Any]] = {}
        if extract_linguistic_features:
            extracted["linguistic"] = extract_linguistic_features(msg)
        if extract_orthographic_features:
            extracted["orthographic"] = extract_orthographic_features(msg)
        if extract_error_features:
            extracted["errors"] = extract_error_features(msg)
        if extract_discourse_features:
            extracted["discourse"] = extract_discourse_features(msg)
        if extract_formatting_features:
            extracted["formatting"] = extract_formatting_features(msg)
        if extract_notation_features:
            extracted["notation"] = extract_notation_features(msg)
        if extract_register_features:
            extracted["register"] = extract_register_features(msg, config=cfg)
        if extract_syntax_features:
            extracted["syntax"] = extract_syntax_features(msg)

        # Compare each extracted layer against the snapshot's stored features.
        layer_scores: Dict[str, Dict[str, float]] = {}
        weighted_scores: Dict[str, float] = {}

        # Map layer names to (extracted_key, snapshot_key, compare_function)
        compare_map = [
            ("linguistic", "linguistic_features", "compare_linguistic_features", "linguistic"),
            ("orthographic", "orthographic_features", "compare_orthographic_features", "orthographic"),
            ("errors", "error_features", "compare_error_features", "errors"),
            ("discourse", "discourse_features", "compare_discourse_features", "discourse"),
            ("formatting", "formatting_features", None, "formatting"),
            ("notation", "notation_features", None, "notation"),
            ("register", "register_features", None, "register"),
            ("syntax", "syntax_features", "compare_syntax_features", "syntax"),
            ("conversation", "conversation_features", None, "conversation"),
            ("temporal", "temporal_features", None, "temporal"),
            ("conditional", "conditional_features", "compare_conditional_features", "conditional"),
            ("interaction", "interaction_features", "compare_interaction_features", "interaction"),
            ("dialogue_acts", "dialogue_acts_features", "compare_dialogue_acts_features", "dialogue_acts"),
        ]

        for layer_name, snapshot_key, compare_fn_name, module_key in compare_map:
            snap_feat = snapshot.get(snapshot_key)
            ext_feat = extracted.get(layer_name)
            if snap_feat is None or ext_feat is None:
                # Layer not available in snapshot or couldn't be extracted.
                # For single-message scoring, conversation/temporal/conditional/
                # interaction layers won't have meaningful data — skip them.
                continue

            if compare_fn_name is None:
                # No compare function — use simple numeric cosine similarity.
                sim = _simple_numeric_similarity(snap_feat, ext_feat)
                conf = min(1.0, len(ext_feat) / 10.0) if ext_feat else 0.0
            else:
                try:
                    mod = _import_compare_module(module_key)
                    fn = getattr(mod, compare_fn_name, None)
                    if fn is not None:
                        result = fn(snap_feat, ext_feat)
                        if isinstance(result, tuple):
                            sim, conf = float(result[0]), float(result[1])
                        else:
                            sim, conf = float(result), 1.0
                    else:
                        sim = _simple_numeric_similarity(snap_feat, ext_feat)
                        conf = min(1.0, len(ext_feat) / 10.0) if ext_feat else 0.0
                except Exception:
                    sim = _simple_numeric_similarity(snap_feat, ext_feat)
                    conf = 0.0

            weight = layer_weights.get(layer_name, 1.0)
            layer_scores[layer_name] = {
                "similarity": round(sim, 6),
                "confidence": round(conf, 6),
            }
            weighted_scores[layer_name] = round(sim * weight, 6)

        # Compute overall similarity.
        if weighted_scores:
            total_weight = sum(
                layer_weights.get(layer, 1.0) for layer in weighted_scores
            )
            overall = sum(weighted_scores.values()) / total_weight if total_weight > 0 else 0.0
        else:
            overall = 0.0

        # Rank layers.
        ranked = sorted(weighted_scores.items(), key=lambda x: x[1], reverse=True)
        dominant = [name for name, _ in ranked[:3]]
        weak = [name for name, _ in ranked[-3:]]

        return {
            "overall_similarity": round(float(overall), 6),
            "layer_scores": layer_scores,
            "weighted_layer_scores": weighted_scores,
            "dominant_layers": dominant,
            "weak_layers": weak,
            "extracted_features": extracted,
        }

    # ── Collection from database ────────────────────────────────────────

    @staticmethod
    def collect_from_database(
        db_path: str | Path,
        target_user_id: int,
        *,
        start: Optional[str] = None,
        end: Optional[str] = None,
        limit: int = 5000,
        negative_ratio: float = 1.0,
        seed: int = 0,
    ) -> List[Dict[str, Any]]:
        """Collect examples from the messages table.

        Positives are the target author's nonempty messages. Negatives are
        deterministically sampled non-target messages in the same date range,
        as temporally matched as practical. Handles minimal standard messages
        schema and the case where no negatives exist.
        """
        import random
        rng = random.Random(seed)
        conn = sqlite3.connect(str(db_path))
        try:
            # Detect schema — messages table may or may not have channel_id.
            cols = {row[1] for row in conn.execute("PRAGMA table_info(messages)").fetchall()}
            has_channel = "channel_id" in cols
            has_user_id = "user_id" in cols
            has_content = "content" in cols
            if not has_content:
                return []

            # Build positive query.
            pos_clauses = ["content IS NOT NULL", "TRIM(content) != ''"]
            pos_params: List[Any] = []
            if has_user_id:
                pos_clauses.append("user_id = ?")
                pos_params.append(target_user_id)
            if start:
                pos_clauses.append("date >= ?")
                pos_params.append(start)
            if end:
                pos_clauses.append("date <= ?")
                pos_params.append(end)
            pos_sql = (
                f"SELECT id, date, content"
                f"{', channel_id' if has_channel else ''}"
                f"{', user_id' if has_user_id else ''}"
                f" FROM messages WHERE {' AND '.join(pos_clauses)}"
                f" ORDER BY date ASC LIMIT ?"
            )
            pos_params.append(limit)
            pos_rows = conn.execute(pos_sql, pos_params).fetchall()

            examples: List[Dict[str, Any]] = []
            for row in pos_rows:
                msg_id = row[0]
                date = row[1]
                content = row[2]
                idx = 3
                channel_id = row[idx] if has_channel else None
                idx += 1 if has_channel else 0
                user_id = row[idx] if has_user_id else None
                examples.append({
                    "target_id": str(target_user_id),
                    "label": "positive",
                    "text": content,
                    "source_type": "message",
                    "source_message_id": msg_id,
                    "source_channel_id": channel_id,
                    "source_user_id": user_id,
                    "observed_at": date,
                    "weight": 1.0,
                })

            # Build negative query — non-target authors in same date range.
            neg_clauses = ["content IS NOT NULL", "TRIM(content) != ''"]
            neg_params: List[Any] = []
            if has_user_id:
                neg_clauses.append("(user_id IS NULL OR user_id != ?)")
                neg_params.append(target_user_id)
            if start:
                neg_clauses.append("date >= ?")
                neg_params.append(start)
            if end:
                neg_clauses.append("date <= ?")
                neg_params.append(end)
            neg_sql = (
                f"SELECT id, date, content"
                f"{', channel_id' if has_channel else ''}"
                f"{', user_id' if has_user_id else ''}"
                f" FROM messages WHERE {' AND '.join(neg_clauses)}"
                f" ORDER BY date ASC"
            )
            neg_rows = conn.execute(neg_sql, neg_params).fetchall()

            # Deterministic sampling for temporally matched negatives.
            n_neg_target = int(len(examples) * negative_ratio)
            if neg_rows and n_neg_target > 0:
                # Sort negatives by date, then sample evenly across the range.
                neg_rows_sorted = sorted(neg_rows, key=lambda r: r[1] or "")
                if len(neg_rows_sorted) <= n_neg_target:
                    sampled = neg_rows_sorted
                else:
                    # Even stride sampling for temporal matching.
                    stride = len(neg_rows_sorted) / n_neg_target
                    indices = [int(i * stride) for i in range(n_neg_target)]
                    sampled = [neg_rows_sorted[i] for i in indices]
                for row in sampled:
                    msg_id = row[0]
                    date = row[1]
                    content = row[2]
                    idx = 3
                    channel_id = row[idx] if has_channel else None
                    idx += 1 if has_channel else 0
                    user_id = row[idx] if has_user_id else None
                    examples.append({
                        "target_id": str(target_user_id),
                        "label": "negative",
                        "text": content,
                        "source_type": "message",
                        "source_message_id": msg_id,
                        "source_channel_id": channel_id,
                        "source_user_id": user_id,
                        "observed_at": date,
                        "weight": 1.0,
                    })
            return examples
        finally:
            conn.close()

    # ── Inferred knowledge observations ─────────────────────────────────

    @staticmethod
    def infer_knowledge_observations(
        target_id: str,
        positive_examples: Sequence[Dict[str, Any]],
        *,
        domain_lexicons: Optional[Dict[str, frozenset[str]]] = None,
    ) -> List[Dict[str, Any]]:
        """Infer domain knowledge observations from positive examples.

        Produces estimates only when domain terms appear. Uses conservative
        calibrated score and sample-size-based confidence. No claim without
        evidence.
        """
        lexicons = domain_lexicons or DEFAULT_DOMAIN_LEXICONS
        # Aggregate all positive text.
        all_tokens: List[str] = []
        for ex in positive_examples:
            all_tokens.extend(_tokenize(ex.get("text", "")))
        if not all_tokens:
            return []
        total_words = len(all_tokens)
        token_set = set(all_tokens)
        token_counts = Counter(all_tokens)
        observations: List[Dict[str, Any]] = []
        observed_at = _now()
        for domain, lexicon in lexicons.items():
            hits = [w for w in token_set if w in lexicon]
            if not hits:
                continue
            hit_count = sum(token_counts[h] for h in hits)
            # Score: density of domain terms relative to total words,
            # calibrated conservatively. Cap at 0.95 to avoid overclaiming.
            density = hit_count / total_words
            # Map density to score: 1% density → ~0.3, 5% → ~0.7, 10%+ → ~0.9
            score = min(0.95, 1.0 - math.exp(-3.0 * density))
            # Confidence: rises with hit count, bounded [0,1].
            # Few hits → low confidence. Many hits → higher.
            confidence = min(0.85, hit_count / (hit_count + 10.0))
            observations.append({
                "target_id": target_id,
                "domain": domain,
                "score": round(score, 4),
                "confidence": round(confidence, 4),
                "evidence_source": f"lexicon:{domain}",
                "evaluator": "persona-v1-lexicon",
                "evaluator_version": "1.0",
                "observed_at": observed_at,
                "notes": f"hit_count={hit_count}, density={density:.4f}",
            })
        return observations

    # ── Export ──────────────────────────────────────────────────────────

    @staticmethod
    def export_jsonl(
        examples: Sequence[Dict[str, Any]],
        snapshot: Dict[str, Any],
        output_path: str | Path,
        *,
        require_authorized: bool = True,
        authorized: bool = False,
    ) -> int:
        """Export training data as JSONL.

        Each record includes: label, text, target_id, source/provenance,
        timestamp, weight, persona_snapshot_id, and disclosure_required=true.

        Refuses with ``PermissionError`` unless ``authorized`` is True or
        ``require_authorized`` is False.

        Returns the number of records written.
        """
        if require_authorized and not authorized:
            raise PermissionError(
                "Export refused: target is not authorized. "
                "Set authorized=True only after verifying consent."
            )
        output_path = Path(output_path)
        snapshot_id = snapshot.get("snapshot_id") or hashlib.sha256(
            json.dumps(snapshot, default=str, sort_keys=True).encode("utf-8")
        ).hexdigest()[:32]
        target_id = snapshot.get("target_id", "")
        records_written = 0
        # Stable deterministic output order: by observed_at then label.
        ordered = sorted(
            examples,
            key=lambda e: (e.get("observed_at") or "", e.get("label", ""), e.get("text", "")),
        )
        with output_path.open("w", encoding="utf-8") as f:
            for ex in ordered:
                record = {
                    "label": ex.get("label"),
                    "text": ex.get("text", ""),
                    "target_id": ex.get("target_id", target_id),
                    "source_type": ex.get("source_type"),
                    "source_message_id": ex.get("source_message_id"),
                    "source_channel_id": ex.get("source_channel_id"),
                    "source_user_id": ex.get("source_user_id"),
                    "observed_at": ex.get("observed_at"),
                    "weight": float(ex.get("weight", 1.0)),
                    "persona_snapshot_id": snapshot_id,
                    "disclosure_required": True,
                    "model": snapshot.get("model", "persona-v1"),
                    "model_version": snapshot.get("model_version", "1.0"),
                }
                f.write(json.dumps(record, default=str, sort_keys=True) + "\n")
                records_written += 1
        return records_written

    # ── Summary ─────────────────────────────────────────────────────────

    @staticmethod
    def summary(
        examples: Sequence[Dict[str, Any]],
        snapshot: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Return a human-readable summary dict of the corpus and snapshot."""
        label_counts: Dict[str, int] = {"positive": 0, "negative": 0, "review": 0}
        for ex in examples:
            label = ex.get("label", "review")
            label_counts[label] = label_counts.get(label, 0) + 1
        vocab_size = len(snapshot.get("vocabulary", {}))
        distinctive_size = len(snapshot.get("distinctive_vocab", {}))
        knowledge = snapshot.get("knowledge_estimates", {})
        return {
            "total_examples": len(examples),
            "label_counts": label_counts,
            "vocabulary_size": vocab_size,
            "distinctive_vocab_size": distinctive_size,
            "knowledge_domains": list(knowledge.keys()),
            "knowledge_estimates": knowledge,
            "as_of": snapshot.get("as_of"),
            "model": snapshot.get("model"),
            "model_version": snapshot.get("model_version"),
            # V2 behavioral layers
            "v2_feature_layers": {
                "orthographic": bool(snapshot.get("orthographic_features")),
                "error": bool(snapshot.get("error_features")),
                "discourse": bool(snapshot.get("discourse_features")),
                "formatting": bool(snapshot.get("formatting_features")),
                "notation": bool(snapshot.get("notation_features")),
                "register": bool(snapshot.get("register_features")),
                "conversation": bool(snapshot.get("conversation_features")),
                "syntax": bool(snapshot.get("syntax_features")),
                "temporal": bool(snapshot.get("temporal_features")),
                "conditional": bool(snapshot.get("conditional_features")),
                "interaction": bool(snapshot.get("interaction_features")),
                "dialogue_acts": bool(snapshot.get("dialogue_acts_features")),
            },
        }


__all__ = [
    "PersonaTrainingModel",
    "DEFAULT_DOMAIN_LEXICONS",
]
