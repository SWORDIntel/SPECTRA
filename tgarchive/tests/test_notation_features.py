"""
Unit tests for L6 numeric/notation style feature extraction.

Tests:
- Empty input returns defaults
- Messages without text return defaults
- JSON serializability of output
- Number word vs digit preference
- Decimal precision distribution
- Thousands separator styles
- Currency format styles
- Date and time format distributions
- Unit spacing and abbreviation conventions
- Hex and binary notations
- Version number and range styles
- Scalar ranges and distribution capping
"""
from __future__ import annotations

import json
import pytest

from tgarchive.intelligence.features.notation import (
    DEFAULT_NOTATION_FEATURES,
    extract_notation_features,
)


class TestNotationFeatures:
    """Tests for notation feature extraction."""

    def test_empty_messages(self):
        feat = extract_notation_features([])
        assert isinstance(feat, dict)
        assert feat["number_word_preference"] == 0.0
        assert feat["decimal_precision_distribution"] == {}
        assert feat["thousands_separator_style"] == {}
        assert feat["currency_format_style"] == {}
        assert feat["date_format_distribution"] == {}
        assert feat["time_format_distribution"] == {}
        assert feat["hex_notation_style"] == {}
        assert feat["binary_notation_style"] == {}
        assert feat["version_number_style"] == {}
        assert feat["range_notation_style"] == {}

    def test_messages_without_text(self):
        feat = extract_notation_features([
            {"id": 1},
            {"date": "2026-01-01"},
            {"content": None},
        ])
        assert feat["number_word_preference"] == 0.0
        assert feat["decimal_precision_distribution"] == {}

    def test_json_serializable(self):
        messages = [
            {
                "content": (
                    "Bought three servers for $1,500 each on 2026-08-23 at 14:30. "
                    "RAM: 64GB (or 64 GB), version v1.2.3, hex 0xFF, binary 0b1010, "
                    "port range 8000-8080 or 9000..9090."
                )
            }
        ]
        feat = extract_notation_features(messages)
        serialized = json.dumps(feat)
        assert isinstance(serialized, str)
        deserialized = json.loads(serialized)
        assert deserialized["number_word_preference"] > 0.0
        assert "YYYY-MM-DD" in deserialized["date_format_distribution"]

    def test_number_word_preference(self):
        # Mostly word numbers
        words_msg = [{"content": "There are one, two, three, four, five, six items."}]
        feat_words = extract_notation_features(words_msg)
        assert feat_words["number_word_preference"] == pytest.approx(1.0, 0.01)

        # Mostly digit numbers
        digits_msg = [{"content": "There are 1, 2, 3, 4, 5, 6 items."}]
        feat_digits = extract_notation_features(digits_msg)
        assert feat_digits["number_word_preference"] == pytest.approx(0.0, 0.01)

        # Mixed
        mixed_msg = [{"content": "Two servers and 10 workstations."}]
        feat_mixed = extract_notation_features(mixed_msg)
        assert 0.0 < feat_mixed["number_word_preference"] < 1.0

    def test_decimal_precision_distribution(self):
        messages = [
            {"content": "Readings: 10, 20, 3.14, 9.8, 0.001"}
        ]
        feat = extract_notation_features(messages)
        dist = feat["decimal_precision_distribution"]
        assert "0" in dist
        assert "1" in dist
        assert "2" in dist
        assert "3" in dist
        assert sum(dist.values()) == pytest.approx(1.0, 0.01)

    def test_thousands_separator_style(self):
        messages = [
            {
                "content": (
                    "Total users: 1,000,000 with 2,500 active. "
                    "Database size is 50000 records. "
                    "Memory pool: 1 000 000 bytes."
                )
            }
        ]
        feat = extract_notation_features(messages)
        sep_dist = feat["thousands_separator_style"]
        assert "comma" in sep_dist
        assert sum(sep_dist.values()) == pytest.approx(1.0, 0.01)

    def test_currency_format_style(self):
        messages = [
            {
                "content": "Price: £30 or $50 or €100. Local deals for 30 quid and 50 dollars."
            }
        ]
        feat = extract_notation_features(messages)
        curr_dist = feat["currency_format_style"]
        assert len(curr_dist) > 0
        assert any("£" in k or "$" in k or "quid" in k or "dollars" in k for k in curr_dist)
        assert sum(curr_dist.values()) == pytest.approx(1.0, 0.01)

    def test_date_and_time_formats(self):
        messages = [
            {
                "content": (
                    "Event on 2026-08-23 and 23/08/2026. "
                    "Meeting at 03:30 PM, logs recorded at 14:45:00 and 0900hrs."
                )
            }
        ]
        feat = extract_notation_features(messages)
        date_dist = feat["date_format_distribution"]
        time_dist = feat["time_format_distribution"]

        assert "YYYY-MM-DD" in date_dist
        assert "DD/MM/YYYY" in date_dist
        assert "12h" in time_dist
        assert "24h" in time_dist
        assert sum(date_dist.values()) == pytest.approx(1.0, 0.01)
        assert sum(time_dist.values()) == pytest.approx(1.0, 0.01)

    def test_unit_spacing_and_abbreviation(self):
        messages = [
            {
                "content": "Disk 30GB vs backup 30 GB. Latency 10ms vs 10 ms. Bandwidth 100 megabytes."
            }
        ]
        feat = extract_notation_features(messages)
        assert len(feat["unit_spacing_style"]) > 0
        assert len(feat["unit_abbreviation_style"]) > 0

    def test_hex_and_binary_notation(self):
        messages = [
            {
                "content": "Hex values: 0xFF, 0x1A2B, and 0ffh. Binary flags: 0b1010 and 11001100b."
            }
        ]
        feat = extract_notation_features(messages)
        hex_dist = feat["hex_notation_style"]
        bin_dist = feat["binary_notation_style"]

        assert len(hex_dist) > 0
        assert len(bin_dist) > 0
        assert sum(hex_dist.values()) == pytest.approx(1.0, 0.01)
        assert sum(bin_dist.values()) == pytest.approx(1.0, 0.01)

    def test_version_and_range_notation(self):
        messages = [
            {
                "content": (
                    "Installed spectra 1.2.3 and patch v2.0. "
                    "Ports: 10-20, indices 10..20, and range 10 to 20."
                )
            }
        ]
        feat = extract_notation_features(messages)
        ver_dist = feat["version_number_style"]
        range_dist = feat["range_notation_style"]

        assert len(ver_dist) > 0
        assert len(range_dist) > 0
        assert sum(ver_dist.values()) == pytest.approx(1.0, 0.01)
        assert sum(range_dist.values()) == pytest.approx(1.0, 0.01)

    def test_scalars_valid_and_distributions_capped(self):
        messages = [
            {"content": f"Measurement {i}: {i * 1.5} GB on 2026-08-{i+1:02d} at {i % 24:02d}:00 with version 1.{i}.0"}
            for i in range(25)
        ]
        feat = extract_notation_features(messages)
        assert 0.0 <= feat["number_word_preference"] <= 1.0
        assert len(feat["decimal_precision_distribution"]) <= 50
        assert len(feat["thousands_separator_style"]) <= 50
        assert len(feat["currency_format_style"]) <= 50
        assert len(feat["date_format_distribution"]) <= 50
        assert len(feat["time_format_distribution"]) <= 50
        assert len(feat["unit_spacing_style"]) <= 50
        assert len(feat["unit_abbreviation_style"]) <= 50
        assert len(feat["hex_notation_style"]) <= 50
        assert len(feat["binary_notation_style"]) <= 50
        assert len(feat["version_number_style"]) <= 50
        assert len(feat["range_notation_style"]) <= 50
