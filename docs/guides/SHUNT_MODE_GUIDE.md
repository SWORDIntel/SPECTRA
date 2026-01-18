# Shunt Mode (File Transfer) - Command Line Guide

Shunt Mode is designed to transfer all media files from one Telegram channel (source) to another (destination) with advanced deduplication and file grouping capabilities. This is useful for consolidating archives, moving collections, or reorganizing media across channels.

## Key Features

*   **Deduplication:** Ensures that files already present in the destination (based on content hash) or previously shunted are not transferred again. It uses the same `forwarded_messages` table as the general forwarding feature.
*   **File Grouping:** Attempts to identify and transfer related files as groups. This helps maintain the integrity of multi-part archives or collections of images/videos sent together.
    *   **Strategies:**
        *   `none`: No grouping; files are transferred individually.
        *   `filename`: Groups files based on common base names and sequential numbering patterns (e.g., `archive_part1.rar`, `archive_part2.rar` or `image_001.jpg`, `image_002.jpg`).
        *   `time`: Groups files sent by the same user within a configurable time window.

## CLI Command

The Shunt Mode is activated using specific arguments with the main `tgarchive` command:

```bash
python -m tgarchive --shunt-from <source_id_or_username> --shunt-to <destination_id_or_username> [options]
```

## CLI Arguments

*   `--shunt-from <id_or_username>`: **Required.** The source channel/chat ID or username from which files will be shunted.
*   `--shunt-to <id_or_username>`: **Required.** The destination channel/chat ID or username to which files will be transferred.
*   `--shunt-account <phone_or_session_name>`: Optional. Specifies which configured Telegram account to use for the shunting operation. If not provided, the first available active account from your configuration is typically used.

## Configuration (`spectra_config.json`)

File grouping behavior for Shunt Mode can be configured in your `spectra_config.json` file under the `grouping` key:

```json
{
  // ... other configurations ...
  "grouping": {
    "strategy": "filename",  // "none", "filename", or "time"
    "time_window_seconds": 300 // Time window in seconds for 'time' strategy (e.g., 300 for 5 minutes)
  },
  // ... other configurations ...
}
```

*   `strategy` (string): Defines the grouping method.
    *   `"none"` (default): No grouping.
    *   `"filename"`: Groups based on filename patterns.
    *   `"time"`: Groups based on time proximity and sender.
*   `time_window_seconds` (integer): Relevant only for the `"time"` strategy. Specifies the maximum time difference (in seconds) between messages from the same sender to be considered part of the same group.

## Usage Example

To shunt all files from `@old_archive_channel` to `@new_consolidated_archive`, using filename-based grouping, and specifying the account `my_worker_account`:

1.  Ensure your `spectra_config.json` has the desired grouping strategy (or rely on defaults):
    ```json
    "grouping": {
      "strategy": "filename"
    }
    ```
2.  Run the command:
    ```bash
    python -m tgarchive --shunt-from @old_archive_channel --shunt-to @new_consolidated_archive --shunt-account my_worker_account
    ```

Files will be fetched from the source, grouped according to the strategy, checked for duplicates against the destination (via the shared deduplication database), and then unique files/groups will be forwarded.

## Advanced Usage

### Running Long Shunt Operations

For extended shunt operations, it is highly recommended to use a terminal multiplexer like `screen` or `tmux` to ensure the process continues running even if your connection drops.

Example using `screen`:
1. Start a new screen session: `screen -S spectra_shunt_session`
2. Run the command: `python -m tgarchive --shunt-from @source --shunt-to @destination`
3. Detach from the session: Press `Ctrl+A` then `D`.
4. To reattach later: `screen -r spectra_shunt_session`

### Monitoring Progress

Shunt operations provide progress feedback through the console. For more detailed monitoring, check the database:

```bash
# Check forwarded messages table for shunt progress
sqlite3 spectra.sqlite3 "SELECT COUNT(*) FROM forwarded_messages WHERE operation_type='shunt';"
```

## Troubleshooting

### Common Issues

**Problem**: Shunt operation fails with "Account not authorized" error.

**Solution**: Ensure the account specified with `--shunt-account` has access to both source and destination channels. You may need to join the channels first using the TUI or CLI.

**Problem**: Files are not being grouped as expected.

**Solution**: Check your grouping strategy configuration. For filename-based grouping, ensure files follow consistent naming patterns. For time-based grouping, adjust `time_window_seconds` to match your file posting patterns.

**Problem**: Duplicate files are being transferred.

**Solution**: Verify that the deduplication database (`spectra.sqlite3`) is accessible and the `forwarded_messages` table exists. You may need to initialize the database first.

## Related Documentation

- [Forwarding Mode Guide](FORWARDING_GUIDE.md) - For message forwarding operations
- [CLI Reference](../reference/CLI_REFERENCE.md) - Complete CLI command reference
- [Database Schema](../reference/DATABASE_SCHEMA.md) - Understanding the deduplication database
