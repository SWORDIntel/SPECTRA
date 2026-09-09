# Persona V2 Phase 2 — Conditional, Interaction, Dialogue/Affective

## Module 10: `conditional.py` — Conditional Behavioral Probabilities

The biggest architectural upgrade: `author × context × time → distribution(feature)`.

```
extract_conditional_features(messages, context_fn=None) -> Dict[str, Any]
```

Contexts are derived from message metadata:
- `channel_id` → context key "channel:<id>"
- `reply_to_message_id` present → context "reply"
- `reply_to_message_id` absent → context "initiation"
- Hour of day buckets: "morning", "afternoon", "evening", "night"
- Message length buckets: "short" (<50 chars), "medium" (50-200), "long" (>200)
- Custom context via `context_fn(msg) -> str`

For each context, compute conditional rates of:
- `P(profanity | context)`
- `P(long_message | context)`
- `P(question | context)` — ends with "?"
- `P(emoji | context)`
- `P(codeblock | context)`
- `P(url | context)`
- `P(technical_jargon | context)`

Output:
```json
{
  "conditional_probabilities": {
    "channel:123": {
      "profanity_rate": 0.12,
      "long_message_rate": 0.34,
      "question_rate": 0.08,
      ...
    },
    "reply": { ... },
    "initiation": { ... },
    "morning": { ... },
    ...
  },
  "context_distribution": {"channel:123": 0.5, "reply": 0.3, ...},
  "context_count": 5,
  "context_entropy": 1.2
}
```

Also compute **context-conditioned variance** — how much a feature varies
across contexts. High variance = context-dependent behavior.

```
context_conditioned_variance: {
  "profanity_rate": 0.034,
  "long_message_rate": 0.12,
  ...
}
```

## Module 11: `interaction.py` — Interaction-Conditioned Style

Groups messages by context (channel, recipient, group size, topic proxy)
and computes per-context style vectors, then measures differences.

```
extract_interaction_features(messages) -> Dict[str, Any]
```

Contexts:
- `style_by_channel` — per channel_id
- `style_by_recipient_class` — DM vs group vs public (inferred from channel_id patterns or explicit)
- `style_by_time_period` — morning/afternoon/evening/night
- `style_by_message_type` — initiation vs reply

For each context, compute a compact style vector:
```json
{
  "avg_length": 45.2,
  "profanity_rate": 0.05,
  "emoji_rate": 0.12,
  "question_rate": 0.08,
  "formality_score": 0.65,
  "slang_rate": 0.03,
  "technical_jargon_rate": 0.15,
  "discourse_marker_rate": 0.22
}
```

Then compute distances:
- `register_shift_score` — max pairwise distance across contexts (0-1)
- `recipient_style_distance` — distance between DM and group styles
- `channel_style_distance` — mean pairwise distance across channels
- `context_style_consistency` — 1 - register_shift_score (how consistent the persona is)

Output:
```json
{
  "style_by_channel": {"123": {...}, "456": {...}},
  "style_by_recipient_class": {"dm": {...}, "group": {...}},
  "style_by_time_period": {"morning": {...}, ...},
  "style_by_message_type": {"initiation": {...}, "reply": {...}},
  "register_shift_score": 0.34,
  "recipient_style_distance": 0.22,
  "channel_style_distance": 0.15,
  "context_style_consistency": 0.66,
  "context_count": 4
}
```

## Module 12: `dialogue_acts.py` — Dialogue Acts + Affective Expression

Two concerns in one module:

### Dialogue Acts (L11)

Classify each message into one of:
- `question` — ends with "?" or has question word
- `answer` — reply that doesn't end with "?"
- `request` — imperative starting with "please", "can you", "could you"
- `command` — imperative without "please"
- `suggestion` — "maybe", "how about", "you could", "I suggest"
- `correction` — "actually", "no,", "that's wrong", "I think you mean"
- `challenge` — "why", "how come", "are you sure", "really?"
- `agreement` — "yes", "yeah", "agree", "true", "exactly", "right"
- `disagreement` — "no", "nope", "disagree", "not really"
- `clarification` — "I mean", "i.e.", "that is", "in other words"
- `joke` — "lol", "haha", "lmao", sarcasm markers
- `complaint` — "ugh", "annoying", "frustrating", "stupid"
- `observation` — declarative statement of fact
- `hypothesis` — "maybe", "perhaps", "I wonder", "could be"
- `prediction` — "will", "going to", "I bet", "expect"

Store:
- `dialogue_act_distribution` — {act: rate}
- `dialogue_act_transition_matrix` — {act -> next_act: rate}
  (requires temporal ordering)

### Affective Expression (L12)

Not "this person is angry" but **how emotion is linguistically encoded**.

- `sentiment_distribution` — {positive: 0.4, neutral: 0.45, negative: 0.15}
  (lexicon-based, stdlib only)
- `emotion_marker_distribution` — {joy: 0.05, anger: 0.12, sadness: 0.03, ...}
- `emphasis_rate` — ALL CAPS words, bold, exclamation marks
- `intensification_under_negative_sentiment` — intensifier rate when sentiment is negative
- `profanity_given_negative_sentiment` — P(profanity | negative sentiment)
- `punctuation_given_emotion` — {positive: {"!": 0.12, "?": 0.05}, negative: {"!": 0.08, "...": 0.03}}
- `message_length_given_emotion` — {positive: 45.2, neutral: 32.1, negative: 67.8}
- `sarcasm_marker_rate` — "yeah right", "sure", "obviously" (in negative context), "/s"
- `humor_marker_rate` — "lol", "haha", "lmao", joke punctuation

Output:
```json
{
  "dialogue_act_distribution": {"observation": 0.3, "question": 0.15, ...},
  "dialogue_act_transition_matrix": {"question": {"clarification": 0.2, "answer": 0.5}, ...},
  "sentiment_distribution": {"positive": 0.4, "neutral": 0.45, "negative": 0.15},
  "emotion_marker_distribution": {"joy": 0.05, "anger": 0.12, ...},
  "emphasis_rate": 0.08,
  "intensification_under_negative_sentiment": 0.15,
  "profanity_given_negative_sentiment": 0.22,
  "punctuation_given_emotion": {"positive": {"!": 0.12}, "negative": {"!": 0.08}},
  "message_length_given_emotion": {"positive": 45.2, "neutral": 32.1, "negative": 67.8},
  "sarcasm_marker_rate": 0.03,
  "humor_marker_rate": 0.05
}
```

## Implementation Notes

- All modules: standard library only (re, collections, math, statistics, datetime)
- Each exports one `extract_*` function taking `List[Dict[str, Any]]`
- All output JSON-serializable
- Distributions capped at reasonable limits (top-50 to top-200)
- Scalars rounded to 6 decimal places
- Empty input returns defaults
- Graceful degradation when metadata is missing
