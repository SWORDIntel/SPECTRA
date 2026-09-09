import importlib
import subprocess
from difflib import SequenceMatcher
from pathlib import Path

import pytest

from tgarchive.native import filesearch_bindings
from tgarchive.services import file_search


@pytest.fixture(scope="module", autouse=True)
def build_native_library():
    native_dir = Path(filesearch_bindings.__file__).parent
    if not filesearch_bindings.native_available():
        subprocess.run(["make"], cwd=native_dir, check=True)
        importlib.reload(filesearch_bindings)
    assert filesearch_bindings.native_available()


@pytest.mark.parametrize(
    ("query", "candidate"),
    [
        ("invoice.pdf", "invoicc.pdf"),
        ("archive.zip", "archiva.zip"),
        ("document.docx", "documant.docx"),
        ("report-2026.pdf", "report-2025.pdf"),
    ],
)
def test_fuzzy_match_tracks_sequence_matcher(query, candidate):
    expected = SequenceMatcher(None, query.lower(), candidate.lower()).ratio()
    actual = filesearch_bindings.fuzzy_match(query, candidate)
    assert actual is not None
    assert actual == pytest.approx(expected, abs=0.05)


def test_fuzzy_match_shortcuts():
    assert filesearch_bindings.fuzzy_match("FILE.ZIP", "file.zip") == 1.0
    assert filesearch_bindings.fuzzy_match("file", "my-file.zip") == 0.9
    assert filesearch_bindings.fuzzy_match("my-file.zip", "file") == 0.8


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("password: s3cr3t", {"s3cr3t"}),
        ('file.zip "myPass"', {"myPass"}),
        ("archive.zip\nbareSecret42", {"bareSecret42"}),
    ],
)
def test_extract_passwords_matches_python_fallback(monkeypatch, text, expected):
    native_result = filesearch_bindings.extract_passwords(text, "")
    assert native_result is not None

    monkeypatch.setattr(file_search, "_native_extract_passwords", None)
    python_result = file_search._extract_passwords(text)

    native_values = {item["value"] for item in native_result}
    python_values = {item["value"] for item in python_result}
    assert native_values == python_values == expected


def test_binding_and_service_fallback(monkeypatch):
    monkeypatch.setattr(filesearch_bindings, "_lib", None)

    assert filesearch_bindings.fuzzy_match("invoice.pdf", "invoicc.pdf") is None
    assert filesearch_bindings.extract_passwords("password: fallback", "") is None

    expected = SequenceMatcher(None, "invoice.pdf", "invoicc.pdf").ratio()
    assert file_search._fuzzy_match("invoice.pdf", "invoicc.pdf") == expected
    assert {item["value"] for item in file_search._extract_passwords("password: fallback")} == {
        "fallback"
    }


# ── Bulk batch scoring tests ──────────────────────────────────────────────


def test_batch_score_available():
    """The batch scoring API should be available after building the native lib."""
    assert filesearch_bindings.batch_available()


def test_batch_score_exact_match():
    """Exact filename match should return score 1.0 with filename_fuzzy type."""
    results = filesearch_bindings.batch_score(
        "test.zip",
        [(1, "test.zip", "Some Title", "https://example.com/test.zip")],
        threshold=0.5,
        fuzzy=True,
    )
    assert results is not None
    assert len(results) == 1
    score, match_type = results[0]
    assert score == 1.0
    assert match_type == filesearch_bindings.MATCH_FILENAME_FUZZY


def test_batch_score_multiple_candidates():
    """Batch scoring should correctly rank multiple candidates."""
    results = filesearch_bindings.batch_score(
        "archive.zip",
        [
            (1, "archive.zip", "", ""),
            (2, "archive_v2.zip", "", ""),
            (3, "report.pdf", "", ""),
            (4, "", "Archive Files", ""),
        ],
        threshold=0.5,
        fuzzy=True,
    )
    assert results is not None
    assert len(results) == 4
    # Exact match first
    assert results[0][0] == 1.0
    # Substring match second
    assert results[1][0] >= 0.5
    # Unrelated low score
    assert results[2][0] < 0.5


def test_batch_score_matches_single_fuzzy_match():
    """Batch scoring should produce the same scores as single fuzzy_match calls
    when using the same query against each candidate."""
    query = "invoice.pdf"
    candidates = ["invoicc.pdf", "archive.zip", "document.docx"]
    batch_results = filesearch_bindings.batch_score(
        query,
        [(i, c, "", "") for i, c in enumerate(candidates)],
        threshold=0.0,
        fuzzy=True,
    )
    assert batch_results is not None
    for i, candidate in enumerate(candidates):
        single = filesearch_bindings.fuzzy_match(query, candidate)
        assert single is not None
        assert batch_results[i][0] == pytest.approx(single, abs=0.01)


def test_batch_score_exact_mode():
    """Non-fuzzy mode should only use exact/substring matching."""
    results = filesearch_bindings.batch_score(
        "test.zip",
        [
            (1, "test.zip", "", ""),
            (2, "my-test.zip", "", ""),
            (3, "tost.zip", "", ""),  # 1 char diff — won't match in exact mode
        ],
        threshold=0.5,
        fuzzy=False,
    )
    assert results is not None
    assert results[0][0] == 1.0  # exact
    assert results[0][1] == filesearch_bindings.MATCH_FILENAME_EXACT
    assert results[1][0] == 0.9  # substring
    assert results[1][1] == filesearch_bindings.MATCH_FILENAME_EXACT
    assert results[2][0] < 0.5  # no match in exact mode


def test_batch_score_empty_inputs():
    """Empty inputs should return None or empty, not crash."""
    assert filesearch_bindings.batch_score("", [(1, "test.zip", "", "")]) is None
    assert filesearch_bindings.batch_score("test", []) is None


def test_batch_score_empty_fields():
    """Empty filename/title/url should score 0, not crash."""
    results = filesearch_bindings.batch_score(
        "test.zip",
        [(1, "", "", "")],
        threshold=0.0,
        fuzzy=True,
    )
    assert results is not None
    assert results[0][0] == 0.0
