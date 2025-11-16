"""
SPECTRA Advanced Features Demonstration

Showcases:
1. Vector database integration (Qdrant/ChromaDB)
2. CNSA 2.0 post-quantum cryptography
3. Enhanced threat actor tracking
   - Temporal analysis
   - Attribution engine
   - Writing style analysis

Usage:
    python examples/advanced_features_demo.py

Author: SPECTRA Intelligence System
"""

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

print("=" * 70)
print("SPECTRA ADVANCED FEATURES DEMONSTRATION")
print("=" * 70)
print()

# ============================================================================
# 1. VECTOR DATABASE DEMONSTRATION
# ============================================================================

print("1. VECTOR DATABASE INTEGRATION")
print("-" * 70)

try:
    from tgarchive.db.vector_store import VectorStoreManager, VectorStoreConfig
    import numpy as np

    # Configure vector store
    config = VectorStoreConfig(
        backend="qdrant",  # Try Qdrant first
        path="./data/demo_vectors",
        vector_size=384,
        distance_metric="cosine"
    )

    try:
        store = VectorStoreManager(config)
        print(f"✓ Vector store initialized: {store.store.__class__.__name__}")
    except Exception as e:
        print(f"! Qdrant not available ({e}), trying ChromaDB...")
        config.backend = "chromadb"
        try:
            store = VectorStoreManager(config)
            print(f"✓ Vector store initialized: ChromaDB")
        except Exception as e2:
            print(f"! ChromaDB not available ({e2}), using Numpy fallback...")
            config.backend = "numpy"
            store = VectorStoreManager(config)
            print(f"✓ Vector store initialized: Numpy (testing only)")

    # Generate sample embeddings (normally from sentence-transformers)
    print("\nIndexing sample messages...")
    sample_messages = [
        (1, "Discussing zero-day exploit in popular browser"),
        (2, "Ransomware campaign targeting healthcare sector"),
        (3, "APT28 using new infrastructure for C2"),
        (4, "Normal conversation about weather"),
        (5, "Cryptocurrency payment for malware"),
    ]

    for msg_id, text in sample_messages:
        # Simulate embedding (in production, use actual embedding model)
        embedding = np.random.rand(384).astype(np.float32)

        store.index_message(
            message_id=msg_id,
            embedding=embedding,
            metadata={
                "user_id": 1000 + (msg_id % 3),
                "threat_score": 8.0 if "apt" in text.lower() or "exploit" in text.lower() else 3.0,
                "date": (datetime.now() - timedelta(days=msg_id)).isoformat(),
                "channel_id": 5000
            }
        )

    print(f"✓ Indexed {len(sample_messages)} messages")

    # Search for similar messages
    query_embedding = np.random.rand(384).astype(np.float32)
    results = store.semantic_search(
        query_embedding=query_embedding,
        top_k=3,
        filters={"threat_score": {"gte": 7.0}}
    )

    print(f"\n✓ Found {len(results)} similar high-threat messages:")
    for r in results:
        print(f"  - Message {r.payload['message_id']}: score={r.score:.3f}, "
              f"threat={r.payload['threat_score']}")

    # Statistics
    stats = store.get_statistics()
    print(f"\n✓ Vector store stats: {stats}")

    print("\n✅ Vector database demo complete!")

except ImportError as e:
    print(f"⚠ Vector database libraries not installed: {e}")
    print("  Install with: pip install -r requirements-advanced.txt")

except Exception as e:
    print(f"❌ Vector database demo failed: {e}")

print()

# ============================================================================
# 2. CNSA 2.0 POST-QUANTUM CRYPTOGRAPHY
# ============================================================================

print("2. CNSA 2.0 POST-QUANTUM CRYPTOGRAPHY")
print("-" * 70)

try:
    from tgarchive.crypto import CNSA20CryptoManager, CNSAKeyManager

    # Initialize crypto manager
    crypto = CNSA20CryptoManager()

    # Show algorithm info
    info = crypto.get_algorithm_info()
    print("Algorithm Information:")
    print(f"  KEM: {info['kem']['algorithm']} ({info['kem']['standard']})")
    print(f"  Signature: {info['signature']['algorithm']} ({info['signature']['standard']})")
    print(f"  Hash: {info['hash']['algorithm']} ({info['hash']['standard']})")
    print(f"  Quantum Resistant: {info['quantum_resistant']}")
    print()

    # Generate key pairs
    print("Generating post-quantum key pairs...")
    recipient_kem = crypto.generate_kem_keypair(key_id="demo_recipient")
    sender_sig = crypto.generate_signature_keypair(key_id="demo_sender")
    print(f"✓ KEM key pair: {len(recipient_kem.public_key)} byte public key")
    print(f"✓ Signature key pair: {len(sender_sig.public_key)} byte public key")
    print()

    # Test encryption/decryption
    plaintext = b"Classified threat intelligence report - Eyes Only"
    print(f"Encrypting: {plaintext.decode()}")

    encrypted = crypto.encrypt_data(plaintext, recipient_kem.public_key)
    print(f"✓ Encrypted with {encrypted.algorithm}")
    print(f"  KEM ciphertext: {len(encrypted.kem_ciphertext)} bytes")
    print(f"  AES ciphertext: {len(encrypted.aes_ciphertext)} bytes")
    print()

    decrypted = crypto.decrypt_data(encrypted, recipient_kem.secret_key)
    print(f"Decrypted: {decrypted.decode()}")
    print(f"✓ Decryption successful: {plaintext == decrypted}")
    print()

    # Test digital signatures
    print("Creating digitally signed package...")
    signed = crypto.create_signed_package(plaintext, sender_sig.secret_key, signer_id="analyst_001")
    print(f"✓ Signed with {signed.algorithm}")
    print(f"  Signature: {len(signed.signature)} bytes")
    print(f"  SHA-384: {signed.hash_sha384[:32]}...")
    print()

    is_valid = crypto.verify_signed_package(signed, sender_sig.public_key)
    print(f"✓ Signature verification: {is_valid}")
    print()

    # Test key management
    print("Testing secure key management...")
    key_manager = CNSAKeyManager("./data/demo_keystore.enc")

    try:
        key_manager.create_keystore(
            password="DemoPassword123!@#",
            kem_key_id="master_kem",
            sig_key_id="master_sig"
        )
        print("✓ Created encrypted keystore")

        keys = key_manager.list_keys("DemoPassword123!@#")
        print(f"✓ Keystore contains {len(keys)} key pairs:")
        for key in keys:
            print(f"  - {key['key_id']}: {key['type']} ({key['algorithm']})")

    except FileExistsError:
        print("✓ Keystore already exists (from previous run)")

    print("\n✅ CNSA 2.0 cryptography demo complete!")

except ImportError as e:
    print(f"⚠ CNSA 2.0 libraries not installed: {e}")
    print("  Install with: pip install liboqs-python cryptography")

except Exception as e:
    print(f"❌ CNSA 2.0 demo failed: {e}")
    import traceback
    traceback.print_exc()

print()

# ============================================================================
# 3. TEMPORAL ANALYSIS
# ============================================================================

print("3. TEMPORAL ANALYSIS")
print("-" * 70)

try:
    from tgarchive.threat.temporal import TemporalAnalyzer

    analyzer = TemporalAnalyzer()

    # Create sample activity data
    base_date = datetime(2024, 6, 15)
    sample_messages = [
        {"date": base_date + timedelta(days=0, hours=9, minutes=30), "text": "msg1"},
        {"date": base_date + timedelta(days=0, hours=10, minutes=15), "text": "msg2"},
        {"date": base_date + timedelta(days=0, hours=14, minutes=45), "text": "msg3"},
        {"date": base_date + timedelta(days=1, hours=9, minutes=20), "text": "msg4"},
        {"date": base_date + timedelta(days=1, hours=10, minutes=30), "text": "msg5"},
        {"date": base_date + timedelta(days=2, hours=11, minutes=0), "text": "msg6"},
        {"date": base_date + timedelta(days=3, hours=9, minutes=45), "text": "msg7"},
    ]

    # Analyze patterns
    patterns = analyzer.analyze_activity_patterns(sample_messages)

    print("Activity Patterns:")
    print(f"  Peak hours: {patterns['peak_hours']}")
    print(f"  Peak days: {patterns['peak_days']}")
    print(f"  Inferred timezone: {patterns['inferred_timezone']}")
    print(f"  Regularity score: {patterns['regularity_score']}/10")
    print(f"  Active days: {patterns['active_days']}")
    print(f"  Total messages: {patterns['total_messages']}")
    print()

    # Detect bursts
    if patterns['burst_periods']:
        print(f"Detected {len(patterns['burst_periods'])} burst periods:")
        for burst in patterns['burst_periods'][:3]:
            print(f"  - {burst['start']}: {burst['message_count']} msgs, "
                  f"intensity {burst['intensity']}")
    else:
        print("No burst activity detected")
    print()

    # Predict next activity
    prediction = analyzer.predict_next_activity(sample_messages)
    print("Activity Prediction:")
    print(f"  Likely active hours: {prediction['likely_active_hours']}")
    print(f"  Confidence: {prediction['confidence']:.1%}")
    print()

    print("✅ Temporal analysis demo complete!")

except Exception as e:
    print(f"❌ Temporal analysis demo failed: {e}")
    import traceback
    traceback.print_exc()

print()

# ============================================================================
# 4. ATTRIBUTION ENGINE
# ============================================================================

print("4. ATTRIBUTION ENGINE")
print("-" * 70)

try:
    from tgarchive.threat.attribution import AttributionEngine

    engine = AttributionEngine()

    # Sample messages from a threat actor
    actor_messages = [
        {
            "id": 1,
            "text": "Running nmap scan on target network to enumerate open ports and services."
        },
        {
            "id": 2,
            "text": "Found vulnerability CVE-2024-1234. Preparing exploit with msfconsole."
        },
        {
            "id": 3,
            "text": "Setting payload to reverse_tcp. LHOST=192.168.1.100 LPORT=4444."
        },
        {
            "id": 4,
            "text": "Shell access obtained. Attempting privilege escalation using local exploit."
        },
        {
            "id": 5,
            "text": "Using mimikatz to dump credentials from lsass process."
        }
    ]

    # Analyze writing style
    profile = engine.analyze_writing_style(actor_messages)
    print("Writing Style Profile:")
    print(f"  Vocabulary size: {profile.vocabulary_size}")
    print(f"  Avg sentence length: {profile.avg_sentence_length:.1f} words")
    print(f"  Technical density: {profile.technical_density:.1%}")
    print(f"  Proficiency level: {profile.proficiency_level}")
    print(f"  Language: {profile.language}")
    print()

    # Detect tool fingerprints
    tools = engine.detect_tool_fingerprints(actor_messages)
    print("Tool Fingerprints Detected:")
    for tool, matches in tools.items():
        print(f"  {tool}: {len(matches)} matches")
        for match in matches[:2]:  # Show first 2
            print(f"    - Pattern: {match['matched_pattern']}")
    print()

    # Detect operational patterns
    patterns = engine.detect_operational_patterns(actor_messages)
    print("Operational Patterns:")
    print(f"  Reconnaissance: {len(patterns['reconnaissance'])} messages")
    print(f"  Exploitation: {len(patterns['exploitation'])} messages")
    print(f"  Post-exploitation: {len(patterns['post_exploitation'])} messages")
    print(f"  OPSEC indicators: {len(patterns['opsec_indicators'])} messages")
    print(f"  Attack chains: {len(patterns['attack_chains'])} detected")
    if patterns['attack_chains']:
        for chain in patterns['attack_chains']:
            print(f"    - {chain['type']}: {' → '.join(chain['stages'])}")
    print()

    # AI content detection
    ai_detect = engine.detect_ai_generated_content(actor_messages)
    print("AI-Generated Content Analysis:")
    print(f"  AI likelihood: {ai_detect['ai_likelihood']:.1%}")
    print(f"  Confidence: {ai_detect['confidence']:.1%}")
    if ai_detect['indicators']:
        print(f"  Indicators:")
        for indicator in ai_detect['indicators']:
            print(f"    - {indicator}")
    print()

    print("✅ Attribution engine demo complete!")

except Exception as e:
    print(f"❌ Attribution demo failed: {e}")
    import traceback
    traceback.print_exc()

print()

# ============================================================================
# SUMMARY
# ============================================================================

print("=" * 70)
print("DEMO SUMMARY")
print("=" * 70)
print()
print("✓ Vector Database: High-dimensional similarity search for millions of messages")
print("✓ CNSA 2.0 Crypto: Quantum-resistant encryption and signatures")
print("✓ Temporal Analysis: Activity patterns, timezone inference, burst detection")
print("✓ Attribution Engine: Writing style analysis, tool fingerprinting, AI detection")
print()
print("For production use:")
print("  1. Install dependencies: pip install -r requirements-advanced.txt")
print("  2. Configure vector store backend (Qdrant recommended)")
print("  3. Generate and securely store CNSA 2.0 keys")
print("  4. Integrate with existing SPECTRA workflows")
print()
print("Documentation:")
print("  - Vector DB: docs/ADVANCED_ENHANCEMENTS_PLAN.md (Section 1)")
print("  - CNSA 2.0: docs/ADVANCED_ENHANCEMENTS_PLAN.md (Section 2)")
print("  - Threat Tracking: docs/ADVANCED_ENHANCEMENTS_PLAN.md (Section 3)")
print()
print("=" * 70)
