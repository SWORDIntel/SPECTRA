# Temporal Analysis

## Overview

Temporal analysis detects activity patterns, timezone inference, burst detection, and campaign periodicity in threat actor behavior. This helps identify coordinated attacks, predict future activity, and infer geographic location.

## Activity Pattern Detection

### Peak Hours Analysis

Identifies when a threat actor is most active:

```python
patterns = temporal_analyzer.analyze_activity_patterns(user_id)

# Results:
{
    "peak_hours": [9, 10, 14, 15],  # Hours 0-23
    "peak_days": ["Monday", "Tuesday", "Wednesday"],
    "inferred_timezone": "UTC+3",
    "regularity_score": 8.5,  # 0-10 (higher = more regular)
    "active_days": 5,  # Days per week
    "total_messages": 1247
}
```

**Process:**
1. Query SQLite for all messages from user
2. Extract hour/day of week for each message
3. Count activity by hour/day
4. Identify peaks (statistical analysis)
5. Infer timezone from peak hours

### Timezone Inference

Infers actor's likely timezone from activity patterns:

```python
# If peak activity is 9-11 AM and 2-4 PM UTC
# And this pattern is consistent across days
# → Likely timezone: UTC+3 (Eastern Europe)
inferred_timezone = "UTC+3"
```

**Method:**
- Analyze peak hours distribution
- Match to known timezone patterns
- Consider consistency across days
- Confidence score based on regularity

## Burst Detection

### Coordinated Activity

Detects sudden spikes in activity (potential coordinated attacks):

```python
bursts = patterns["burst_periods"]

# Example:
[
    {
        "start": "2024-06-15T09:00:00Z",
        "end": "2024-06-15T11:30:00Z",
        "message_count": 47,
        "intensity": 9.2,  # 0-10 (higher = more intense)
        "anomaly_score": 0.95  # Statistical anomaly
    }
]
```

**Detection Method:**
1. Calculate message rate (messages per hour)
2. Identify periods with rate > 3x normal
3. Check for multiple actors active simultaneously
4. Flag as potential coordinated campaign

### Campaign Periodicity

Detects recurring patterns (weekly, monthly campaigns):

```python
periodicity = temporal_analyzer.detect_periodicity(user_id)

# Results:
{
    "pattern": "weekly",
    "peak_day": "Monday",
    "confidence": 0.87,
    "next_predicted_activity": "2024-06-22T09:00:00Z"
}
```

## Activity Prediction

### Next Activity Forecast

Predicts when actor will be active next:

```python
prediction = temporal_analyzer.predict_next_activity(user_id)

# Results:
{
    "likely_active_hours": [9, 10, 14, 15],
    "confidence": 0.82,  # 0-1
    "next_24h_probability": 0.75,
    "next_72h_probability": 0.95
}
```

**Method:**
- Time series analysis of historical patterns
- Seasonal decomposition (daily, weekly patterns)
- Probability distribution over next 24-72 hours
- Confidence based on pattern regularity

## Database Schema

### Temporal Data Storage

```sql
-- Activity patterns table
CREATE TABLE user_activity_patterns (
    user_id INTEGER PRIMARY KEY,
    peak_hours TEXT,  -- JSON array [9, 10, 14, 15]
    peak_days TEXT,   -- JSON array ["Monday", "Tuesday"]
    inferred_timezone TEXT,
    regularity_score REAL,
    last_analyzed TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- Burst periods table
CREATE TABLE burst_periods (
    id INTEGER PRIMARY KEY,
    user_id INTEGER,
    start_time TEXT,
    end_time TEXT,
    message_count INTEGER,
    intensity REAL,
    anomaly_score REAL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- Activity predictions table
CREATE TABLE activity_predictions (
    user_id INTEGER PRIMARY KEY,
    next_24h_probability REAL,
    next_72h_probability REAL,
    likely_active_hours TEXT,  -- JSON array
    confidence REAL,
    predicted_at TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id)
);
```

## Integration with Archiving

### Automatic Analysis

When `advanced_features.threat_analysis.temporal_analysis` is enabled:

1. **Message Archived** → User activity tracked
2. **Batch Analysis** → After N messages (configurable, default: 10)
3. **Pattern Detection** → Analyze activity patterns
4. **Burst Detection** → Identify coordinated activity
5. **Results Stored** → SQLite `user_activity_patterns` table

### Real-Time Monitoring

```python
# During archiving
if config["advanced_features"]["threat_analysis"]["temporal_analysis"]:
    # Track message activity
    temporal_analyzer.track_message(user_id, message_date)
    
    # Analyze if threshold reached
    if message_count >= min_messages_for_analysis:
        patterns = temporal_analyzer.analyze_activity_patterns(user_id)
        store_patterns(user_id, patterns)
```

## Query Patterns

### Find Active Actors

```sql
-- Find actors active during specific hours
SELECT user_id, peak_hours
FROM user_activity_patterns
WHERE peak_hours LIKE '%9%'  -- Active at 9 AM
AND regularity_score >= 7.0;
```

### Detect Coordinated Campaigns

```sql
-- Find bursts with multiple actors
SELECT bp1.user_id, bp2.user_id, bp1.start_time
FROM burst_periods bp1
JOIN burst_periods bp2 ON bp1.start_time = bp2.start_time
WHERE bp1.user_id != bp2.user_id
AND bp1.intensity >= 8.0
AND bp2.intensity >= 8.0;
```

## Configuration

```json
{
  "advanced_features": {
    "threat_analysis": {
      "temporal_analysis": true,
      "auto_analyze_users": true,
      "min_messages_for_analysis": 10,
      "burst_detection_threshold": 3.0,
      "timezone_inference": true
    }
  }
}
```

## Use Cases

### 1. Coordinated Attack Detection

Detect when multiple actors are active simultaneously:

```python
# Analyze burst periods
bursts = temporal_analyzer.detect_coordinated_campaigns([user1, user2, user3])

# Results show synchronized activity
# → Potential coordinated attack
```

### 2. Geographic Inference

Infer actor location from activity patterns:

```python
patterns = temporal_analyzer.analyze_activity_patterns(user_id)
timezone = patterns["inferred_timezone"]

# Map timezone to likely countries
# UTC+3 → Eastern Europe (Russia, Turkey, etc.)
```

### 3. Activity Prediction

Predict when actor will be active:

```python
prediction = temporal_analyzer.predict_next_activity(user_id)

# Schedule monitoring during predicted hours
# → More efficient resource allocation
```

## Performance Characteristics

### Analysis Performance

- **Pattern Detection**: ~100-500ms per user (depends on message count)
- **Burst Detection**: ~50-200ms per time period
- **Prediction**: ~10-50ms (uses cached patterns)

### Storage Requirements

- **Per User**: ~1-2 KB (activity patterns)
- **Burst Periods**: ~100 bytes per burst
- **10K Users**: ~10-20 MB total

## Troubleshooting

### No Patterns Detected

- **Check Message Count**: Need minimum messages (default: 10)
- **Verify Date Format**: Ensure proper timestamp parsing
- **Check Timezone**: Verify timezone handling

### Inaccurate Predictions

- **Increase Sample Size**: More messages = better patterns
- **Check Regularity**: Low regularity = lower confidence
- **Verify Timezone**: Incorrect timezone affects predictions
