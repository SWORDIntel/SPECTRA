from yoyo import step

__depends__ = {}

steps = [
    step("""
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY,
    username      TEXT,
    first_name    TEXT,
    last_name     TEXT,
    tags          TEXT,
    avatar        TEXT,
    last_updated  TEXT
);
    """),
    step("""
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
    """),
    step("""
CREATE TABLE IF NOT EXISTS media (
    id          INTEGER PRIMARY KEY,
    type        TEXT,
    url         TEXT,
    title       TEXT,
    description TEXT,
    thumb       TEXT,
    checksum    TEXT
);
    """),
    step("""
CREATE INDEX IF NOT EXISTS idx_media_type ON media(type);
    """),
    step("""
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
    """),
    step("""
CREATE INDEX IF NOT EXISTS idx_messages_date ON messages(date);
    """),
    step("""
CREATE INDEX IF NOT EXISTS idx_messages_user ON messages(user_id);
    """),
    step("""
CREATE TABLE IF NOT EXISTS checkpoints (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    last_message_id  INTEGER,
    checkpoint_time  TEXT,
    context          TEXT
);
    """),
    step("""
CREATE TABLE IF NOT EXISTS account_channel_access (
    account_phone_number TEXT NOT NULL,
    channel_id           BIGINT NOT NULL,
    channel_name         TEXT,
    access_hash          BIGINT,
    last_seen            TEXT,
    PRIMARY KEY (account_phone_number, channel_id)
);
    """),
    step("""
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
    """),
    step("""
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
    """),
    step("""
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
    """),
    step("""
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
    """),
    step("""
CREATE TABLE IF NOT EXISTS category_to_group_mapping (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    category            TEXT NOT NULL,
    group_id            INTEGER NOT NULL,
    priority            INTEGER DEFAULT 0,
    UNIQUE(category, group_id)
);
    """),
    step("""
CREATE TABLE IF NOT EXISTS category_stats (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    category            TEXT NOT NULL,
    files_count         INTEGER NOT NULL,
    bytes_count         INTEGER NOT NULL,
    UNIQUE(category)
);
    """),
    step("""
CREATE TABLE IF NOT EXISTS sorting_groups (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    group_name          TEXT NOT NULL,
    template            TEXT NOT NULL,
    is_enabled          BOOLEAN DEFAULT TRUE,
    UNIQUE(group_name)
);
    """),
    step("""
CREATE TABLE IF NOT EXISTS sorting_stats (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    source              TEXT NOT NULL,
    files_sorted        INTEGER NOT NULL,
    bytes_sorted        INTEGER NOT NULL,
    started_at          TEXT NOT NULL,
    finished_at         TEXT NOT NULL
);
    """),
    step("""
CREATE TABLE IF NOT EXISTS sorting_audit_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    source              TEXT NOT NULL,
    message_id          INTEGER NOT NULL,
    file_id             TEXT NOT NULL,
    category            TEXT NOT NULL,
    group_id            INTEGER NOT NULL,
    created_at          TEXT NOT NULL
);
    """),
    step("""
CREATE TABLE IF NOT EXISTS attribution_stats (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    source_channel_id   BIGINT NOT NULL,
    attributions_count  INTEGER NOT NULL,
    UNIQUE(source_channel_id)
);
    """),
    step("""
CREATE TABLE IF NOT EXISTS file_forward_stats (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    schedule_id         INTEGER REFERENCES file_forward_schedule(id),
    files_forwarded     INTEGER NOT NULL,
    bytes_forwarded     INTEGER NOT NULL,
    started_at          TEXT NOT NULL,
    finished_at         TEXT NOT NULL,
    status              TEXT NOT NULL
);
    """),
    step("""
CREATE TABLE IF NOT EXISTS migration_progress (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    source              TEXT NOT NULL,
    destination         TEXT NOT NULL,
    last_message_id     INTEGER,
    status              TEXT NOT NULL,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);
    """),
    step("""
CREATE TABLE IF NOT EXISTS file_hashes (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id             INTEGER REFERENCES media(id) ON DELETE CASCADE,
    sha256_hash         TEXT,
    perceptual_hash     TEXT,
    fuzzy_hash          TEXT,
    created_at          TEXT NOT NULL,
    UNIQUE(file_id)
);
    """),
    step("""
CREATE INDEX IF NOT EXISTS idx_file_hashes_sha256 ON file_hashes(sha256_hash);
    """),
    step("""
CREATE INDEX IF NOT EXISTS idx_file_hashes_perceptual ON file_hashes(perceptual_hash);
    """),
    step("""
CREATE INDEX IF NOT EXISTS idx_file_hashes_fuzzy ON file_hashes(fuzzy_hash);
    """),
    step("""
CREATE TABLE IF NOT EXISTS channel_file_inventory (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id          INTEGER NOT NULL,
    file_id             INTEGER NOT NULL,
    message_id          INTEGER NOT NULL,
    topic_id            INTEGER,
    created_at          TEXT NOT NULL,
    UNIQUE(channel_id, file_id, message_id)
);
    """),
    step("""
CREATE TABLE IF NOT EXISTS topic_file_mapping (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id            INTEGER NOT NULL,
    file_id             INTEGER NOT NULL,
    message_id          INTEGER NOT NULL,
    created_at          TEXT NOT NULL,
    UNIQUE(topic_id, file_id, message_id)
);
    """),
    step("""
CREATE INDEX IF NOT EXISTS idx_channel_file_inventory_channel_id ON channel_file_inventory(channel_id);
    """),
    step("""
CREATE INDEX IF NOT EXISTS idx_channel_file_inventory_file_id ON channel_file_inventory(file_id);
    """),
    step("""
CREATE INDEX IF NOT EXISTS idx_topic_file_mapping_topic_id ON topic_file_mapping(topic_id);
    """),
    step("""
CREATE INDEX IF NOT EXISTS idx_topic_file_mapping_file_id ON topic_file_mapping(file_id);
    """)
]
