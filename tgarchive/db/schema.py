"""
SPECTRA-004 SQL Schema
======================
SQLite schema definitions for the SPECTRA archiver database.
"""

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY,
    username      TEXT,
    first_name    TEXT,
    last_name     TEXT,
    tags          TEXT,
    avatar        TEXT,
    last_updated  TEXT
);
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);

CREATE TABLE IF NOT EXISTS media (
    id          INTEGER PRIMARY KEY,
    type        TEXT,
    url         TEXT,
    title       TEXT,
    description TEXT,
    thumb       TEXT,
    checksum    TEXT
);
CREATE INDEX IF NOT EXISTS idx_media_type ON media(type);

CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY,
    type        TEXT NOT NULL,
    date        TEXT NOT NULL,
    edit_date   TEXT,
    content     TEXT,
    reply_to    INTEGER,
    user_id     INTEGER REFERENCES users(id),
    media_id    INTEGER REFERENCES media(id),
    checksum    TEXT
);
CREATE INDEX IF NOT EXISTS idx_messages_date ON messages(date);
CREATE INDEX IF NOT EXISTS idx_messages_user ON messages(user_id);

CREATE TABLE IF NOT EXISTS checkpoints (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    last_message_id  INTEGER,
    checkpoint_time  TEXT,
    context          TEXT
);

CREATE TABLE IF NOT EXISTS account_channel_access (
    account_phone_number TEXT NOT NULL,
    channel_id           BIGINT NOT NULL,
    channel_name         TEXT,
    access_hash          BIGINT,
    last_seen            TEXT,
    PRIMARY KEY (account_phone_number, channel_id)
);

CREATE TABLE IF NOT EXISTS channel_forward_schedule (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id          BIGINT NOT NULL,
    destination         TEXT NOT NULL,
    schedule            TEXT NOT NULL,
    last_message_id     INTEGER,
    is_enabled          BOOLEAN DEFAULT TRUE,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS channel_forward_stats (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    schedule_id         INTEGER REFERENCES channel_forward_schedule(id),
    messages_forwarded  INTEGER NOT NULL,
    files_forwarded     INTEGER NOT NULL,
    bytes_forwarded     INTEGER NOT NULL,
    started_at          TEXT NOT NULL,
    finished_at         TEXT NOT NULL,
    status              TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS file_forward_schedule (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    source              TEXT NOT NULL,
    destination         TEXT NOT NULL,
    schedule            TEXT NOT NULL,
    file_types          TEXT,
    min_file_size       INTEGER,
    max_file_size       INTEGER,
    is_enabled          BOOLEAN DEFAULT TRUE,
    priority            INTEGER DEFAULT 0,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS file_forward_queue (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    schedule_id         INTEGER REFERENCES file_forward_schedule(id) ON DELETE SET NULL,
    message_id          INTEGER NOT NULL,
    file_id             TEXT NOT NULL,
    destination         INTEGER,
    status              TEXT NOT NULL,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS category_to_group_mapping (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    category            TEXT NOT NULL,
    group_id            INTEGER NOT NULL,
    priority            INTEGER DEFAULT 0,
    UNIQUE(category, group_id)
);

CREATE TABLE IF NOT EXISTS category_stats (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    category            TEXT NOT NULL,
    files_count         INTEGER NOT NULL,
    bytes_count         INTEGER NOT NULL,
    UNIQUE(category)
);

CREATE TABLE IF NOT EXISTS sorting_groups (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    group_name          TEXT NOT NULL,
    template            TEXT NOT NULL,
    is_enabled          BOOLEAN DEFAULT TRUE,
    UNIQUE(group_name)
);

CREATE TABLE IF NOT EXISTS sorting_stats (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    source              TEXT NOT NULL,
    files_sorted        INTEGER NOT NULL,
    bytes_sorted        INTEGER NOT NULL,
    started_at          TEXT NOT NULL,
    finished_at         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sorting_audit_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    source              TEXT NOT NULL,
    message_id          INTEGER NOT NULL,
    file_id             TEXT NOT NULL,
    category            TEXT NOT NULL,
    group_id            INTEGER NOT NULL,
    created_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS attribution_stats (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    source_channel_id   BIGINT NOT NULL,
    attributions_count  INTEGER NOT NULL,
    UNIQUE(source_channel_id)
);

CREATE TABLE IF NOT EXISTS file_forward_stats (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    schedule_id         INTEGER REFERENCES file_forward_schedule(id),
    files_forwarded     INTEGER NOT NULL,
    bytes_forwarded     INTEGER NOT NULL,
    started_at          TEXT NOT NULL,
    finished_at         TEXT NOT NULL,
    status              TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS migration_progress (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    source              TEXT NOT NULL,
    destination         TEXT NOT NULL,
    last_message_id     INTEGER,
    status              TEXT NOT NULL,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS file_hashes (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id             INTEGER NOT NULL,
    sha256_hash         TEXT,
    perceptual_hash     TEXT,
    fuzzy_hash          TEXT,
    created_at          TEXT NOT NULL,
    UNIQUE(file_id)
);

CREATE TABLE IF NOT EXISTS channel_file_inventory (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id          BIGINT NOT NULL,
    file_id             INTEGER NOT NULL,
    message_id          INTEGER NOT NULL,
    topic_id            INTEGER,
    created_at          TEXT NOT NULL,
    UNIQUE(channel_id, file_id, message_id)
);
"""

__all__ = ["SCHEMA_SQL"]
