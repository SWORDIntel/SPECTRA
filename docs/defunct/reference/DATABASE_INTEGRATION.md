# Database Integration

SPECTRA stores all discovery and archiving data in a SQLite database:

- Discovered groups with metadata and priority scores
- Group relationships and network graph data
- Account usage statistics and health metrics
- Archive status tracking

You can specify a custom database path with `--db path/to/database.db`

For detailed database schema information, see [DATABASE_SCHEMA.md](DATABASE_SCHEMA.md).
