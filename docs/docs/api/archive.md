---
id: 'archive'
title: 'Archive Commands'
sidebar_position: 5
description: 'Message and media archiving'
tags: ['api', 'archive', 'cli']
---

# Archive Mode

Archive messages and media from Telegram channels and groups.

## Commands

### Archive Channel

```bash
python -m tgarchive archive --entity @example_channel
```

Archives all messages and media from a specific channel or group.

## Options

- `--entity`: Channel/group username or ID to archive
- `--date-range`: Optional date range filter
- `--media-only`: Archive only media files
- `--text-only`: Archive only text messages
