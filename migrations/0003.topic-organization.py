"""
Migration 0003: Topic Organization Schema
=========================================

Database schema extensions for topic management and content organization.
Adds support for topic tracking, content classification, and organization statistics.
"""

from typing import Dict, Any


TOPIC_ORGANIZATION_SCHEMA = """
-- Topic Management Tables
CREATE TABLE IF NOT EXISTS forum_topics (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id          BIGINT NOT NULL,
    topic_id            INTEGER NOT NULL,
    title               TEXT NOT NULL,
    icon_color          INTEGER,
    icon_emoji_id       INTEGER,
    category            TEXT,
    subcategory         TEXT,
    description         TEXT,
    message_count       INTEGER DEFAULT 0,
    created_at          TEXT NOT NULL,
    last_activity       TEXT,
    is_active           BOOLEAN DEFAULT TRUE,
    UNIQUE(channel_id, topic_id)
);
CREATE INDEX IF NOT EXISTS idx_forum_topics_channel ON forum_topics(channel_id);
CREATE INDEX IF NOT EXISTS idx_forum_topics_category ON forum_topics(category);

-- Content Classification Rules
CREATE TABLE IF NOT EXISTS classification_rules (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT NOT NULL UNIQUE,
    strategy            TEXT NOT NULL,
    pattern             TEXT NOT NULL,
    category            TEXT NOT NULL,
    priority            INTEGER DEFAULT 0,
    conditions          TEXT,  -- JSON data
    metadata_extractors TEXT,  -- JSON array
    is_enabled          BOOLEAN DEFAULT TRUE,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_classification_rules_priority ON classification_rules(priority);

-- Topic Creation Rules
CREATE TABLE IF NOT EXISTS topic_creation_rules (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT NOT NULL UNIQUE,
    strategy            TEXT NOT NULL,
    pattern             TEXT NOT NULL,
    title_template      TEXT NOT NULL,
    icon_color          INTEGER DEFAULT 3498212,
    icon_emoji_id       INTEGER,
    priority            INTEGER DEFAULT 0,
    conditions          TEXT,  -- JSON data
    is_enabled          BOOLEAN DEFAULT TRUE,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_topic_creation_rules_priority ON topic_creation_rules(priority);

-- Message Content Metadata
CREATE TABLE IF NOT EXISTS message_content_metadata (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id          INTEGER NOT NULL,
    channel_id          BIGINT NOT NULL,
    content_type        TEXT NOT NULL,
    category            TEXT NOT NULL,
    subcategory         TEXT,
    file_extension      TEXT,
    file_size           INTEGER,
    mime_type           TEXT,
    duration            INTEGER,
    width               INTEGER,
    height              INTEGER,
    keywords            TEXT,  -- JSON array
    classification_confidence REAL DEFAULT 1.0,
    additional_metadata TEXT,  -- JSON data
    created_at          TEXT NOT NULL,
    UNIQUE(message_id, channel_id)
);
CREATE INDEX IF NOT EXISTS idx_message_metadata_channel ON message_content_metadata(channel_id);
CREATE INDEX IF NOT EXISTS idx_message_metadata_category ON message_content_metadata(category);
CREATE INDEX IF NOT EXISTS idx_message_metadata_type ON message_content_metadata(content_type);

-- Topic Assignment History
CREATE TABLE IF NOT EXISTS topic_assignments (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id          INTEGER NOT NULL,
    channel_id          BIGINT NOT NULL,
    topic_id            INTEGER,
    topic_title         TEXT,
    category            TEXT,
    assignment_method   TEXT NOT NULL, -- auto, manual, fallback
    confidence          REAL DEFAULT 1.0,
    fallback_used       BOOLEAN DEFAULT FALSE,
    created_at          TEXT NOT NULL,
    UNIQUE(message_id, channel_id)
);
CREATE INDEX IF NOT EXISTS idx_topic_assignments_channel ON topic_assignments(channel_id);
CREATE INDEX IF NOT EXISTS idx_topic_assignments_topic ON topic_assignments(topic_id);
CREATE INDEX IF NOT EXISTS idx_topic_assignments_method ON topic_assignments(assignment_method);

-- Organization Statistics
CREATE TABLE IF NOT EXISTS organization_stats (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id          BIGINT NOT NULL,
    date                TEXT NOT NULL, -- YYYY-MM-DD format
    messages_processed  INTEGER DEFAULT 0,
    topics_created      INTEGER DEFAULT 0,
    successful_assignments INTEGER DEFAULT 0,
    failed_assignments  INTEGER DEFAULT 0,
    fallback_used       INTEGER DEFAULT 0,
    categories_data     TEXT,  -- JSON with category counts
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    UNIQUE(channel_id, date)
);
CREATE INDEX IF NOT EXISTS idx_organization_stats_channel ON organization_stats(channel_id);
CREATE INDEX IF NOT EXISTS idx_organization_stats_date ON organization_stats(date);

-- Topic Usage Statistics
CREATE TABLE IF NOT EXISTS topic_usage_stats (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id          BIGINT NOT NULL,
    topic_id            INTEGER NOT NULL,
    topic_title         TEXT,
    category            TEXT,
    messages_assigned   INTEGER DEFAULT 0,
    last_message_date   TEXT,
    total_file_size     INTEGER DEFAULT 0,
    unique_senders      INTEGER DEFAULT 0,
    date                TEXT NOT NULL, -- YYYY-MM-DD format
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    UNIQUE(channel_id, topic_id, date)
);
CREATE INDEX IF NOT EXISTS idx_topic_usage_channel ON topic_usage_stats(channel_id);
CREATE INDEX IF NOT EXISTS idx_topic_usage_topic ON topic_usage_stats(topic_id);
CREATE INDEX IF NOT EXISTS idx_topic_usage_date ON topic_usage_stats(date);

-- Failed Topic Creations Log
CREATE TABLE IF NOT EXISTS topic_creation_failures (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id          BIGINT NOT NULL,
    intended_title      TEXT NOT NULL,
    category            TEXT,
    error_type          TEXT NOT NULL,
    error_message       TEXT,
    retry_count         INTEGER DEFAULT 0,
    resolved            BOOLEAN DEFAULT FALSE,
    created_at          TEXT NOT NULL,
    last_retry_at       TEXT,
    resolved_at         TEXT
);
CREATE INDEX IF NOT EXISTS idx_topic_failures_channel ON topic_creation_failures(channel_id);
CREATE INDEX IF NOT EXISTS idx_topic_failures_resolved ON topic_creation_failures(resolved);

-- Organization Engine Configuration
CREATE TABLE IF NOT EXISTS organization_configs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id          BIGINT NOT NULL UNIQUE,
    mode                TEXT NOT NULL DEFAULT 'auto_create',
    topic_strategy      TEXT NOT NULL DEFAULT 'content_type',
    fallback_strategy   TEXT NOT NULL DEFAULT 'general_topic',
    max_topics_per_channel INTEGER DEFAULT 100,
    topic_creation_cooldown INTEGER DEFAULT 30,
    enable_content_analysis BOOLEAN DEFAULT TRUE,
    confidence_threshold REAL DEFAULT 0.7,
    general_topic_title TEXT DEFAULT 'General Discussion',
    auto_cleanup_empty  BOOLEAN DEFAULT FALSE,
    enable_statistics   BOOLEAN DEFAULT TRUE,
    debug_mode          BOOLEAN DEFAULT FALSE,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_organization_configs_channel ON organization_configs(channel_id);

-- Content Type Mappings
CREATE TABLE IF NOT EXISTS content_type_mappings (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    file_extension      TEXT NOT NULL UNIQUE,
    content_type        TEXT NOT NULL,
    category            TEXT NOT NULL,
    subcategory         TEXT,
    icon_color          INTEGER,
    priority            INTEGER DEFAULT 0,
    is_enabled          BOOLEAN DEFAULT TRUE,
    created_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_content_type_ext ON content_type_mappings(file_extension);
CREATE INDEX IF NOT EXISTS idx_content_type_category ON content_type_mappings(category);

-- Organization Queue for Retry Operations
CREATE TABLE IF NOT EXISTS organization_retry_queue (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id          INTEGER NOT NULL,
    channel_id          BIGINT NOT NULL,
    category            TEXT,
    error_type          TEXT,
    retry_count         INTEGER DEFAULT 0,
    max_retries         INTEGER DEFAULT 3,
    next_retry_at       TEXT NOT NULL,
    metadata            TEXT,  -- JSON data
    created_at          TEXT NOT NULL,
    last_attempt_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_retry_queue_channel ON organization_retry_queue(channel_id);
CREATE INDEX IF NOT EXISTS idx_retry_queue_next_retry ON organization_retry_queue(next_retry_at);

-- Topic Templates
CREATE TABLE IF NOT EXISTS topic_templates (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT NOT NULL UNIQUE,
    title_template      TEXT NOT NULL,
    description_template TEXT,
    icon_color          INTEGER DEFAULT 3498212,
    icon_emoji_id       INTEGER,
    category            TEXT NOT NULL,
    strategy            TEXT NOT NULL,
    conditions          TEXT,  -- JSON conditions
    is_default          BOOLEAN DEFAULT FALSE,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_topic_templates_category ON topic_templates(category);
CREATE INDEX IF NOT EXISTS idx_topic_templates_strategy ON topic_templates(strategy);
"""


def get_migration_sql() -> str:
    """Get the SQL for this migration."""
    return TOPIC_ORGANIZATION_SCHEMA


def get_default_data() -> Dict[str, Any]:
    """Get default data to insert after schema creation."""
    return {
        'content_type_mappings': [
            # Image files
            ('.jpg', 'photo', 'images', 'photo', 3498212),
            ('.jpeg', 'photo', 'images', 'photo', 3498212),
            ('.png', 'photo', 'images', 'photo', 3498212),
            ('.gif', 'animation', 'images', 'animated', 15844367),
            ('.webp', 'photo', 'images', 'photo', 3498212),
            ('.bmp', 'photo', 'images', 'photo', 3498212),
            ('.svg', 'document', 'images', 'vector', 10181046),

            # Video files
            ('.mp4', 'video', 'videos', 'video', 15158332),
            ('.mkv', 'video', 'videos', 'video', 15158332),
            ('.avi', 'video', 'videos', 'video', 15158332),
            ('.mov', 'video', 'videos', 'video', 15158332),
            ('.webm', 'video', 'videos', 'video', 15158332),
            ('.wmv', 'video', 'videos', 'video', 15158332),
            ('.flv', 'video', 'videos', 'video', 15158332),

            # Audio files
            ('.mp3', 'audio', 'audio', 'music', 10181046),
            ('.wav', 'audio', 'audio', 'audio', 10181046),
            ('.flac', 'audio', 'audio', 'music', 10181046),
            ('.aac', 'audio', 'audio', 'music', 10181046),
            ('.ogg', 'audio', 'audio', 'music', 10181046),
            ('.m4a', 'audio', 'audio', 'music', 10181046),
            ('.wma', 'audio', 'audio', 'music', 10181046),

            # Document files
            ('.pdf', 'document', 'documents', 'pdf', 15844367),
            ('.doc', 'document', 'documents', 'word', 3910932),
            ('.docx', 'document', 'documents', 'word', 3910932),
            ('.xls', 'document', 'documents', 'excel', 2067276),
            ('.xlsx', 'document', 'documents', 'excel', 2067276),
            ('.ppt', 'document', 'documents', 'powerpoint', 14315734),
            ('.pptx', 'document', 'documents', 'powerpoint', 14315734),
            ('.txt', 'document', 'documents', 'text', 9807270),

            # Archive files
            ('.zip', 'document', 'archives', 'archive', 6765239),
            ('.rar', 'document', 'archives', 'archive', 6765239),
            ('.7z', 'document', 'archives', 'archive', 6765239),
            ('.tar', 'document', 'archives', 'archive', 6765239),
            ('.gz', 'document', 'archives', 'archive', 6765239),

            # Code files
            ('.py', 'document', 'source_code', 'python', 3447003),
            ('.js', 'document', 'source_code', 'javascript', 16772608),
            ('.html', 'document', 'source_code', 'html', 14315734),
            ('.css', 'document', 'source_code', 'css', 1679334),
            ('.java', 'document', 'source_code', 'java', 14315734),
            ('.cpp', 'document', 'source_code', 'cpp', 6765239),
            ('.c', 'document', 'source_code', 'c', 6765239),

            # Data files
            ('.json', 'document', 'data', 'json', 16772608),
            ('.xml', 'document', 'data', 'xml', 15844367),
            ('.csv', 'document', 'data', 'csv', 2067276),
            ('.sql', 'document', 'data', 'sql', 3447003),

            # Executable files
            ('.exe', 'document', 'executables', 'windows', 9807270),
            ('.msi', 'document', 'executables', 'windows', 9807270),
            ('.deb', 'document', 'executables', 'linux', 15844367),
            ('.rpm', 'document', 'executables', 'linux', 15158332),
            ('.dmg', 'document', 'executables', 'macos', 9807270),
        ],

        'topic_templates': [
            {
                'name': 'content_type_photos',
                'title_template': '📸 Photos',
                'description_template': 'Photo and image files',
                'icon_color': 3498212,
                'category': 'photos',
                'strategy': 'content_type',
                'conditions': '{"content_type": ["photo"]}',
                'is_default': True
            },
            {
                'name': 'content_type_videos',
                'title_template': '🎬 Videos',
                'description_template': 'Video files and animations',
                'icon_color': 15158332,
                'category': 'videos',
                'strategy': 'content_type',
                'conditions': '{"content_type": ["video", "animation"]}',
                'is_default': True
            },
            {
                'name': 'content_type_audio',
                'title_template': '🎵 Audio',
                'description_template': 'Audio files and voice messages',
                'icon_color': 10181046,
                'category': 'audio',
                'strategy': 'content_type',
                'conditions': '{"content_type": ["audio", "voice"]}',
                'is_default': True
            },
            {
                'name': 'content_type_documents',
                'title_template': '📄 Documents',
                'description_template': 'Text documents and files',
                'icon_color': 15844367,
                'category': 'documents',
                'strategy': 'content_type',
                'conditions': '{"content_type": ["document"]}',
                'is_default': True
            },
            {
                'name': 'daily_archive',
                'title_template': '📅 {date}',
                'description_template': 'Daily archive for {date}',
                'icon_color': 3498212,
                'category': 'daily',
                'strategy': 'date_based',
                'conditions': '{"period": "daily"}',
                'is_default': False
            },
            {
                'name': 'weekly_archive',
                'title_template': '📆 Week {week_num} - {year}',
                'description_template': 'Weekly archive for week {week_num} of {year}',
                'icon_color': 2067276,
                'category': 'weekly',
                'strategy': 'date_based',
                'conditions': '{"period": "weekly"}',
                'is_default': False
            }
        ],

        'classification_rules': [
            {
                'name': 'large_files',
                'strategy': 'size_based',
                'pattern': 'large',
                'category': 'large_files',
                'priority': 50,
                'conditions': '{"min_size": 52428800}',  # 50MB
                'metadata_extractors': '["file_size", "mime_type"]'
            },
            {
                'name': 'archive_files',
                'strategy': 'file_extension',
                'pattern': 'archive',
                'category': 'archives',
                'priority': 80,
                'conditions': '{}',
                'metadata_extractors': '["file_extension", "file_size"]'
            },
            {
                'name': 'source_code',
                'strategy': 'file_extension',
                'pattern': 'code',
                'category': 'source_code',
                'priority': 70,
                'conditions': '{}',
                'metadata_extractors': '["file_extension", "content_analysis"]'
            }
        ]
    }


if __name__ == "__main__":
    print("Migration 0003: Topic Organization Schema")
    print("=" * 50)
    print(get_migration_sql())