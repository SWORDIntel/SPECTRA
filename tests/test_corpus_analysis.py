import importlib.util
import sqlite3
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "corpus_analysis.py"
SPEC = importlib.util.spec_from_file_location("corpus_analysis", MODULE_PATH)
corpus_analysis = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(corpus_analysis)

SUBJECT = 8685287529
RELATED = 8000000005
OPERATOR = 8000000002


def create_database(path):
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE spectra_channels (
            id INTEGER PRIMARY KEY,
            title TEXT
        );
        CREATE TABLE spectra_messages (
            id INTEGER,
            channel_id INTEGER,
            sender_id INTEGER,
            date TEXT,
            text TEXT,
            has_media INTEGER DEFAULT 0,
            sender_name TEXT DEFAULT '',
            crime_score INTEGER DEFAULT 0,
            reply_to INTEGER DEFAULT 0,
            forwarded_from INTEGER DEFAULT 0,
            PRIMARY KEY(id, channel_id)
        );
        CREATE TABLE dm_corpus (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account TEXT,
            dialog_id INTEGER,
            peer_id INTEGER,
            peer_username TEXT,
            peer_display TEXT,
            message_id INTEGER,
            date TEXT,
            sender_id INTEGER,
            sender_name TEXT,
            text TEXT,
            has_media INTEGER,
            media_type TEXT,
            reply_to_msg INTEGER,
            is_out INTEGER,
            ingested_at TEXT
        );
    """)
    db.commit()
    return db


def add_dm(db, message_id, date, text, is_out):
    sender_id = OPERATOR if is_out else SUBJECT
    db.execute("""INSERT INTO dm_corpus
        (account, dialog_id, peer_id, peer_display, message_id, date, sender_id,
         sender_name, text, has_media, media_type, reply_to_msg, is_out, ingested_at)
        VALUES ('O07en', ?, ?, 'Subject', ?, ?, ?, '', ?, 0, '', 0, ?, ?)""",
        (SUBJECT, SUBJECT, message_id, date, sender_id, text, is_out, date))


def add_channel_message(db, message_id, channel_id, sender_id, date, text, reply_to=0):
    db.execute("""INSERT INTO spectra_messages
        (id, channel_id, sender_id, date, text, reply_to)
        VALUES (?, ?, ?, ?, ?, ?)""",
        (message_id, channel_id, sender_id, date, text, reply_to))


def test_analysis_preserves_context_and_avoids_authorship_claim(tmp_path):
    path = tmp_path / "analysis.db"
    db = create_database(path)
    add_dm(db, 1, "2026-08-07T20:24:11+00:00", "Could you be an AI trained on Maya?", 1)
    add_dm(db, 2, "2026-08-07T20:24:51+00:00", "Couldn't that just be AI gen", 0)
    add_dm(db, 3, "2026-08-07T20:25:06+00:00", "I'm not her though", 0)
    add_dm(db, 4, "2026-08-07T20:30:00+00:00", "I can't do any type of crime for financial benefit", 0)
    add_dm(db, 5, "2026-08-07T20:30:05+00:00", "One of the current limitations", 0)
    db.commit()
    db.close()

    result = corpus_analysis.analyze(path, SUBJECT, (RELATED, OPERATOR), persist=False)

    keys = {item["key"] for item in result["observations"]}
    assert "identity_proof_exchange" in keys
    assert "self_reported_constraints" in keys
    assert "identity_and_ai_discourse" in keys
    assert result["assessment"].startswith("Indeterminate")
    assert result["review_priority"] < 100
    proof = next(item for item in result["observations"] if item["key"] == "identity_proof_exchange")
    assert proof["count"] == 1
    assert proof["evidence"][0]["request"]["source_key"].endswith(":1")
    assert proof["evidence"][0]["response"]["source_key"].endswith(":2")
    assert "does not establish AI authorship" in proof["alternatives"]


def test_persisted_runs_are_idempotent_and_track_new_messages(tmp_path):
    path = tmp_path / "analysis.db"
    db = create_database(path)
    add_dm(db, 1, "2026-08-01T00:00:00+00:00", "Hello", 0)
    db.commit()
    db.close()

    first = corpus_analysis.analyze(path, SUBJECT, (RELATED,), persist=True)
    second = corpus_analysis.analyze(path, SUBJECT, (RELATED,), persist=True)

    assert first["unchanged"] is False
    assert second["unchanged"] is True
    assert second["new_message_count"] == 0
    assert first["run_id"] == second["run_id"]

    db = sqlite3.connect(path)
    add_dm(db, 2, "2026-08-01T00:01:00+00:00", "What happened?", 0)
    db.commit()
    db.close()

    third = corpus_analysis.analyze(path, SUBJECT, (RELATED,), persist=True)
    assert third["unchanged"] is False
    assert third["run_id"] != first["run_id"]
    assert third["new_message_count"] == 1

    db = sqlite3.connect(path)
    assert db.execute("SELECT COUNT(*) FROM corpus_analysis_runs").fetchone()[0] == 2
    assert db.execute(
        "SELECT status FROM analysis_method_registry WHERE method_name='ai_detection_scores'"
    ).fetchone()[0] == "deprecated"
    db.close()


def test_temporal_proximity_counts_each_subject_message_once(tmp_path):
    path = tmp_path / "analysis.db"
    db = create_database(path)
    db.execute("INSERT INTO spectra_channels (id, title) VALUES (10, 'Shared')")
    add_channel_message(db, 1, 10, SUBJECT, "2026-08-01T00:00:00+00:00", "one")
    add_channel_message(db, 2, 10, SUBJECT, "2026-08-01T00:30:00+00:00", "two")
    add_channel_message(db, 3, 10, RELATED, "2026-08-01T00:03:00+00:00", "related one")
    add_channel_message(db, 4, 10, RELATED, "2026-08-01T00:04:00+00:00", "related two")
    db.commit()
    db.close()

    result = corpus_analysis.analyze(path, SUBJECT, (RELATED,), persist=False)
    proximity = next(
        item for item in result["observations"]
        if item["key"] == f"shared_channel_temporal_proximity:{RELATED}"
    )
    derived = proximity["evidence"][0]
    assert derived["subject_messages_in_shared_channels"] == 2
    assert derived["within_ten_minutes"] == 1
    assert derived["ratio"] == 0.5


def test_style_shift_requires_sufficient_samples(tmp_path):
    path = tmp_path / "analysis.db"
    db = create_database(path)
    db.execute("INSERT INTO spectra_channels (id, title) VALUES (10, 'Shared')")
    for index in range(10):
        add_dm(db, index + 1, f"2026-08-01T00:{index:02d}:00+00:00", "short", 0)
        add_channel_message(db, index + 1, 10, SUBJECT, f"2026-08-01T01:{index:02d}:00+00:00", "longer channel text")
    db.commit()
    db.close()

    result = corpus_analysis.analyze(path, SUBJECT, (RELATED,), persist=False)
    assert "dm_channel_style_shift" not in {item["key"] for item in result["observations"]}


def _add_users_table(db):
    db.execute("CREATE TABLE IF NOT EXISTS spectra_users (id INTEGER PRIMARY KEY, bot INTEGER DEFAULT 0)")


def test_peer_calibration_requires_five_controls(tmp_path):
    """Peer calibration must return None when fewer than 5 eligible controls exist."""
    path = tmp_path / "analysis.db"
    db = create_database(path)
    _add_users_table(db)
    db.execute("INSERT INTO spectra_channels (id, title) VALUES (10, 'Shared')")
    for index in range(35):
        add_channel_message(db, index + 1, 10, SUBJECT,
                            f"2026-08-01T00:{index % 60:02d}:00+00:00",
                            f"subject message number {index}")
    for index in range(3):
        add_channel_message(db, 100 + index, 10, 2000000 + index,
                            f"2026-08-01T01:{index:02d}:00+00:00",
                            f"peer message {index} with enough text to count")
    for index in range(35):
        add_channel_message(db, 200 + index, 10, 2000000,
                            f"2026-08-01T02:{index % 60:02d}:00+00:00",
                            f"peer long message {index} with content")
    db.commit()
    db.close()

    result = corpus_analysis.analyze(path, SUBJECT, (RELATED,), persist=False)
    assert "peer_calibrated_style" not in {item["key"] for item in result["observations"]}


def test_peer_calibration_emits_outlier_features(tmp_path):
    """With 5+ controls, peer calibration must emit observations with robust deviations."""
    path = tmp_path / "analysis.db"
    db = create_database(path)
    _add_users_table(db)
    db.execute("INSERT INTO spectra_channels (id, title) VALUES (10, 'Shared')")
    for index in range(40):
        add_channel_message(db, index + 1, 10, SUBJECT,
                            f"2026-08-01T00:{index % 60:02d}:00+00:00",
                            f"subject writes a fairly long message about topic {index} here")
    for peer in range(6):
        for index in range(35):
            add_channel_message(db, 1000 + peer * 100 + index, 10, 3000000 + peer,
                                f"2026-08-01T03:{index % 60:02d}:00+00:00",
                                f"ok {peer}")
    db.commit()
    db.close()

    result = corpus_analysis.analyze(path, SUBJECT, (RELATED,), persist=False)
    peer_obs = next(
        (item for item in result["observations"] if item["key"] == "peer_calibrated_style"),
        None,
    )
    assert peer_obs is not None
    assert peer_obs["confidence"] == "moderate"
    assert "not an AI classification" in peer_obs["alternatives"]
    derived = peer_obs["evidence"][0]
    assert derived["peer_count"] >= 5
    assert "outlier_features" in derived
    assert "comparisons" in derived
    assert "mean_length" in derived["comparisons"]


def test_longitudinal_style_detects_shift(tmp_path):
    """Longitudinal style must detect a shift when the first and last windows differ significantly."""
    path = tmp_path / "analysis.db"
    db = create_database(path)
    for index in range(50):
        add_dm(db, index + 1, f"2026-08-01T00:{index % 60:02d}:00+00:00", "hi", 0)
    for index in range(50):
        add_dm(db, 100 + index, f"2026-09-01T00:{index % 60:02d}:00+00:00",
                "Well, I must say that this is quite a remarkably verbose and elaborate message, wouldn't you agree?", 0)
    db.commit()
    db.close()

    result = corpus_analysis.analyze(path, SUBJECT, (RELATED,), persist=False)
    longitudinal = next(
        (item for item in result["observations"] if item["key"] == "longitudinal_style:dm"),
        None,
    )
    assert longitudinal is not None
    assert longitudinal["confidence"] == "moderate"
    assert "not an authorship classifier" in longitudinal["alternatives"]
    derived = longitudinal["evidence"][0]
    assert derived["context"] == "dm"
    assert len(derived["windows"]) == 4
    assert "mean_length" in derived["shifted_features"]


def test_longitudinal_style_skips_insufficient_samples(tmp_path):
    """Longitudinal style must not emit when there are fewer than 80 dated messages."""
    path = tmp_path / "analysis.db"
    db = create_database(path)
    for index in range(50):
        add_dm(db, index + 1, f"2026-08-01T00:{index % 60:02d}:00+00:00", "hi", 0)
    db.commit()
    db.close()

    result = corpus_analysis.analyze(path, SUBJECT, (RELATED,), persist=False)
    assert "longitudinal_style:dm" not in {item["key"] for item in result["observations"]}


def test_repetition_patterns_detects_duplicates(tmp_path):
    """Repetition detection must find exact normalized duplicates and repeated phrases."""
    path = tmp_path / "analysis.db"
    db = create_database(path)
    for index in range(35):
        add_dm(db, index + 1, f"2026-08-01T00:{index % 60:02d}:00+00:00",
               "the quick brown fox jumps over the lazy dog", 0)
    for index in range(10):
        add_dm(db, 100 + index, f"2026-08-02T00:{index:02d}:00+00:00",
               f"unique message {index} about something different", 0)
    db.commit()
    db.close()

    result = corpus_analysis.analyze(path, SUBJECT, (RELATED,), persist=False)
    repetition = next(
        (item for item in result["observations"] if item["key"] == "repetition_and_templating"),
        None,
    )
    assert repetition is not None
    assert repetition["confidence"] == "moderate"
    assert "not proof of generated text" in repetition["alternatives"]
    summary = repetition["evidence"][0]
    assert summary["exact_duplicate_groups"] >= 1
    assert summary["exact_duplicate_excess"] >= 34


def test_repetition_patterns_skips_insufficient_samples(tmp_path):
    """Repetition detection must not emit when there are fewer than 30 eligible messages."""
    path = tmp_path / "analysis.db"
    db = create_database(path)
    for index in range(10):
        add_dm(db, index + 1, f"2026-08-01T00:{index:02d}:00+00:00",
               "the quick brown fox", 0)
    db.commit()
    db.close()

    result = corpus_analysis.analyze(path, SUBJECT, (RELATED,), persist=False)
    assert "repetition_and_templating" not in {item["key"] for item in result["observations"]}


def test_explicit_claim_conflicts_detects_opposing_claims(tmp_path):
    """Claim conflict detection must find opposing polarity relationship claims."""
    path = tmp_path / "analysis.db"
    db = create_database(path)
    add_dm(db, 1, "2026-08-01T00:00:00+00:00", "my girlfriend is jewish", 0)
    add_dm(db, 2, "2026-08-02T00:00:00+00:00", "my girlfriend isn't jewish", 0)
    add_dm(db, 3, "2026-08-03T00:00:00+00:00", "some unrelated filler message", 0)
    db.commit()
    db.close()

    result = corpus_analysis.analyze(path, SUBJECT, (RELATED,), persist=False)
    conflicts = next(
        (item for item in result["observations"]
         if item["key"] == "explicit_claim_conflict_candidates"),
        None,
    )
    assert conflicts is not None
    assert conflicts["confidence"] == "low"
    assert "requires contextual human review" in conflicts["alternatives"]
    assert conflicts["count"] >= 1
    conflict = conflicts["evidence"][0]
    assert conflict["relation"] == "girlfriend"
    assert conflict["predicate"] == "jewish"
    assert len(conflict["affirming"]) >= 1
    assert len(conflict["negating"]) >= 1


def test_explicit_claim_conflicts_no_conflict(tmp_path):
    """Claim conflict detection must not emit when there are no opposing pairs."""
    path = tmp_path / "analysis.db"
    db = create_database(path)
    add_dm(db, 1, "2026-08-01T00:00:00+00:00", "my girlfriend is jewish", 0)
    add_dm(db, 2, "2026-08-02T00:00:00+00:00", "my girlfriend is awesome", 0)
    db.commit()
    db.close()

    result = corpus_analysis.analyze(path, SUBJECT, (RELATED,), persist=False)
    assert "explicit_claim_conflict_candidates" not in {
        item["key"] for item in result["observations"]
    }


def test_response_dynamics_latency_metrics(tmp_path):
    """Response dynamics must compute latency metrics with IQR and outlier counts."""
    path = tmp_path / "analysis.db"
    db = create_database(path)
    base = "2026-08-01T00:00:00+00:00"
    for index in range(15):
        offset = index * 120
        add_dm(db, 2 * index + 1, f"2026-08-01T{offset // 3600:02d}:{(offset % 3600) // 60:02d}:00+00:00",
               f"question from operator {index}", 1)
        add_dm(db, 2 * index + 2, f"2026-08-01T{offset // 3600:02d}:{(offset % 3600) // 60 + 1}:00+00:00",
               f"response from subject {index}", 0)
    db.commit()
    db.close()

    result = corpus_analysis.analyze(path, SUBJECT, (RELATED,), persist=False)
    dynamics = next(
        (item for item in result["observations"] if item["key"] == "dm_response_dynamics"),
        None,
    )
    assert dynamics is not None
    assert dynamics["confidence"] == "moderate"
    assert "does not identify AI authorship" in dynamics["alternatives"]
    derived = dynamics["evidence"][0]
    assert "subject" in derived
    assert "counterpart" in derived
    subject_metrics = derived["subject"]
    assert "median_seconds" in subject_metrics
    assert "p90_seconds" in subject_metrics
    assert "iqr_seconds" in subject_metrics
    assert "outlier_count" in subject_metrics
    assert "instant_rate" in subject_metrics
    assert subject_metrics["count"] >= 10


def test_response_dynamics_insufficient_exchanges(tmp_path):
    """Response dynamics must not emit when there are fewer than 10 subject exchanges."""
    path = tmp_path / "analysis.db"
    db = create_database(path)
    for index in range(5):
        add_dm(db, 2 * index + 1, f"2026-08-01T00:{index:02d}:00+00:00", "q", 1)
        add_dm(db, 2 * index + 2, f"2026-08-01T00:{index:02d}:30+00:00", "a", 0)
    db.commit()
    db.close()

    result = corpus_analysis.analyze(path, SUBJECT, (RELATED,), persist=False)
    assert "dm_response_dynamics" not in {item["key"] for item in result["observations"]}


def test_analysis_version_is_three(tmp_path):
    """The analyzer must report version 3.0."""
    path = tmp_path / "analysis.db"
    db = create_database(path)
    add_dm(db, 1, "2026-08-01T00:00:00+00:00", "hello", 0)
    db.commit()
    db.close()

    result = corpus_analysis.analyze(path, SUBJECT, (RELATED,), persist=False)
    assert result["analysis_version"] == "3.0"
