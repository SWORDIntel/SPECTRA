---
id: 'temporal-analysis'
title: 'Temporal Analysis'
sidebar_position: 6
description: 'Time-based pattern analysis and prediction'
tags: ['temporal', 'analysis', 'prediction', 'features']
---

# Temporal Analysis & Prediction

Analyze time-based patterns in threat actor behavior.

## Capabilities

- Activity timeline analysis with burst detection
- Timezone inference from peak activity hours
- Sleep pattern analysis for geolocation
- Campaign periodicity detection
- Predictive activity forecasting
- Coordinated campaign detection

## Usage

```python
from tgarchive.threat.temporal import TemporalAnalyzer

analyzer = TemporalAnalyzer()
patterns = analyzer.analyze_activity_patterns(messages)
campaigns = analyzer.detect_coordinated_campaigns(actor_messages)
prediction = analyzer.predict_next_activity(messages, forecast_hours=24)
```
