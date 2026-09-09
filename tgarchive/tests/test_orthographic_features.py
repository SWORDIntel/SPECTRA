"""
Unit tests for orthographic feature extraction and comparison.

Tests:
- Empty messages and messages without text return defaults
- Known input produces expected orthographic and character fingerprints
- Output is JSON-serializable
- Distributions are capped at their limits (top-200 / top-100 / top-50)
- All scalar values are in valid ranges [0.0, 1.0]
- Profile comparison works correctly
"""
from __future__ import annotations

import json
import random
import string
import pytest

from tgarchive.intelligence.features.orthographic import (
    DEFAULT_ORTHOGRAPHIC_FEATURES,
    compare_orthographic_features,
    extract_orthographic_features,
)


class TestOrthographicFeatures:
    """Tests for L1 orthographic feature extraction."""

    def test_empty_messages_returns_defaults(self):
        feat = extract_orthographic_features([])
        assert isinstance(feat, dict)
        assert feat == DEFAULT_ORTHOGRAPHIC_FEATURES
        assert feat["char_ngram_freq_2"] == {}
        assert feat["char_ngram_freq_3"] == {}
        assert feat["char_ngram_freq_4"] == {}
        assert feat["char_ngram_freq_5"] == {}
        assert feat["char_ngram_freq_6"] == {}
        assert feat["word_initial_char_ngrams"] == {}
        assert feat["word_final_char_ngrams"] == {}
        assert feat["punctuation_sequence_freq"] == {}
        assert feat["repeated_punctuation_patterns"] == {}
        assert feat["capitalization_transition_patterns"] == {}
        assert feat["digit_format_patterns"] == {}

    def test_messages_without_text(self):
        feat = extract_orthographic_features([
            {"id": 1},
            {"date": "2026-08-23"},
            {"content": None},
            {"text": ""},
        ])
        assert feat == DEFAULT_ORTHOGRAPHIC_FEATURES

    def test_known_input_character_and_word_ngrams(self):
        messages = [
            {"content": "The quick brown fox jumps over the lazy dog."},
            {"text": "And the dog barked loudly at the moon!"},
        ]
        feat = extract_orthographic_features(messages)

        # Character n-grams 2..6 must be populated
        assert len(feat["char_ngram_freq_2"]) > 0
        assert len(feat["char_ngram_freq_3"]) > 0
        assert len(feat["char_ngram_freq_4"]) > 0
        assert len(feat["char_ngram_freq_5"]) > 0
        assert len(feat["char_ngram_freq_6"]) > 0

        # "th" should be among top 2-grams
        assert "th" in feat["char_ngram_freq_2"]
        assert feat["char_ngram_freq_2"]["th"] > 0.0

        # Word boundary initial & final 3-grams
        assert len(feat["word_initial_char_ngrams"]) > 0
        assert len(feat["word_final_char_ngrams"]) > 0
        assert "the" in feat["word_initial_char_ngrams"]
        assert "the" in feat["word_final_char_ngrams"]
        assert "qui" in feat["word_initial_char_ngrams"]
        assert "ick" in feat["word_final_char_ngrams"]

    def test_punctuation_sequences_and_repeated_patterns(self):
        messages = [
            {"content": "What?! Are you sure... really??? Look here ( now ) - okay !!"},
        ]
        feat = extract_orthographic_features(messages)

        # Punctuation sequences
        p_seqs = feat["punctuation_sequence_freq"]
        assert len(p_seqs) > 0
        assert any(k in p_seqs for k in ("...", "?!", "???", " - ", "( ", " )", "!!"))

        # Repeated punctuation
        rep_p = feat["repeated_punctuation_patterns"]
        assert len(rep_p) > 0
        assert any(k in rep_p for k in ("...", "???", "!!"))

    def test_capitalization_transitions(self):
        messages = [
            {"text": "iPhone with CamelCase and ALLCAPS words."},
        ]
        feat = extract_orthographic_features(messages)

        transitions = feat["capitalization_transition_patterns"]
        assert len(transitions) > 0
        assert "lower->Upper" in transitions  # iPhone, CamelCase
        assert "Upper->lower" in transitions  # CamelCase, words
        assert "Upper->Upper" in transitions  # ALLCAPS
        assert "lower->lower" in transitions

    def test_digit_format_patterns(self):
        messages = [
            {
                "content": (
                    "Specs: 16GB RAM, price is £30, hex 0xFF, date 23/08/26, "
                    "time 14:30, latency 100ms, release v1.2.3, range 10-20."
                )
            }
        ]
        feat = extract_orthographic_features(messages)

        digits = feat["digit_format_patterns"]
        assert len(digits) > 0
        assert "16GB" in digits
        assert "£30" in digits
        assert "0xFF" in digits
        assert "23/08/26" in digits
        assert "14:30" in digits
        assert "100ms" in digits
        assert "v1.2.3" in digits
        assert "10-20" in digits

    def test_json_serializability(self):
        messages = [
            {"content": "Mixed content: 16GB, £50, 0xAA, test...?! Hello World ( yes ) - fine !!"},
            {"text": "Another test message with various n-grams and 23/08/26 dates."},
        ]
        feat = extract_orthographic_features(messages)

        # Verify json.dumps succeeds without error
        serialized = json.dumps(feat)
        deserialized = json.loads(serialized)
        assert isinstance(deserialized, dict)
        assert len(deserialized) == 11

    def test_distributions_capped_at_limits(self):
        # Generate large diverse corpus
        rng = random.Random(42)
        words = [
            "".join(rng.choices(string.ascii_letters, k=rng.randint(4, 12)))
            for _ in range(1000)
        ]
        numbers = [f"{rng.randint(1, 1000)}GB" for _ in range(200)]
        puncts = ["...", "??", "!!", "?!", " - ", "( ", " )", "---", ":::"]
        combined = []
        for i in range(500):
            combined.append(f"{words[i]} {numbers[i % len(numbers)]} {puncts[i % len(puncts)]}")

        messages = [{"content": "\n".join(combined)}]
        feat = extract_orthographic_features(messages)

        assert len(feat["char_ngram_freq_2"]) <= 200
        assert len(feat["char_ngram_freq_3"]) <= 200
        assert len(feat["char_ngram_freq_4"]) <= 200
        assert len(feat["char_ngram_freq_5"]) <= 200
        assert len(feat["char_ngram_freq_6"]) <= 200
        assert len(feat["word_initial_char_ngrams"]) <= 100
        assert len(feat["word_final_char_ngrams"]) <= 100
        assert len(feat["punctuation_sequence_freq"]) <= 100
        assert len(feat["repeated_punctuation_patterns"]) <= 50
        assert len(feat["capitalization_transition_patterns"]) <= 50
        assert len(feat["digit_format_patterns"]) <= 50

    def test_scalars_in_valid_range(self):
        messages = [
            {"content": "Standard testing message with 100MB and multiple... n-grams !!"},
        ]
        feat = extract_orthographic_features(messages)

        for k, distrib in feat.items():
            assert isinstance(distrib, dict)
            for item, val in distrib.items():
                assert isinstance(item, str)
                assert isinstance(val, float)
                assert 0.0 <= val <= 1.0

    def test_compare_orthographic_features(self):
        messages_a = [
            {"content": "Operational communication 16GB £30 0xFF test...?! Hello World ( yes ) - fine !!"},
        ]
        messages_b = [
            {"content": "Operational communication 16GB £30 0xFF test...?! Hello World ( yes ) - fine !!"},
        ]
        messages_c = [
            {"content": "Completely different text without numbers or special symbols."},
        ]

        feat_a = extract_orthographic_features(messages_a)
        feat_b = extract_orthographic_features(messages_b)
        feat_c = extract_orthographic_features(messages_c)

        sim_ab, conf_ab = compare_orthographic_features(feat_a, feat_b)
        assert sim_ab == pytest.approx(1.0, 0.01)
        assert conf_ab > 0.0

        sim_ac, _ = compare_orthographic_features(feat_a, feat_c)
        assert sim_ac < sim_ab

        empty_sim, empty_conf = compare_orthographic_features({}, {})
        assert empty_sim == 0.0
        assert empty_conf == 0.0
