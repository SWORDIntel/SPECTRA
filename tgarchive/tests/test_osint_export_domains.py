import argparse
import json
import sqlite3
from pathlib import Path
import pytest

from tgarchive.__main__ import cmd_osint_export_domains, handle_osint, setup_parser


@pytest.fixture
def temp_db(tmp_path):
    db_path = tmp_path / "test_spectra.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            tags TEXT,
            avatar TEXT,
            last_updated TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY,
            type TEXT NOT NULL,
            date TEXT NOT NULL,
            edit_date TEXT,
            content TEXT,
            reply_to INTEGER,
            user_id INTEGER REFERENCES users(id),
            media_id INTEGER,
            checksum TEXT,
            channel_id INTEGER
        )
        """
    )
    # Insert users
    conn.execute(
        "INSERT INTO users (id, username, first_name, last_name) VALUES (1, 'threat_actor', 'Threat', 'Actor')"
    )
    conn.execute(
        "INSERT INTO users (id, username, first_name, last_name) VALUES (2, 'innocent_user', 'Innocent', 'User')"
    )

    # Insert messages
    conn.execute(
        """
        INSERT INTO messages (id, type, date, content, user_id, channel_id)
        VALUES (101, 'message', '2026-01-01T10:00:00Z', 'Check out https://evil-c2.example.com/panel and https://malware-drop.org/payload.exe', 1, 1001)
        """
    )
    conn.execute(
        """
        INSERT INTO messages (id, type, date, content, user_id, channel_id)
        VALUES (102, 'message', '2026-01-01T11:00:00Z', 'Backup domain at http://phishing-hub.net/login and BTC 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa', 1, 1002)
        """
    )
    conn.execute(
        """
        INSERT INTO messages (id, type, date, content, user_id, channel_id)
        VALUES (103, 'message', '2026-01-01T12:00:00Z', 'Visit https://legit-site.com for news', 2, 1001)
        """
    )
    conn.commit()
    conn.close()
    return db_path


def test_export_domains_all_cloudclear(temp_db, capsys):
    args = argparse.Namespace(
        db=str(temp_db),
        channel=None,
        user=None,
        format="cloudclear",
        output=None,
    )
    ret = cmd_osint_export_domains(args)
    assert ret == 0

    captured = capsys.readouterr()
    assert "Exported 4 domains from 3 messages" in captured.err
    lines = [line.strip() for line in captured.out.strip().splitlines()]
    assert "# SPECTRA OSINT Domain Export" in lines
    assert "# Channel: all" in lines
    assert "# Count: 4" in lines
    assert "evil-c2.example.com" in lines
    assert "malware-drop.org" in lines
    assert "phishing-hub.net" in lines
    assert "legit-site.com" in lines


def test_export_domains_filter_channel(temp_db, capsys):
    args = argparse.Namespace(
        db=str(temp_db),
        channel=1001,
        user=None,
        format="cloudclear",
        output=None,
    )
    ret = cmd_osint_export_domains(args)
    assert ret == 0

    captured = capsys.readouterr()
    assert "Exported 3 domains from 2 messages" in captured.err
    lines = [line.strip() for line in captured.out.strip().splitlines()]
    assert "# Channel: 1001" in lines
    assert "# Count: 3" in lines
    assert "evil-c2.example.com" in lines
    assert "malware-drop.org" in lines
    assert "legit-site.com" in lines
    assert "phishing-hub.net" not in lines


def test_export_domains_filter_user(temp_db, capsys):
    args = argparse.Namespace(
        db=str(temp_db),
        channel=None,
        user="@threat_actor",
        format="cloudclear",
        output=None,
    )
    ret = cmd_osint_export_domains(args)
    assert ret == 0

    captured = capsys.readouterr()
    assert "Exported 3 domains from 2 messages" in captured.err
    lines = [line.strip() for line in captured.out.strip().splitlines()]
    assert "evil-c2.example.com" in lines
    assert "malware-drop.org" in lines
    assert "phishing-hub.net" in lines
    assert "legit-site.com" not in lines


def test_export_domains_filter_user_id(temp_db, capsys):
    args = argparse.Namespace(
        db=str(temp_db),
        channel=None,
        user="2",
        format="cloudclear",
        output=None,
    )
    ret = cmd_osint_export_domains(args)
    assert ret == 0

    captured = capsys.readouterr()
    assert "Exported 1 domains from 1 messages" in captured.err
    lines = [line.strip() for line in captured.out.strip().splitlines()]
    assert "legit-site.com" in lines
    assert "evil-c2.example.com" not in lines


def test_export_domains_json_format(temp_db, capsys):
    args = argparse.Namespace(
        db=str(temp_db),
        channel=1002,
        user=None,
        format="json",
        output=None,
    )
    ret = cmd_osint_export_domains(args)
    assert ret == 0

    captured = capsys.readouterr()
    assert "Exported 1 domains from 1 messages" in captured.err
    data = json.loads(captured.out)
    assert "domains" in data
    assert "phishing-hub.net" in data["domains"]
    assert "wallets" in data
    assert "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa" in data["wallets"]


def test_export_domains_output_file(temp_db, tmp_path, capsys):
    out_file = tmp_path / "subdir" / "exported_domains.txt"
    args = argparse.Namespace(
        db=str(temp_db),
        channel=None,
        user=None,
        format="cloudclear",
        output=str(out_file),
    )
    ret = cmd_osint_export_domains(args)
    assert ret == 0

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Exported" in captured.err

    assert out_file.exists()
    content = out_file.read_text(encoding="utf-8")
    assert "# SPECTRA OSINT Domain Export" in content
    assert "evil-c2.example.com" in content


def test_export_domains_empty_db(tmp_path, capsys):
    empty_db = tmp_path / "empty.db"
    conn = sqlite3.connect(empty_db)
    conn.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, content TEXT)")
    conn.commit()
    conn.close()

    args = argparse.Namespace(
        db=str(empty_db),
        channel=None,
        user=None,
        format="cloudclear",
        output=None,
    )
    ret = cmd_osint_export_domains(args)
    assert ret == 0

    captured = capsys.readouterr()
    assert "No messages found" in captured.err
    assert captured.out == ""


def test_export_domains_nonexistent_db(tmp_path, capsys):
    nonexistent = tmp_path / "nonexistent.db"
    args = argparse.Namespace(
        db=str(nonexistent),
        channel=None,
        user=None,
        format="cloudclear",
        output=None,
    )
    ret = cmd_osint_export_domains(args)
    assert ret == 0

    captured = capsys.readouterr()
    assert "No messages found" in captured.err
    assert captured.out == ""


def test_export_domains_channel_messages_table(tmp_path, capsys):
    cm_db = tmp_path / "channel_messages.db"
    conn = sqlite3.connect(cm_db)
    conn.execute(
        """
        CREATE TABLE channel_messages (
            message_id INTEGER PRIMARY KEY,
            channel_id INTEGER,
            user_id INTEGER,
            content TEXT
        )
        """
    )
    conn.execute(
        """
        INSERT INTO channel_messages (message_id, channel_id, user_id, content)
        VALUES (1, 5555, 10, 'Find us at https://darknet-market.org and http://c2-backup.com')
        """
    )
    conn.commit()
    conn.close()

    args = argparse.Namespace(
        db=str(cm_db),
        channel=5555,
        user=None,
        format="cloudclear",
        output=None,
    )
    ret = cmd_osint_export_domains(args)
    assert ret == 0

    captured = capsys.readouterr()
    assert "Exported 2 domains from 1 messages" in captured.err
    assert "darknet-market.org" in captured.out
    assert "c2-backup.com" in captured.out


@pytest.mark.asyncio
async def test_handle_osint_export_domains_dispatch(temp_db, capsys):
    args = argparse.Namespace(
        osint_command="export-domains",
        db=str(temp_db),
        channel=None,
        user=None,
        format="cloudclear",
        output=None,
    )
    ret = await handle_osint(args)
    assert ret == 0

    captured = capsys.readouterr()
    assert "Exported 4 domains from 3 messages" in captured.err
    assert "evil-c2.example.com" in captured.out


def test_cli_parser_export_domains(temp_db, capsys):
    parser = setup_parser()
    args = parser.parse_args(["osint", "export-domains", "--db", str(temp_db), "--channel", "1001", "--format", "json"])
    assert args.command == "osint"
    assert args.osint_command == "export-domains"
    assert args.channel == 1001
    assert args.format == "json"
    assert args.db == str(temp_db)
