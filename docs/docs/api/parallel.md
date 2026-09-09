---
id: 'parallel'
title: 'Parallel Processing'
sidebar_position: 7
description: 'Parallel operations using multiple accounts'
tags: ['api', 'parallel', 'cli']
---

# Parallel Processing

Leverage multiple Telegram accounts and proxies simultaneously.

## Commands

### Parallel Discovery

```bash
python -m tgarchive parallel discover --seeds-file seeds.txt --depth 2 --max-workers 4
```

Runs discovery in parallel across multiple accounts.

### Parallel Join

```bash
python -m tgarchive parallel join --file groups.txt --max-workers 4
```

Joins multiple groups in parallel.

### Parallel Archive

```bash
python -m tgarchive parallel archive --file entities.txt --max-workers 4
```

Archives multiple entities in parallel.

### Parallel Archive from DB

```bash
python -m tgarchive parallel archive --from-db --limit 20 --min-priority 0.1
```

Archives high-priority entities from database in parallel.

## Options

- `--max-workers`: Number of parallel workers (default: 4)
- `--file`: File containing list of entities
- `--from-db`: Process from database
- `--limit`: Maximum number of entities
- `--min-priority`: Minimum priority threshold
