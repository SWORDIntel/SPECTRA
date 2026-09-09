"""
Unit tests for intelligence feature extractors and comparators.

Tests:
- Linguistic feature extraction and stylometric metrics
- Linguistic feature comparison (cosine similarity, confidence)
- Temporal feature extraction (circadian, weekday/weekend, burst, latency, gaps)
- Temporal feature comparison (histogram intersection, metric differences)
"""
from __future__ import annotations

from datetime import datetime, timezone
import pytest

from tgarchive.intelligence.features import (
    extract_linguistic_features,
    compare_linguistic_features,
    extract_temporal_features,
    compare_temporal_features,
)


class TestLinguisticFeatures:
    """Tests for linguistic feature extraction and comparison."""

    def test_empty_messages(self):
        feat = extract_linguistic_features([])
        assert isinstance(feat, dict)
        assert feat["char_2gram_diversity"] == 0.0
        assert feat["fw_the"] == 0.0
        assert feat["punctuation_density"] == 0.0
        assert feat["avg_message_length"] == 0.0

    def test_messages_without_text(self):
        feat = extract_linguistic_features([{"id": 1}, {"date": "2024-01-01"}, {"content": None}])
        assert feat["char_2gram_diversity"] == 0.0
        assert feat["lexical_richness_ttr"] == 0.0

    def test_content_and_text_fields(self):
        messages = [
            {"content": "The quick brown fox jumps over the lazy dog."},
            {"text": "And the dog barked at the moon!"},
        ]
        feat = extract_linguistic_features(messages)
        assert feat["avg_message_length"] > 0
        assert feat["char_2gram_diversity"] > 0
        assert feat["char_3gram_diversity"] > 0
        assert feat["char_4gram_diversity"] > 0
        assert feat["fw_the"] > 0
        assert feat["fw_and"] > 0
        assert feat["punctuation_density"] > 0
        assert feat["punctuation_diversity"] > 0
        assert feat["lexical_richness_ttr"] > 0

    def test_whitespace_features(self):
        messages = [
            {"text": "Trailing space message "},
            {"text": "Double  space inside message"},
            {"text": "Normal clean message"},
        ]
        feat = extract_linguistic_features(messages)
        assert pytest.approx(feat["whitespace_trailing_ratio"], 0.01) == 1 / 3
        assert pytest.approx(feat["whitespace_double_space_ratio"], 0.01) == 1 / 3

    def test_typo_and_contraction_detection(self):
        messages = [
            {"text": "I can't believe this soooo cool! Don't miss it!"},
            {"text": "It's amazinggggg and we'll see!"},
        ]
        feat = extract_linguistic_features(messages)
        assert feat["typo_rate"] > 0  # 'soooo', 'amazinggggg'
        assert feat["contraction_rate"] > 0  # can't, don't, it's, we'll

    def test_emoji_extraction(self):
        messages = [
            {"text": "Hello world! 😊🚀🔥"},
            {"text": "Another test without emoji"},
        ]
        feat = extract_linguistic_features(messages)
        assert feat["emoji_density"] > 0
        assert feat["emoji_diversity"] > 0

    def test_lexical_richness_yule_k(self):
        # Repetitive text should have higher Yule's K than diverse text
        repetitive = [{"text": "word word word word word word word word"}]
        diverse = [{"text": "one two three four five six seven eight nine ten"}]
        feat_rep = extract_linguistic_features(repetitive)
        feat_div = extract_linguistic_features(diverse)
        assert feat_rep["lexical_richness_yule_k"] > feat_div["lexical_richness_yule_k"]
        assert feat_div["lexical_richness_ttr"] > feat_rep["lexical_richness_ttr"]

    def test_code_switching_detection(self):
        messages = [
            {"text": "This is purely English text."},
            {"text": "Привет and hello mixing Cyrillic with English."},
        ]
        feat = extract_linguistic_features(messages)
        assert pytest.approx(feat["code_switching_score"], 0.01) == 0.5

    def test_line_breaks_and_structural_metrics(self):
        messages = [
            {"text": "Line 1\nLine 2\nLine 3"},
            {"text": "Single line message"},
        ]
        feat = extract_linguistic_features(messages)
        assert pytest.approx(feat["avg_line_breaks"], 0.01) == 1.0

    def test_ratios(self):
        messages = [{"text": "ABC 123 !@#"}]
        feat = extract_linguistic_features(messages)
        assert feat["uppercase_ratio"] > 0
        assert feat["digit_ratio"] > 0
        assert feat["special_char_ratio"] > 0

    def test_compare_linguistic_features_identical(self):
        messages = [
            {"text": "Threat actor operational communications with specialized technical terms."},
            {"text": "Another message analyzing exploits and vulnerabilities in software."},
        ]
        feat_a = extract_linguistic_features(messages)
        feat_b = extract_linguistic_features(messages)

        sim, conf = compare_linguistic_features(feat_a, feat_b)
        assert sim == pytest.approx(1.0, 0.01)
        assert conf == pytest.approx(1.0, 0.01)

    def test_compare_linguistic_features_empty(self):
        sim, conf = compare_linguistic_features({}, {})
        assert sim == 0.0
        assert conf == 0.0

    def test_compare_linguistic_features_partial(self):
        feat_a = {"fw_the": 0.05, "avg_message_length": 50.0}
        feat_b = {"fw_the": 0.05, "avg_message_length": 50.0}
        sim, conf = compare_linguistic_features(feat_a, feat_b)
        assert sim == pytest.approx(1.0, 0.01)
        assert 0.0 < conf < 1.0


class TestTemporalFeatures:
    """Tests for temporal feature extraction and comparison."""

    def test_empty_messages(self):
        feat = extract_temporal_features([])
        assert isinstance(feat, dict)
        assert feat["hour_0"] == 0.0
        assert feat["weekday_ratio"] == 0.0
        assert feat["burst_frequency"] == 0.0

    def test_invalid_dates(self):
        feat = extract_temporal_features([{"date": "invalid_date_string"}, {"date": None}])
        assert feat["hour_0"] == 0.0

    def test_datetime_formats(self):
        messages = [
            {"date": datetime(2024, 1, 15, 14, 0, 0, tzinfo=timezone.utc)},  # Monday 14:00
            {"date": "2024-01-15T14:30:00Z"},                                  # Monday 14:30
            {"date": "2024-01-20 18:00:00"},                                  # Saturday 18:00
        ]
        feat = extract_temporal_features(messages)
        assert feat["hour_14"] == pytest.approx(2 / 3, 0.01)
        assert feat["hour_18"] == pytest.approx(1 / 3, 0.01)
        assert feat["weekday_ratio"] == pytest.approx(2 / 3, 0.01)
        assert feat["weekend_ratio"] == pytest.approx(1 / 3, 0.01)
        # Sum of 24 hours must be 1.0
        assert sum(feat[f"hour_{h}"] for h in range(24)) == pytest.approx(1.0, 0.01)

    def test_response_latency_calculation(self):
        messages = [
            {"id": 100, "date": "2024-01-15T10:00:00Z"},
            {"id": 101, "reply_to": 100, "date": "2024-01-15T10:05:00Z"},  # 300s latency
            {"id": 102, "reply_to": 101, "date": "2024-01-15T10:15:00Z"},  # 600s latency
            {"id": 103, "reply_to": 102, "date": "2024-01-15T10:30:00Z"},  # 900s latency
            {"id": 104, "reply_to": 103, "date": "2024-01-15T11:00:00Z"},  # 1800s latency
        ]
        feat = extract_temporal_features(messages)
        assert feat["response_latency_median"] > 0
        assert feat["response_latency_iqr"] >= 0

    def test_direct_reply_latency_field(self):
        messages = [
            {"date": "2024-01-15T10:00:00Z", "reply_latency": 120.0},
            {"date": "2024-01-15T10:05:00Z", "reply_latency": 240.0},
        ]
        feat = extract_temporal_features(messages)
        assert feat["response_latency_median"] == pytest.approx(180.0, 0.01)

    def test_burst_detection(self):
        # 6 messages within 30 minutes on the same day -> 1 burst
        messages = [
            {"date": f"2024-01-15T10:0{i}:00Z"} for i in range(6)
        ]
        feat = extract_temporal_features(messages)
        assert feat["burst_frequency"] >= 1.0
        assert feat["burst_intensity"] >= 5.0

    def test_inactivity_gaps(self):
        messages = [
            {"date": "2024-01-15T10:00:00Z"},
            {"date": "2024-01-15T12:00:00Z"},  # 2 hours gap
            {"date": "2024-01-15T18:00:00Z"},  # 6 hours gap
        ]
        feat = extract_temporal_features(messages)
        assert feat["longest_inactivity_hours"] == pytest.approx(6.0, 0.01)
        assert feat["typical_gap_hours"] == pytest.approx(4.0, 0.01)

    def test_timezone_confidence(self):
        # All messages in hour 14 -> high confidence (peaked)
        peaked_messages = [{"date": f"2024-01-15T14:{i:02d}:00Z"} for i in range(12)]
        feat_peaked = extract_temporal_features(peaked_messages)
        assert feat_peaked["timezone_inference_confidence"] > 0.8

        # Messages spread across 24 different hours -> low confidence
        spread_messages = [{"date": f"2024-01-15T{h:02d}:00:00Z"} for h in range(24)]
        feat_spread = extract_temporal_features(spread_messages)
        assert feat_spread["timezone_inference_confidence"] < 0.1

    def test_compare_temporal_features_identical(self):
        messages = [
            {"date": "2024-01-15T10:00:00Z"},
            {"date": "2024-01-15T11:00:00Z"},
            {"date": "2024-01-15T12:00:00Z"},
        ]
        feat_a = extract_temporal_features(messages)
        feat_b = extract_temporal_features(messages)

        sim, conf = compare_temporal_features(feat_a, feat_b)
        assert sim == pytest.approx(1.0, 0.01)
        assert conf > 0.0

    def test_compare_temporal_features_distinct_timezones(self):
        # Morning UTC vs Night UTC
        messages_a = [{"date": f"2024-01-15T09:{i:02d}:00Z"} for i in range(10)]
        messages_b = [{"date": f"2024-01-15T21:{i:02d}:00Z"} for i in range(10)]
        feat_a = extract_temporal_features(messages_a)
        feat_b = extract_temporal_features(messages_b)

        sim, _ = compare_temporal_features(feat_a, feat_b)
        # Low similarity due to zero histogram overlap in hours
        assert sim < 0.6

    def test_compare_temporal_features_empty(self):
        sim, conf = compare_temporal_features({}, {})
        assert sim == 0.0
        assert conf == 0.0


class TestInfrastructureFeatures:
    """Tests for infrastructure feature extraction and comparison."""

    def test_empty_messages(self):
        from tgarchive.intelligence.features.infrastructure import (
            extract_infrastructure_features,
            compare_infrastructure_features,
        )
        feat = extract_infrastructure_features([])
        assert feat["wallets"] == []
        assert feat["urls"] == []
        assert feat["domains"] == []
        assert feat["ips"] == []
        assert feat["onions"] == []
        assert feat["bot_ids"] == []
        assert feat["contact_handles"] == []
        assert feat["emails"] == []
        assert feat["phone_numbers"] == []

        sim, conf = compare_infrastructure_features({}, {})
        assert sim == 0.0
        assert conf == 0.0

    def test_extraction(self):
        from tgarchive.intelligence.features.infrastructure import extract_infrastructure_features
        messages = [
            {
                "content": (
                    "Send 1.0 BTC to 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa or ETH 0x71C7656EC7ab88b098defB751B7401B5f6d8976F. "
                    "Visit https://example.com/panel and http://3g2upl4pq6kufc4m.onion/shop. "
                    "Contact @dark_bot or @support_admin at support@example.com or +1-800-555-0199. "
                    "Host: 1.1.1.1, private: 192.168.1.1"
                )
            }
        ]
        feat = extract_infrastructure_features(messages)
        assert "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa" in feat["wallets"]
        assert "0x71c7656ec7ab88b098defb751b7401b5f6d8976f" in feat["wallets"]
        assert "https://example.com/panel" in feat["urls"]
        assert "example.com" in feat["domains"]
        assert "3g2upl4pq6kufc4m.onion" in feat["onions"]
        assert "@dark_bot" in feat["bot_ids"]
        assert "@support_admin" in feat["contact_handles"]
        assert "@dark_bot" not in feat["contact_handles"]
        assert "support@example.com" in feat["emails"]
        assert "1.1.1.1" in feat["ips"]
        assert "192.168.1.1" not in feat["ips"]
        assert len(feat["phone_numbers"]) > 0

    def test_comparison_anti_double_counting(self):
        from tgarchive.intelligence.features.infrastructure import (
            extract_infrastructure_features,
            compare_infrastructure_features,
        )
        msgs_a = [{"content": "Check https://shadow-market.org/login and 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"}]
        msgs_b = [{"content": "Check https://shadow-market.org/panel and 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"}]

        feat_a = extract_infrastructure_features(msgs_a)
        feat_b = extract_infrastructure_features(msgs_b)

        sim, conf = compare_infrastructure_features(feat_a, feat_b)
        assert sim > 0.8
        assert conf > 0.0


class TestTelegramNativeFeatures:
    """Tests for telegram native feature extraction and comparison."""

    def test_empty_messages(self):
        from tgarchive.intelligence.features.telegram_native import (
            extract_telegram_features,
            compare_telegram_features,
        )
        feat = extract_telegram_features([], user_id=10)
        assert feat["channels"] == []
        assert feat["reply_targets"] == []
        assert feat["reply_sources"] == []
        assert feat["forwarded_from"] == []
        assert feat["shared_media_ids"] == []
        assert feat["username_changes"] == []

        sim, conf = compare_telegram_features({}, {})
        assert sim == 0.0
        assert conf == 0.0

    def test_extraction_and_username_changes(self):
        from tgarchive.intelligence.features.telegram_native import (
            extract_telegram_features,
            compare_telegram_features,
        )
        msgs_a = [
            {
                "channel_id": 100,
                "user_id": 10,
                "reply_to_user_id": 20,
                "forward_from_id": 30,
                "media_id": "media_99",
                "username": "handle_v1",
                "date": "2026-01-01T10:00:00Z",
            },
            {
                "channel_id": 101,
                "user_id": 10,
                "reply_to_user_id": 21,
                "username": "handle_v2",
                "date": "2026-01-02T10:00:00Z",
            },
        ]
        msgs_b = [
            {
                "channel_id": 100,
                "user_id": 11,
                "reply_to_user_id": 20,
                "media_id": "media_99",
                "action": "username_change",
                "old_username": "handle_v1",
                "new_username": "handle_v2",
            }
        ]

        feat_a = extract_telegram_features(msgs_a, user_id=10, channel_id=100)
        feat_b = extract_telegram_features(msgs_b, user_id=11, channel_id=100)

        assert "100" in feat_a["channels"]
        assert "20" in feat_a["reply_targets"]
        assert "media_99" in feat_a["shared_media_ids"]
        assert len(feat_a["username_changes"]) > 0
        assert len(feat_b["username_changes"]) > 0

        sim, conf = compare_telegram_features(feat_a, feat_b)
        assert sim > 0.5
        assert conf > 0.5


class TestMediaFeatures:
    """Tests for media feature extraction and comparison."""

    def test_empty_media(self):
        from tgarchive.intelligence.features.media import (
            extract_media_features,
            compare_media_features,
        )
        feat = extract_media_features([])
        assert feat["perceptual_hashes"] == []
        assert feat["exact_hashes"] == []
        assert feat["ocr_strings"] == []
        assert feat["file_names"] == []
        assert feat["file_extensions"] == []
        assert feat["mime_types"] == []

        sim, conf = compare_media_features({}, {})
        assert sim == 0.0
        assert conf == 0.0

    def test_media_comparison(self):
        from tgarchive.intelligence.features.media import (
            extract_media_features,
            compare_media_features,
        )
        media_a = [
            {
                "phash": "a1b2c3d4e5f60718",
                "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "ocr_text": "CREDENTIAL DUMP LEAK 2026",
                "file_name": "credentials_2026.csv",
                "mime_type": "text/csv",
            }
        ]
        media_b = [
            {
                "phash": "a1b2c3d4e5f60718",
                "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "ocr_text": "CREDENTIAL DUMP LEAK",
                "file_name": "credentials_2026.csv",
                "mime_type": "text/csv",
            }
        ]

        feat_a = extract_media_features(media_a)
        feat_b = extract_media_features(media_b)
        assert feat_a["file_extensions"] == ["csv"]

        sim, conf = compare_media_features(feat_a, feat_b)
        assert sim == pytest.approx(1.0, 0.01)
        assert conf > 0.5


class TestCommercialFeatures:
    """Tests for commercial feature extraction and comparison."""

    def test_empty_messages(self):
        from tgarchive.intelligence.features.commercial import (
            extract_commercial_features,
            compare_commercial_features,
        )
        feat = extract_commercial_features([])
        assert feat["price_points"] == []
        assert feat["currencies"] == []
        assert feat["min_order_sizes"] == []
        assert feat["product_categories"] == []
        assert feat["sales_phrases"] == []
        assert feat["escrow_mentions"] == 0
        assert feat["discount_patterns"] == []

        sim, conf = compare_commercial_features({}, {})
        assert sim == 0.0
        assert conf == 0.0

    def test_extraction_and_comparison(self):
        from tgarchive.intelligence.features.commercial import (
            extract_commercial_features,
            compare_commercial_features,
        )
        msgs_a = [
            {
                "content": (
                    "Selling redline stealer logs, min order 10 logs. "
                    "Price $150 USD or 0.005 BTC. Escrow accepted. DM for info! 20% off for bulk."
                )
            }
        ]
        msgs_b = [
            {
                "content": (
                    "Available redline logs, price 150 USD. MOQ 10 logs. "
                    "PM for info. Verified escrow accepted. Bulk discount available."
                )
            }
        ]

        feat_a = extract_commercial_features(msgs_a)
        feat_b = extract_commercial_features(msgs_b)

        assert "logs_credentials" in feat_a["product_categories"]
        assert "USD" in feat_a["currencies"]
        assert 150.0 in feat_a["price_points"]
        assert feat_a["escrow_mentions"] > 0
        assert len(feat_a["discount_patterns"]) > 0

        sim, conf = compare_commercial_features(feat_a, feat_b)
        assert sim > 0.7
        assert conf > 0.5

