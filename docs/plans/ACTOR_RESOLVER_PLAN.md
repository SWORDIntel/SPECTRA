# WP4: Actor Identity-Resolution Engine — Implementation Plan

## Goal

Replace `"similar writing = probably same actor"` with `P(A=B | E_1, E_2, ..., E_n)` — a traceable, calibrated attribution dossier.

## Architecture

```
tgarchive/intelligence/
├── features/
│   ├── __init__.py
│   ├── linguistic.py      # character n-grams, function words, punctuation, emoji, etc.
│   ├── temporal.py        # circadian, weekday/weekend, response latency, bursts
│   ├── infrastructure.py  # wallets, URLs, domains, IPs, onion addresses, bot IDs
│   ├── telegram_native.py # shared channels, replies, forwards, username changes
│   ├── media.py           # perceptual hashes, exact hashes, OCR, EXIF, file naming
│   └── commercial.py      # pricing, currency, min order, product taxonomy, sales language
├── resolver.py            # ActorIdentityResolver — combines feature families
└── schema.py              # (already exists)
```

## Feature Extractor Interface

Every feature family module exports a `extract_*` function that returns a feature dict:

```python
def extract_linguistic_features(messages: List[Dict]) -> Dict[str, float]:
    """Extract linguistic features from a list of messages.
    Returns a dict of feature_name -> value (float).
    """
```

And a `compare_*` function that compares two feature dicts:

```python
def compare_linguistic_features(feat_a: Dict, feat_b: Dict) -> Tuple[float, float]:
    """Compare two linguistic feature dicts.
    Returns (similarity_score, confidence).
    """
```

## Feature Families

### linguistic.py
- character n-gram distribution (2-gram, 3-gram, 4-gram)
- function-word frequency distribution (top 50 function words)
- punctuation sequence patterns
- whitespace habits (trailing spaces, double spaces, tab usage)
- spelling/error fingerprints (common misspellings, typo rate)
- contraction usage rate
- emoji patterns (frequency, type distribution, position)
- lexical richness (type-token ratio, Yule's K)
- code-switching detection (language mixing)
- message segmentation behavior (line breaks per message, paragraph style)
- avg message length, word length, sentence length
- uppercase ratio, digit ratio, special char ratio

### temporal.py
- circadian activity distribution (24-hour histogram)
- weekday vs weekend activity ratio
- response latency distribution (median, IQR)
- burst characteristics (burst frequency, intensity)
- inactivity windows (longest gap, typical gap)
- timezone inference confidence

### infrastructure.py
- wallet addresses used (BTC, ETH, XMR) with set overlap
- URLs/domains shared with set overlap
- IP addresses mentioned
- onion addresses used
- bot IDs referenced
- contact identifiers (phone numbers, emails, Telegram handles)

### telegram_native.py
- shared channels (set overlap)
- reply relationships (who replies to whom)
- forwards (forwarded from same sources)
- username changes over time
- user-ID persistence
- common administrators
- shared media (media IDs posted by both)

### media.py
- perceptual hash overlap (pHash, dHash)
- exact hash overlap (SHA256)
- OCR string similarity
- EXIF data overlap
- file naming conventions (patterns, extensions, prefixes)
- archive structure (zip/rar naming, internal structure)

### commercial.py
- pricing patterns (price points, currency, ranges)
- currency preference
- minimum order sizes
- product taxonomy (categories sold)
- sales language (boilerplate phrases, templates)
- negotiation behavior (discount patterns, escrow usage)

## resolver.py — ActorIdentityResolver

```python
class ActorIdentityResolver:
    """
    Combines evidence from all feature families to produce
    P(A=B | E_1, ..., E_n) with full provenance.
    """
    def resolve(self, actor_a_messages, actor_b_messages, actor_a_id, actor_b_id) -> ActorHypothesis:
        # 1. Extract features from each family
        # 2. Compare within each family → (score, confidence)
        # 3. Build AnalysisEvidence per family
        # 4. Combine into competing hypotheses:
        #    H0: same human, H1: different human, H2: shared org,
        #    H3: automation/bot, H4: copied content, H5: compromised
        # 5. Return ActorHypothesis with supporting + contradicting evidence
```

## Anti-Double-Counting Rule

Correlated evidence must be deduplicated. For example:
- same URL, same domain, same hostname → one infrastructure observation, not three
- Implementation: group evidence by correlation cluster, take max score per cluster

## Output

```json
{
  "same_actor_probability": 0.93,
  "confidence": 0.81,
  "support": {
    "stylometry": 0.84,
    "temporal": 0.73,
    "infrastructure": 0.98,
    "social_graph": 0.88
  },
  "contradictions": {
    "language": 0.21
  },
  "insufficient_evidence": ["media", "commercial"]
}
```
