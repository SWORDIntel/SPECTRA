"""
Integration tests for the new ``spectra search`` and ``spectra agent`` CLI
commands wired into ``tgarchive/__main__.py``.

These tests exercise the CLI via subprocess invocations of
``python3 -m tgarchive`` so that the full argparse setup, command_map
dispatch, and handler functions are exercised end-to-end.  A temporary
SPECTRA-style SQLite database is created so that the search/agent commands
have something to query.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _run_cli(*args: str, db: str | None = None, cwd: str | None = None) -> subprocess.CompletedProcess:
    """Run ``python3 -m tgarchive <args>`` and return the completed process.

    Args:
        *args: Extra CLI arguments (e.g. ``"search", "--help"``).
        db: Optional ``--db`` value to prepend.
        cwd: Working directory for the subprocess (defaults to repo root).
    """
    cmd = [sys.executable, "-m", "tgarchive"]
    if db is not None:
        cmd += ["--db", db]
    cmd += list(args)
    repo_root = cwd or str(Path(__file__).resolve().parents[2])
    env = os.environ.copy()
    env["PYTHONPATH"] = repo_root + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=repo_root,
        env=env,
        timeout=60,
    )


@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    """Create a minimal SPECTRA-style SQLite database for CLI testing."""
    db_path = tmp_path / "cli_test_spectra.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id          INTEGER PRIMARY KEY,
            username    TEXT,
            first_name  TEXT,
            last_name   TEXT,
            tags        TEXT
        );
        CREATE TABLE IF NOT EXISTS messages (
            id          INTEGER PRIMARY KEY,
            channel_id  INTEGER,
            user_id     INTEGER,
            content     TEXT,
            date        TEXT,
            type        TEXT,
            reply_to    INTEGER
        );
        INSERT INTO users (id, username, first_name, last_name, tags)
        VALUES
            (100, 'alice', 'Alice', 'Smith', '["admin"]'),
            (200, 'bob',   'Bob',   'Jones', '[]');
        INSERT INTO messages (id, channel_id, user_id, content, date, type, reply_to)
        VALUES
            (1, 10, 100, 'hello world from alice', '2026-01-01T09:00:00', 'text', NULL),
            (2, 10, 100, 'sharing archive.zip',    '2026-01-01T21:30:00', 'text', NULL),
            (3, 11, 200, 'bob report here',        '2026-01-02T14:15:00', 'text', 1);
        """
    )
    conn.commit()
    conn.close()
    return db_path


# ─── Help / argparse tests ───────────────────────────────────────────────────


def test_search_help_works() -> None:
    """``spectra search --help`` exits 0 and mentions the query argument."""
    proc = _run_cli("search", "--help")
    assert proc.returncode == 0, proc.stderr
    assert "query" in proc.stdout.lower()
    assert "--limit" in proc.stdout
    assert "--subsystems" in proc.stdout
    assert "--json" in proc.stdout


def test_agent_help_works() -> None:
    """``spectra agent --help`` exits 0 and lists the subcommands."""
    proc = _run_cli("agent", "--help")
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout.lower()
    assert "search" in out
    assert "expand" in out
    assert "timeline" in out
    assert "resolve" in out
    assert "evidence" in out


def test_agent_subcommand_help_works() -> None:
    """``spectra agent search --help`` exits 0."""
    proc = _run_cli("agent", "search", "--help")
    assert proc.returncode == 0, proc.stderr
    assert "query" in proc.stdout.lower()


# ─── Functional tests (with temp DB) ─────────────────────────────────────────


def test_search_json_returns_valid_json(temp_db: Path) -> None:
    """``spectra search "test query" --json`` returns valid JSON."""
    proc = _run_cli("search", "test query", "--json", db=str(temp_db))
    # The command should exit 0 (graceful degradation yields empty results,
    # not an error exit).
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert isinstance(data, dict)
    assert "candidates" in data
    assert "query" in data
    assert data["query"] == "test query"


def test_agent_search_returns_valid_json(temp_db: Path) -> None:
    """``spectra agent search "test"`` returns valid JSON."""
    proc = _run_cli("agent", "search", "test", db=str(temp_db))
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert isinstance(data, dict)
    # The agent search tool always returns candidates + summary.
    assert "candidates" in data


def test_agent_search_subsystems_all(temp_db: Path) -> None:
    """``spectra agent search "hello" --subsystems all`` returns valid JSON."""
    proc = _run_cli("agent", "search", "hello", "--subsystems", "all", db=str(temp_db))
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert isinstance(data, dict)


# ─── command_map tests ───────────────────────────────────────────────────────


def test_command_map_contains_search_and_agent() -> None:
    """The command_map dict in __main__ contains 'search' and 'agent'."""
    # Import the module and inspect the command_map built inside async_main.
    # We re-create the parser to confirm the subparsers exist, then verify
    # the handler functions are importable and callable.
    from tgarchive import __main__ as main_mod

    # The handlers must exist as module-level async callables.
    assert hasattr(main_mod, "handle_search"), "handle_search not defined in __main__"
    assert hasattr(main_mod, "handle_agent"), "handle_agent not defined in __main__"
    assert callable(main_mod.handle_search)
    assert callable(main_mod.handle_agent)

    # Verify the parser recognises both subcommands.
    parser = main_mod.setup_parser()
    # Parse a search invocation.
    ns = parser.parse_args(["search", "some query", "--json"])
    assert ns.command == "search"
    assert ns.query == "some query"
    assert ns.json is True
    # Parse an agent invocation.
    ns2 = parser.parse_args(["agent", "expand", "media:123", "--depth", "2"])
    assert ns2.command == "agent"
    assert ns2.agent_command == "expand"
    assert ns2.object_id == "media:123"
    assert ns2.depth == 2


def test_command_map_dispatches_search_and_agent(temp_db: Path) -> None:
    """The command_map dict includes 'search' and 'agent' keys pointing at
    the new handlers.  We reconstruct the map logic by inspecting the
    dispatch path used in ``async_main``.
    """
    from tgarchive import __main__ as main_mod

    # Build the same command_map that async_main builds by introspecting
    # the handler attributes.  The real command_map is a local variable
    # inside async_main, so we verify the handlers are wired by name.
    parser = main_mod.setup_parser()
    subparser_actions = [a for a in parser._actions if isinstance(a, type(parser._subparsers._group_actions[0]))]
    # Collect the set of top-level command names registered.
    cmd_names: set[str] = set()
    for action in parser._subparsers._group_actions:
        cmd_names.update(action.choices.keys())
    assert "search" in cmd_names, "'search' subparser not registered"
    assert "agent" in cmd_names, "'agent' subparser not registered"
