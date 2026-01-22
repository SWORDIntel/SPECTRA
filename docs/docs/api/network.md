---
id: 'network'
title: 'Network Analysis'
sidebar_position: 4
description: 'Network relationship analysis'
tags: ['api', 'network', 'analysis', 'cli']
---

# Network Analysis

Analyze group relationships and identify high-value targets.

## Commands

### Analyze from Crawler Data

```bash
python -m tgarchive network --crawler-dir ./telegram-groups-crawler/ --plot
```

Analyzes network from crawler directory and generates plot.

### Analyze from Database

```bash
python -m tgarchive network --from-db --export priority_targets.json --top 50
```

Analyzes network from SQL database and exports priority targets.

## Options

- `--crawler-dir`: Analyze from crawler data directory
- `--from-db`: Analyze from SQL database
- `--plot`: Generate network visualization plot
- `--export`: Export results to JSON file
- `--top`: Number of top targets to include
