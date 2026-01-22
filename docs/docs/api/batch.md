---
id: 'batch'
title: 'Batch Operations'
sidebar_position: 6
description: 'Batch processing of multiple groups'
tags: ['api', 'batch', 'cli']
---

# Batch Operations

Process multiple groups from a file or database.

## Commands

### Process from File

```bash
python -m tgarchive batch --file groups.txt --delay 30
```

Processes multiple groups listed in a file with delay between operations.

### Process from Database

```bash
python -m tgarchive batch --from-db --limit 20 --min-priority 0.1
```

Processes high-priority groups from the database.

## Options

- `--file`: File containing list of groups to process
- `--from-db`: Process groups from database
- `--delay`: Delay in seconds between operations
- `--limit`: Maximum number of groups to process
- `--min-priority`: Minimum priority score threshold
