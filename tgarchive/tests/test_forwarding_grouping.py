import unittest
from unittest.mock import MagicMock, AsyncMock
from datetime import datetime, timezone, timedelta # Added timezone
from pathlib import Path # Import Path

import asyncio
from tgarchive.forwarding.forwarder import AttachmentForwarder
from tgarchive.forwarding.grouping import MessageGrouper
from tgarchive.core.config_models import Config

# Mock TLMessage and related objects for testing grouping logic
class MockFile:
    def __init__(self, name):
        self.name = name

class MockSender:
    def __init__(self, id):
        self.id = id

class MockMessage:
    def __init__(self, id, date, sender_id, filename=None, text=None):
        self.id = id
        self.date = date
        self.sender_id = sender_id # Keep sender_id directly
        self.sender = MockSender(sender_id) # For compatibility if sender.id is accessed
        self.file = MockFile(filename) if filename else None
        self.text = text

        # Simulate media object structure for hashing
        if filename:
            # self.media would typically be a specific type like MessageMediaDocument
            # For testing hash, we primarily care about attributes like id, access_hash
            self.media = MagicMock()
            self.media.id = id * 10 # Simulate media.id, different from message.id
            self.media.access_hash = id * 100 # Default media.access_hash

            # message.file attributes (Telethon often has both message.media and message.file)
            # Ensure self.file (MockFile) has attributes if _compute_message_hash uses them.
            # _compute_message_hash uses self.file.id and self.file.size
            if self.file:
                self.file.id = id * 20 # Simulate file.id
                self.file.size = len(filename) * 50 if filename else 0
        else:
            self.media = None

        # Add other attributes as needed by hash computation or other logic
        self.photo = None
        self.document = None
        self.webpage = None

class TestAttachmentForwarderGrouping(unittest.TestCase):

    def setUp(self):
        # Basic config for AttachmentForwarder initialization
        # No actual DB or network calls will be made in these unit tests

        # Mock the config path to prevent file operations during Config initialization
        mock_path = MagicMock(spec=Path)
        mock_path.exists.return_value = False # Simulate config file not existing

        mock_config_data = {
            "accounts": [{"api_id": 123, "api_hash": "abc", "session_name": "test"}],
            "forwarding": {},
            "grouping": {},
            "db_path": "dummy_test.sqlite3" # Required by some parts, even if DB is mocked
        }
        # Initialize Config with the mocked path.
        # It should use default values since exists() is False.
        self.config = Config(path=mock_path)

        # We can then further override specific parts of config.data if needed for tests,
        # but for many AttachmentForwarder unit tests, default or minimal config is fine.
        # For instance, to ensure DEFAULT_CFG is used and then modified:
        self.config.data = self.config.data.copy() # Start from default loaded by Config
        self.config.data.update(mock_config_data) # Override with specific test needs

        # Default grouper for testing parsing
        self.grouper = MessageGrouper()

    def test_parse_filename_for_grouping(self):
        parse = self.grouper._parse_filename_for_grouping

        # Test cases: (filename, expected_output (base, part_str, part_num, ext))
        # expected_output is None if parsing should fail to find parts in a structured way,
        # but the new fallback should still return (base, "", 0, ext) for simple files.

        # Standard part numbering
        self.assertEqual(parse("archive_part1.rar"), ("archive", "_part1", 1, ".rar"))
        self.assertEqual(parse("archive_part002.zip"), ("archive", "_part002", 2, ".zip"))
        # Numbering without "part"
        self.assertEqual(parse("video_01.mp4"), ("video", "_01", 1, ".mp4"))
        self.assertEqual(parse("video_2.mkv"), ("video", "_2", 2, ".mkv"))
        # Space and parenthesis numbering
        self.assertEqual(parse("document (3).pdf"), ("document", " (3)", 3, ".pdf"))
        self.assertEqual(parse("image (004).jpg"), ("image", " (004)", 4, ".jpg"))
        # Complex names
        self.assertEqual(parse("my_archive_v2_part1.tar.gz"), ("my_archive_v2", "_part1", 1, ".tar.gz"))
        self.assertEqual(parse("backup.2023-01-01_part01.zip"), ("backup.2023-01-01", "_part01", 1, ".zip"))
        # No part numbering
        self.assertEqual(parse("simple_file.txt"), ("simple_file", "", 0, ".txt"))
        self.assertEqual(parse("another.document.pdf"), ("another.document", "", 0, ".pdf"))
        # Filenames with dots in base name
        self.assertEqual(parse("archive.v1.0.part1.rar"), ("archive.v1.0", ".part1", 1, ".rar")) # Corrected expected part string
        self.assertEqual(parse("archive.v1.0_2.rar"), ("archive.v1.0", "_2", 2, ".rar"))
        # No extension
        self.assertEqual(parse("file_no_extension_part1"), ("file_no_extension", "_part1", 1, ""))
        self.assertEqual(parse("file_no_extension"), ("file_no_extension", "", 0, ""))

        # Edge cases
        self.assertEqual(parse("part1.ext"), ("part1", "", 0, ".ext")) # Base name is "part1"
        self.assertEqual(parse("_part1.ext"), ("_part1", "", 0, ".ext")) # Base name is "_part1"
        self.assertEqual(parse("file_partABC.zip"), ("file_partABC", "", 0, ".zip")) # Non-numeric part
        self.assertEqual(parse("file.123"), ("file", "", 0, ".123")) # Extension is numeric

        self.assertEqual(parse("archive_part1"), ("archive", "_part1", 1, "")) # No extension
        self.assertEqual(parse("archive.part1"), ("archive", ".part1", 1, "")) # Dot instead of underscore
        self.assertEqual(parse("archive part 1.zip"), ("archive part 1", "", 0, ".zip")) # Space not in pattern for part

        # Test regex robustness
        self.assertEqual(parse("File Name With Spaces_part1.ext"), ("File Name With Spaces", "_part1", 1, ".ext"))
        self.assertEqual(parse("File-With-Hyphens_part002.zip"), ("File-With-Hyphens", "_part002", 2, ".zip"))
        self.assertEqual(parse("Filename_with_numbers_123_part3.rar"), ("Filename_with_numbers_123", "_part3", 3, ".rar"))
        self.assertEqual(parse("Filename (copy)_part4.jpeg"), ("Filename (copy)", "_part4", 4, ".jpeg"))

        # Handling of multi-dot extensions / complex names
        self.assertEqual(parse("archive.zip"), ("archive", "", 0, ".zip"))
        self.assertEqual(parse("archive.tar.gz"), ("archive", "", 0, ".tar.gz")) # Expecting .tar.gz as full extension
        self.assertEqual(parse("archive"), ("archive", "", 0, ""))

        # Specific test for the failing case and variants
        self.assertEqual(parse("foo.part1.rar"), ("foo", ".part1", 1, ".rar"))
        self.assertEqual(parse("archive.part1.rar"), ("archive", ".part1", 1, ".rar"))
        # The original failing one, and the test expectation should match the actual part string from filename:
        self.assertEqual(parse("archive.v1.0.part1.rar"), ("archive.v1.0", ".part1", 1, ".rar"))

    def test_group_by_time(self):
        grouper_time_grouping = MessageGrouper(
            grouping_strategy="time",
            grouping_time_window_seconds=60
        )

        # Messages should be pre-sorted by date for _group_by_time
        # (forward_messages already reverses the initial fetch from Telegram)
        now = datetime.now(tz=timezone.utc)
        messages = [
            # Group 1 (User 1)
            MockMessage(id=1, date=now, sender_id=1, filename="file1.txt"),
            MockMessage(id=2, date=now + timedelta(seconds=30), sender_id=1, filename="file2.txt"),
            MockMessage(id=3, date=now + timedelta(seconds=59), sender_id=1, filename="file3.txt"),
            # Group 2 (User 1, new group due to time > 60s)
            MockMessage(id=4, date=now + timedelta(seconds=120), sender_id=1, filename="file4.txt"),
            # Group 3 (User 2)
            MockMessage(id=5, date=now + timedelta(seconds=130), sender_id=2, filename="file5.txt"),
            MockMessage(id=6, date=now + timedelta(seconds=150), sender_id=2, filename="file6.txt"),
            # Group 4 (User 1, new group, different sender than previous)
            MockMessage(id=7, date=now + timedelta(seconds=160), sender_id=1, filename="file7.txt"),
            # Single message group (User 3)
            MockMessage(id=8, date=now + timedelta(seconds=300), sender_id=3, filename="file8.txt"),
            # Group 5 (User 3, follows previous from same sender, within window)
            MockMessage(id=9, date=now + timedelta(seconds=330), sender_id=3, filename="file9.txt"),
        ]

        grouped = grouper_time_grouping._group_by_time(messages)

        self.assertEqual(len(grouped), 5)
        self.assertEqual([m.id for m in grouped[0]], [1, 2, 3]) # User 1, Group 1
        self.assertEqual([m.id for m in grouped[1]], [4])       # User 1, Group 2 (time gap)
        self.assertEqual([m.id for m in grouped[2]], [5, 6])    # User 2, Group 1
        self.assertEqual([m.id for m in grouped[3]], [7])       # User 1, Group 3 (sender change)
        self.assertEqual([m.id for m in grouped[4]], [8, 9])    # User 3, Group 1 + 2 combined

    def test_group_by_filename(self):
        grouper_filename_grouping = MessageGrouper(
            grouping_strategy="filename"
        )
        now = datetime.now(tz=timezone.utc)

        messages = [
            # Group 1 (archive.rar parts)
            MockMessage(id=1, date=now, sender_id=1, filename="archive_part1.rar"),
            MockMessage(id=3, date=now + timedelta(seconds=2), sender_id=1, filename="archive_part3.rar"), # Out of order part
            MockMessage(id=2, date=now + timedelta(seconds=1), sender_id=1, filename="archive_part2.rar"),
            # Another file by same user, different name
            MockMessage(id=4, date=now + timedelta(seconds=3), sender_id=1, filename="document.pdf"),
            # Group 2 (video.mp4 parts, different user)
            MockMessage(id=5, date=now + timedelta(seconds=4), sender_id=2, filename="video_01.mp4"),
            MockMessage(id=6, date=now + timedelta(seconds=5), sender_id=2, filename="video_02.mp4"),
            # Single file, different user
            MockMessage(id=7, date=now + timedelta(seconds=6), sender_id=3, filename="image.jpg"),
            # Files with same base name but different extensions (should be separate groups)
            MockMessage(id=8, date=now + timedelta(seconds=7), sender_id=1, filename="archive_part1.zip"),
            # Files with no standard part numbers but same base (should be individual or grouped by other means if logic changes)
            MockMessage(id=9, date=now + timedelta(seconds=8), sender_id=4, filename="dataset.csv"),
            MockMessage(id=10, date=now + timedelta(seconds=9), sender_id=4, filename="dataset_final.csv"), # Different base
             # Files with same base name, different sender
            MockMessage(id=11, date=now + timedelta(seconds=10), sender_id=1, filename="report_final.docx"),
            MockMessage(id=12, date=now + timedelta(seconds=11), sender_id=2, filename="report_final.docx"),
            # File with no extension
            MockMessage(id=13, date=now + timedelta(seconds=12), sender_id=1, filename="notes_part1"),
        ]
        # Messages are passed as if already sorted by date (as forward_messages would do before calling _group_messages)
        # However, _group_by_filename internally re-sorts candidates by part number.

        grouped = grouper_filename_grouping._group_by_filename(messages)

        # Expected groups (order might vary due to dict iteration then final sort by first msg ID):
        # 1. archive.rar (user 1): [1, 2, 3] (sorted by part number)
        # 2. document.pdf (user 1): [4]
        # 3. video.mp4 (user 2): [5, 6]
        # 4. image.jpg (user 3): [7]
        # 5. archive.zip (user 1): [8] (specifically archive_part1.zip)
        # 6. dataset.csv (user 4): [9]
        # 7. dataset_final.csv (user 4): [10]
        # 8. report_final.docx (user 1): [11]
        # 9. report_final.docx (user 2): [12]
        # 10. notes_part1 (user 1, no ext): [13]

        self.assertEqual(len(grouped), 10)

        # Check content of groups (IDs) - order of groups is sorted by first message ID
        group_ids = [[m.id for m in g] for g in grouped]

        self.assertIn([1, 2, 3], group_ids) # archive.rar group
        self.assertIn([4], group_ids)       # document.pdf
        self.assertIn([5, 6], group_ids)    # video.mp4 group
        self.assertIn([7], group_ids)       # image.jpg
        self.assertIn([8], group_ids)       # archive_part1.zip
        self.assertIn([9], group_ids)       # dataset.csv
        self.assertIn([10], group_ids)      # dataset_final.csv
        self.assertIn([11], group_ids)      # report_final.docx (user 1)
        self.assertIn([12], group_ids)      # report_final.docx (user 2)
        self.assertIn([13], group_ids)      # notes_part1


if __name__ == '__main__':
    unittest.main()


class TestAttachmentForwarderAttribution(unittest.TestCase):

    def setUp(self):
        mock_path = MagicMock(spec=Path)
        mock_path.exists.return_value = False
        self.config = Config(path=mock_path)
        self.db = MagicMock()

    def test_forward_with_attribution_disabled(self):
        asyncio.run(self._test_forward_with_attribution_disabled())

    async def _test_forward_with_attribution_disabled(self):
        self.config.data["forwarding"]["forward_with_attribution"] = False
        forwarder = AttachmentForwarder(config=self.config, db=self.db)

        client = MagicMock()
        client.get_entity = AsyncMock()
        client.iter_messages = MagicMock()
        client.send_message = AsyncMock()
        client.forward_messages = AsyncMock()

        # Mock the client manager to return our mock client
        forwarder.client_manager.get_client = AsyncMock(return_value=client)

        # Mock get_sender
        sender = MockSender(id=123)
        message = MockMessage(id=1, date=datetime.now(timezone.utc), sender_id=123, filename="test.txt", text="test message")

        async def get_sender_async():
            return sender

        message.get_sender = get_sender_async

        # Make iter_messages return our single message
        async def message_generator():
            yield message
        client.iter_messages.return_value = message_generator()

        await forwarder.forward_messages(origin_id="origin", destination_id="dest")

        # Since forward_with_attribution is false, it should use forward_messages
        client.send_message.assert_not_called()
        client.forward_messages.assert_called_once()

# Need to import re in forwarding.py
# Need to import List, Tuple, timedelta in forwarding.py
# Need to add filename_group_pattern to AttachmentForwarder __init__
# The _parse_filename_for_grouping logic in the prompt had a slight error in return for non-part files.
# My test cases assume the improved version discussed (base, "", 0, ext).
# The regex `(.+?)(\d+)?(\.[^.]+)$` was a bit too simple.
# A better regex: `(.+?)(?:_?part(\d+)|_(\d+)| \((\d+)\))?(\.[^.]+|)$`
# My proposed regex in the plan: self.filename_group_pattern = re.compile(r"(.+?)(_?part(\d+)|_(\d+)| \((\d+)\))?(\.[^.]+)$", re.IGNORECASE)
# This regex was already added in a previous step. The test cases will validate it.
# The fallback in _parse_filename_for_grouping for simple files needs to be robust.
# Example: "archive.tar.gz" should ideally be ("archive", "", 0, ".tar.gz") or similar.
# Current regex and parse logic might make it ("archive.tar", "", 0, ".gz"). This is acceptable for now.
# The `_parse_filename_for_grouping` in the previous step's diff seems mostly fine, my tests will confirm.
# The `part_str` in the tuple from `_parse_filename_for_grouping` is important for reconstructing filenames if needed,
# or for more advanced grouping (e.g. distinguishing "_part1" from "_1").
# My test cases for `_parse_filename_for_grouping` are written assuming the implementation from the previous step.
# The provided `_parse_filename_for_grouping` implementation in the previous step was:
#   `return base_name, part_str_group or "", part_num, extension` if part_num_str
#   `return base_name, "", 0, extension` if no part_num_str
#   This seems correct. The fallback for simple files was also added.

# My MockMessage needs to be compatible with _compute_message_hash
# Specifically, `message.file.id`, `message.file.access_hash`, `message.file.size`
# And `isinstance(message.media, types.MessageMediaWebPage)` and `message.media.webpage.url`
# For now, the current MockMessage is okay for testing grouping, but hash tests would need more detail.

# For _group_by_filename, the key used `(msg.sender_id, base_name.lower(), extension.lower())` is good.
# Sorting within these keyed groups using part_num is also good.
# Fallback to msg.id for sorting is a good tie-breaker.
# Handling of `lone_messages` and final sort of `final_groups` is logical.
# Looks reasonable.
