"""
Unit tests for syntax and structural feature extraction and comparison (L3).

Tests:
- Empty messages and messages without text return defaults
- Regex and rule-based POS tagging works for suffixes and lexicons
- Sentence type detection correctly classifies question, imperative, declarative, fragment
- Passive and active voice detection functions properly
- Clause rates (subordinate, coordinate, average clause count) are computed
- Noun and verb phrase lengths are estimated
- Characteristic POS sequences are generated as string lists
- Output is JSON-serializable
- Distributions are capped at their specified limits
- All scalar values are in valid non-negative ranges
- Profile comparison works correctly
"""
from __future__ import annotations

import json
import pytest

from tgarchive.intelligence.features.syntax import (
    DEFAULT_SYNTAX_FEATURES,
    compare_syntax_features,
    extract_syntax_features,
    tag_token,
    tokenize_and_tag,
)


class TestSyntaxFeatures:
    """Tests for L3 syntax and structural feature extraction."""

    def test_empty_messages_returns_defaults(self):
        feat = extract_syntax_features([])
        assert isinstance(feat, dict)
        assert feat == DEFAULT_SYNTAX_FEATURES
        assert feat["pos_unigram_distribution"] == {}
        assert feat["pos_bigram_distribution"] == {}
        assert feat["sentence_type_distribution"] == {
            "declarative": 0.0,
            "question": 0.0,
            "imperative": 0.0,
            "fragment": 0.0,
        }
        assert feat["characteristic_pos_sequences"] == []
        assert feat["question_rate"] == 0.0
        assert feat["imperative_rate"] == 0.0
        assert feat["declarative_rate"] == 0.0
        assert feat["sentence_fragment_rate"] == 0.0
        assert feat["run_on_sentence_rate"] == 0.0
        assert feat["avg_clause_count"] == 0.0
        assert feat["subordinate_clause_rate"] == 0.0
        assert feat["coordinate_clause_rate"] == 0.0
        assert feat["active_voice_rate"] == 0.0
        assert feat["passive_voice_rate"] == 0.0
        assert feat["avg_noun_phrase_length"] == 0.0
        assert feat["avg_verb_phrase_length"] == 0.0

    def test_messages_without_text(self):
        feat = extract_syntax_features([
            {"id": 10},
            {"date": "2026-08-23"},
            {"content": None},
            {"text": ""},
        ])
        assert feat == DEFAULT_SYNTAX_FEATURES

    def test_pos_tagger_suffix_rules_and_lexicons(self):
        # Suffix rules: -ing -> VERB, -ed -> VERB, -ly -> ADV
        assert tag_token("running") == "VERB"
        assert tag_token("analyzed") == "VERB"
        assert tag_token("quickly") == "ADV"

        # Suffix rules: -tion/-ment/-ness -> NOUN
        assert tag_token("operation") == "NOUN"
        assert tag_token("development") == "NOUN"
        assert tag_token("darkness") == "NOUN"

        # Suffix rules: -ous/-ful/-al -> ADJ
        assert tag_token("dangerous") == "ADJ"
        assert tag_token("powerful") == "ADJ"
        assert tag_token("structural") == "ADJ"

        # Suffix rules: -ize/-ise -> VERB
        assert tag_token("optimize") == "VERB"
        assert tag_token("prioritise") == "VERB"

        # Lexicon function words
        assert tag_token("can") == "MODAL"
        assert tag_token("was") == "AUX"
        assert tag_token("the") == "DET"
        assert tag_token("under") == "PREP"
        assert tag_token("they") == "PRON"
        assert tag_token("because") == "CONJ"
        assert tag_token("42") == "NUM"
        assert tag_token(".") == "PUNCT"

    def test_content_and_text_fields(self):
        messages = [
            {"content": "The operator configured the server."},
            {"text": "Is the payload ready?"},
        ]
        feat = extract_syntax_features(messages)
        assert len(feat["pos_unigram_distribution"]) > 0
        assert len(feat["pos_bigram_distribution"]) > 0
        assert feat["declarative_rate"] > 0.0
        assert feat["question_rate"] > 0.0

    def test_sentence_type_detection(self):
        messages = [
            {"content": "Where did the attacker deploy the binary?"},  # question
            {"content": "Download the encrypted payload now."},        # imperative
            {"content": "The database contains thirty user records."},  # declarative
            {"content": "Top secret."},                                 # fragment
        ]
        feat = extract_syntax_features(messages)

        assert feat["question_rate"] == pytest.approx(0.25, 0.01)
        assert feat["imperative_rate"] == pytest.approx(0.25, 0.01)
        assert feat["declarative_rate"] == pytest.approx(0.25, 0.01)
        assert feat["sentence_fragment_rate"] == pytest.approx(0.25, 0.01)

        st_dist = feat["sentence_type_distribution"]
        assert sum(st_dist.values()) == pytest.approx(1.0, 0.01)

    def test_passive_and_active_voice(self):
        passive_msg = [{"content": "The server was compromised by the intruder."}]
        active_msg = [{"content": "The intruder compromised the server."}]

        feat_passive = extract_syntax_features(passive_msg)
        feat_active = extract_syntax_features(active_msg)

        assert feat_passive["passive_voice_rate"] > 0.0
        assert feat_active["active_voice_rate"] > 0.0
        assert feat_active["passive_voice_rate"] == 0.0

    def test_subordinate_and_coordinate_clauses(self):
        messages = [
            {"content": "We backed up the database because the disk failed and the alert triggered."},
        ]
        feat = extract_syntax_features(messages)

        assert feat["subordinate_clause_rate"] > 0.0  # 'because'
        assert feat["coordinate_clause_rate"] > 0.0   # 'and'
        assert feat["avg_clause_count"] >= 2.0

    def test_phrase_lengths(self):
        messages = [
            {"content": "The very dangerous malware could definitely have executed quickly."},
        ]
        feat = extract_syntax_features(messages)

        assert feat["avg_noun_phrase_length"] > 0.0
        assert feat["avg_verb_phrase_length"] > 0.0

    def test_characteristic_pos_sequences(self):
        messages = [
            {"content": "The quick brown fox jumps over the lazy dog."},
            {"content": "The big red fox jumps over the sleeping dog."},
        ]
        feat = extract_syntax_features(messages)
        seqs = feat["characteristic_pos_sequences"]

        assert isinstance(seqs, list)
        assert len(seqs) > 0
        assert all(isinstance(s, str) for s in seqs)
        # Check that POS sequence contains valid tags
        assert any("DET" in s and "NOUN" in s for s in seqs)

    def test_json_serializability(self):
        messages = [
            {"content": "The analyst examined the suspicious traffic. Was it malicious?"},
            {"text": "Inspect the certificates immediately! No errors."},
        ]
        feat = extract_syntax_features(messages)

        serialized = json.dumps(feat)
        deserialized = json.loads(serialized)
        assert isinstance(deserialized, dict)
        assert len(deserialized) == len(DEFAULT_SYNTAX_FEATURES)

    def test_distributions_capped_at_limits(self):
        # Long message with diverse vocabulary
        tokens = [f"word{i}" for i in range(150)]
        messages = [{"content": ". ".join(" ".join(tokens[i:i + 8]) for i in range(0, 140, 8))}]
        feat = extract_syntax_features(messages)

        assert len(feat["pos_unigram_distribution"]) <= 50
        assert len(feat["pos_bigram_distribution"]) <= 50
        assert len(feat["characteristic_pos_sequences"]) <= 20
        assert len(feat["sentence_type_distribution"]) == 4

    def test_scalars_in_valid_range(self):
        messages = [
            {"content": "The system was updated because the vulnerability was patched."},
            {"content": "Did the team verify the hashes?"},
        ]
        feat = extract_syntax_features(messages)

        rate_keys = [
            "question_rate",
            "imperative_rate",
            "declarative_rate",
            "sentence_fragment_rate",
            "run_on_sentence_rate",
            "subordinate_clause_rate",
            "coordinate_clause_rate",
            "active_voice_rate",
            "passive_voice_rate",
        ]

        for k in rate_keys:
            val = feat[k]
            assert isinstance(val, float)
            assert 0.0 <= val <= 1.0

        assert feat["avg_clause_count"] >= 0.0
        assert feat["avg_noun_phrase_length"] >= 0.0
        assert feat["avg_verb_phrase_length"] >= 0.0

    def test_compare_syntax_features(self):
        messages_a = [
            {"content": "The quick brown fox jumps over the lazy dog."},
            {"text": "Did the dog bark at the fox?"},
        ]
        messages_b = [
            {"content": "The quick brown fox jumps over the lazy dog."},
            {"text": "Did the dog bark at the fox?"},
        ]
        messages_c = [
            {"content": "Run immediately! Stop now! Check log! Download file!"},
        ]

        feat_a = extract_syntax_features(messages_a)
        feat_b = extract_syntax_features(messages_b)
        feat_c = extract_syntax_features(messages_c)

        sim_ab, conf_ab = compare_syntax_features(feat_a, feat_b)
        assert sim_ab == pytest.approx(1.0, 0.01)
        assert conf_ab > 0.0

        sim_ac, _ = compare_syntax_features(feat_a, feat_c)
        assert sim_ac < sim_ab

        empty_sim, empty_conf = compare_syntax_features({}, {})
        assert empty_sim == 0.0
        assert empty_conf == 0.0
