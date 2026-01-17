# SPECTRA Targeting - Quick Start Guide

## 🚀 Quick Launch Options

### Option 1: CLI (Fastest)
```bash
# Archive a channel
python -m tgarchive archive --entity @channel_name

# Discover from seed
python -m tgarchive discover --seed @seed_channel

# Forward messages
python -m tgarchive forward --origin @source --destination @dest
```

### Option 2: TUI (Interactive)
```bash
python -m tgarchive tui
```
Then navigate menus to select targets.

### Option 3: Config File (Persistent)
Edit `spectra_config.json`:
```json
{
  "entity": "@default_channel",
  "default_forwarding_destination_id": "@default_dest"
}
```

---

## 📋 Target Format Reference

| Format | Example | Use Case |
|--------|---------|----------|
| **Channel ID** | `123456789` | Most reliable, works always |
| **Username** | `@channel_name` | Human-readable, easy to type |
| **Invite Link** | `https://t.me/joinchat/ABC123` | For private channels |

---

## 🎯 Common Targeting Scenarios

### Scenario 1: Archive Single Channel
```bash
python -m tgarchive archive --entity @target_channel
```

### Scenario 2: Discover Network
```bash
# Start from seed channel
python -m tgarchive discover --seed @seed_channel --depth 2

# Or use TUI for interactive selection
python -m tgarchive tui
# Select: [2] Discover Groups
# Enter: @seed_channel
```

### Scenario 3: Forward Messages
```bash
# Forward from source to destination
python -m tgarchive forward \
    --origin @source_channel \
    --destination @dest_channel
```

### Scenario 4: OSINT Investigation
```bash
# Add target user
python -m tgarchive osint add-target --user @target_user

# Scan channel for target
python -m tgarchive osint scan \
    --channel @investigation_channel \
    --user @target_user
```

### Scenario 5: Batch Operations
```bash
# Archive multiple channels from file
python -m tgarchive batch archive --file channels.txt

# Parallel discovery
python -m tgarchive parallel discover \
    --seeds-file seeds.txt \
    --depth 2
```

---

## 🔍 TUI Targeting Flow (Step-by-Step)

### Archive Channel via TUI

1. **Launch TUI**
   ```bash
   python -m tgarchive tui
   ```

2. **Main Menu** → Press `1` (Archive Channel)

3. **Target Input Screen**
   ```
   Enter target: [@channel_name or 123456789]
   ```

4. **Options Screen**
   - [X] Download media
   - [X] Download avatars
   - [ ] Archive topics

5. **Start** → Press `Enter`

### Discover Groups via TUI

1. **Main Menu** → Press `2` (Discover Groups)

2. **Seed Input**
   ```
   Starting point: [@seed_channel]
   ```

3. **Discovery Options**
   - Max depth: `[3]`
   - Max targets: `[100]`
   - [X] Auto-invite accounts

4. **Start** → Press `Enter`

### Forward Messages via TUI

1. **Main Menu** → Press `4` (Forward Messages)

2. **Origin Channel**
   ```
   Origin: [@source_channel]
   ```

3. **Destination Channel**
   ```
   Destination: [@dest_channel]
   ```

4. **Options**
   - [X] Enable deduplication
   - [ ] Prepend origin info

5. **Start** → Press `Enter`

---

## ⚙️ Configuration File Targeting

### Setting Defaults

Edit `spectra_config.json`:

```json
{
  "entity": "@default_channel",
  "default_forwarding_destination_id": "@default_dest",
  "forwarding": {
    "enable_deduplication": true,
    "always_prepend_origin_info": false
  }
}
```

### Using Config Defaults

```bash
# Uses "entity" from config
python -m tgarchive archive

# Uses "default_forwarding_destination_id" from config
python -m tgarchive forward --origin @source
```

---

## 🛠️ Troubleshooting

### "Entity not found"
- ✅ Check spelling of username
- ✅ Try using channel ID instead
- ✅ Verify account has access

### "Access denied"
- ✅ Run: `python -m tgarchive channels update-access`
- ✅ Check account is member of channel
- ✅ Verify session is valid

### "Invalid format"
- ✅ Use: ID (integer), username (@name), or invite link
- ✅ Check for typos

---

## 📚 Full Documentation

See `UX_TARGETING_WALKTHROUGH.md` for complete details.
