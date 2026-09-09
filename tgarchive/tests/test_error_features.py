"""
Unit tests for error and typo feature extraction and comparison.

Tests:
- Empty messages and messages without text return defaults
- Known input produces expected typo, error mechanism, and misspelling features
- QWERTY adjacency detection works for keyboard substitutions
- Output is JSON-serializable
- Distributions are capped at their limits (top-100 / top-50)
- All scalar values are in valid non-negative ranges
- Profile comparison works correctly
"""
from __future__ import annotations

import json
import pytest

from tgarchive.intelligence.features.errors import (
    DEFAULT_ERROR_FEATURES,
    QWERTY_ADJACENCY,
    compare_error_features,
    extract_error_features,
)


class TestErrorFeatures:
    """Tests for L2 error and typo feature extraction."""

    def test_empty_messages_returns_defaults(self):
        feat = extract_error_features([])
        assert isinstance(feat, dict)
        assert feat == DEFAULT_ERROR_FEATURES
        assert feat["misspelling_frequency"] == 0.0
        assert feat["misspelling_dictionary"] == {}
        assert feat["edit_distance_error_distribution"] == {}
        assert feat["character_deletion_rate"] == 0.0
        assert feat["character_insertion_rate"] == 0.0
        assert feat["character_substitution_rate"] == 0.0
        assert feat["character_transposition_rate"] == 0.0
        assert feat["adjacent_keyboard_error_rate"] == 0.0
        assert feat["space_omission_rate"] == 0.0
        assert feat["space_insertion_rate"] == 0.0
        assert feat["apostrophe_omission_rate"] == 0.0
        assert feat["capitalization_error_rate"] == 0.0
        assert feat["repeated_character_distribution"] == {}
        assert feat["word_merge_rate"] == 0.0
        assert feat["word_split_rate"] == 0.0
        assert feat["correction_after_typo_rate"] == 0.0
        assert feat["typo_signature"] == {}

    def test_messages_without_text(self):
        feat = extract_error_features([
            {"id": 10},
            {"date": "2026-08-23"},
            {"content": None},
            {"text": ""},
        ])
        assert feat == DEFAULT_ERROR_FEATURES

    def test_known_misspellings_and_transpositions(self):
        messages = [
            {"content": "teh quick brown fox and adn jumped over hvae lazy dog."},
        ]
        feat = extract_error_features(messages)

        assert feat["misspelling_frequency"] > 0.0
        assert "teh->the" in feat["misspelling_dictionary"]
        assert "adn->and" in feat["misspelling_dictionary"]
        assert "hvae->have" in feat["misspelling_dictionary"]

        # Edit distance 1 should be recorded
        assert "1" in feat["edit_distance_error_distribution"]
        assert feat["edit_distance_error_distribution"]["1"] > 0.0

        # Transposition rate must be detected for teh, adn, hvae
        assert feat["character_transposition_rate"] > 0.0

        # Typo signature maps
        sig = feat["typo_signature"]
        assert "the->teh" in sig
        assert "and->adn" in sig
        assert "have->hvae" in sig

    def test_qwerty_adjacent_keyboard_substitutions(self):
        # 'g' is adjacent to 'h' on QWERTY -> 'tge' for 'the'
        messages = [
            {"content": "Look at tge screen now."},
        ]
        feat = extract_error_features(messages)

        assert feat["character_substitution_rate"] > 0.0
        assert feat["adjacent_keyboard_error_rate"] > 0.0
        assert "tge->the" in feat["misspelling_dictionary"]

    def test_character_deletions_and_insertions(self):
        messages = [
            # 'becaus' missing 'e' (deletion), 'thee' extra 'e' (insertion)
            {"content": "We left becaus thee weather was cold."},
        ]
        feat = extract_error_features(messages)

        assert feat["character_deletion_rate"] > 0.0
        assert feat["character_insertion_rate"] > 0.0
        assert "becaus->because" in feat["misspelling_dictionary"]
        assert "thee->the" in feat["misspelling_dictionary"]

    def test_space_omission_and_word_merges(self):
        messages = [
            {"content": "The member ofthe team inthat channel is active."},
        ]
        feat = extract_error_features(messages)

        assert feat["space_omission_rate"] > 0.0
        assert feat["word_merge_rate"] > 0.0
        assert "ofthe->of the" in feat["misspelling_dictionary"]
        assert "inthat->in that" in feat["misspelling_dictionary"]

    def test_space_insertion_and_word_splits(self):
        messages = [
            {"content": "He left beca use he was al ways busy."},
        ]
        feat = extract_error_features(messages)

        assert feat["space_insertion_rate"] > 0.0
        assert feat["word_split_rate"] > 0.0

    def test_apostrophe_omissions(self):
        messages = [
            {"content": "I dont know why they cant come and wont agree."},
        ]
        feat = extract_error_features(messages)

        assert feat["apostrophe_omission_rate"] > 0.0
        assert "dont->don't" in feat["misspelling_dictionary"]
        assert "cant->can't" in feat["misspelling_dictionary"]
        assert "wont->won't" in feat["misspelling_dictionary"]

    def test_capitalization_errors(self):
        messages = [
            {"text": "tHIS is an inverted caps error and tHe mid-word caps. lowercase sentence start."},
        ]
        feat = extract_error_features(messages)

        assert feat["capitalization_error_rate"] > 0.0

    def test_repeated_characters_distribution(self):
        messages = [
            {"content": "That is soooo cool and lolllll very funnyyyy!"},
        ]
        feat = extract_error_features(messages)

        rep = feat["repeated_character_distribution"]
        assert len(rep) > 0
        assert "oooo" in rep
        assert "lllll" in rep
        assert "yyyy" in rep

    def test_correction_after_typo(self):
        messages = [
            {"content": "We will go to the parkk."},
            {"content": "*park"},
            {"content": "right*"},
        ]
        feat = extract_error_features(messages)

        assert feat["correction_after_typo_rate"] > 0.0

    def test_json_serializability(self):
        messages = [
            {"content": "teh quick brown fox and adn jumped over hvae lazy dog."},
            {"text": "I dont know why they cant come and wont agree. *agree"},
            {"content": "Look at tge screen now with soooo much energy!"},
        ]
        feat = extract_error_features(messages)

        # Verify json.dumps succeeds without error
        serialized = json.dumps(feat)
        deserialized = json.loads(serialized)
        assert isinstance(deserialized, dict)
        assert len(deserialized) == 17

    def test_distributions_capped_at_limits(self):
        # Generate messages with multiple varied misspellings
        typos = [f"teh{i}" for i in range(150)]
        messages = [{"content": " ".join(typos)}]
        feat = extract_error_features(messages)

        assert len(feat["misspelling_dictionary"]) <= 100
        assert len(feat["repeated_character_distribution"]) <= 50
        assert len(feat["typo_signature"]) <= 50

    def test_scalars_in_valid_range(self):
        messages = [
            {"content": "teh quick brown fox and adn jumped over hvae lazy dog."},
            {"text": "I dont know why they cant come and wont agree. *agree"},
        ]
        feat = extract_error_features(messages)

        rate_keys = [
            "misspelling_frequency",
            "character_deletion_rate",
            "character_insertion_rate",
            "character_substitution_rate",
            "character_transposition_rate",
            "adjacent_keyboard_error_rate",
            "space_omission_rate",
            "space_insertion_rate",
            "apostrophe_omission_rate",
            "capitalization_error_rate",
            "word_merge_rate",
            "word_split_rate",
            "correction_after_typo_rate",
        ]

        for k in rate_keys:
            val = feat[k]
            assert isinstance(val, float)
            assert val >= 0.0

        for dist_key in ("edit_distance_error_distribution", "typo_signature"):
            for item, val in feat[dist_key].items():
                assert isinstance(item, str)
                assert isinstance(val, float)
                assert 0.0 <= val <= 1.0

    def test_compare_error_features(self):
        messages_a = [
            {"content": "teh quick brown fox and adn jumped over hvae lazy dog."},
            {"text": "I dont know why they cant come."},
        ]
        messages_b = [
            {"content": "teh quick brown fox and adn jumped over hvae lazy dog."},
            {"text": "I dont know why they cant come."},
        ]
        messages_c = [
            {"content": "The quick brown fox and they jumped over have lazy dog without any mistake."},
        ]

        feat_a = extract_error_features(messages_a)
        feat_b = extract_error_features(messages_b)
        feat_c = extract_error_features(messages_c)

        sim_ab, conf_ab = compare_error_features(feat_a, feat_b)
        assert sim_ab == pytest.approx(1.0, 0.01)
        assert conf_ab > 0.0

        sim_ac, _ = compare_error_features(feat_a, feat_c)
        assert sim_ac < sim_ab

        empty_sim, empty_conf = compare_error_features({}, {})
        assert empty_sim == 0.0
        assert empty_conf == 0.0
