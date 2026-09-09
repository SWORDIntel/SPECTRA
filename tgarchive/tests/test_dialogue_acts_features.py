"""
Unit tests for Dialogue Acts and Affective Expression feature extraction (L11/L12).

Tests:
- Empty messages and messages without text return defaults
- Known input produces expected dialogue act distributions and transition matrix
- Dialogue acts classification works for all 15 speech acts
- Sentiment detection (positive, neutral, negative) and negation handling work
- Emotion markers (joy, anger, sadness, fear, surprise, disgust) are correctly identified
- Emphasis rate, sarcasm rate, and humor rate are correctly computed
- Conditionals under negative sentiment (intensification, profanity) are measured
- Punctuation and message length given emotion are correctly formatted
- Output is JSON-serializable
- Distributions are capped at 50 entries
- All scalar values are in valid ranges
- Profile comparison works correctly
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from tgarchive.intelligence.features.dialogue_acts import (
    ALL_DIALOGUE_ACTS,
    DEFAULT_DIALOGUE_ACTS_FEATURES,
    classify_dialogue_act,
    classify_sentiment,
    compare_dialogue_acts_features,
    detect_emotion_markers,
    extract_dialogue_acts_features,
)


def _msg(content, date=None, reply_to=None, msg_id=None):
    m = {"content": content}
    if date is not None:
        m["date"] = date
    if reply_to is not None:
        m["reply_to_message_id"] = reply_to
    if msg_id is not None:
        m["id"] = msg_id
    return m


class TestDialogueActsFeatures:
    """Tests for Dialogue Acts & Affective Expression module."""

    def test_empty_messages_returns_defaults(self):
        feat = extract_dialogue_acts_features([])
        assert isinstance(feat, dict)
        assert feat == DEFAULT_DIALOGUE_ACTS_FEATURES
        assert feat["dialogue_act_distribution"] == {}
        assert feat["dialogue_act_transition_matrix"] == {}
        assert feat["sentiment_distribution"] == {"positive": 0.0, "neutral": 0.0, "negative": 0.0}
        assert feat["emotion_marker_distribution"] == {
            "joy": 0.0, "anger": 0.0, "sadness": 0.0,
            "fear": 0.0, "surprise": 0.0, "disgust": 0.0,
        }
        assert feat["emphasis_rate"] == 0.0
        assert feat["intensification_under_negative_sentiment"] == 0.0
        assert feat["profanity_given_negative_sentiment"] == 0.0
        assert feat["punctuation_given_emotion"] == {
            "positive": {"exclaim": 0.0},
            "negative": {"exclaim": 0.0, "ellipsis": 0.0},
        }
        assert feat["message_length_given_emotion"] == {
            "positive": 0.0, "neutral": 0.0, "negative": 0.0,
        }
        assert feat["sarcasm_marker_rate"] == 0.0
        assert feat["humor_marker_rate"] == 0.0

    def test_messages_without_text(self):
        feat = extract_dialogue_acts_features([
            {"id": 1},
            {"date": "2026-08-23T10:00:00Z"},
            {"content": None},
            {"text": ""},
            {"content": "   "},
        ])
        assert feat == DEFAULT_DIALOGUE_ACTS_FEATURES

    def test_json_serializability(self):
        msgs = [
            _msg("What time does the deployment start?", date="2026-08-23T10:00:00Z", msg_id=1),
            _msg("The deployment starts at 14:00 UTC", date="2026-08-23T10:01:00Z", reply_to=1, msg_id=2),
            _msg("Great, thanks!", date="2026-08-23T10:02:00Z", reply_to=2, msg_id=3),
        ]
        feat = extract_dialogue_acts_features(msgs)
        dumped = json.dumps(feat)
        loaded = json.loads(dumped)
        assert isinstance(loaded, dict)
        assert "dialogue_act_distribution" in loaded
        assert "sentiment_distribution" in loaded
        assert "dialogue_act_transition_matrix" in loaded

    def test_dialogue_act_classification_all_15_types(self):
        assert classify_dialogue_act({"content": "What is the status of the server?"}) == "question"
        assert classify_dialogue_act({"content": "How do we configure nginx"}) == "question"
        assert classify_dialogue_act({"content": "Is the database reachable?"}) == "question"

        assert classify_dialogue_act({"content": "The database is online at port 5432", "reply_to_message_id": 10}) == "answer"
        assert classify_dialogue_act({"content": "Here is the log file", "reply_to": 10}) == "answer"

        assert classify_dialogue_act({"content": "Please send the telemetry report"}) == "request"
        assert classify_dialogue_act({"content": "Could you check the error logs?"}) == "request"
        assert classify_dialogue_act({"content": "Would you mind reviewing this PR"}) == "request"

        assert classify_dialogue_act({"content": "Restart the docker service"}) == "command"
        assert classify_dialogue_act({"content": "Check the memory allocation"}) == "command"
        assert classify_dialogue_act({"content": "Do not delete the backup"}) == "command"

        assert classify_dialogue_act({"content": "How about we try caching the responses?"}) == "suggestion"
        assert classify_dialogue_act({"content": "You could use redis for that"}) == "suggestion"
        assert classify_dialogue_act({"content": "I suggest updating the dependencies"}) == "suggestion"

        assert classify_dialogue_act({"content": "Actually, that is wrong"}) == "correction"
        assert classify_dialogue_act({"content": "I think you mean port 8080"}) == "correction"
        assert classify_dialogue_act({"content": "That's wrong, it was fixed in v2"}) == "correction"

        assert classify_dialogue_act({"content": "Are you sure about that?"}) == "challenge"
        assert classify_dialogue_act({"content": "How come it failed in CI?"}) == "challenge"
        assert classify_dialogue_act({"content": "Why?"}) == "challenge"

        assert classify_dialogue_act({"content": "Yes, exactly right"}) == "agreement"
        assert classify_dialogue_act({"content": "I agree with this assessment"}) == "agreement"
        assert classify_dialogue_act({"content": "True, that makes sense"}) == "agreement"

        assert classify_dialogue_act({"content": "No, nope, that won't work"}) == "disagreement"
        assert classify_dialogue_act({"content": "I disagree with this decision"}) == "disagreement"
        assert classify_dialogue_act({"content": "I don't think so"}) == "disagreement"

        assert classify_dialogue_act({"content": "In other words, the database is healthy"}) == "clarification"
        assert classify_dialogue_act({"content": "Basically it acts as a FIFO queue"}) == "clarification"
        assert classify_dialogue_act({"content": "I mean that we should refactor"}) == "clarification"

        assert classify_dialogue_act({"content": "lol that was hilarious"}) == "joke"
        assert classify_dialogue_act({"content": "Haha yeah lmao"}) == "joke"
        assert classify_dialogue_act({"content": "rofl"}) == "joke"

        assert classify_dialogue_act({"content": "Ugh, this build is broken again and so annoying"}) == "complaint"
        assert classify_dialogue_act({"content": "Stupid bug is frustrating and broken"}) == "complaint"

        assert classify_dialogue_act({"content": "I wonder if there is a lock contention"}) == "hypothesis"
        assert classify_dialogue_act({"content": "Could be an issue with memory limits"}) == "hypothesis"
        assert classify_dialogue_act({"content": "Maybe it is a DNS propagation delay"}) == "hypothesis"

        assert classify_dialogue_act({"content": "I bet the build will pass on the next run"}) == "prediction"
        assert classify_dialogue_act({"content": "We are going to hit the rate limit"}) == "prediction"

        assert classify_dialogue_act({"content": "The system has 64 GB of RAM"}) == "observation"
        assert classify_dialogue_act({"content": "Configuration file is located at /etc/spectra.conf"}) == "observation"

    def test_dialogue_act_distribution(self):
        msgs = [
            _msg("What is this?"),
            _msg("What is that?"),
            _msg("Yes, I agree"),
            _msg("Restart the server"),
        ]
        feat = extract_dialogue_acts_features(msgs)
        dist = feat["dialogue_act_distribution"]
        assert "question" in dist
        assert "agreement" in dist
        assert "command" in dist
        assert dist["question"] == 0.5
        assert dist["agreement"] == 0.25
        assert dist["command"] == 0.25

    def test_dialogue_act_transition_matrix(self):
        base = datetime(2026, 8, 23, 10, 0, 0, tzinfo=timezone.utc)
        msgs = [
            _msg("What is the issue?", date=(base + timedelta(seconds=0)).isoformat(), msg_id=1),
            _msg("The service crashed due to OOM", date=(base + timedelta(seconds=10)).isoformat(), reply_to=1, msg_id=2),
            _msg("Yes, exactly, I noticed high memory earlier", date=(base + timedelta(seconds=20)).isoformat(), reply_to=2, msg_id=3),
            _msg("Restart the daemon now", date=(base + timedelta(seconds=30)).isoformat(), msg_id=4),
        ]
        feat = extract_dialogue_acts_features(msgs)
        matrix = feat["dialogue_act_transition_matrix"]
        assert "question" in matrix
        assert "answer" in matrix["question"]
        assert matrix["question"]["answer"] == 1.0

        assert "answer" in matrix
        assert "agreement" in matrix["answer"]
        assert matrix["answer"]["agreement"] == 1.0

        assert "agreement" in matrix
        assert "command" in matrix["agreement"]
        assert matrix["agreement"]["command"] == 1.0

    def test_sentiment_distribution_and_negation(self):
        msgs = [
            _msg("This is fantastic and great, excellent work!"),  # positive
            _msg("The server temperature is 45 degrees Celsius."),  # neutral
            _msg("Terrible failure, horrible bug and awful crash!"),  # negative
            _msg("This is not bad at all, quite good."),  # positive / negated bad
            _msg("This is not good, very buggy and broken."),  # negative / negated good
        ]
        feat = extract_dialogue_acts_features(msgs)
        sent = feat["sentiment_distribution"]
        assert sent["positive"] > 0.0
        assert sent["neutral"] > 0.0
        assert sent["negative"] > 0.0
        total_sent = sent["positive"] + sent["neutral"] + sent["negative"]
        assert pytest.approx(total_sent, 0.001) == 1.0

    def test_emotion_marker_distribution(self):
        msgs = [
            _msg("I am so happy and delighted with this win!"),  # joy
            _msg("I am furious, raging mad and hate this!"),  # anger
            _msg("Feeling so sad, depressed, lonely and weeping."),  # sadness
            _msg("I am terrified, panicked and scared of data loss."),  # fear
            _msg("Wow omg I am shocked and astonished!"),  # surprise
            _msg("This is disgusting, repulsive, foul and gross."),  # disgust
        ]
        feat = extract_dialogue_acts_features(msgs)
        emotions = feat["emotion_marker_distribution"]
        assert emotions["joy"] > 0.0
        assert emotions["anger"] > 0.0
        assert emotions["sadness"] > 0.0
        assert emotions["fear"] > 0.0
        assert emotions["surprise"] > 0.0
        assert emotions["disgust"] > 0.0

    def test_emphasis_rate(self):
        msgs = [
            _msg("PLEASE STOP THIS IMMEDIATELY!"),  # ALL CAPS + !
            _msg("This is **critical** information."),  # bold
            _msg("Just a normal lowercase sentence."),
        ]
        feat = extract_dialogue_acts_features(msgs)
        assert feat["emphasis_rate"] == pytest.approx(2 / 3, 0.0001)

    def test_intensification_and_profanity_under_negative_sentiment(self):
        msgs = [
            _msg("This is extremely bad and very terrible!"),  # negative + intensifiers
            _msg("This broken crap is totally fucked up!"),  # negative + profanity + intensifier
            _msg("Normal neutral observation about logs."),  # neutral
            _msg("Awesome and brilliant success!"),  # positive
        ]
        feat = extract_dialogue_acts_features(msgs)
        assert feat["intensification_under_negative_sentiment"] == 1.0  # 2 of 2 negative messages
        assert feat["profanity_given_negative_sentiment"] == 0.5  # 1 of 2 negative messages

    def test_punctuation_given_emotion(self):
        msgs = [
            _msg("Awesome result!"),  # positive with !
            _msg("Good job"),  # positive without !
            _msg("Terrible crash!"),  # negative with !
            _msg("Awful bug..."),  # negative with ellipsis
        ]
        feat = extract_dialogue_acts_features(msgs)
        punct = feat["punctuation_given_emotion"]
        assert punct["positive"]["exclaim"] == 0.5
        assert punct["negative"]["exclaim"] == 0.5
        assert punct["negative"]["ellipsis"] == 0.5

    def test_message_length_given_emotion(self):
        msgs = [
            _msg("Great!"),  # len 6
            _msg("This is a standard neutral log entry."),  # len 37
            _msg("This failed miserably and crashed!"),  # len 35
        ]
        feat = extract_dialogue_acts_features(msgs)
        lens = feat["message_length_given_emotion"]
        assert lens["positive"] == 6.0
        assert lens["neutral"] == 37.0
        assert lens["negative"] == 34.0

    def test_sarcasm_and_humor_marker_rates(self):
        msgs = [
            _msg("Yeah right, like that would ever work /s"),  # sarcasm + /s
            _msg("lol haha that was so funny lmao 😂"),  # humor
            _msg("Sure, obviously you broke the production database again."),  # sarcasm in negative context
            _msg("Plain text without special markers."),
        ]
        feat = extract_dialogue_acts_features(msgs)
        assert feat["sarcasm_marker_rate"] == 0.5  # 2 of 4
        assert feat["humor_marker_rate"] == 0.25  # 1 of 4

    def test_scalars_in_valid_range(self):
        msgs = [
            _msg("What is your plan for tomorrow?"),
            _msg("We are going to deploy the update at noon.", reply_to=1),
            _msg("Fantastic! Looking forward to it!"),
            _msg("Ugh, wait, there is an annoying bug in the auth module..."),
        ]
        feat = extract_dialogue_acts_features(msgs)
        scalar_keys = [
            "emphasis_rate",
            "intensification_under_negative_sentiment",
            "profanity_given_negative_sentiment",
            "sarcasm_marker_rate",
            "humor_marker_rate",
        ]
        for k in scalar_keys:
            val = feat[k]
            assert isinstance(val, (int, float)), f"{k} is not numeric"
            assert 0.0 <= val <= 1.0, f"{k}={val} is out of [0, 1] range"

        for k, v in feat["sentiment_distribution"].items():
            assert 0.0 <= v <= 1.0, f"sentiment {k}={v} out of range"

        for k, v in feat["emotion_marker_distribution"].items():
            assert 0.0 <= v <= 1.0, f"emotion {k}={v} out of range"

        for em, pdict in feat["punctuation_given_emotion"].items():
            for pk, pv in pdict.items():
                assert 0.0 <= pv <= 1.0, f"punct {em}.{pk}={pv} out of range"

        for em, mlen in feat["message_length_given_emotion"].items():
            assert mlen >= 0.0, f"length {em}={mlen} is negative"

    def test_distributions_capped_at_50(self):
        # Generate messages that trigger varied dialogue acts
        msgs = [_msg(f"Message number {i}") for i in range(100)]
        feat = extract_dialogue_acts_features(msgs)
        assert len(feat["dialogue_act_distribution"]) <= 50
        for act, trans in feat["dialogue_act_transition_matrix"].items():
            assert len(trans) <= 50

    def test_compare_dialogue_acts_features(self):
        msgs_a = [
            _msg("What is the build status?"),
            _msg("Awesome, it passed!"),
            _msg("lol haha great job"),
        ]
        msgs_b = [
            _msg("How is the test suite?"),
            _msg("Brilliant, all tests green!"),
            _msg("haha lol amazing"),
        ]
        msgs_c = [
            _msg("This broken crap is stupid and frustrating!"),
            _msg("Ugh, hate this terrible failure..."),
        ]

        feat_a = extract_dialogue_acts_features(msgs_a)
        feat_b = extract_dialogue_acts_features(msgs_b)
        feat_c = extract_dialogue_acts_features(msgs_c)

        sim_ab, conf_ab = compare_dialogue_acts_features(feat_a, feat_b)
        sim_ac, conf_ac = compare_dialogue_acts_features(feat_a, feat_c)

        assert 0.0 <= sim_ab <= 1.0
        assert 0.0 <= conf_ab <= 1.0
        assert 0.0 <= sim_ac <= 1.0
        assert 0.0 <= conf_ac <= 1.0
        assert sim_ab > sim_ac  # a and b are both positive/humorous/questioning, c is negative/complaining

        # Empty comparison
        assert compare_dialogue_acts_features({}, {}) == (0.0, 0.0)
