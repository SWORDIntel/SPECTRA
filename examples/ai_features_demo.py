#!/usr/bin/env python3
"""
SPECTRA AI Features Demonstration
==================================
Shows how to use the new AI/ML intelligence capabilities.

Features demonstrated:
1. Semantic search across messages
2. Entity extraction and network analysis
3. Knowledge graph construction
"""
import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from tgarchive.ai.semantic_search import SemanticSearchEngine
from tgarchive.ai.entity_extraction import EntityNetworkAnalyzer

# Example messages (in production, load from database)
EXAMPLE_MESSAGES = [
    {
        "id": 1,
        "channel_id": 123,
        "content": "President Putin announced new military operation in Eastern Ukraine today.",
        "date": "2025-01-15T10:30:00Z",
        "user_id": 1001,
    },
    {
        "id": 2,
        "channel_id": 123,
        "content": "Wagner Group forces reported near Bakhmut. Prigozhin making statements on Telegram.",
        "date": "2025-01-15T11:45:00Z",
        "user_id": 1002,
    },
    {
        "id": 3,
        "channel_id": 124,
        "content": "NATO Secretary General met with Ukrainian President Zelenskyy in Brussels.",
        "date": "2025-01-15T14:20:00Z",
        "user_id": 1003,
    },
    {
        "id": 4,
        "channel_id": 123,
        "content": "Russian Ministry of Defense released update on special military operation.",
        "date": "2025-01-15T16:00:00Z",
        "user_id": 1004,
    },
    {
        "id": 5,
        "channel_id": 125,
        "content": "Wagner Group chief Prigozhin criticizes Russian military leadership in video message.",
        "date": "2025-01-15T18:30:00Z",
        "user_id": 1005,
    },
]


def demo_semantic_search():
    """Demonstrate semantic search functionality."""
    print("\n" + "=" * 70)
    print("SEMANTIC SEARCH DEMONSTRATION")
    print("=" * 70)

    # Initialize search engine
    print("\n1. Initializing semantic search engine...")
    engine = SemanticSearchEngine(
        model_name="all-MiniLM-L6-v2",  # Lightweight model
        device="cpu",  # Use "cuda" if GPU available
        persist_directory=Path("./data/demo_vector_db"),
    )

    # Index messages
    print("\n2. Indexing example messages...")
    indexed_count = engine.index_messages(
        messages=EXAMPLE_MESSAGES,
        show_progress=True,
    )
    print(f"   ✓ Indexed {indexed_count} messages")

    # Search queries
    queries = [
        "What did Wagner Group do?",
        "Military operations in Ukraine",
        "NATO meetings",
    ]

    print("\n3. Running semantic search queries...")
    for query in queries:
        print(f"\n   Query: '{query}'")
        results = engine.search(query, top_k=3)

        for i, result in enumerate(results, 1):
            print(f"\n   Result {i} (score: {result.score:.3f}):")
            print(f"   Message ID: {result.message_id}")
            print(f"   Content: {result.content[:100]}...")

    # Get statistics
    stats = engine.get_stats()
    print("\n4. Search engine statistics:")
    for key, value in stats.items():
        print(f"   {key}: {value}")


def demo_entity_extraction():
    """Demonstrate entity extraction and network analysis."""
    print("\n" + "=" * 70)
    print("ENTITY EXTRACTION & NETWORK ANALYSIS DEMONSTRATION")
    print("=" * 70)

    # Initialize analyzer
    print("\n1. Initializing entity network analyzer...")
    analyzer = EntityNetworkAnalyzer(
        ner_model="en_core_web_sm",  # Download with: python -m spacy download en_core_web_sm
    )

    # Process messages
    print("\n2. Extracting entities from messages...")
    stats = analyzer.process_messages(EXAMPLE_MESSAGES)

    print("\n   Statistics:")
    for key, value in stats.items():
        print(f"   {key}: {value}")

    # Get influential entities
    print("\n3. Top influential entities (by PageRank):")
    influential = analyzer.get_influential_entities(top_k=10)

    for i, (entity, score) in enumerate(influential[:10], 1):
        # Parse entity format "canonical:TYPE"
        parts = entity.split(":")
        canonical = parts[0] if parts else entity
        entity_type = parts[1] if len(parts) > 1 else "UNKNOWN"
        print(f"   {i}. {canonical} ({entity_type}) - Score: {score:.4f}")

    # Get entity details
    print("\n4. Entity timeline examples:")

    # Try to find some key entities
    all_entities = analyzer.resolver.get_all_entities()
    for entity in all_entities[:5]:  # Show first 5
        timeline = analyzer.get_entity_timeline(
            entity.canonical_form or entity.text,
            entity.type
        )
        if timeline:
            print(f"\n   Entity: {timeline['entity']}")
            print(f"   Type: {timeline['type']}")
            print(f"   Mentions: {timeline['mentions']}")
            print(f"   First seen: {timeline['first_seen']}")
            print(f"   Aliases: {timeline['aliases']}")

    # Export knowledge graph
    print("\n5. Exporting knowledge graph...")
    export_path = Path("./data/demo_knowledge_graph.gexf")
    export_path.parent.mkdir(parents=True, exist_ok=True)
    analyzer.knowledge_graph.export_to_gexf(export_path)
    print(f"   ✓ Graph exported to {export_path}")
    print(f"   (Open in Gephi for visualization)")


def demo_combined_analysis():
    """Demonstrate combined semantic search + entity analysis."""
    print("\n" + "=" * 70)
    print("COMBINED ANALYSIS DEMONSTRATION")
    print("=" * 70)

    print("\n1. Scenario: Find all information about 'Wagner Group'")

    # Step 1: Semantic search
    print("\n   Step 1: Semantic search for relevant messages...")
    search_engine = SemanticSearchEngine(device="cpu")
    search_engine.index_messages(EXAMPLE_MESSAGES)

    results = search_engine.search("Wagner Group", top_k=5)
    print(f"   Found {len(results)} relevant messages")

    # Step 2: Extract entities from results
    print("\n   Step 2: Extract entities from relevant messages...")
    analyzer = EntityNetworkAnalyzer()

    relevant_messages = [
        msg for msg in EXAMPLE_MESSAGES
        if any(r.message_id == msg["id"] for r in results)
    ]

    analyzer.process_messages(relevant_messages)

    # Step 3: Get entity network
    print("\n   Step 3: Analyze entity co-occurrences...")
    all_entities = analyzer.resolver.get_all_entities()

    print(f"\n   Entities found: {len(all_entities)}")
    for entity in all_entities:
        print(f"   - {entity.text} ({entity.type}): {entity.mentions} mentions")

    # Step 4: Get relationships
    print("\n   Step 4: Entity relationships:")
    graph_stats = analyzer.knowledge_graph.get_stats()
    print(f"   Nodes: {graph_stats.get('nodes', 0)}")
    print(f"   Edges: {graph_stats.get('edges', 0)}")


def main():
    """Run all demonstrations."""
    print("\n" + "=" * 70)
    print("SPECTRA AI INTELLIGENCE FEATURES DEMONSTRATION")
    print("=" * 70)
    print("\nThis demo shows the new AI/ML capabilities:")
    print("• Semantic search (find messages by meaning, not just keywords)")
    print("• Entity extraction (identify people, organizations, locations)")
    print("• Network analysis (map relationships between entities)")
    print("• Knowledge graphs (visualize entity connections)")

    # Check dependencies
    missing_deps = []

    try:
        import sentence_transformers
    except ImportError:
        missing_deps.append("sentence-transformers")

    try:
        import spacy
    except ImportError:
        missing_deps.append("spacy")

    if missing_deps:
        print("\n⚠️  WARNING: Missing dependencies!")
        print("Install with:")
        print(f"  pip install {' '.join(missing_deps)}")
        print("\nFor spaCy, also download language models:")
        print("  python -m spacy download en_core_web_sm")
        print("\nContinuing with limited functionality...\n")

    # Run demonstrations
    try:
        demo_semantic_search()
    except Exception as e:
        print(f"\n❌ Semantic search demo failed: {e}")
        print("   This might be due to missing dependencies.")

    try:
        demo_entity_extraction()
    except Exception as e:
        print(f"\n❌ Entity extraction demo failed: {e}")
        print("   This might be due to missing spaCy model.")
        print("   Download with: python -m spacy download en_core_web_sm")

    try:
        demo_combined_analysis()
    except Exception as e:
        print(f"\n❌ Combined analysis demo failed: {e}")

    print("\n" + "=" * 70)
    print("DEMONSTRATION COMPLETE")
    print("=" * 70)
    print("\nNext steps:")
    print("1. Install AI dependencies: pip install -r requirements-ai.txt")
    print("2. Download spaCy models: python -m spacy download en_core_web_sm")
    print("3. Integrate with your SPECTRA database")
    print("4. Scale to millions of messages")
    print("\nFor full documentation, see: docs/AI_INTELLIGENCE_ENHANCEMENTS.md")


if __name__ == "__main__":
    main()
