# SPECTRA-004 Project Structure

## Resolved Merge Conflict
The merge conflict was resolved by keeping the new hash methods from HEAD:
- `get_all_fuzzy_hashes()`
- `get_all_perceptual_hashes()`

## Modular Folder Structure

```
spectra_004_db/
├── __init__.py               # Package initialization, logging setup
├── models.py                 # Data models (User, Media, Message, Month, Day)
├── schema.py                 # SQL schema definitions
├── db_base.py                # Base database connection and utilities
├── core_operations.py        # Core operations (users, messages, media, timeline)
├── forward_operations.py     # Channel and file forwarding operations  
├── sorting_hash_operations.py # Sorting, categorization, and hash operations
├── migration_operations.py   # Migration tracking operations
└── spectra_db.py            # Main SpectraDB class combining all modules

usage_example.py              # Example usage (can be outside the package)
```

## Module Breakdown

### 1. **models.py**
- NamedTuple definitions for all data types
- User, Media, Message, Month, Day

### 2. **schema.py**
- Complete SQL schema in `SCHEMA_SQL` constant
- All table definitions and indexes

### 3. **db_base.py**
- BaseDB class with connection management
- WAL mode, foreign keys, retry logic
- Common utilities like `export_csv()`

### 4. **core_operations.py**
- User, media, message operations
- Account channel access
- Checkpoints and timeline queries
- Integrity checks

### 5. **forward_operations.py**
- Channel forward schedules and stats
- File forward schedules and queue
- File forward stats

### 6. **sorting_hash_operations.py**
- Category to group mappings
- Sorting groups and stats
- File hashing (SHA256, perceptual, fuzzy)
- Channel file inventory
- Attribution stats

### 7. **migration_operations.py**
- Migration progress tracking
- Migration reporting

### 8. **spectra_db.py**
- Main class inheriting from BaseDB
- Initializes all operation modules
- Delegates methods to appropriate modules
- Maintains backward compatibility

## Benefits of This Structure

1. **Separation of Concerns**: Each module handles a specific domain
2. **Maintainability**: Easier to find and modify specific functionality
3. **Testability**: Can test each module independently
4. **Scalability**: New operation types can be added as new modules
5. **Backward Compatibility**: Main SpectraDB class preserves original API

## Usage

```python
from spectra_004_db import SpectraDB, User, Media, Message

# Works exactly like before
with SpectraDB("archive.db") as db:
    db.upsert_user(user)
    db.add_file_hash(...)
    
    # Can also access operations directly
    db.core.verify_checksums("messages")
    db.forward.get_channel_forward_schedules()
```
