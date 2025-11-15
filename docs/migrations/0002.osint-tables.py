from yoyo import step

__depends__ = {"0001.initial-schema"}

steps = [
    step("""
CREATE TABLE IF NOT EXISTS osint_targets (
    user_id       INTEGER PRIMARY KEY,
    username      TEXT,
    notes         TEXT,
    created_at    TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);
    """),
    step("""
CREATE INDEX IF NOT EXISTS idx_osint_targets_username ON osint_targets(username);
    """),
    step("""
CREATE TABLE IF NOT EXISTS osint_interactions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    source_user_id      INTEGER NOT NULL,
    target_user_id      INTEGER NOT NULL,
    interaction_type    TEXT NOT NULL,
    channel_id          INTEGER NOT NULL,
    message_id          INTEGER NOT NULL,
    timestamp           TEXT NOT NULL,
    FOREIGN KEY (source_user_id) REFERENCES users(id),
    FOREIGN KEY (target_user_id) REFERENCES users(id)
);
    """),
    step("""
CREATE INDEX IF NOT EXISTS idx_osint_interactions_source_user ON osint_interactions(source_user_id);
    """),
    step("""
CREATE INDEX IF NOT EXISTS idx_osint_interactions_target_user ON osint_interactions(target_user_id);
    """)
]
