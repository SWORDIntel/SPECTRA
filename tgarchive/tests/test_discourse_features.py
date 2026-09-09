"""
Unit tests for discourse and rhetorical feature extraction and comparison (L4).

Tests:
- Empty messages and messages without text return defaults
- Known input produces expected discourse marker rates and distributions
- Sentence openers, closers, and phrase distributions are correctly extracted
- N-grams (trigrams, fourgrams, skipgrams) are properly formed
- Output is JSON-serializable
- Distributions are capped at their specified limits
- All scalar values are in valid non-negative ranges
- Profile comparison works correctly
"""
from __future__ import annotations

import json
import pytest

from tgarchive.intelligence.features.discourse import (
    DEFAULT_DISCOURSE_FEATURES,
    compare_discourse_features,
    extract_discourse_features,
)


class TestDiscourseFeatures:
    """Tests for L4 discourse and rhetorical feature extraction."""

    def test_empty_messages_returns_defaults(self):
        feat = extract_discourse_features([])
        assert isinstance(feat, dict)
        assert feat == DEFAULT_DISCOURSE_FEATURES
        assert feat["hedge_rate"] == 0.0
        assert feat["certainty_marker_rate"] == 0.0
        assert feat["intensifier_rate"] == 0.0
        assert feat["qualifier_rate"] == 0.0
        assert feat["self_correction_rate"] == 0.0
        assert feat["parenthetical_rate"] == 0.0
        assert feat["aside_rate"] == 0.0
        assert feat["clarification_rate"] == 0.0
        assert feat["reformulation_rate"] == 0.0
        assert feat["example_introduction_rate"] == 0.0
        assert feat["analogy_rate"] == 0.0
        assert feat["contrast_marker_rate"] == 0.0
        assert feat["causal_marker_rate"] == 0.0
        assert feat["discourse_marker_distribution"] == {}
        assert feat["sentence_initial_phrase_distribution"] == {}
        assert feat["sentence_final_phrase_distribution"] == {}
        assert feat["sentence_openers"] == {}
        assert feat["sentence_closers"] == {}
        assert feat["trigrams"] == {}
        assert feat["fourgrams"] == {}
        assert feat["skipgrams"] == {}

    def test_messages_without_text(self):
        feat = extract_discourse_features([
            {"id": 10},
            {"date": "2026-08-23"},
            {"content": None},
            {"text": ""},
        ])
        assert feat == DEFAULT_DISCOURSE_FEATURES

    def test_content_and_text_fields(self):
        messages = [
            {"content": "I think this is definitely very important."},
            {"text": "However we must be careful because of errors."},
        ]
        feat = extract_discourse_features(messages)
        assert feat["hedge_rate"] > 0.0
        assert feat["certainty_marker_rate"] > 0.0
        assert feat["intensifier_rate"] > 0.0
        assert feat["contrast_marker_rate"] > 0.0
        assert feat["causal_marker_rate"] > 0.0

    def test_hedges_and_certainty_markers(self):
        messages = [
            {"content": "Maybe we should wait. Perhaps it will work, I think so, sort of."},
            {"content": "This is definitely true, absolutely confirmed, and clearly superior."},
        ]
        feat = extract_discourse_features(messages)
        assert feat["hedge_rate"] > 0.0
        assert feat["certainty_marker_rate"] > 0.0

        marker_dist = feat["discourse_marker_distribution"]
        assert "maybe" in marker_dist or "perhaps" in marker_dist or "i think" in marker_dist
        assert "definitely" in marker_dist or "absolutely" in marker_dist or "clearly" in marker_dist

    def test_intensifiers_and_qualifiers(self):
        messages = [
            {"content": "This is very fast, really powerful, and extremely effective."},
            {"content": "It is kind of tricky, sort of complicated, and fairly difficult."},
        ]
        feat = extract_discourse_features(messages)
        assert feat["intensifier_rate"] > 0.0
        assert feat["qualifier_rate"] > 0.0

    def test_self_correction_and_reformulation(self):
        messages = [
            {"content": "We need five servers, I mean six servers, actually seven."},
            {"content": "The attack succeeded, or rather it was mitigated in other words."},
        ]
        feat = extract_discourse_features(messages)
        assert feat["self_correction_rate"] > 0.0
        assert feat["reformulation_rate"] > 0.0

    def test_parentheticals_and_asides(self):
        messages = [
            {"content": "By the way (this is an important note) we should verify [backup copy]."},
            {"content": "The system —which was rebuilt yesterday— handled the load well."},
        ]
        feat = extract_discourse_features(messages)
        assert feat["parenthetical_rate"] > 0.0
        assert feat["aside_rate"] > 0.0

    def test_clarification_and_example_introducers(self):
        messages = [
            {"content": "The payload is polymorphic, i.e. it mutates constantly."},
            {"content": "Consider common indicators, for example hash collisions, such as SHA256."},
        ]
        feat = extract_discourse_features(messages)
        assert feat["clarification_rate"] > 0.0
        assert feat["example_introduction_rate"] > 0.0

    def test_analogy_contrast_and_causal_markers(self):
        messages = [
            {"content": "The botnet acts as if it were a neural network, similar to a swarm."},
            {"content": "We probed the port, but it was closed; however the API responded."},
            {"content": "Because the key was leaked, therefore the credentials expired."},
        ]
        feat = extract_discourse_features(messages)
        assert feat["analogy_rate"] > 0.0
        assert feat["contrast_marker_rate"] > 0.0
        assert feat["causal_marker_rate"] > 0.0

    def test_sentence_openers_and_closers(self):
        messages = [
            {"content": "First message starts here. Second sentence concludes now."},
            {"content": "Third message is brief."},
        ]
        feat = extract_discourse_features(messages)
        openers = feat["sentence_openers"]
        closers = feat["sentence_closers"]

        assert "first" in openers
        assert "second" in openers
        assert "third" in openers

        assert "here" in closers
        assert "now" in closers
        assert "brief" in closers

    def test_initial_and_final_phrase_distributions(self):
        messages = [
            {"content": "The quick brown fox jumps over the lazy dog."},
            {"content": "The quick brown bear rests under the green tree."},
        ]
        feat = extract_discourse_features(messages)
        init_phrases = feat["sentence_initial_phrase_distribution"]
        final_phrases = feat["sentence_final_phrase_distribution"]

        assert "the quick brown" in init_phrases
        assert init_phrases["the quick brown"] == 2
        assert "the lazy dog" in final_phrases
        assert "the green tree" in final_phrases

    def test_trigrams_fourgrams_and_skipgrams(self):
        messages = [
            {"content": "the quick brown fox jumped high."},
        ]
        feat = extract_discourse_features(messages)

        assert "the quick brown" in feat["trigrams"]
        assert "quick brown fox" in feat["trigrams"]

        assert "the quick brown fox" in feat["fourgrams"]
        assert "quick brown fox jumped" in feat["fourgrams"]

        assert "the _ brown" in feat["skipgrams"]
        assert "quick _ fox" in feat["skipgrams"]

    def test_json_serializability(self):
        messages = [
            {"content": "I mean, maybe we should definitely verify this! (Important step)"},
            {"text": "For example, the logs show errors because of network timeout."},
        ]
        feat = extract_discourse_features(messages)

        serialized = json.dumps(feat)
        deserialized = json.loads(serialized)
        assert isinstance(deserialized, dict)
        assert len(deserialized) == len(DEFAULT_DISCOURSE_FEATURES)

    def test_distributions_capped_at_limits(self):
        # Generate varied sentences to produce many distinct n-grams
        words = [f"token{i}" for i in range(250)]
        long_text = ". ".join(" ".join(words[i:i + 10]) for i in range(0, 240, 10))
        messages = [{"content": long_text}]
        feat = extract_discourse_features(messages)

        assert len(feat["discourse_marker_distribution"]) <= 100
        assert len(feat["sentence_initial_phrase_distribution"]) <= 100
        assert len(feat["sentence_final_phrase_distribution"]) <= 100
        assert len(feat["sentence_openers"]) <= 100
        assert len(feat["sentence_closers"]) <= 100
        assert len(feat["trigrams"]) <= 200
        assert len(feat["fourgrams"]) <= 100
        assert len(feat["skipgrams"]) <= 100

    def test_scalars_in_valid_range(self):
        messages = [
            {"content": "I think perhaps we definitely should check this, because it seems critical."},
        ]
        feat = extract_discourse_features(messages)

        rate_keys = [
            "hedge_rate",
            "certainty_marker_rate",
            "intensifier_rate",
            "qualifier_rate",
            "self_correction_rate",
            "parenthetical_rate",
            "aside_rate",
            "clarification_rate",
            "reformulation_rate",
            "example_introduction_rate",
            "analogy_rate",
            "contrast_marker_rate",
            "causal_marker_rate",
        ]

        for k in rate_keys:
            val = feat[k]
            assert isinstance(val, float)
            assert 0.0 <= val <= 1.0

    def test_compare_discourse_features(self):
        messages_a = [
            {"content": "I think we should definitely check the results because they seem consistent."},
            {"text": "For example, the server responded quickly however latency spiked later."},
        ]
        messages_b = [
            {"content": "I think we should definitely check the results because they seem consistent."},
            {"text": "For example, the server responded quickly however latency spiked later."},
        ]
        messages_c = [
            {"content": "No markers here just raw operational coordinates 12345 67890."},
        ]

        feat_a = extract_discourse_features(messages_a)
        feat_b = extract_discourse_features(messages_b)
        feat_c = extract_discourse_features(messages_c)

        sim_ab, conf_ab = compare_discourse_features(feat_a, feat_b)
        assert sim_ab == pytest.approx(1.0, 0.01)
        assert conf_ab > 0.0

        sim_ac, _ = compare_discourse_features(feat_a, feat_c)
        assert sim_ac < sim_ab

        empty_sim, empty_conf = compare_discourse_features({}, {})
        assert empty_sim == 0.0
        assert empty_conf == 0.0
