# Persona V2 Feature Expansion Plan

## Goal

Expand the persona trait system from ~27 scalar stylometric features to a
multi-layer behavioral persona model. The architectural shift is:

```
CURRENT:  author -> feature (scalar)
BETTER:   author × context × time -> distribution(feature)
```

## New Feature Modules

All modules live under `tgarchive/intelligence/features/`.
All modules are **standard library only** (re, collections, math, statistics,
hashlib, datetime, unicodedata). No NLTK, spaCy, or external dependencies.

Each module exports a single `extract_*` function that takes
`List[Dict[str, Any]]` (messages with `content`/`text`, optional `date`,
`user_id`, `channel_id`, `reply_to_message_id`) and returns a
`Dict[str, Any]` feature dict. Distributions are stored as JSON-serializable
dicts (top-N items, capped at 200 entries). Scalars are floats rounded to 6
decimal places.

### Module 1: `orthographic.py` — L1 Character Fingerprint

```
char_ngram_freq_2, char_ngram_freq_3, char_ngram_freq_4,
char_ngram_freq_5, char_ngram_freq_6   — top-200 frequency distributions

word_initial_char_ngrams   — top-100 (first 3 chars of each word)
word_final_char_ngrams     — top-100 (last 3 chars of each word)

punctuation_sequence_freq  — top-100 ("...", "..", "?!", "???", " - ", "—", "( ")
repeated_punctuation_patterns — top-50 ("!!", "??", "...", "!!!")
capitalization_transition_patterns — top-50 ("lower->Upper", "Upper->lower", etc.)
digit_format_patterns      — top-50 ("16GB", "£30", "0xFF", "23/08/26")
```

### Module 2: `errors.py` — L2 Typo/Error Fingerprint

```
misspelling_frequency      — rate of likely misspellings
misspelling_dictionary     — top-100 {misspelled->corrected: count}
edit_distance_error_distribution — {1: 0.6, 2: 0.3, ...}
character_deletion_rate
character_insertion_rate
character_substitution_rate
character_transposition_rate
adjacent_keyboard_error_rate
space_omission_rate
space_insertion_rate
apostrophe_omission_rate
capitalization_error_rate
repeated_character_distribution — top-50 {"aaa": 3, "lll": 2}
word_merge_rate
word_split_rate
correction_after_typo_rate
typo_signature             — top-50 {"the->teh": 0.004, "ing->ign": 0.001}
```

Uses QWERTY adjacency map for adjacent_keyboard_error_rate.
Misspelling detection: edit distance ≤ 2 against a small common-words list.
All rates are per-word or per-character, normalized.

### Module 3: `discourse.py` — L4 Discourse/Rhetoric

```
discourse_marker_distribution — top-100 {"I mean": 12, "basically": 8, ...}
sentence_initial_phrase_distribution — top-100 (first 3 words of sentences)
sentence_final_phrase_distribution   — top-100 (last 3 words of sentences)

hedge_rate                 — "maybe", "perhaps", "I think", "sort of"
certainty_marker_rate      — "definitely", "absolutely", "clearly"
intensifier_rate           — "very", "really", "extremely", "super"
qualifier_rate             — "kind of", "sort of", "fairly", "somewhat"
self_correction_rate       — "I mean", "actually", "well", "or rather"
parenthetical_rate         — parenthetical asides (em-dash, parenthetical)
aside_rate
clarification_rate         — "i.e.", "that is", "in other words"
reformulation_rate         — "or rather", "I mean", "actually"
example_introduction_rate  — "for example", "for instance", "e.g."
analogy_rate               — "like", "as if", "similar to"
contrast_marker_rate       — "but", "however", "on the other hand"
causal_marker_rate         — "because", "so", "therefore", "since"

trigrams                   — top-200 word trigrams
fourgrams                  — top-100 word fourgrams
skipgrams                  — top-100 skip-2-grams (word _ word)
sentence_openers           — top-100 (first word of sentences)
sentence_closers           — top-100 (last word of sentences)
```

### Module 4: `formatting.py` — L5 Formatting Fingerprint

```
paragraph_count
paragraph_length_distribution — {mean, median, std, min, max}
blank_line_rate
bullet_usage_rate           — -, *, •, ·
numbered_list_rate          — 1., 2., etc.
markdown_heading_rate
bold_rate                   — **text** or __text__
italic_rate                 — *text* or _text_
inline_code_rate            — `code`
codeblock_rate              — ``` blocks
blockquote_rate             — > text
colon_usage_context         — {after_word: 0.3, after_phrase: 0.2, ...}
semicolon_usage_context
dash_type_distribution      — {"-": 0.5, "—": 0.3, "--": 0.2}
newline_after_punctuation_rate

shell_command_rate          — lines starting with $ or common commands
code_language_distribution  — top-20 from codeblock fences
inline_path_rate            — /usr/local, ~/path
environment_variable_rate   — $VAR, ${VAR}
url_rate
```

### Module 5: `notation.py` — L6 Numeric/Notation Style

```
number_word_preference      — ratio of word-form vs digit-form numbers
decimal_precision_distribution — {0: 0.3, 1: 0.4, 2: 0.2, ...}
thousands_separator_style   — {"comma": 0.6, "none": 0.3, "space": 0.1}
currency_format_style       — {"£30": 0.5, "30 quid": 0.3, "30 pounds": 0.2}
date_format_distribution    — {"DD/MM/YY": 0.4, "YYYY-MM-DD": 0.3, ...}
time_format_distribution    — {"12h": 0.6, "24h": 0.4}
unit_spacing_style          — {"30GB": 0.5, "30 GB": 0.5}
unit_abbreviation_style     — {"GB": 0.3, "G": 0.1, "gigabytes": 0.1}
hex_notation_style          — {"0xFF": 0.6, "ffh": 0.1, "FF": 0.3}
binary_notation_style       — {"0b1010": 0.5, "1010b": 0.1}
version_number_style        — {"1.2.3": 0.5, "v1.2": 0.3}
range_notation_style        — {"10-20": 0.4, "10..20": 0.2}
```

### Module 6: `register.py` — L7 Register/Formality

```
formality_score             — 0-1 composite (longer words, no slang, etc.)
slang_rate
profanity_rate
abbreviation_rate
acronym_rate
technical_jargon_rate
colloquialism_rate
idiom_rate
politeness_marker_rate      — "please", "thank you", "sorry"
greeting_rate               — "hi", "hey", "hello", "yo"
signoff_rate                — "cheers", "regards", "bye", "later"
honorific_rate              — "Mr", "Dr", "Ms"
direct_address_rate         — "@username, "you"

profanity_vocabulary        — top-50
slang_vocabulary            — top-50
abbreviation_vocabulary     — top-50
```

### Module 7: `conversation.py` — L6 Conversation Mechanics

Takes messages with `date`, `user_id`, `reply_to_message_id`, `channel_id`.

```
reply_probability
reply_latency_median        — seconds
reply_latency_distribution  — {median, p25, p75, p90, std}
messages_per_burst          — mean
burst_duration              — mean seconds
inter_message_interval_distribution — {median, p25, p75, std}
conversation_initiation_rate
conversation_termination_rate
double_message_rate         — consecutive messages by same user < 60s
triple_message_rate
followup_message_probability
quote_usage_rate
reply_to_message_rate
edit_rate                   — (if edit metadata available)
delete_rate                 — (if delete metadata available)
response_length_given_prompt_length — correlation coefficient
```

Burst = consecutive messages by same user with gaps < 300s (configurable).

### Module 8: `syntax.py` — L3 Syntax (Stdlib Approximation)

No spaCy/NLTK. Uses regex-based POS approximation and sentence structure heuristics.

```
pos_unigram_distribution    — top-50 {NOUN: 0.3, VERB: 0.2, ...}
pos_bigram_distribution     — top-50 {"DET NOUN": 0.1, ...}
sentence_type_distribution  — {declarative: 0.6, question: 0.2, imperative: 0.15, fragment: 0.05}
question_rate
imperative_rate
declarative_rate
sentence_fragment_rate      — sentences with no finite verb
run_on_sentence_rate        — comma-spliced or excessively long
avg_clause_count            — estimated from conjunctions
subordinate_clause_rate     — because, although, since, while, if
coordinate_clause_rate      — and, but, or
active_voice_rate           — heuristic
passive_voice_rate          — "was X-ed", "is X-ed", "been X-ed"
avg_noun_phrase_length      — estimated
avg_verb_phrase_length      — estimated
characteristic_pos_sequences — top-20 ["PRON AUX ADV VERB", ...]
```

POS approximation uses suffix rules + function word lists:
- Modal verbs: can, could, should, would, will, must, may, might
- Auxiliaries: is, are, was, were, be, been, being, have, has, had, do, does, did
- Determiners: the, a, an, this, that, these, those, my, your, his, her, its, our, their
- Prepositions: in, on, at, to, for, with, by, from, of, about, into, through
- Pronouns: I, you, he, she, it, we, they, me, him, her, us, them
- Suffix-based: -ing → VBG, -ed → VBD, -ly → RB, -tion/-ment → NOUN, -ous/-ful → ADJ

### Module 9: `temporal.py` — L8 Temporal Behaviour

Takes messages with `date` timestamps.

```
hour_of_day_distribution    — 24-element {0: 0.01, 1: 0.0, ..., 23: 0.05}
day_of_week_distribution    — 7-element {Mon: 0.15, ...}
message_length_by_hour      — 24-element mean length per hour
activity_session_length     — mean minutes
session_start_distribution  — hour histogram
session_end_distribution    — hour histogram
response_latency_by_hour    — 24-element median latency
persona_drift_30d           — JS divergence of vocab 30d ago vs now
persona_drift_90d
persona_drift_365d
feature_half_life           — estimated days for vocabulary turnover
```

Session = activity gaps < 1800s (30 min).

## Integration

### `persona_training.py` changes

`build_snapshot()` will call all 9 extractors and merge their outputs into
the snapshot's `linguistic_features` JSON field (renamed conceptually to
`behavioral_features` but kept as `linguistic_features` for backward compat).

New snapshot fields (stored in the existing JSON columns):
- `orthographic_features` — JSON
- `error_features` — JSON
- `discourse_features` — JSON
- `formatting_features` — JSON
- `notation_features` — JSON
- `register_features` — JSON
- `conversation_features` — JSON
- `syntax_features` — JSON
- `temporal_features` — JSON

### Schema changes

Add columns to `persona_profile_snapshots`:
```sql
orthographic_features TEXT,      -- JSON
error_features TEXT,             -- JSON
discourse_features TEXT,         -- JSON
formatting_features TEXT,        -- JSON
notation_features TEXT,          -- JSON
register_features TEXT,          -- JSON
conversation_features TEXT,      -- JSON
syntax_features TEXT,            -- JSON
temporal_features TEXT,          -- JSON
```

### Backward compatibility

Existing snapshots without the new columns return empty dicts for the new
feature sets. The original `linguistic_features` field is preserved unchanged.

## Testing

Each module gets a dedicated test file:
- `test_orthographic_features.py`
- `test_error_features.py`
- `test_discourse_features.py`
- `test_formatting_features.py`
- `test_notation_features.py`
- `test_register_features.py`
- `test_conversation_features.py`
- `test_syntax_features.py`
- `test_temporal_features.py`

Each test verifies:
1. Empty input returns defaults
2. Known input produces expected features
3. All outputs are JSON-serializable
4. Distributions are capped at their limits
5. Scalars are in valid ranges

## Priority Order

1. orthographic.py (highest ROI)
2. errors.py
3. discourse.py
4. syntax.py
5. formatting.py
6. notation.py
7. register.py
8. conversation.py
9. temporal.py
