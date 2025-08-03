"""
SPECTRA-004 Usage Example
========================
Example of how to use the modular SpectraDB system.
"""
from pathlib import Path
from spectra_004_db import SpectraDB, User, Media, Message
from datetime import datetime, timezone

# Initialize database
db_path = Path("telegram_archive.db")
with SpectraDB(db_path, tz="America/New_York") as db:
    
    # 1. Working with users
    user = User(
        id=12345,
        username="johndoe",
        first_name="John",
        last_name="Doe",
        tags=["admin", "trusted"],
        avatar="avatar_url",
        last_updated=datetime.now(timezone.utc)
    )
    db.upsert_user(user)
    
    # 2. Working with media
    media = Media(
        id=54321,
        type="photo",
        url="https://example.com/photo.jpg",
        title="Sample Photo",
        description="A sample photo",
        thumb="thumb_url",
        checksum="abc123"
    )
    db.upsert_media(media)
    
    # 3. Working with messages
    message = Message(
        id=99999,
        type="text",
        date=datetime.now(timezone.utc),
        edit_date=None,
        content="Hello, world!",
        reply_to=None,
        user=user,
        media=None,
        checksum="xyz789"
    )
    db.upsert_message(message)
    
    # 4. Channel forwarding
    db.add_channel_forward_schedule(
        channel_id=123456789,
        destination="@destination_channel",
        schedule="*/30 * * * *"  # Every 30 minutes
    )
    
    # 5. File sorting groups
    db.add_sorting_group("documents", "/archive/docs/{year}/{month}")
    db.add_category_to_group_mapping("pdf", 1, priority=10)
    
    # 6. Migration tracking
    migration_id = db.add_migration_progress(
        source="@old_channel",
        destination="@new_channel",
        status="in_progress"
    )
    
    # 7. File hashing
    db.add_file_hash(
        file_id=12345,
        sha256_hash="a665a45920422f9d417e4867efdc4fb8a04a1f3fff1fa07e998e86f7f7a27ae3",
        perceptual_hash="8c8c8c8c",
        fuzzy_hash="96:U7dmSmQ7tTCAXVVbsVV4VbVViTbVT4Vb8bV..."
    )
    
    # 8. Timeline queries
    for month in db.months():
        print(f"{month.label}: {month.count} messages")
        
    # 9. Channel access tracking
    db.upsert_account_channel_access(
        account_phone_number="+1234567890",
        channel_id=123456789,
        channel_name="My Channel",
        access_hash=987654321,
        last_seen=datetime.now(timezone.utc).isoformat()
    )
    
    # 10. Get unique channels
    channels = db.get_all_unique_channels()
    for channel_id, phone in channels:
        print(f"Channel {channel_id} accessible by {phone}")
    
    # 11. Direct access to operation modules
    # Access core operations directly
    latest_checkpoint = db.core.latest_checkpoint("sync")
    
    # Access forward operations directly
    schedules = db.forward.get_file_forward_schedules()
    
    # Access sorting/hash operations directly
    fuzzy_hashes = db.sorting_hash.get_all_fuzzy_hashes(channel_id=123456789)
    
    # 12. Export data
    db.export_csv("messages", Path("messages_export.csv"))
