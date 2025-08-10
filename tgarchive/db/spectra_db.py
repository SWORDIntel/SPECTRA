"""
SPECTRA-004 Main Database Handler
=================================
Main SpectraDB class combining all operation modules.
"""
from pathlib import Path

from .core_operations import CoreOperations
from .db_base import BaseDB
from .forward_operations import ForwardOperations
from .migration_operations import MigrationOperations
from .sorting_hash_operations import SortingHashOperations
from .mirror_operations import MirrorOperations


class SpectraDB(BaseDB):
    """SQLite wrapper providing all SPECTRA database operations."""

    def __init__(self, db_path: Path | str, *, tz: str | None = None) -> None:
        super().__init__(db_path, tz=tz)
        
        # Initialize operation modules
        self.core = CoreOperations(self)
        self.forward = ForwardOperations(self)
        self.sorting_hash = SortingHashOperations(self)
        self.migration = MigrationOperations(self)
        self.mirror = MirrorOperations(self)

    # Delegate core operations
    def upsert_user(self, user):
        return self.core.upsert_user(user)

    def upsert_media(self, media):
        return self.core.upsert_media(media)

    def upsert_message(self, msg):
        return self.core.upsert_message(msg)

    def upsert_account_channel_access(self, *args, **kwargs):
        return self.core.upsert_account_channel_access(*args, **kwargs)

    def get_all_unique_channels(self):
        return self.core.get_all_unique_channels()

    def save_checkpoint(self, *args, **kwargs):
        return self.core.save_checkpoint(*args, **kwargs)

    def latest_checkpoint(self, *args, **kwargs):
        return self.core.latest_checkpoint(*args, **kwargs)

    def months(self):
        return self.core.months()

    def days(self, *args, **kwargs):
        return self.core.days(*args, **kwargs)

    def verify_checksums(self, *args, **kwargs):
        return self.core.verify_checksums(*args, **kwargs)

    # Delegate forward operations
    def add_channel_forward_schedule(self, *args, **kwargs):
        return self.forward.add_channel_forward_schedule(*args, **kwargs)

    def get_channel_forward_schedules(self):
        return self.forward.get_channel_forward_schedules()

    def get_channel_forward_schedule_by_channel_and_destination(self, *args, **kwargs):
        return self.forward.get_channel_forward_schedule_by_channel_and_destination(*args, **kwargs)

    def update_channel_forward_schedule_checkpoint(self, *args, **kwargs):
        return self.forward.update_channel_forward_schedule_checkpoint(*args, **kwargs)

    def add_channel_forward_stats(self, *args, **kwargs):
        return self.forward.add_channel_forward_stats(*args, **kwargs)

    def add_file_forward_schedule(self, *args, **kwargs):
        return self.forward.add_file_forward_schedule(*args, **kwargs)

    def get_file_forward_schedules(self):
        return self.forward.get_file_forward_schedules()

    def get_file_forward_schedule_by_id(self, *args, **kwargs):
        return self.forward.get_file_forward_schedule_by_id(*args, **kwargs)

    def add_to_file_forward_queue(self, *args, **kwargs):
        return self.forward.add_to_file_forward_queue(*args, **kwargs)

    def get_file_forward_queue(self):
        return self.forward.get_file_forward_queue()

    def update_file_forward_queue_status(self, *args, **kwargs):
        return self.forward.update_file_forward_queue_status(*args, **kwargs)

    def get_file_forward_queue_status_by_schedule_id(self, *args, **kwargs):
        return self.forward.get_file_forward_queue_status_by_schedule_id(*args, **kwargs)

    def add_file_forward_stats(self, *args, **kwargs):
        return self.forward.add_file_forward_stats(*args, **kwargs)

    # Delegate sorting/hash operations
    def add_category_to_group_mapping(self, *args, **kwargs):
        return self.sorting_hash.add_category_to_group_mapping(*args, **kwargs)

    def get_group_id_for_category(self, *args, **kwargs):
        return self.sorting_hash.get_group_id_for_category(*args, **kwargs)

    def update_category_stats(self, *args, **kwargs):
        return self.sorting_hash.update_category_stats(*args, **kwargs)

    def add_sorting_group(self, *args, **kwargs):
        return self.sorting_hash.add_sorting_group(*args, **kwargs)

    def get_sorting_group_template(self, *args, **kwargs):
        return self.sorting_hash.get_sorting_group_template(*args, **kwargs)

    def add_sorting_stats(self, *args, **kwargs):
        return self.sorting_hash.add_sorting_stats(*args, **kwargs)

    def add_sorting_audit_log(self, *args, **kwargs):
        return self.sorting_hash.add_sorting_audit_log(*args, **kwargs)

    def update_attribution_stats(self, *args, **kwargs):
        return self.sorting_hash.update_attribution_stats(*args, **kwargs)

    def add_file_hash(self, *args, **kwargs):
        return self.sorting_hash.add_file_hash(*args, **kwargs)

    def get_all_fuzzy_hashes(self, *args, **kwargs):
        return self.sorting_hash.get_all_fuzzy_hashes(*args, **kwargs)

    def get_all_perceptual_hashes(self, *args, **kwargs):
        return self.sorting_hash.get_all_perceptual_hashes(*args, **kwargs)

    def add_channel_file_inventory(self, *args, **kwargs):
        return self.sorting_hash.add_channel_file_inventory(*args, **kwargs)

    # Delegate migration operations
    def add_migration_progress(self, *args, **kwargs):
        return self.migration.add_migration_progress(*args, **kwargs)

    def update_migration_progress(self, *args, **kwargs):
        return self.migration.update_migration_progress(*args, **kwargs)

    def get_migration_progress(self, *args, **kwargs):
        return self.migration.get_migration_progress(*args, **kwargs)

    def get_migration_report(self, *args, **kwargs):
        return self.migration.get_migration_report(*args, **kwargs)

    # Delegate mirror operations
    def add_mirror_progress(self, *args, **kwargs):
        return self.mirror.add_mirror_progress(*args, **kwargs)

    def update_mirror_progress(self, *args, **kwargs):
        return self.mirror.update_mirror_progress(*args, **kwargs)

    def get_mirror_progress(self, *args, **kwargs):
        return self.mirror.get_mirror_progress(*args, **kwargs)


__all__ = ["SpectraDB"]
