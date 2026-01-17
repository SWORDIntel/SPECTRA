# SPECTRA Targeting Parameters - UX Walkthrough

## Overview

This document walks through the user experience for setting targeting parameters when launching SPECTRA. Targeting parameters determine which channels, users, or entities SPECTRA will operate on.

## Launch Methods

SPECTRA can be launched in three ways:
1. **Command Line Interface (CLI)** - Direct commands with parameters
2. **Terminal User Interface (TUI)** - Interactive menu-driven interface
3. **Configuration File** - Persistent settings in `spectra_config.json`

---

## Method 1: Command Line Interface (CLI)

### Basic Launch

```bash
python -m tgarchive <command> [options]
```

### Setting Targets via CLI

#### Archive a Specific Channel

```bash
# By channel ID
python -m tgarchive archive --entity 123456789

# By username
python -m tgarchive archive --entity @channel_username

# By invite link
python -m tgarchive archive --entity https://t.me/joinchat/ABC123
```

#### Discovery with Targeting

```bash
# Discover from specific starting points
python -m tgarchive discover --entity @starting_channel

# Network analysis with priority targets
python -m tgarchive network --top 10
```

#### Forwarding with Targets

```bash
# Forward from origin to destination
python -m tgarchive forward \
    --origin @source_channel \
    --destination @dest_channel
```

#### OSINT Targeting

```bash
# Add a target user
python -m tgarchive osint add-target --user @target_username --notes "Person of interest"

# Scan channel for target interactions
python -m tgarchive osint scan --channel @channel_name --user @target_username
```

### CLI Targeting Parameters

| Parameter | Command | Description |
|-----------|---------|-------------|
| `--entity` | `archive`, `discover` | Target channel/group ID, username, or invite link |
| `--origin` | `forward` | Source channel for forwarding |
| `--destination` | `forward` | Destination channel for forwarding |
| `--channel-id` | `channels forward` | Specific channel ID (integer) |
| `--user` | `osint` | Target username for OSINT operations |
| `--server-id` | `download-users` | Server/channel ID to download users from |

---

## Method 2: Terminal User Interface (TUI)

### Launching TUI

```bash
python -m tgarchive tui
```

### TUI Targeting Flow

#### Step 1: Main Menu
```
┌─────────────────────────────────────────┐
│  SPECTRA Main Menu                      │
├─────────────────────────────────────────┤
│  [1] Archive Channel                    │
│  [2] Discover Groups                    │
│  [3] Network Analysis                   │
│  [4] Forward Messages                   │
│  [5] OSINT Operations                   │
│  [6] Channel Management                 │
│  [7] Configuration                     │
│  [Q] Quit                               │
└─────────────────────────────────────────┘
```

#### Step 2: Select Operation
- Press number key or navigate with arrow keys
- Example: Press `1` for Archive Channel

#### Step 3: Target Selection Screen

**For Archive Channel:**
```
┌─────────────────────────────────────────┐
│  Archive Channel                        │
├─────────────────────────────────────────┤
│  Enter target:                          │
│  ┌───────────────────────────────────┐ │
│  │ @channel_name or 123456789        │ │
│  └───────────────────────────────────┘ │
│                                         │
│  Options:                               │
│  [ ] Download media                     │
│  [ ] Download avatars                   │
│  [ ] Archive topics                     │
│                                         │
│  [Enter] Start Archive                  │
│  [Esc]   Cancel                         │
└─────────────────────────────────────────┘
```

**For Discovery:**
```
┌─────────────────────────────────────────┐
│  Discover Groups                        │
├─────────────────────────────────────────┤
│  Starting point:                         │
│  ┌───────────────────────────────────┐ │
│  │ @seed_channel                     │ │
│  └───────────────────────────────────┘ │
│                                         │
│  Discovery options:                     │
│  [ ] Auto-invite accounts               │
│  [ ] Parallel discovery                 │
│  [ ] Network analysis                   │
│                                         │
│  Max depth: [3]                         │
│  Max targets: [100]                     │
│                                         │
│  [Enter] Start Discovery                │
│  [Esc]   Cancel                         │
└─────────────────────────────────────────┘
```

**For Forwarding:**
```
┌─────────────────────────────────────────┐
│  Forward Messages                       │
├─────────────────────────────────────────┤
│  Origin Channel:                        │
│  ┌───────────────────────────────────┐ │
│  │ @source_channel                    │ │
│  └───────────────────────────────────┘ │
│                                         │
│  Destination Channel:                   │
│  ┌───────────────────────────────────┐ │
│  │ @dest_channel (or use default)     │ │
│  └───────────────────────────────────┘ │
│                                         │
│  Options:                               │
│  [ ] Enable deduplication               │
│  [ ] Prepend origin info                │
│                                         │
│  [Enter] Start Forwarding               │
│  [Esc]   Cancel                         │
└─────────────────────────────────────────┘
```

#### Step 4: Channel Selection (Alternative)

If you select "Channel Management" from main menu:

```
┌─────────────────────────────────────────┐
│  Channel Management                     │
├─────────────────────────────────────────┤
│  Available Channels:                    │
│  ┌───────────────────────────────────┐ │
│  │ > @channel1 (ID: 123456)         │ │
│  │   @channel2 (ID: 789012)         │ │
│  │   @channel3 (ID: 345678)         │ │
│  │   ...                             │ │
│  └───────────────────────────────────┘ │
│                                         │
│  [Enter] Select Channel                 │
│  [A]     Archive Selected               │
│  [F]     Forward from Selected          │
│  [D]     Discover from Selected         │
│  [Esc]   Back                           │
└─────────────────────────────────────────┘
```

---

## Method 3: Configuration File

### Location
- Default: `spectra_config.json` in current directory
- Custom: `--config /path/to/config.json`

### Setting Default Targets

Edit `spectra_config.json`:

```json
{
  "api_id": 123456,
  "api_hash": "your_api_hash",
  "accounts": [
    {
      "api_id": 123456,
      "api_hash": "your_api_hash",
      "session_name": "spectra_1"
    }
  ],
  "entity": "@default_channel",
  "default_forwarding_destination_id": "@default_dest",
  "forwarding": {
    "enable_deduplication": true,
    "secondary_unique_destination": null,
    "always_prepend_origin_info": false
  },
  "cloud": {
    "auto_invite_accounts": true,
    "invitation_delays": {
      "min_seconds": 120,
      "max_seconds": 600,
      "variance": 0.3
    }
  }
}
```

### Configuration Targeting Fields

| Field | Description | Example |
|-------|-------------|---------|
| `entity` | Default channel/group to operate on | `"@channel"` or `123456789` |
| `default_forwarding_destination_id` | Default destination for forwarding | `"@dest_channel"` |
| `accounts[].session_name` | Account sessions (affects access) | `"spectra_1"` |

---

## Targeting Parameter Formats

### Accepted Formats

1. **Channel ID** (Integer)
   - `123456789`
   - `-1001234567890` (supergroup)

2. **Username** (String)
   - `@channel_name`
   - `channel_name` (without @)

3. **Invite Link** (URL)
   - `https://t.me/joinchat/ABC123`
   - `https://t.me/+ABC123def456`

4. **User ID** (Integer)
   - `123456789` (for user operations)

### Validation

SPECTRA validates targeting parameters:
- Checks if entity exists and is accessible
- Verifies account permissions
- Validates format (ID vs username vs link)

---

## Complete Workflow Examples

### Example 1: Archive a Channel (CLI)

```bash
# Step 1: Launch with target
python -m tgarchive archive --entity @target_channel

# Step 2: Program validates access
# Step 3: Shows channel info
# Step 4: Starts archiving
```

### Example 2: Discover Network (TUI)

```
1. Launch: python -m tgarchive tui
2. Select: [2] Discover Groups
3. Enter: @seed_channel
4. Configure: Max depth = 3, Max targets = 50
5. Start: Press Enter
6. Monitor: Progress shown in status window
```

### Example 3: Forward with Targeting (CLI)

```bash
# Forward from source to destination
python -m tgarchive forward \
    --origin @source_channel \
    --destination @dest_channel \
    --enable-deduplication
```

### Example 4: OSINT Target Investigation (TUI)

```
1. Launch: python -m tgarchive tui
2. Select: [5] OSINT Operations
3. Select: [1] Add Target
4. Enter: Username: @target_user
5. Enter: Notes: "Person of interest"
6. Select: [2] Scan Channel
7. Enter: Channel: @investigation_channel
8. Enter: Target: @target_user
9. View: Results show interactions
```

---

## Advanced Targeting

### Batch Operations

```bash
# Archive multiple channels
python -m tgarchive batch archive \
    --channels @channel1 @channel2 @channel3

# Parallel discovery from multiple seeds
python -m tgarchive parallel discover \
    --entities @seed1 @seed2 @seed3 \
    --max-depth 2
```

### Priority Targets

```bash
# Get priority targets from network analysis
python -m tgarchive network --top 10 --export targets.json

# Use exported targets
python -m tgarchive batch archive --targets-file targets.json
```

### Channel Access Management

```bash
# Populate channel access for accounts
python -m tgarchive channels populate-access

# List accessible channels
python -m tgarchive channels list
```

---

## Troubleshooting

### Common Issues

1. **"Entity not found"**
   - Check if channel/username is correct
   - Verify account has access
   - Try using channel ID instead of username

2. **"Access denied"**
   - Account may not be member of channel
   - Use `channels populate-access` to refresh
   - Check account permissions

3. **"Invalid format"**
   - Use correct format: ID (integer), username (@name), or invite link
   - Check for typos in username

### Getting Help

```bash
# Show command help
python -m tgarchive <command> --help

# Example
python -m tgarchive archive --help
python -m tgarchive forward --help
```

---

## Summary

**Quick Reference:**

| Method | Use Case | Command |
|--------|----------|---------|
| CLI | Quick operations, scripting | `python -m tgarchive archive --entity @channel` |
| TUI | Interactive exploration | `python -m tgarchive tui` |
| Config | Persistent defaults | Edit `spectra_config.json` |

**Target Formats:**
- Channel ID: `123456789`
- Username: `@channel_name`
- Invite Link: `https://t.me/joinchat/ABC123`

**Most Common Workflow:**
1. Launch TUI: `python -m tgarchive tui`
2. Select operation (Archive/Discover/Forward)
3. Enter target in format prompt
4. Configure options
5. Start operation
