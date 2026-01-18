# Attribution Engine

## Overview

The Attribution Engine performs cross-platform identity correlation through writing style analysis, tool fingerprinting, and operational pattern matching. This helps identify the same actor across multiple accounts or platforms.

## Writing Style Analysis

### Stylometric Features

Analyzes linguistic patterns unique to each author:

```python
profile = attribution_engine.analyze_writing_style(user_id)

# Results:
{
    "vocabulary_size": 1247,  # Unique words
    "avg_sentence_length": 12.5,  # Words per sentence
    "technical_density": 0.34,  # Technical terms / total words
    "proficiency_level": "advanced",  # beginner/intermediate/advanced
    "language": "en",  # ISO 639-1 code
    "punctuation_profile": {
        "periods": 0.45,
        "commas": 0.32,
        "exclamation": 0.08,
        "question_marks": 0.15
    },
    "emoji_usage": 0.12,  # Emojis per message
    "capitalization_style": "mixed"  # all_lower/mixed/proper_case
}
```

**Features Analyzed:**
- Vocabulary richness (unique words)
- Sentence structure (length, complexity)
- Punctuation patterns
- Technical jargon density
- Language proficiency
- Emoji usage
- Capitalization style

### Similarity Matching

Find actors with similar writing styles:

```python
similar_actors = attribution_engine.find_similar_actors_by_style(
    user_id=1001,
    threshold=0.85
)

# Results:
[
    (user_id=2005, similarity=0.92),  # Very similar
    (user_id=3001, similarity=0.87),  # Similar
    (user_id=4002, similarity=0.85)   # Threshold match
]
```

**Use Cases:**
- Same person with multiple accounts
- Coordinated group with shared training
- AI-generated content detection

## Tool Fingerprinting

### Detected Tools

Identifies tools and frameworks used by actors:

```python
tools = attribution_engine.detect_tool_fingerprints(user_id)

# Results:
{
    "Metasploit": 12,  # 12 messages with Metasploit patterns
    "Cobalt Strike": 8,
    "PowerShell": 15,
    "Custom Tooling": 3
}
```

**Detection Methods:**
- Pattern matching (command syntax)
- Artifact analysis (file paths, registry keys)
- Behavioral signatures (execution patterns)

### Tool Patterns

```python
# Metasploit patterns
"use exploit/windows/smb/ms17_010_eternalblue"
"set LHOST 192.168.1.100"
"set LPORT 4444"
"exploit"

# Cobalt Strike patterns
"beacon> getuid"
"beacon> shell whoami"
"beacon> upload mimikatz.exe"
```

## Operational Pattern Detection

### Attack Chain Analysis

Detects multi-stage attack patterns:

```python
patterns = attribution_engine.detect_operational_patterns(user_id)

# Results:
{
    "reconnaissance": 15,  # Messages about recon
    "exploitation": 8,     # Messages about exploits
    "post_exploitation": 12,  # Messages about post-exploit
    "opsec_indicators": 3,  # OPSEC mistakes
    "attack_chains": [
        {
            "type": "lateral_movement",
            "stages": ["recon", "exploit", "privilege_escalation", "lateral"]
        }
    ]
}
```

### MITRE ATT&CK Mapping

Maps behavior to MITRE ATT&CK framework:

```python
ttps = attribution_engine.extract_ttps(user_id)

# Results:
[
    {
        "technique_id": "T1566.001",
        "technique_name": "Spearphishing Attachment",
        "tactic": "Initial Access",
        "confidence": 0.85,
        "evidence": [12345, 12346, 12347]
    },
    {
        "technique_id": "T1059.001",
        "technique_name": "PowerShell",
        "tactic": "Execution",
        "confidence": 0.92,
        "evidence": [12350, 12351]
    }
]
```

## AI-Generated Content Detection

### Detection Method

Identifies AI-generated content:

```python
ai_detect = attribution_engine.detect_ai_generated_content(user_id)

# Results:
{
    "ai_likelihood": 0.78,  # 0-1 (higher = more likely AI)
    "confidence": 0.85,
    "indicators": [
        "Unusually consistent sentence length",
        "Perfect grammar with no typos",
        "Lack of personal writing quirks",
        "Generic phrasing patterns"
    ]
}
```

**Indicators:**
- Unusually consistent sentence length
- Perfect grammar (no typos)
- Lack of personal writing quirks
- Generic phrasing patterns
- Repetitive structures

## Database Schema

### Attribution Data Storage

```sql
-- Writing style profiles
CREATE TABLE writing_style_profiles (
    user_id INTEGER PRIMARY KEY,
    vocabulary_size INTEGER,
    avg_sentence_length REAL,
    technical_density REAL,
    proficiency_level TEXT,
    language TEXT,
    punctuation_profile TEXT,  -- JSON
    emoji_usage REAL,
    last_analyzed TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- Tool fingerprints
CREATE TABLE tool_fingerprints (
    id INTEGER PRIMARY KEY,
    user_id INTEGER,
    tool_name TEXT,
    match_count INTEGER,
    first_detected TEXT,
    last_detected TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- Operational patterns
CREATE TABLE operational_patterns (
    user_id INTEGER PRIMARY KEY,
    reconnaissance_count INTEGER,
    exploitation_count INTEGER,
    post_exploitation_count INTEGER,
    opsec_indicators INTEGER,
    attack_chains TEXT,  -- JSON
    last_analyzed TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- Similar actors (cross-correlation)
CREATE TABLE similar_actors (
    user_id_1 INTEGER,
    user_id_2 INTEGER,
    similarity_score REAL,
    match_type TEXT,  -- "writing_style", "tool_fingerprint", "operational_pattern"
    detected_at TEXT,
    PRIMARY KEY (user_id_1, user_id_2),
    FOREIGN KEY (user_id_1) REFERENCES users(id),
    FOREIGN KEY (user_id_2) REFERENCES users(id)
);
```

## Integration with Archiving

### Automatic Analysis

When `advanced_features.threat_analysis.attribution_engine` is enabled:

1. **Message Archived** → User messages tracked
2. **Batch Analysis** → After N messages (configurable, default: 10)
3. **Style Analysis** → Writing style profiled
4. **Tool Detection** → Tools identified
5. **Pattern Detection** → Operational patterns extracted
6. **Cross-Correlation** → Similar actors identified
7. **Results Stored** → SQLite attribution tables

### Real-Time Correlation

```python
# During archiving
if config["advanced_features"]["threat_analysis"]["attribution_engine"]:
    # Analyze writing style
    profile = attribution_engine.analyze_writing_style(user_id)
    store_writing_style(user_id, profile)
    
    # Detect tools
    tools = attribution_engine.detect_tool_fingerprints(user_id)
    store_tool_fingerprints(user_id, tools)
    
    # Find similar actors
    similar = attribution_engine.find_similar_actors_by_style(user_id)
    store_similar_actors(user_id, similar)
```

## Query Patterns

### Find Similar Actors

```sql
-- Find actors with similar writing styles
SELECT sa.user_id_2, sa.similarity_score, wsp.vocabulary_size
FROM similar_actors sa
JOIN writing_style_profiles wsp ON sa.user_id_2 = wsp.user_id
WHERE sa.user_id_1 = 1001
AND sa.match_type = 'writing_style'
AND sa.similarity_score >= 0.85
ORDER BY sa.similarity_score DESC;
```

### Tool Usage Analysis

```sql
-- Find all actors using specific tool
SELECT DISTINCT user_id, match_count
FROM tool_fingerprints
WHERE tool_name = 'Metasploit'
ORDER BY match_count DESC;
```

### Attack Chain Detection

```sql
-- Find actors with specific attack patterns
SELECT user_id, attack_chains
FROM operational_patterns
WHERE attack_chains LIKE '%lateral_movement%'
AND post_exploitation_count >= 5;
```

## Configuration

```json
{
  "advanced_features": {
    "threat_analysis": {
      "attribution_engine": true,
      "auto_analyze_users": true,
      "min_messages_for_analysis": 10,
      "similarity_threshold": 0.85,
      "tool_detection": true,
      "ai_detection": true
    }
  }
}
```

## Use Cases

### 1. Cross-Account Correlation

Identify same actor across multiple accounts:

```python
# Analyze writing style
profile1 = attribution_engine.analyze_writing_style(user_id_1)
profile2 = attribution_engine.analyze_writing_style(user_id_2)

# Compare
similarity = compare_profiles(profile1, profile2)

if similarity >= 0.90:
    # Likely same person
    link_accounts(user_id_1, user_id_2)
```

### 2. Tool Attribution

Identify actor by tool usage:

```python
# Detect tools
tools1 = attribution_engine.detect_tool_fingerprints(user_id_1)
tools2 = attribution_engine.detect_tool_fingerprints(user_id_2)

# Compare
if tools1 == tools2:
    # Same toolset → possible same actor
    correlate_by_tools(user_id_1, user_id_2)
```

### 3. AI Content Detection

Detect AI-generated threat intelligence:

```python
# Detect AI content
ai_detect = attribution_engine.detect_ai_generated_content(user_id)

if ai_detect["ai_likelihood"] >= 0.80:
    # Flag as potentially AI-generated
    flag_ai_content(user_id, ai_detect)
```

## Performance Characteristics

### Analysis Performance

- **Writing Style**: ~200-500ms per user (depends on message count)
- **Tool Detection**: ~50-100ms per user
- **Pattern Detection**: ~100-300ms per user
- **Similarity Matching**: ~1-5ms per comparison

### Storage Requirements

- **Per User Profile**: ~2-5 KB
- **Tool Fingerprints**: ~100 bytes per tool
- **Operational Patterns**: ~1-2 KB per user
- **10K Users**: ~50-100 MB total

## Troubleshooting

### Low Similarity Scores

- **Check Message Count**: Need sufficient messages for analysis
- **Verify Language**: Language mismatch affects similarity
- **Check Quality**: Low-quality messages reduce accuracy

### Tool Detection Failures

- **Update Patterns**: Tool patterns may need updating
- **Check Message Content**: Ensure messages contain tool references
- **Verify Format**: Tool commands must be in expected format

### False Positives

- **Adjust Threshold**: Increase similarity threshold
- **Cross-Validate**: Use multiple attribution methods
- **Manual Review**: Flag for manual review if uncertain
