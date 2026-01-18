"""
Mass Migration Manager for SPECTRA
==================================

This module contains the MassMigrationManager class for managing mass migrations.
"""

import asyncio
import logging
from .forwarding import AttachmentForwarder

logger = logging.getLogger(__name__)

class MassMigrationManager:
    """
    A class for managing mass migrations.
    """
    def __init__(self, config, db, client):
        self.config = config
        self.db = db
        self.client = client
        # Store db_path for MigrationOperations
        if hasattr(db, 'db_path'):
            self.db_path = db.db_path
        elif hasattr(db, '_db_path'):
            self.db_path = db._db_path
        else:
            self.db_path = None
        self.forwarder = AttachmentForwarder(
            config=config,
            db=db,
            prepend_origin_info=config.data.get("forwarding", {}).get("always_prepend_origin_info", False)
        )

    async def one_time_migration(self, source, destination, dry_run=False, parallel=False):
        """
        Performs a one-time migration from a source to a destination.
        """
        use_parallel = parallel or self.config.get("migration_mode", {}).get("use_parallel", False)

        if use_parallel:
            # Parallel migration: split messages into batches and process concurrently
            logger.info("Starting parallel migration")
            
            # Get message count to determine batch size
            try:
                from telethon.tl.types import InputPeerChannel, InputPeerChat
                entity = await self.client.get_entity(source)
                total_messages = 0
                async for message in self.client.iter_messages(entity, limit=None):
                    total_messages += 1
                    if total_messages > 1000:  # Sample first 1000 to estimate
                        break
                
                # Use multiple forwarders for parallel processing
                batch_size = max(100, total_messages // 4)  # 4 parallel workers
                logger.info(f"Parallel migration: {total_messages} messages, batch size: {batch_size}")
                
                # Create multiple migration tasks
                tasks = []
                for batch_start in range(0, total_messages, batch_size):
                    task = self._migrate_batch(source, destination, batch_start, batch_size, migration_id)
                    tasks.append(task)
                
                # Run tasks in parallel
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                # Check for errors
                errors = [r for r in results if isinstance(r, Exception)]
                if errors:
                    logger.error(f"Parallel migration completed with {len(errors)} errors")
                    for error in errors:
                        logger.error(f"Migration error: {error}")
                else:
                    logger.info("Parallel migration completed successfully")
                
                # Update progress
                self.db.update_migration_progress(migration_id, total_messages, "completed")
                return
            except Exception as e:
                logger.error(f"Parallel migration failed, falling back to sequential: {e}")
                # Fall through to sequential migration

        progress = self.db.get_migration_progress(source, destination)
        if progress:
            migration_id, last_message_id = progress
            print(f"Resuming migration from message ID: {last_message_id}")
        else:
            migration_id = self.db.add_migration_progress(source, destination, "in_progress")
            last_message_id = 0

        if dry_run:
            print(f"DRY RUN: Would migrate files from {source} to {destination} starting from message ID {last_message_id}")
            return

        try:
            new_last_message_id, _ = await self.forwarder.forward_messages(
                origin_id=source,
                destination_id=destination,
                start_message_id=last_message_id
            )
            if new_last_message_id:
                self.db.update_migration_progress(migration_id, new_last_message_id, "completed")
        except Exception as e:
            self.db.update_migration_progress(migration_id, last_message_id, f"error: {e}")
            raise

    async def _migrate_batch(self, source, destination, start_id, batch_size, migration_id):
        """Migrate a batch of messages (used for parallel migration)."""
        try:
            new_last_message_id, _ = await self.forwarder.forward_messages(
                origin_id=source,
                destination_id=destination,
                start_message_id=start_id
            )
            return new_last_message_id
        except Exception as e:
            logger.error(f"Batch migration failed (start_id={start_id}): {e}")
            raise

    def rollback_migration(self, migration_id):
        """
        Rolls back a migration by marking it as rolled back in the database.
        
        Note: Full message deletion rollback requires tracking individual forwarded message IDs
        in the migration records, which is not currently implemented. This method marks the
        migration as rolled back for tracking purposes.
        """
        try:
            # Get migration details using MigrationOperations
            from ..db.migration_operations import MigrationOperations
            if not self.db_path:
                # Try to get db_path from db object
                if hasattr(self.db, 'db_path'):
                    db_path = self.db.db_path
                else:
                    logger.error("Database path not available for rollback")
                    return False
            else:
                db_path = self.db_path
            
            # MigrationOperations expects a db object, not a path
            # Check if self.db has the right interface
            if hasattr(self.db, 'cur') and hasattr(self.db, '_exec_retry'):
                migration_ops = MigrationOperations(self.db)
            else:
                logger.error("Database object does not have required interface for MigrationOperations")
                return False
            
            report = migration_ops.get_migration_report(migration_id)
            
            if report:
                source, destination, last_message_id, status, created_at, updated_at = report
                logger.info(f"Rollback migration {migration_id}: source={source}, destination={destination}")
                
                # Mark migration as rolled back
                migration_ops.update_migration_progress(migration_id, last_message_id, "rolled_back")
                logger.info(f"Migration {migration_id} marked as rolled back")
                logger.warning("Note: Individual message deletion requires message ID tracking in migration records")
                return True
            else:
                logger.error(f"Migration {migration_id} not found")
                return False
        except Exception as e:
            logger.error(f"Rollback failed for migration {migration_id}: {e}")
            return False
