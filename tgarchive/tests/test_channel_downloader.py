import asyncio
import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from tgarchive.services.channel_downloader import (
    ChannelDownloader,
    ChannelDownloadOptions,
    safe_path_component,
    serialize_message,
)
from tgarchive.db.index_projector import IndexProjector
from tgarchive.sqlite_runtime import connect_sqlite


class AsyncMessageIterator:
    def __init__(self, messages):
        self._messages = list(messages)

    async def __aiter__(self):
        for message in self._messages:
            yield message


class FakeMessage:
    def __init__(self, message_id, text, *, media=False, delay=0):
        self.id = message_id
        self.date = datetime(2026, 7, 28, 12, message_id, tzinfo=timezone.utc)
        self.edit_date = None
        self.sender_id = 9000 + message_id
        self.sender = SimpleNamespace(id=9000 + message_id, username=f"user{message_id}", first_name="Test", last_name=None)
        self.message = text
        self.raw_text = text
        self.reply_to_msg_id = None
        self.reply_to = None
        self.post_author = None
        self.views = None
        self.forwards = None
        self.grouped_id = None
        self.media = object() if media else None
        self.file = SimpleNamespace(id=7000 + message_id, name="payload.bin", mime_type="application/octet-stream", size=4, ext=".bin") if media else None
        self.download_calls = []
        self.delay = delay
        self.download_attempts = 0

    async def download_media(self, file, **kwargs):
        self.download_attempts += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        path = Path(file)
        path.write_bytes(b"test")
        callback = kwargs.get("progress_callback")
        if callback:
            callback(4, 4)
        self.download_calls.append(path)
        return str(path)


class FakeClient:
    def __init__(self, messages):
        self.entity = SimpleNamespace(id=123, title="Test Channel")
        self.messages = list(messages)
        self.iter_calls = []

    async def get_entity(self, entity):
        self.requested_entity = entity
        return self.entity

    def iter_messages(self, entity, **kwargs):
        self.iter_calls.append(kwargs)
        return AsyncMessageIterator(self.messages)

    async def get_messages(self, entity, ids):
        self.requested_entity = entity
        return [m for m in self.messages if m.id in ids]


class TestChannelDownloader(unittest.TestCase):
    def test_safe_path_component_normalizes_titles(self):
        self.assertEqual(safe_path_component("@test channel/one"), "test_channel_one")
        self.assertEqual(safe_path_component(""), "channel")

    def test_serialize_message_includes_relative_media_path(self):
        message = FakeMessage(1, "hello", media=True)
        output_dir = Path("/tmp/export")
        media_path = output_dir / "media" / "1_payload.bin"

        record = serialize_message(message, media_path=media_path, output_dir=output_dir)

        self.assertEqual(record["id"], 1)
        self.assertEqual(record["sender"]["username"], "user1")
        self.assertEqual(record["media"]["mime_type"], "application/octet-stream")
        self.assertEqual(record["media_path"], "media/1_payload.bin")

    def test_real_channel_identity_uses_operator_facing_peer_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            client = FakeClient([FakeMessage(1, "indexed", media=True)])
            client.entity.broadcast = True
            database = Path(tmpdir) / "spectra.db"

            asyncio.run(ChannelDownloader(client).download(ChannelDownloadOptions(
                entity="-100123",
                output_dir=Path(tmpdir) / "exports",
                index_database=database,
            )))

            export_dir = Path(tmpdir) / "exports" / "Test_Channel_123"
            manifest = json.loads((export_dir / "manifest.json").read_text())
            event = IndexProjector(database).outbox.events()[0]
            self.assertEqual(manifest["entity_id"], 123)
            self.assertEqual(manifest["peer_id"], -1000000000123)
            self.assertEqual(event["source_key"], "-1000000000123:1")
            self.assertEqual(event["payload"]["channel_id"], -1000000000123)

    def test_download_writes_jsonl_manifest_state_and_media(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            messages = [FakeMessage(1, "one"), FakeMessage(2, "two", media=True)]
            client = FakeClient(messages)
            downloader = ChannelDownloader(client)

            result = asyncio.run(
                downloader.download(
                    ChannelDownloadOptions(
                        entity="@source",
                        output_dir=Path(tmpdir),
                        include_media=True,
                    )
                )
            )

            self.assertEqual(result.messages_written, 2)
            self.assertEqual(result.media_downloaded, 1)
            self.assertEqual(result.media_skipped, 0)
            self.assertEqual(client.iter_calls[0], {"reverse": True})

            export_dir = Path(tmpdir) / "Test_Channel_123"
            records = [json.loads(line) for line in (export_dir / "messages.jsonl").read_text().splitlines()]
            self.assertEqual([record["id"] for record in records], [1, 2])
            self.assertEqual(records[1]["media_path"], "media/2_payload.bin")
            self.assertTrue((export_dir / "media" / "2_payload.bin").exists())

            manifest = json.loads((export_dir / "manifest.json").read_text())
            self.assertEqual(manifest["entity"], "@source")
            state = json.loads((export_dir / "state.json").read_text())
            self.assertEqual(state["last_message_id"], 2)
            self.assertTrue(state["complete"])
            summary = json.loads((export_dir / "summary.json").read_text())
            self.assertTrue(summary["complete"])
            media_manifest = [json.loads(line) for line in (export_dir / "media_manifest.jsonl").read_text().splitlines()]
            self.assertEqual(media_manifest[0]["message_id"], 2)
            self.assertEqual(media_manifest[0]["path"], "media/2_payload.bin")
            self.assertEqual(media_manifest[0]["size"], 4)
            self.assertFalse((export_dir / "media" / "2_payload.bin.part").exists())

    def test_download_emits_committed_index_outbox_events(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            database = Path(tmpdir) / "spectra.db"
            downloader = ChannelDownloader(
                FakeClient([FakeMessage(1, "indexed"), FakeMessage(2, "also indexed", media=True)])
            )

            asyncio.run(downloader.download(ChannelDownloadOptions(
                entity="@source",
                output_dir=Path(tmpdir) / "exports",
                include_media=True,
                index_database=database,
            )))

            with connect_sqlite(database, read_only=True) as connection:
                rows = connection.execute(
                    "SELECT source_key, payload_json FROM index_outbox ORDER BY sequence_id"
                ).fetchall()
            self.assertEqual([row[0] for row in rows], ["123:1", "123:2"])
            media_payload = json.loads(rows[1][1])
            self.assertEqual(media_payload["message"], "also indexed")
            offset_record = media_payload["media_manifest"]
            manifest_path = (
                Path(tmpdir)
                / "exports"
                / "Test_Channel_123"
                / offset_record["manifest_path"]
            )
            with manifest_path.open("rb") as handle:
                handle.seek(offset_record["byte_offset"])
                serialized = handle.read(offset_record["byte_length"])
            self.assertEqual(hashlib.sha256(serialized).hexdigest(), offset_record["record_sha256"])
            self.assertEqual(json.loads(serialized)["message_id"], 2)

            projector = IndexProjector(database)
            projector.drain()
            verified = projector.verify(projection="media", native=False)
            self.assertTrue(verified["ok"])
            self.assertEqual(verified["projections"][0]["actual_rows"], 1)

    def test_existing_destination_is_checked_before_download(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            export_dir = Path(tmpdir) / "Test_Channel_123" / "media"
            export_dir.mkdir(parents=True)
            existing = export_dir / "2_payload.bin"
            existing.write_bytes(b"test")
            message = FakeMessage(2, "already present", media=True)
            result = asyncio.run(
                ChannelDownloader(FakeClient([message])).download(
                    ChannelDownloadOptions(entity="@source", output_dir=Path(tmpdir), include_media=True)
                )
            )

            self.assertEqual(result.media_downloaded, 0)
            self.assertEqual(result.media_skipped, 1)
            self.assertEqual(message.download_calls, [])

    def test_resume_uses_last_message_id_as_min_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            export_dir = Path(tmpdir) / "Test_Channel_123"
            export_dir.mkdir(parents=True)
            (export_dir / "state.json").write_text(json.dumps({"last_message_id": 42}))
            client = FakeClient([])
            downloader = ChannelDownloader(client)

            asyncio.run(
                downloader.download(
                    ChannelDownloadOptions(
                        entity="@source",
                        output_dir=Path(tmpdir),
                        include_media=False,
                        resume=True,
                    )
                )
            )

            self.assertEqual(client.iter_calls[0], {"reverse": True, "min_id": 42})

    def test_deduplicate_removes_media_matching_existing_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "existing.bin").write_bytes(b"test")
            client = FakeClient([FakeMessage(3, "duplicate", media=True)])
            result = asyncio.run(
                ChannelDownloader(client).download(
                    ChannelDownloadOptions(entity="@source", output_dir=root, include_media=True)
                )
            )

            export_dir = root / "Test_Channel_123"
            self.assertEqual(result.media_downloaded, 0)
            self.assertEqual(result.media_duplicates, 1)
            self.assertFalse((export_dir / "media" / "3_payload.bin").exists())

    def test_download_keeps_configured_media_transfers_in_flight(self):
        class TrackedMessage(FakeMessage):
            active = 0
            max_active = 0

            async def download_media(self, file, **kwargs):
                type(self).active += 1
                type(self).max_active = max(type(self).max_active, type(self).active)
                try:
                    return await super().download_media(file, **kwargs)
                finally:
                    type(self).active -= 1

        with tempfile.TemporaryDirectory() as tmpdir:
            messages = [TrackedMessage(message_id, f"media {message_id}", media=True, delay=0.02) for message_id in range(1, 7)]
            client = FakeClient(messages)

            result = asyncio.run(
                ChannelDownloader(client).download(
                    ChannelDownloadOptions(entity="@source", output_dir=Path(tmpdir), include_media=True, max_concurrency=3)
                )
            )

            export_dir = Path(tmpdir) / "Test_Channel_123"
            records = [json.loads(line) for line in (export_dir / "messages.jsonl").read_text().splitlines()]
            self.assertEqual(TrackedMessage.max_active, 3)
            self.assertEqual(result.media_downloaded, 1)
            self.assertEqual(result.media_duplicates, 5)
            self.assertEqual([record["id"] for record in records], [1, 2, 3, 4, 5, 6])

    def test_media_download_retries_transient_failure(self):
        class FlakyMessage(FakeMessage):
            async def download_media(self, file, **kwargs):
                self.download_attempts += 1
                if self.download_attempts == 1:
                    raise OSError("temporary disconnect")
                path = Path(file)
                path.write_bytes(b"test")
                callback = kwargs.get("progress_callback")
                if callback:
                    callback(4, 4)
                self.download_calls.append(path)
                return str(path)

        with tempfile.TemporaryDirectory() as tmpdir:
            message = FlakyMessage(7, "retry", media=True)
            result = asyncio.run(
                ChannelDownloader(FakeClient([message])).download(
                    ChannelDownloadOptions(entity="@source", output_dir=Path(tmpdir), include_media=True, max_retries=1, retry_delay=0)
                )
            )

            export_dir = Path(tmpdir) / "Test_Channel_123"
            self.assertEqual(message.download_attempts, 2)
            self.assertEqual(result.media_downloaded, 1)
            self.assertTrue((export_dir / "media" / "7_payload.bin").exists())
            self.assertFalse((export_dir / "media" / "7_payload.bin.part").exists())

    def test_media_download_failure_records_state_without_checkpointing_failed_message(self):
        class FailingMessage(FakeMessage):
            async def download_media(self, file, **kwargs):
                self.download_attempts += 1
                Path(file).write_bytes(b"partial")
                raise OSError("connection lost")

        with tempfile.TemporaryDirectory() as tmpdir:
            message = FailingMessage(8, "fail", media=True)
            result = asyncio.run(
                ChannelDownloader(FakeClient([message])).download(
                    ChannelDownloadOptions(entity="@source", output_dir=Path(tmpdir), include_media=True, max_retries=1, retry_delay=0)
                )
            )

            export_dir = Path(tmpdir) / "Test_Channel_123"
            state = json.loads((export_dir / "state.json").read_text())
            media_manifest = [json.loads(line) for line in (export_dir / "media_manifest.jsonl").read_text().splitlines()]
            self.assertEqual(message.download_attempts, 2)
            self.assertEqual(result.media_downloaded, 0)
            self.assertEqual(state["failed_media_ids"], [8])
            self.assertIsNone(state["last_message_id"])
            self.assertFalse((export_dir / "media" / "8_payload.bin.part").exists())
            self.assertTrue(media_manifest[0]["failed"])

    def test_flood_wait_errors_are_retried_without_sleeping_in_tests(self):
        class FakeFloodWaitError(Exception):
            def __init__(self):
                super().__init__("flood wait")
                self.seconds = 30

        class FloodThenSuccessMessage(FakeMessage):
            async def download_media(self, file, **kwargs):
                self.download_attempts += 1
                if self.download_attempts == 1:
                    raise FakeFloodWaitError()
                Path(file).write_bytes(b"test")
                return str(file)

        class NoSleepDownloader(ChannelDownloader):
            def _retry_delay(self, exc, options):
                return 0

        with tempfile.TemporaryDirectory() as tmpdir:
            message = FloodThenSuccessMessage(9, "flood retry", media=True)
            result = asyncio.run(
                NoSleepDownloader(FakeClient([message])).download(
                    ChannelDownloadOptions(entity="@source", output_dir=Path(tmpdir), include_media=True, max_retries=1)
                )
            )

            self.assertEqual(message.download_attempts, 2)
            self.assertEqual(result.media_downloaded, 1)

    def test_stalled_media_download_is_cancelled_and_retried(self):
        class StallingThenSuccessMessage(FakeMessage):
            async def download_media(self, file, **kwargs):
                self.download_attempts += 1
                if self.download_attempts == 1:
                    await asyncio.sleep(2)
                    return None
                Path(file).write_bytes(b"test")
                callback = kwargs.get("progress_callback")
                if callback:
                    callback(4, 4)
                return str(file)

        with tempfile.TemporaryDirectory() as tmpdir:
            message = StallingThenSuccessMessage(10, "stall retry", media=True)
            result = asyncio.run(
                ChannelDownloader(FakeClient([message])).download(
                    ChannelDownloadOptions(
                        entity="@source",
                        output_dir=Path(tmpdir),
                        include_media=True,
                        max_retries=1,
                        retry_delay=0,
                        stall_timeout=1,
                    )
                )
            )

            self.assertEqual(message.download_attempts, 2)
            self.assertEqual(result.media_downloaded, 1)


    def test_retry_failed_downloads_only_failed_media(self):
        class FailingThenSuccessMessage(FakeMessage):
            async def download_media(self, file, **kwargs):
                self.download_attempts += 1
                if self.download_attempts == 1:
                    raise OSError("connection lost")
                Path(file).write_bytes(b"test")
                return str(file)

        with tempfile.TemporaryDirectory() as tmpdir:
            # Step 1: Normal download that fails
            message = FailingThenSuccessMessage(11, "fail then success", media=True)
            downloader = ChannelDownloader(FakeClient([message]))
            asyncio.run(
                downloader.download(
                    ChannelDownloadOptions(entity="@source", output_dir=Path(tmpdir), include_media=True, max_retries=0, retry_delay=0)
                )
            )

            export_dir = Path(tmpdir) / "Test_Channel_123"
            state = json.loads((export_dir / "state.json").read_text())
            self.assertEqual(state["failed_media_ids"], [11])

            # Step 2: Retry failed
            client = FakeClient([message])
            downloader = ChannelDownloader(client)
            result = asyncio.run(
                downloader.retry_failed(
                    ChannelDownloadOptions(entity="@source", output_dir=Path(tmpdir), include_media=True, max_retries=1, retry_delay=0)
                )
            )

            state = json.loads((export_dir / "state.json").read_text())
            self.assertEqual(state["failed_media_ids"], [])
            self.assertEqual(result.media_downloaded, 1)

if __name__ == "__main__":
    unittest.main()
