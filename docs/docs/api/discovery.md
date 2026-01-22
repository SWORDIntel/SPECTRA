---
id: 'discovery'
title: 'Discovery Commands'
sidebar_position: 3
description: 'Network discovery and group finding'
tags: ['api', 'discovery', 'cli']
---

# Discovery Mode

Discover groups and channels from seed entities.

## Commands

### Discover from Seed

```bash
python -m tgarchive discover --seed @example_channel --depth 2
```

Discovers groups from a single seed entity.

### Discover from File

```bash
python -m tgarchive discover --seeds-file seeds.txt --depth 2 --export discovered.txt
```

Discovers groups from multiple seeds listed in a file.

### Import Crawler Data

```bash
python -m tgarchive discover --crawler-dir ./telegram-groups-crawler/
```

Imports existing scan data from a crawler directory.

## Options

- `--seed`: Single channel/group to start discovery from
- `--seeds-file`: File containing list of seed channels
- `--depth`: How many hops to explore (default: 2)
- `--export`: Export discovered groups to file
- `--crawler-dir`: Import from existing crawler data
