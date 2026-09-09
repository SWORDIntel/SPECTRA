"""Tests for import_service — streaming JSON parsing, chunking, progress callbacks, and format handling."""

import csv
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from tgarchive.db.index_outbox import IndexOutbox
from tgarchive.services import import_service
from tgarchive.services.import_service import (
    import_batch,
    import_data,
    import_with_resume,
    validate_import,
)


class TestImportService(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmpdir.name)
        self.db_path = self.tmp_path / "spectra.db"

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_telegram_export_import_with_fallback(self):
        export_data = {
            "name": "Test Group",
            "type": "public_supergroup",
            "id": 99999,
            "messages": [
                {
                    "id": i,
                    "type": "message",
                    "date": "2024-01-01T12:00:00",
                    "from": f"User {i}",
                    "from_id": f"user{1000 + i}",
                    "text": f"Telegram export message {i}",
                }
                for i in range(1, 2501)
            ],
        }
        export_file = self.tmp_path / "result.json"
        export_file.write_text(json.dumps(export_data), encoding="utf-8")

        progress_calls = []

        def on_progress(scanned, inserted, already):
            progress_calls.append((scanned, inserted, already))

        result = import_data(
            self.db_path,
            export_file,
            format="telegram-export",
            progress_callback=on_progress,
            chunk_size=1000,
        )

        self.assertEqual(result["scanned"], 2500)
        self.assertEqual(result["inserted"], 2500)
        self.assertEqual(result["already_present"], 0)
        # Should be called at 1000, 2000, and 2500
        self.assertEqual(len(progress_calls), 3)
        self.assertEqual(progress_calls[0], (1000, 1000, 0))
        self.assertEqual(progress_calls[1], (2000, 2000, 0))
        self.assertEqual(progress_calls[2], (2500, 2500, 0))

    def test_streaming_with_mock_ijson(self):
        mock_ijson = MagicMock()
        mock_items = [
            {"id": 1, "type": "message", "date": "2024-01-01T10:00:00", "text": "Msg 1"},
            {"id": 2, "type": "message", "date": "2024-01-01T10:01:00", "text": "Msg 2"},
            {"id": 3, "type": "message", "date": "2024-01-01T10:02:00", "text": "Msg 3"},
        ]
        mock_ijson.items.side_effect = lambda f, prefix: iter(mock_items) if prefix == "messages.item" else iter([])

        with patch.object(import_service, "_HAS_IJSON", True), patch.object(import_service, "ijson", mock_ijson):
            export_file = self.tmp_path / "mock_export.json"
            export_file.write_text('{"messages": []}', encoding="utf-8")

            result = import_data(
                self.db_path,
                export_file,
                format="telegram-export",
                chunk_size=2,
            )

            self.assertEqual(result["scanned"], 3)
            self.assertEqual(result["inserted"], 3)

    def test_ndjson_import(self):
        ndjson_file = self.tmp_path / "messages.ndjson"
        with open(ndjson_file, "w", encoding="utf-8") as f:
            for i in range(1, 101):
                f.write(json.dumps({"id": 5000 + i, "content": f"Line {i}"}) + "\n")

        result = import_data(
            self.db_path,
            ndjson_file,
            format="json",
            chunk_size=50,
        )

        self.assertEqual(result["scanned"], 100)
        self.assertEqual(result["inserted"], 100)

    def test_json_array_import(self):
        json_array_file = self.tmp_path / "array.json"
        messages = [{"id": 7000 + i, "content": f"Array msg {i}"} for i in range(1, 51)]
        json_array_file.write_text(json.dumps(messages), encoding="utf-8")

        result = import_data(
            self.db_path,
            json_array_file,
            format="json",
        )

        self.assertEqual(result["scanned"], 50)
        self.assertEqual(result["inserted"], 50)

    def test_csv_import(self):
        csv_file = self.tmp_path / "messages.csv"
        with open(csv_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["id", "content", "user_id"])
            for i in range(1, 21):
                writer.writerow([8000 + i, f"CSV content {i}", 42])

        result = import_data(
            self.db_path,
            csv_file,
            format="csv",
        )

        self.assertEqual(result["scanned"], 20)
        self.assertEqual(result["inserted"], 20)

    def test_sqlite_import(self):
        foreign_db = self.tmp_path / "foreign.db"
        with sqlite3.connect(str(foreign_db)) as conn:
            conn.execute("""
                CREATE TABLE messages (
                    id INTEGER PRIMARY KEY,
                    type TEXT,
                    date TEXT,
                    content TEXT,
                    user_id INTEGER
                )
            """)
            for i in range(1, 15):
                conn.execute(
                    "INSERT INTO messages VALUES (?, ?, ?, ?, ?)",
                    (9000 + i, "text", "2024-01-01T00:00:00", f"Foreign {i}", 10),
                )
            conn.commit()

        result = import_data(
            self.db_path,
            foreign_db,
            format="sqlite",
        )

        self.assertEqual(result["scanned"], 14)
        self.assertEqual(result["inserted"], 14)
        self.assertIn("messages", result["tables"])

    def test_validate_import(self):
        json_file = self.tmp_path / "valid.json"
        json_file.write_text(json.dumps([{"id": 1, "content": "hello"}]), encoding="utf-8")

        val = validate_import(json_file)
        self.assertTrue(val["valid"])
        self.assertEqual(val["record_count"], 1)

    def test_import_with_resume(self):
        json_file = self.tmp_path / "resume_test.json"
        messages = [{"id": 30000 + i, "content": f"Resume {i}"} for i in range(1, 101)]
        json_file.write_text(json.dumps(messages), encoding="utf-8")

        # Import first 50
        res1 = import_with_resume(self.db_path, json_file, format="json", limit=50, chunk_size=20)
        self.assertEqual(res1["scanned"], 50)
        self.assertEqual(res1["inserted"], 50)

        # Resume to import remainder
        res2 = import_with_resume(self.db_path, json_file, format="json", resume=True, chunk_size=20)
        self.assertEqual(res2["skipped_for_resume"], 50)
        self.assertEqual(res2["scanned"], 50)
        self.assertEqual(res2["inserted"], 50)


if __name__ == "__main__":
    unittest.main()
