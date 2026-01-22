# Advanced Features Guide

SPECTRA includes enterprise-grade enhancements for high-scale intelligence operations, AI/ML capabilities, and advanced OPSEC features.

## AI/ML Intelligence & Threat Scoring

SPECTRA includes advanced AI/ML capabilities for intelligence analysis:

### Threat Scoring System

Automatically identifies and scores threat actors on a 1-10 scale based on message content, behavior patterns, and network associations:

```bash
# Run the threat scoring demo
python examples/threat_scoring_demo.py
```

**Features:**
- **Multi-factor Scoring**: Combines keyword detection (30%), pattern matching (25%), behavioral analysis (20%), network associations (15%), and temporal patterns (10%)
- **Threat Classifications**: Harmless (1-2), Low Risk (3-4), Medium (5-6), High Risk (7-8), Critical/Nation-State (9-10)
- **Network Tracking**: "Guilt by association" scoring and community detection
- **Mermaid Visualizations**: Color-coded network graphs, community clusters, and activity timelines
- **Intelligence Reports**: Executive summaries with top threat actors and recommended actions

**Detection Capabilities:**
- 100+ critical security keywords (zero-day, APT groups, ransomware, etc.)
- Pattern matching for CVEs, crypto addresses, malware hashes, Tor addresses, IPs
- Behavioral flags for OPSEC awareness, code sharing, coordinated activity
- Network relationship tracking with 6 interaction types

**Usage:**
```python
from tgarchive.threat import (
    ThreatIndicatorDetector,
    ThreatScorer,
    ThreatNetworkTracker,
    MermaidGenerator
)

# Analyze messages for threat indicators
detector = ThreatIndicatorDetector()
indicators = detector.analyze_message(message_text, message_id)

# Calculate threat scores
threat_score, confidence = ThreatScorer.calculate_threat_score(
    keyword_indicators=indicators,
    # ... other parameters
)

# Generate network visualization
mermaid_graph = MermaidGenerator.generate_network_graph(
    profiles=threat_profiles,
    network_tracker=network_tracker
)
```

**Documentation:**
- **Usage Guide**: See `docs/THREAT_SCORING_USAGE.md`
- **System Architecture**: See `docs/THREAT_SCORING_SYSTEM_PLAN.md`
- **Demo Script**: See `examples/threat_scoring_demo.py`

### High-Performance Search Algorithms

SPECTRA includes optimized search algorithms for improved performance. These algorithms are automatically used when available.

**Note:** NOT_STISLA and QIHSE are third-party libraries with specific licensing requirements. See the [Third-Party Licenses](../reference/THIRD_PARTY_LICENSES.md) section for details.

### Entity Extraction & Knowledge Graphs

Named Entity Recognition and relationship mapping:

```python
from tgarchive.ai import NERModel, KnowledgeGraph

# Extract entities
ner = NERModel(model_name="en_core_web_lg")
entities = ner.extract_entities(text)

# Build knowledge graph
kg = KnowledgeGraph()
kg.add_entities_from_messages(messages)
influential = kg.pagerank(top_k=100)
```

**AI/ML Documentation:**
- **Full Feature Plan**: See `docs/AI_INTELLIGENCE_ENHANCEMENTS.md`
- **Requirements**: Install with `pip install -r requirements-ai.txt`
- **Demo**: See `examples/ai_features_demo.py`

## Advanced Intelligence Features

### Vector Database Integration

Scale to billions of messages with high-dimensional similarity search using **QIHSE (Quantum-Inspired Hilbert Space Expansion)** as the primary vector storage backend:

```bash
# Install vector database support
pip install -r requirements-advanced.txt
```

**Features:**
- **QIHSE Primary Backend**: Quantum-inspired vector storage with direct embedding storage (replaces Qdrant)
- **Dual-Database Architecture**: SQLite for metadata + QIHSE for semantic search
- **Semantic Search**: Find similar messages across millions of documents with quantum-inspired algorithms
- **Actor Similarity**: Identify actors with similar behavioral patterns
- **Anomaly Detection**: Flag messages that don't match normal patterns
- **High Confidence**: Quantum verification reduces false positives
- **Automatic Integration**: Messages automatically indexed during archiving (when enabled)

**Usage:**
```python
from tgarchive.db.vector_store import VectorStoreManager, VectorStoreConfig

# Initialize vector store (QIHSE is default)
config = VectorStoreConfig(
    backend="qihse",  # Primary: "qihse", fallback: "qdrant", "chromadb", "numpy"
    vector_size=384,
    distance_metric="cosine",
    confidence_threshold=0.95
)

store = VectorStoreManager(config)

# Index messages with embeddings
store.index_message(
    message_id=123,
    embedding=message_embedding,
    metadata={"user_id": 1001, "threat_score": 8.5}
)

# Semantic search (uses QIHSE quantum-inspired algorithm)
results = store.semantic_search(
    query_embedding=query_emb,
    top_k=10,
    filters={"threat_score": {"gte": 7.0}}
)
```

**Note:** QIHSE completely replaces Qdrant as the primary vector storage. Qdrant is available as an optional fallback if QIHSE is unavailable.

### CNSA 2.0 Quantum-Resistant Cryptography

Post-quantum cryptography for future-proof security:

**Standards Compliance:**
- **ML-KEM-1024** (FIPS 203): Quantum-resistant key encapsulation
- **ML-DSA-87** (FIPS 204): Quantum-resistant digital signatures
- **SHA-384** (FIPS 180-4): 384-bit secure hashing
- **NSA CNSA 2.0 Compliant**: Future-proof against quantum attacks

**Features:**
- Hybrid encryption (ML-KEM-1024 + AES-256-GCM)
- Digital signatures for threat reports (ML-DSA-87)
- Secure key management with encrypted keystore
- Archive encryption with quantum resistance
- Database integrity verification

**Usage:**
```python
from tgarchive.crypto import CNSA20CryptoManager, CNSAKeyManager

# Initialize crypto manager
crypto = CNSA20CryptoManager()

# Generate quantum-resistant keys
kem_keys = crypto.generate_kem_keypair()
sig_keys = crypto.generate_signature_keypair()

# Encrypt data
encrypted = crypto.encrypt_data(plaintext, recipient_public_key)

# Sign threat reports
signed_report = crypto.create_signed_package(
    report_data,
    signing_key,
    signer_id="analyst_001"
)

# Verify signature
is_valid = crypto.verify_signed_package(signed_report, public_key)

# Secure key management
key_manager = CNSAKeyManager("./keys/keystore.enc")
key_manager.create_keystore(password="SecurePassword")
```

### Temporal Analysis & Prediction

Analyze time-based patterns in threat actor behavior:

**Capabilities:**
- Activity timeline analysis with burst detection
- Timezone inference from peak activity hours
- Sleep pattern analysis for geolocation
- Campaign periodicity detection
- Predictive activity forecasting
- Coordinated campaign detection

**Usage:**
```python
from tgarchive.threat.temporal import TemporalAnalyzer

analyzer = TemporalAnalyzer()

# Analyze activity patterns
patterns = analyzer.analyze_activity_patterns(messages)
# Returns: peak_hours, peak_days, inferred_timezone, burst_periods, regularity_score

# Detect coordinated campaigns
campaigns = analyzer.detect_coordinated_campaigns(
    actor_messages,
    time_window_minutes=30,
    min_actors=3
)

# Predict next activity
prediction = analyzer.predict_next_activity(messages, forecast_hours=24)
# Returns: likely_active_hours, probability_by_hour, confidence
```

### Attribution Engine

Cross-platform identity correlation and behavioral analysis:

**Features:**
- Writing style analysis (stylometry)
- Vocabulary richness and sentence complexity
- Tool/technique fingerprinting (Metasploit, Cobalt Strike, etc.)
- Operational pattern matching (recon → exploit → post-exploit)
- AI-generated content detection
- Cross-account correlation
- Language proficiency assessment

**Usage:**
```python
from tgarchive.threat.attribution import AttributionEngine

engine = AttributionEngine()

# Analyze writing style
profile = engine.analyze_writing_style(messages)
# Returns: vocabulary_size, avg_sentence_length, technical_density, language

# Find similar actors (potential sock puppets)
similar = engine.find_similar_actors_by_style(
    target_profile,
    candidate_profiles,
    threshold=0.85
)

# Detect tool fingerprints
tools = engine.detect_tool_fingerprints(messages)
# Returns: {"Metasploit": [...matches...], "Cobalt Strike": [...]}

# Detect AI-generated content
ai_analysis = engine.detect_ai_generated_content(messages)
# Returns: ai_likelihood, indicators, confidence

# Correlate accounts
account_clusters = engine.correlate_accounts(profiles, min_similarity=0.85)
# Returns: [[1001, 1005, 1009], [2003, 2015]]  # Likely same actor
```

### Advanced Features Demo

The Advanced Features Demo has been moved to a dedicated folder with comprehensive documentation:

```bash
# Run comprehensive demo of all advanced features
python examples/advanced_features/demo.py
```

**Demonstrates:**
- Vector database operations using QIHSE (indexing, searching, clustering)
- Post-quantum encryption and digital signatures (CNSA 2.0)
- Temporal pattern analysis and prediction
- Attribution analysis and tool fingerprinting
- AI content detection

### Advanced Features Documentation

**Comprehensive Documentation:**
- **Main Guide**: `examples/advanced_features/README.md` - Overview and quick start
- **Architecture**: `examples/advanced_features/docs/ARCHITECTURE.md` - System architecture and data flow
- **Vector Database**: `examples/advanced_features/docs/VECTOR_DATABASE.md` - QIHSE storage and search
- **CNSA Cryptography**: `examples/advanced_features/docs/CNSA_CRYPTOGRAPHY.md` - Post-quantum crypto
- **Temporal Analysis**: `examples/advanced_features/docs/TEMPORAL_ANALYSIS.md` - Activity patterns
- **Attribution Engine**: `examples/advanced_features/docs/ATTRIBUTION_ENGINE.md` - Cross-platform correlation
- **Example Config**: `examples/advanced_features/config/example_advanced_config.json`

**Integration:**
- Advanced features are automatically integrated into the archiving workflow when enabled in `spectra_config.json`
- See `examples/advanced_features/README.md` for configuration details

**Legacy Documentation:**
- **Architecture & Planning**: `docs/ADVANCED_ENHANCEMENTS_PLAN.md` (historical reference)
- **Requirements**: `requirements-advanced.txt`

### INT8 Neural Acceleration (Planned)

**Leverage 130 TOPS INT8 compute for real-time intelligence at scale:**

**Capabilities:**
- **10,000+ messages/second** continuous psycho-forensic analysis
- **<10ms** actor correlation across 10 million profiles
- **Real-time radicalization detection** with sub-second alerting
- **GPU/NPU acceleration** (NVIDIA/Intel/AMD support)

**Psycho-Forensic Linguistics:**
- Big Five personality profiling (OCEAN model)
- Dark Triad detection (Narcissism, Machiavellianism, Psychopathy)
- Deception detection (hedging, distancing, verbosity)
- Radicalization stage tracking (0-5 scale progression)
- Emotional state analysis (anger, fear, confidence)

**Hardware-Accelerated Operations:**
- INT8 quantization (4x throughput vs FP32)
- GPU tensor cores for vector similarity
- NPU acceleration for linguistic models
- Batch inference at 100μs/message latency

**Documentation:**
- **Master Plan**: `docs/INT8_ACCELERATION_PLAN.md` (13 sections, comprehensive architecture)
- **Implementation Status**: `docs/INT8_IMPLEMENTATION_STATUS.md`
- **Timeline**: 10-week phased implementation
- **Target Performance**: 90% utilization of 130 TOPS, <2% accuracy loss

**Deployment Scenarios:**
- Workstation: NVIDIA RTX 4070 (150 TOPS) - $600
- Laptop: Intel Core Ultra 7 (134 TOPS combined) - Mobile ops
- Cloud: 4× NVIDIA A10G (600+ TOPS) - Auto-scaling

## Advanced OPSEC & Red Team Features

- **Account & API key rotation**: Smart, persistent, and SQL-audited
- **Proxy rotation**: Supports rotating proxies for every operation
- **SQL audit trail**: All group discovery, joins, and archiving are logged in the database
- **Sidecar metadata**: Forensic metadata and integrity checksums for all archives
- **Persistent state**: All operations are resumable and stateful
- **Modular backend**: All TUI/CLI operations use the same importable modules for maximum reusability
- **Detection/OPSEC notes**: Designed for red team and forensic use, with anti-detection and audit features
