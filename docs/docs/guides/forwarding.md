---
id: forwarding
title: Forwarding Guide
sidebar_position: 2
description: Message forwarding and deduplication features
tags: [forwarding, deduplication, messages]
---

# Forwarding Guide

SPECTRA includes powerful features for forwarding messages with attachments from origin channels/chats to a specified destination, or even to the "Saved Messages" of multiple configured accounts. This can be useful for consolidating information, creating backups, or distributing content.

## Forwarding Modes

### 1. Selective Forwarding

Forward messages from a specific origin to a specific destination.

```bash
python -m tgarchive forward --origin <origin_id_or_username> --destination <destination_id_or_username>
```

### 2. Total Forward Mode

Forward messages from all channels accessible by your configured accounts (as listed in the `account_channel_access` table) to a specific destination. This mode requires the channel access table to be populated first.

```bash
python -m tgarchive forward --total-mode [--destination <destination_id_or_username>]
```

To populate the `account_channel_access` table, run:

```bash
python -m tgarchive channels --update-access
```

## Forwarding Command Details

The main command for forwarding is `python -m tgarchive forward` with the following options:

- `--origin <id_or_username>`: Specifies the source channel or chat from which to forward messages. This is required unless `--total-mode` is used.
- `--destination <id_or_username>`: Specifies the target channel or chat to which messages will be forwarded. If not provided, SPECTRA will use the `default_forwarding_destination_id` set in your `spectra_config.json` file.
- `--account <phone_or_session_name>`: Specifies which configured Telegram account to use for the forwarding operation. If not provided, the first account in your configuration is typically used. For "Total Forward Mode", this account is used for orchestration, while individual channel forwarding uses an account known to have access to that specific channel (from the `account_channel_access` table).
- `--total-mode`: Enables "Total Forward Mode". When this flag is used, the `--origin` argument is ignored, and SPECTRA will attempt to forward messages from all channels recorded in the `account_channel_access` database table.
- `--forward-to-all-saved`: When enabled, messages successfully forwarded to the main destination will *also* be forwarded to the "Saved Messages" of *every account* configured in `spectra_config.json`. This can be useful for creating broad personal backups but will significantly increase API calls and data redundancy. Use with caution.
- `--copy-into-destination`: Re-posts messages using the signed-in account so they appear native in the destination (no `Forwarded from` banner). Omit this flag to preserve the original sender/forward headers from the origin.
- `--prepend-origin-info`: If enabled, and if not using topic-based forwarding (see below), information about the original channel (e.g., "[Forwarded from OriginalChannelName (ID: 12345)]") will be prepended to the text of the forwarded message. This helps in identifying the source of messages when they are consolidated into a general channel.

## Enhanced Forwarding & Deduplication

SPECTRA now includes advanced capabilities for message deduplication during forwarding and an automated account invitation system for channels discovered in Forwarding Mode.

### Deduplication Forwarding

To prevent redundant information and save on API calls, SPECTRA's forwarding mechanism can now detect and skip messages that have already been processed and forwarded.

**Overview:**

*   When enabled, SPECTRA computes a unique hash for each message's content (text and media attributes) before forwarding.
*   These hashes are stored in the local database (`spectra.sqlite3` in a table named `forwarded_messages`).
*   If a message's hash is already found in the database or an in-memory cache for the current session, it's considered a duplicate and will not be forwarded to the primary destination.
*   Unique messages can optionally be routed to a secondary, specified channel, ensuring this channel only receives content not seen before.

**Configuration (`spectra_config.json`):**

Add or modify the `forwarding` section in your `spectra_config.json`:

```json
{
  "forwarding": {
    "enable_deduplication": true,
    "secondary_unique_destination": "@your_unique_content_channel"
  }
  // ... other forwarding settings ...
}
```

*   `enable_deduplication` (boolean): Set to `true` (default) to enable duplicate detection, `false` to disable.
*   `secondary_unique_destination` (string | null): Optional. The username or ID of a channel where unique messages (those not previously forwarded) will be sent. If `null` or not provided, unique messages are only sent to the primary destination.

**CLI Flags for `tgarchive forward`:**

*   `--enable-deduplication` / `--disable-deduplication`: Overrides the `enable_deduplication` setting from `spectra_config.json` for the current command.
    *   Example: `python -m tgarchive forward --origin @source --destination @main_dest --disable-deduplication`
*   `--secondary-unique-destination <channel_id_or_username>`: Specifies the secondary destination for unique messages, overriding the config for the current command.
    *   Example: `python -m tgarchive forward --origin @source --destination @main_dest --secondary-unique-destination @only_uniques_here`

**Usage Example:**

To forward messages from `@news_source` to `@my_archive`, skip duplicates, and send unique messages also to `@special_uniques`:

1.  Ensure your `spectra_config.json` has:
    ```json
    "forwarding": {
      "enable_deduplication": true,
      "secondary_unique_destination": "@special_uniques"
    }
    ```
2.  Run the command:
    ```bash
    python -m tgarchive forward --origin @news_source --destination @my_archive
    ```
    Or, using CLI overrides:
    ```bash
    python -m tgarchive forward --origin @news_source --destination @my_archive --enable-deduplication --secondary-unique-destination @special_uniques
    ```

### Forwarding Mode: Automated Account Invitations

When operating in Forwarding Mode, SPECTRA can now automatically invite other configured accounts to join newly discovered and accessible public channels. This helps distribute channel membership across your available accounts.

**Overview:**

*   After the primary Forwarding Mode account successfully accesses/joins a new channel, that channel is added to an invitation queue.
*   Other accounts configured in `spectra_config.json` (excluding the primary Forwarding Mode account) will be gradually invited to join these queued channels.
*   Invitations are processed with randomized delays to simulate natural user behavior and respect Telegram's rate limits.
*   The system tracks successful and failed invitations in a state file (`invitation_state.json` in your forward output directory) to avoid re-processing and to allow resumability.

**Configuration (`spectra_config.json`):**

Add or modify the `forwarding` section in your `spectra_config.json`:

```json
{
  "forwarding": {
    "auto_invite_accounts": true,
    "invitation_delays": {
      "min_seconds": 120,
      "max_seconds": 600,
      "variance": 0.3
    }
  }
  // ... other forwarding settings ...
}
```

*   `auto_invite_accounts` (boolean): Set to `true` (default) to enable this feature, `false` to disable.
*   `invitation_delays`: An object defining the timing for invitations:
    *   `min_seconds` (integer): Minimum base delay before an invitation attempt.
    *   `max_seconds` (integer): Maximum base delay.
    *   `variance` (float, 0.0 to 1.0): Percentage of random variance applied to the base delay. For example, 0.3 means +/- 30%.

**CLI Flags for `tgarchive forward`:**

*   `--enable-auto-invites` / `--disable-auto-invites`: Overrides the `auto_invite_accounts` setting from `spectra_config.json` for the current forward session.
    *   Example: `python -m tgarchive forward --channels-file seeds.txt --output-dir ./forward_out --disable-auto-invites`

**Usage Example:**

To run Forwarding Mode, discover channels, and have your other accounts automatically invited:

1.  Ensure your `spectra_config.json` has multiple accounts configured and the `forwarding` section is set up (or use defaults):
    ```json
    "accounts": [
      {"session_name": "main_forward_acc", "api_id": 123, "api_hash": "abc"},
      {"session_name": "invitee_acc1", "api_id": 456, "api_hash": "def"},
      {"session_name": "invitee_acc2", "api_id": 789, "api_hash": "ghi"}
    ],
    "forwarding": {
      "auto_invite_accounts": true
    }
    ```
2.  Run the Forwarding Mode command (the first account, `main_forward_acc`, will be used for discovery):
    ```bash
    python -m tgarchive forward --channels-file initial_seeds.txt --output-dir ./my_forward_data
    ```
    As `main_forward_acc` discovers and joins new channels, `invitee_acc1` and `invitee_acc2` will be queued and then invited to join them after randomized delays.

## Related Configuration and Utility Commands

### Setting Default Destination

```bash
python -m tgarchive config --set-forward-dest <destination_id_or_username>
```

This command updates the `default_forwarding_destination_id` in your `spectra_config.json`.

### Viewing Default Destination

```bash
python -m tgarchive config --view-forward-dest
```

### Updating Channel Access Data (for Total Mode)

```bash
python -m tgarchive channels --update-access
```

This command populates the `account_channel_access` table in the database by iterating through all your configured accounts and listing the channels each can access. This table is crucial for the `--total-mode` forwarding feature.

## Configuration for Forwarding

*   **`default_forwarding_destination_id`**: Located in `spectra_config.json`, this key (added manually or via the `config --set-forward-dest` command) allows you to set a global default destination for forwarding operations, so you don't have to specify `--destination` every time.
*   **Supergroup Topic Sorting (Conceptual):**
    Telegram's "Topics" feature in supergroups allows for organized discussions. SPECTRA's forwarding can conceptually support sending messages into specific topics. This is typically done by forwarding a message as a *reply* to the message that represents the topic's creation or its main "general" topic message.
    If you manually identify the message ID for a specific topic in the destination supergroup, this ID could be used (currently via code modification or future enhancement as `destination_topic_id` in the `AttachmentForwarder`) with the `reply_to` parameter in Telegram's API when forwarding.
    Currently, SPECTRA does **not** automatically create or manage topics by name due to limitations with user accounts (topic creation/management often requires bot privileges or specific admin rights).
    The `--prepend-origin-info` flag is the primary method for distinguishing messages from different origins when forwarded to a common, non-topic-based channel.

## "Forward to All Saved Messages" Feature

Enabling `--forward-to-all-saved` provides a way to create a distributed backup or personal archive of forwarded content across all your configured Telegram accounts. Each message successfully forwarded to the main destination will also be sent to the "Saved Messages" chat of each account.

**Implications:**

*   **Increased API Usage:** This feature will make significantly more API calls (one forward per account for each original message). Be mindful of Telegram's rate limits. The system has built-in handling for `FloodWaitError` (rate limit exceeded) and will pause as instructed by Telegram, but excessive use could still lead to temporary restrictions on accounts.
*   **Data Redundancy:** You will have multiple copies of the forwarded messages across your accounts.
*   **Sequential Operation:** Forwarding to each account's "Saved Messages" happens sequentially for each original message to manage client connections and reduce simultaneous API load from this specific feature.

## Database and `account_channel_access` Table

The "Total Forward Mode" (`--total-mode`) relies on the `account_channel_access` table in the SPECTRA database. This table stores a record of which channels are accessible by which of your configured accounts, including their names and access hashes. It is populated by the `tgarchive channels --update-access` command.

For more details on the database schema, please refer to the [Database Schema](../reference/database-schema.md) documentation.
