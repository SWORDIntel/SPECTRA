# Persona Training-Data — Captured Traits Reference

Every trait picked up by the persona training-data pipeline, organized by
extraction layer, with a brief reason for why each is captured.

---

## Layer 1: Linguistic / Stylometric Features

Extracted from positive examples via `extract_linguistic_features()` and
stored in `snapshot["linguistic_features"]`. These are stylometric
fingerprints that distinguish one author from another even when the topic
is identical.

### Character N-Gram Diversity

| Trait | Key | Reason |
|-------|-----|--------|
| 2-gram diversity | `char_2gram_diversity` | Captures habitual letter-pair usage (e.g. "th", "qu") — a low-level orthographic fingerprint. |
| 3-gram diversity | `char_3gram_diversity` | Captures common trigram patterns — more granular spelling/typing habits. |
| 4-gram diversity | `char_4gram_diversity` | Captures morphological patterns (suffixes, prefixes) — distinguishes agglutinative vs analytic writers. |

### Function Word Frequencies (Top 10)

Function words ("the", "and", "is") are used unconsciously and vary
consistently between authors. They are among the strongest stylometric
signals because they are topic-independent.

| Trait | Key | Reason |
|-------|-----|--------|
| "the" frequency | `fw_the` | Definite-article habit — varies by dialect and education. |
| "and" frequency | `fw_and` | Conjunction preference — some authors over-chain with "and". |
| "to" frequency | `fw_to` | Infinitive/preposition density — sentence-structure fingerprint. |
| "of" frequency | `fw_of` | Possessive vs genitive preference. |
| "a" frequency | `fw_a` | Indefinite-article habit. |
| "in" frequency | `fw_in` | Preposition preference — spatial vs abstract reasoning style. |
| "that" frequency | `fw_that` | Subordination style — complex vs simple sentences. |
| "is" frequency | `fw_is` | Copula density — declarative vs active voice tendency. |
| "i" frequency | `fw_i` | First-person usage — self-reference rate (confidence / egocentrism). |
| "it" frequency | `fw_it` | Pronoun usage — anaphora habits. |

### Punctuation

| Trait | Key | Reason |
|-------|-----|--------|
| Punctuation density | `punctuation_density` | How heavily the author punctuates — formal vs casual style. |
| Punctuation diversity | `punctuation_diversity` | Range of punctuation marks used — sophisticated vs minimal punctuation. |

### Whitespace Habits

Whitespace habits are highly idiosyncratic and persist across devices,
making them strong identity signals.

| Trait | Key | Reason |
|-------|-----|--------|
| Trailing whitespace ratio | `whitespace_trailing_ratio` | Captures trailing-space-before-newline habit — a keyboard/platform fingerprint. |
| Double-space ratio | `whitespace_double_space_ratio` | Captures double-space after period (typewriter-era habit) or accidental spacing. |

### Typos & Contractions

| Trait | Key | Reason |
|-------|-----|--------|
| Typo rate | `typo_rate` | Words with 3+ repeated characters — captures typing speed / carelessness / intentional emphasis ("soooo"). |
| Contraction rate | `contraction_rate` | Contraction usage (I've, don't, won't) — formal vs informal register. |

### Emoji Usage

| Trait | Key | Reason |
|-------|-----|--------|
| Emoji density | `emoji_density` | Emoji-per-character rate — emotional expressiveness / visual communication preference. |
| Emoji diversity | `emoji_diversity` | Range of distinct emoji used — vocabulary of emotional expression. |

### Lexical Richness

| Trait | Key | Reason |
|-------|-----|--------|
| Type-Token Ratio (TTR) | `lexical_richness_ttr` | Unique words / total words — vocabulary breadth. High TTR = diverse vocabulary. |
| Yule's K | `lexical_richness_yule_k` | Vocabulary richness constant — less sensitive to text length than TTR. Captures repeated-word patterns. |

### Code Switching / Script Mixing

| Trait | Key | Reason |
|-------|-----|--------|
| Code switching score | `code_switching_score` | Fraction of messages mixing 2+ scripts (Latin + Cyrillic, Arabic + Latin, etc.) — bilingual/multilingual identity signal. |

Scripts detected: Latin, Cyrillic, Arabic, CJK, Greek, Hebrew, Devanagari,
Japanese, Korean.

### Structural & Length Metrics

| Trait | Key | Reason |
|-------|-----|--------|
| Avg line breaks | `avg_line_breaks` | Message formatting habit — single-line vs multi-line writers. |
| Avg message length | `avg_message_length` | Verbosity — terse vs verbose communication style. |
| Avg word length | `avg_word_length` | Word complexity — simple vs sophisticated vocabulary. |
| Avg sentence length | `avg_sentence_length` | Sentence complexity — short punchy vs long flowing sentences. |

### Character Type Ratios

| Trait | Key | Reason |
|-------|-----|--------|
| Uppercase ratio | `uppercase_ratio` | SHOUTING vs normal casing — emphasis style. |
| Digit ratio | `digit_ratio` | Numeric content density — technical vs conversational writing. |
| Special char ratio | `special_char_ratio` | Non-alphanumeric usage — markdown, code snippets, decorative text. |

**Total: 27 linguistic traits.**

---

## Layer 2: Vocabulary & Style Distributions

Stored in the snapshot alongside linguistic features. These capture the
actual words and word-pairs the target uses, and which words distinguish
them from other authors.

| Trait | Field | Reason |
|-------|-------|-------|
| Word frequency distribution | `vocabulary` | Top 200 words with normalized frequencies from positives — the target's core vocabulary. |
| Distinctive vocabulary | `distinctive_vocab` | Top 200 words ranked by smoothed log-odds (positive vs negative) — what the target says that others in the same channels don't. This is the key signal for persona replication. |
| Bigram frequencies | `bigrams` | Top 200 word-pairs with normalized frequencies — captures phrasing patterns and collocations ("kind of", "you know", "I think"). |
| Positive count | `positive_count` | Number of positive examples in the snapshot — corpus size signal. |
| Negative count | `negative_count` | Number of negative examples — contrast set size for training. |
| Review count | `review_count` | Number of uncertain examples — data quality signal. |

---

## Layer 3: Domain Knowledge

Domain knowledge is captured as observations with `score` (measurement,
[0,1]) and `confidence` (trust in the measurement, [0,1]) kept strictly
separate. This separation prevents a single high-score-but-low-confidence
observation from being treated as reliable knowledge.

### Aggregation

Multiple observations per domain are aggregated via:
- **Confidence-weighted mean** for score (high-trust observations count more).
- **Beta-inspired confidence** that rises with sample size but is penalized
  by variance (contradictory evidence lowers confidence).
- Final confidence is bounded [0,1].

### Inferred Domains (Lexicon-Based)

`infer_knowledge_observations()` scans positive examples for domain-specific
terminology. Score is calibrated from term density; confidence rises with hit
count. No claim is made without evidence — domains with zero hits produce no
observation.

| Domain | Terms | Reason |
|--------|-------|--------|
| `computers` | 57 | code, server, kernel, linux, python, docker, compiler, binary, hex, ssh, regex, cpu, gpu, encryption, cipher, hash, sha, aes, rsa, tls, ssl, http, pointer, array, loop, syntax, runtime, bytecode, opcode... — captures technical literacy and programming knowledge. |
| `biology` | 43 | cell, dna, rna, protein, enzyme, gene, genome, membrane, mitochondria, nucleus, ribosome, chromosome, organism, neuron, synapse, hormone, metabolism, photosynthesis, evolution, bacteria, virus, antibody, immune, pathogen, ecosystem, anatomy, physiology, molecule, lipid, carbohydrate, amino, acid, polymerase, replication, transcription... — captures life-sciences education and interest. |
| `finance` | 42 | money, dollar, euro, currency, bank, account, loan, credit, debit, interest, principal, bond, stock, share, equity, dividend, portfolio, asset, liability, revenue, profit, loss, income, expense, budget, tax, audit, invoice, transaction, transfer, deposit, withdrawal, forex, exchange, inflation, deflation, market, trade, broker, commodity, derivative, option... — captures financial literacy and economic interest. |
| `security` | 43 | attack, defend, threat, vulnerability, exploit, payload, malware, trojan, worm, rootkit, backdoor, firewall, ids, ips, siem, soc, pentest, redteam, blueteam, zero-day, cve, patch, hardening, sandbox, honeypot, phishing, spearphishing, reconnaissance, foothold, lateral, exfiltration, c2, apt, ransomware, encryption, decryption, forensics, triage... — captures cybersecurity expertise and threat-intelligence vocabulary. |
| `medicine` | 43 | patient, diagnosis, symptom, treatment, therapy, dose, medication, drug, prescription, clinical, trial, study, disease, syndrome, chronic, acute, infection, inflammation, surgery, procedure, prognosis, epidemiology, vaccine, immunization, antibiotic, antiviral, pathology, radiology, mri, ct, ultrasound, biopsy, blood, pressure, heart, cardiac, pulmonary, respiratory, neurological, oncology... — captures medical knowledge and health-literacy. |

**Total: 228 lexicon terms across 5 domains.**

Custom lexicons can be supplied via the `domain_lexicons` parameter for
domain-specific personas (e.g. legal, military, automotive).

### Manual Domains

Any domain can be recorded manually with explicit `score` and `confidence`:

```python
store.save_knowledge_observation("t1", "computers", 0.75, 0.8)
store.save_knowledge_observation("t1", "biology", 0.32, 0.6)
```

There is no limit on the number of manual domains.

---

## Layer 4: Provenance Metadata

Every example records full source provenance for audit, deduplication, and
temporal analysis. This ensures training data can be traced back to its
origin and replayed.

| Field | Reason |
|-------|--------|
| `source_type` | Distinguishes collected messages from manual entries from imported data. |
| `source_message_id` | Links the example back to the original Telegram message for audit. |
| `source_channel_id` | Channel context — the same person may write differently in different channels. |
| `source_user_id` | Author ID — confirms the example came from the target, not a forward. |
| `observed_at` | Timestamp of the original message — enables temporal analysis and longitudinal snapshots. |
| `collected_at` | When the example was ingested into the corpus — separates observation time from collection time. |
| `weight` | Example importance — allows upweighting high-confidence positives or downweighting noisy data. |
| `label` | positive / negative / review — the explicit training signal. Review is never treated as positive by default. |
| `source_revision` | Dedup hash — prevents the same message from being ingested twice. |

---

## Summary

| Layer | Traits | Purpose |
|-------|--------|---------|
| Linguistic / stylometric | 27 features | Writing-style fingerprint — how the target writes. |
| Vocabulary & style | 3 distributions + 3 counts | What the target says and how it differs from others. |
| Domain knowledge | 5 inferred domains (228 terms) + unlimited manual | What the target knows — expertise profile. |
| Provenance | 9 metadata fields per example | Audit trail — where, when, and from whom each example came. |
| **V1 Total** | **~42 distinct trait categories** | |

---

## V2 Behavioral Feature Layers (Phase 1 + Phase 2)

The V1 system recorded *what tokens occur* much better than it recorded
**how the person constructs thoughts, interacts conversationally, makes
errors, changes register, and behaves over time**. V2 adds 12 new
extraction layers covering the full behavioral spectrum.

The architectural shift: `author -> feature` becomes
`author × context × time -> distribution(feature)`.

### Layer 1: Orthographic / Character Fingerprint (`orthographic.py`)

| Trait | Reason |
|-------|--------|
| `char_ngram_freq_2` through `char_ngram_freq_6` | Full frequency distributions (top-200 each) — far stronger than diversity alone. Captures habitual letter sequences. |
| `word_initial_char_ngrams` | First-3-chars of words — captures spelling/abbreviation habits. |
| `word_final_char_ngrams` | Last-3-chars of words — captures suffix/morphology habits. |
| `punctuation_sequence_freq` | Top-100 sequences like "...", "..", "?!", "???", " - ", "—" — distinctive punctuation fingerprints. |
| `repeated_punctuation_patterns` | Top-50 like "!!", "??", "...", "!!!" — emphasis style. |
| `capitalization_transition_patterns` | Top-50 like "lower->Upper", "Upper->lower" — capitalization habits. |
| `digit_format_patterns` | Top-50 like "16GB", "£30", "0xFF", "23/08/26" — notation fingerprints. |

### Layer 2: Typo / Error Fingerprint (`errors.py`)

| Trait | Reason |
|-------|--------|
| `misspelling_frequency` | Rate of likely misspellings — error habits are highly individual. |
| `misspelling_dictionary` | Top-100 {misspelled->corrected: count} — specific error patterns. |
| `edit_distance_error_distribution` | {1: 0.6, 2: 0.3, ...} — error severity profile. |
| `character_deletion_rate` | How often characters are omitted. |
| `character_insertion_rate` | How often extra characters appear. |
| `character_substitution_rate` | How often wrong characters replace correct ones. |
| `character_transposition_rate` | How often adjacent characters are swapped ("teh" vs "the"). |
| `adjacent_keyboard_error_rate` | QWERTY-adjacent key errors — typing mechanics. |
| `space_omission_rate` | Missing spaces between words. |
| `space_insertion_rate` | Extra spaces within words. |
| `apostrophe_omission_rate` | "dont" vs "don't" — contraction habits. |
| `capitalization_error_rate` | Wrong-case errors. |
| `repeated_character_distribution` | Top-50 {"aaa": 3, "lll": 2} — emphasis vs typo. |
| `word_merge_rate` | Two words merged into one. |
| `word_split_rate` | One word split into two. |
| `correction_after_typo_rate` | Self-correction behavior. |
| `typo_signature` | Top-50 {"the->teh": 0.004, "ing->ign": 0.001} — the composite error fingerprint. |

### Layer 3: Syntax / Morphosyntactic Fingerprint (`syntax.py`)

Stdlib-only POS approximation (no spaCy/NLTK). Uses suffix rules + function word lists.

| Trait | Reason |
|-------|--------|
| `pos_unigram_distribution` | Top-50 {NOUN: 0.3, VERB: 0.2, ...} — grammatical habits. |
| `pos_bigram_distribution` | Top-50 {"DET NOUN": 0.1, ...} — syntactic construction patterns. |
| `sentence_type_distribution` | {declarative, question, imperative, fragment} — sentence structure habits. |
| `question_rate` | How often the target asks questions. |
| `imperative_rate` | How often the target gives commands. |
| `declarative_rate` | How often the target makes statements. |
| `sentence_fragment_rate` | Incomplete sentences — informal writing style. |
| `run_on_sentence_rate` | Excessively long or comma-spliced sentences. |
| `avg_clause_count` | Estimated clause complexity. |
| `subordinate_clause_rate` | "because", "although", "since", "while", "if" — complex sentence construction. |
| `coordinate_clause_rate` | "and", "but", "or" — simple sentence linking. |
| `active_voice_rate` | Active voice usage (heuristic). |
| `passive_voice_rate` | Passive voice usage ("was X-ed", "is X-ed"). |
| `avg_noun_phrase_length` | Estimated NP complexity. |
| `avg_verb_phrase_length` | Estimated VP complexity. |
| `characteristic_pos_sequences` | Top-20 ["PRON AUX ADV VERB", ...] — topic-resistant syntactic fingerprint. |

### Layer 4: Discourse / Rhetoric (`discourse.py`)

| Trait | Reason |
|-------|--------|
| `discourse_marker_distribution` | Top-100 {"I mean": 12, "basically": 8, ...} — recurring rhetorical phrases. |
| `sentence_initial_phrase_distribution` | Top-100 (first 3 words) — how sentences begin. |
| `sentence_final_phrase_distribution` | Top-100 (last 3 words) — how sentences end. |
| `hedge_rate` | "maybe", "perhaps", "I think", "sort of" — uncertainty expression. |
| `certainty_marker_rate` | "definitely", "absolutely", "clearly" — confidence expression. |
| `intensifier_rate` | "very", "really", "extremely", "super" — emphasis style. |
| `qualifier_rate` | "kind of", "sort of", "fairly", "somewhat" — hedging style. |
| `self_correction_rate` | "I mean", "actually", "well", "or rather" — self-monitoring behavior. |
| `parenthetical_rate` | Em-dash and parenthetical asides. |
| `aside_rate` | Tangential remarks. |
| `clarification_rate` | "i.e.", "that is", "in other words" — explanation habits. |
| `reformulation_rate` | "or rather", "I mean", "actually" — thought revision behavior. |
| `example_introduction_rate` | "for example", "for instance", "e.g." — illustration habits. |
| `analogy_rate` | "like", "as if", "similar to" — comparison style. |
| `contrast_marker_rate` | "but", "however", "on the other hand" — argumentation style. |
| `causal_marker_rate` | "because", "so", "therefore", "since" — reasoning style. |
| `trigrams` | Top-200 word trigrams — captures 3-word phrases. |
| `fourgrams` | Top-100 word fourgrams — captures longer phrases. |
| `skipgrams` | Top-100 skip-2-grams (word _ word) — captures non-adjacent patterns. |
| `sentence_openers` | Top-100 (first word) — sentence-starting habits. |
| `sentence_closers` | Top-100 (last word) — sentence-ending habits. |

### Layer 5: Formatting Fingerprint (`formatting.py`)

| Trait | Reason |
|-------|--------|
| `paragraph_count` | How many paragraphs per message. |
| `paragraph_length_distribution` | {mean, median, std, min, max} — paragraph sizing. |
| `blank_line_rate` | Spacing habits between paragraphs. |
| `bullet_usage_rate` | -, *, •, · — list formatting. |
| `numbered_list_rate` | 1., 2., etc. — structured list usage. |
| `markdown_heading_rate` | # headings — document structuring. |
| `bold_rate` | **text** or __text__ — emphasis formatting. |
| `italic_rate` | *text* or _text_ — emphasis formatting. |
| `inline_code_rate` | `code` — technical formatting. |
| `codeblock_rate` | ``` blocks — code-heavy messages. |
| `blockquote_rate` | > text — quoting style. |
| `colon_usage_context` | Where colons appear (after word, after phrase, etc.). |
| `semicolon_usage_context` | Where semicolons appear. |
| `dash_type_distribution` | {"-": 0.5, "—": 0.3, "--": 0.2} — dash preference. |
| `newline_after_punctuation_rate` | Line-break habits after punctuation. |
| `shell_command_rate` | Lines starting with $ or common commands. |
| `code_language_distribution` | Top-20 from codeblock fences. |
| `inline_path_rate` | /usr/local, ~/path — file path references. |
| `environment_variable_rate` | $VAR, ${VAR} — env var references. |
| `url_rate` | Link sharing habits. |

### Layer 6: Numeric / Notation Style (`notation.py`)

| Trait | Reason |
|-------|--------|
| `number_word_preference` | Ratio of word-form vs digit-form numbers ("thirty" vs "30"). |
| `decimal_precision_distribution` | {0: 0.3, 1: 0.4, 2: 0.2, ...} — precision habits. |
| `thousands_separator_style` | {"comma": 0.6, "none": 0.3, "space": 0.1} — separator preference. |
| `currency_format_style` | {"£30": 0.5, "30 quid": 0.3, "30 pounds": 0.2} — money notation. |
| `date_format_distribution` | {"DD/MM/YY": 0.4, "YYYY-MM-DD": 0.3, ...} — date notation. |
| `time_format_distribution` | {"12h": 0.6, "24h": 0.4} — time notation. |
| `unit_spacing_style` | {"30GB": 0.5, "30 GB": 0.5} — unit spacing. |
| `unit_abbreviation_style` | {"GB": 0.3, "G": 0.1, "gigabytes": 0.1} — unit abbreviation. |
| `hex_notation_style` | {"0xFF": 0.6, "ffh": 0.1, "FF": 0.3} — hex notation. |
| `binary_notation_style` | {"0b1010": 0.5, "1010b": 0.1} — binary notation. |
| `version_number_style` | {"1.2.3": 0.5, "v1.2": 0.3} — version notation. |
| `range_notation_style` | {"10-20": 0.4, "10..20": 0.2} — range notation. |

### Layer 7: Register / Formality (`register.py`)

| Trait | Reason |
|-------|--------|
| `formality_score` | 0-1 composite (word length, slang absence, complex syntax). |
| `slang_rate` | Slang word frequency. |
| `profanity_rate` | Profanity frequency. |
| `abbreviation_rate` | Abbreviation frequency (btw, imo, tbh). |
| `acronym_rate` | Acronym frequency (NASA, API, ROI). |
| `technical_jargon_rate` | Domain-specific term frequency. |
| `colloquialism_rate` | Informal expression frequency. |
| `idiom_rate` | Idiomatic expression frequency. |
| `politeness_marker_rate` | "please", "thank you", "sorry" — social register. |
| `greeting_rate` | "hi", "hey", "hello", "yo" — opening habits. |
| `signoff_rate` | "cheers", "regards", "bye", "later" — closing habits. |
| `honorific_rate` | "Mr", "Dr", "Ms" — formal address. |
| `direct_address_rate` | @username, "you" — directness. |
| `profanity_vocabulary` | Top-50 — which profanity words are used. |
| `slang_vocabulary` | Top-50 — which slang terms are used. |
| `abbreviation_vocabulary` | Top-50 — which abbreviations are used. |

### Layer 8: Conversation Mechanics (`conversation.py`)

| Trait | Reason |
|-------|--------|
| `reply_probability` | How often the target replies vs initiates. |
| `reply_latency_median` | Median seconds to reply — responsiveness. |
| `reply_latency_distribution` | {median, p25, p75, p90, std} — response time profile. |
| `messages_per_burst` | Mean messages per burst (gaps < 300s). |
| `burst_duration` | Mean burst duration in seconds. |
| `inter_message_interval_distribution` | {median, p25, p75, std} — typing rhythm. |
| `conversation_initiation_rate` | How often the target starts conversations. |
| `conversation_termination_rate` | How often the target ends conversations. |
| `double_message_rate` | Consecutive messages < 60s — rapid-fire habits. |
| `triple_message_rate` | Three consecutive messages < 60s. |
| `followup_message_probability` | Probability of a follow-up within 300s. |
| `quote_usage_rate` | How often the target quotes others. |
| `reply_to_message_rate` | How often replies use the reply feature. |
| `edit_rate` | How often messages are edited. |
| `delete_rate` | How often messages are deleted. |
| `response_length_given_prompt_length` | Correlation between prompt and response length. |

### Layer 9: Temporal Behaviour / Drift (`temporal.py`)

| Trait | Reason |
|-------|--------|
| `hour_of_day_distribution` | 24-element histogram — circadian activity pattern. |
| `day_of_week_distribution` | 7-element histogram — weekly activity pattern. |
| `message_length_by_hour` | 24-element mean length per hour — time-of-day style shift. |
| `activity_session_length` | Mean session duration in minutes (gaps < 1800s). |
| `session_start_distribution` | Hour histogram of session starts. |
| `session_end_distribution` | Hour histogram of session ends. |
| `response_latency_by_hour` | Median reply latency per hour. |
| `persona_drift_30d` | JS divergence of vocabulary (30-day window) — short-term drift. |
| `persona_drift_90d` | JS divergence (90-day window) — medium-term drift. |
| `persona_drift_365d` | JS divergence (365-day window) — long-term drift. |
| `feature_half_life` | Estimated days for vocabulary turnover — how fast the persona changes. |
| `weekday_ratio` / `weekend_ratio` | Weekday vs weekend activity split. |
| `timezone_inference_confidence` | Confidence in timezone inference from activity peaks. |

### Layer 10: Conditional Behavioral Probabilities (`conditional.py`)

The biggest architectural upgrade: `author × context → P(feature | context)`.

| Trait | Reason |
|-------|--------|
| `conditional_probabilities` | Per-context rates: P(profanity\|context), P(long_message\|context), P(question\|context), P(emoji\|context), P(codeblock\|context), P(url\|context), P(technical_jargon\|context). Contexts: channel, reply/initiation, time-of-day, message length. |
| `context_distribution` | How messages are distributed across contexts. |
| `context_count` | Number of distinct contexts. |
| `context_entropy` | Shannon entropy of context distribution — how context-diverse the target is. |
| `context_conditioned_variance` | Variance of each feature across contexts — high variance = context-dependent behavior. |

### Layer 11: Interaction-Conditioned Style (`interaction.py`)

| Trait | Reason |
|-------|--------|
| `style_by_channel` | Per-channel style vectors — how the target adapts to different channels. |
| `style_by_recipient_class` | DM vs group style vectors — audience adaptation. |
| `style_by_time_period` | Morning/afternoon/evening/night style vectors — temporal style shift. |
| `style_by_message_type` | Initiation vs reply style vectors — role-dependent style. |
| `register_shift_score` | Max pairwise distance across contexts (0-1) — how much the persona shifts. |
| `recipient_style_distance` | Distance between DM and group styles. |
| `channel_style_distance` | Mean pairwise distance across channels. |
| `context_style_consistency` | 1 - register_shift_score — how consistent the persona is across contexts. |

### Layer 12: Dialogue Acts + Affective Expression (`dialogue_acts.py`)

| Trait | Reason |
|-------|--------|
| `dialogue_act_distribution` | {question, answer, request, command, suggestion, correction, challenge, agreement, disagreement, clarification, joke, complaint, observation, hypothesis, prediction} — conversational role profile. |
| `dialogue_act_transition_matrix` | {act → next_act: rate} — conversational flow patterns. |
| `sentiment_distribution` | {positive, neutral, negative} — emotional valence profile. |
| `emotion_marker_distribution` | {joy, anger, sadness, fear, surprise, disgust} — emotion encoding. |
| `emphasis_rate` | ALL CAPS, exclamation marks, bold — emphasis style. |
| `intensification_under_negative_sentiment` | Intensifier rate when negative — emotional amplification. |
| `profanity_given_negative_sentiment` | P(profanity \| negative) — anger expression style. |
| `punctuation_given_emotion` | Punctuation patterns conditioned on sentiment. |
| `message_length_given_emotion` | Mean length conditioned on sentiment — emotional verbosity. |
| `sarcasm_marker_rate` | "yeah right", "sure", "obviously" in negative context, "/s". |
| `humor_marker_rate` | "lol", "haha", "lmao" — humor expression. |

---

## V2 Summary

| Layer | Module | Trait count |
|-------|--------|-------------|
| L1 Orthographic | `orthographic.py` | 10 |
| L2 Error fingerprint | `errors.py` | 17 |
| L3 Syntax | `syntax.py` | 16 |
| L4 Discourse | `discourse.py` | 21 |
| L5 Formatting | `formatting.py` | 20 |
| L6 Notation | `notation.py` | 12 |
| L7 Register | `register.py` | 16 |
| L8 Conversation | `conversation.py` | 16 |
| L9 Temporal | `temporal.py` | 13 |
| L10 Conditional | `conditional.py` | 5 |
| L11 Interaction | `interaction.py` | 8 |
| L12 Dialogue/Affective | `dialogue_acts.py` | 11 |
| **V2 Total** | | **~165 trait categories** |
| **V1 + V2 Grand Total** | | **~207 distinct trait categories** |

All V2 modules are standard library only (re, collections, math, statistics,
datetime, hashlib, unicodedata). No spaCy, NLTK, or external dependencies.

All traits flow through the IndexOutbox → IndexProjector pipeline into
QIHSE (content + graph) and KEYSTONE (anchor lookup), making them searchable
and cross-indexable with the rest of the SPECTRA intelligence stack.
