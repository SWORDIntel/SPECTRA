---
id: 'attribution-engine'
title: 'Attribution Engine'
sidebar_position: 7
description: 'Cross-platform identity correlation and behavioral analysis'
tags: ['attribution', 'identity', 'behavioral-analysis', 'features']
---

# Attribution Engine

Cross-platform identity correlation and behavioral analysis.

## Features

- Writing style analysis (stylometry)
- Vocabulary richness and sentence complexity
- Tool/technique fingerprinting (Metasploit, Cobalt Strike, etc.)
- Operational pattern matching (recon → exploit → post-exploit)
- AI-generated content detection
- Cross-account correlation
- Language proficiency assessment

## Usage

```python
from tgarchive.threat.attribution import AttributionEngine

engine = AttributionEngine()
profile = engine.analyze_writing_style(messages)
similar = engine.find_similar_actors_by_style(target_profile, candidates)
tools = engine.detect_tool_fingerprints(messages)
account_clusters = engine.correlate_accounts(profiles)
```
