"""
SPECTRA Entity Extraction & Network Analysis Module
===================================================
Implements Named Entity Recognition (NER) and knowledge graph construction.

Features:
- Multi-lingual NER (people, organizations, locations, events)
- Entity resolution and deduplication
- Knowledge graph construction
- Network analysis (centrality, communities, influence)
- Temporal entity tracking
"""
from __future__ import annotations

import hashlib
import json
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# Optional dependencies with graceful fallback
try:
    import spacy
    HAS_SPACY = True
except ImportError:
    HAS_SPACY = False
    logger.warning("spaCy not installed. Entity extraction will be limited.")

try:
    import networkx as nx
    HAS_NETWORKX = True
except ImportError:
    HAS_NETWORKX = False
    logger.warning("networkx not installed. Network analysis will be limited.")


@dataclass
class Entity:
    """A single extracted entity."""
    text: str
    type: str  # PER, ORG, LOC, EVENT, etc.
    confidence: float = 1.0
    canonical_form: Optional[str] = None
    aliases: Set[str] = field(default_factory=set)
    mentions: int = 0
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __hash__(self) -> int:
        """Make entity hashable for use in sets/dicts."""
        return hash((self.canonical_form or self.text, self.type))

    def __eq__(self, other) -> bool:
        """Equality based on canonical form and type."""
        if not isinstance(other, Entity):
            return False
        return (
            (self.canonical_form or self.text) == (other.canonical_form or other.text)
            and self.type == other.type
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "text": self.text,
            "canonical_form": self.canonical_form or self.text,
            "type": self.type,
            "confidence": self.confidence,
            "aliases": list(self.aliases),
            "mentions": self.mentions,
            "first_seen": self.first_seen.isoformat() if self.first_seen else None,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
            "metadata": self.metadata,
        }


@dataclass
class Relationship:
    """A relationship between two entities."""
    source: str
    target: str
    relationship_type: str  # MENTIONS, AFFILIATED_WITH, LOCATED_IN, etc.
    weight: float = 1.0
    timestamp: Optional[datetime] = None
    context: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "source": self.source,
            "target": self.target,
            "type": self.relationship_type,
            "weight": self.weight,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "context": self.context,
            "metadata": self.metadata,
        }


class NERModel:
    """
    Named Entity Recognition using spaCy.
    Supports multiple languages and custom entity types.
    """

    # Entity type mapping
    ENTITY_TYPE_MAP = {
        "PERSON": "PER",
        "PER": "PER",
        "ORG": "ORG",
        "GPE": "LOC",  # Geopolitical entity -> Location
        "LOC": "LOC",
        "FAC": "LOC",  # Facility -> Location
        "EVENT": "EVENT",
        "DATE": "DATE",
        "TIME": "TIME",
        "MONEY": "MONEY",
        "PRODUCT": "PRODUCT",
        "NORP": "GROUP",  # Nationalities, religious/political groups
    }

    def __init__(
        self,
        model_name: str = "en_core_web_sm",
        custom_labels: Optional[Dict[str, str]] = None,
    ):
        """
        Initialize NER model.

        Args:
            model_name: spaCy model name (e.g., en_core_web_sm, ru_core_news_sm)
            custom_labels: Optional custom entity type mappings
        """
        self.model_name = model_name
        self.model = None

        if custom_labels:
            self.ENTITY_TYPE_MAP.update(custom_labels)

        self._load_model()

    def _load_model(self) -> None:
        """Load spaCy model."""
        if not HAS_SPACY:
            logger.error("spaCy not installed. Cannot load NER model.")
            logger.error("Install with: pip install spacy")
            logger.error(f"Then download model: python -m spacy download {self.model_name}")
            return

        try:
            logger.info(f"Loading spaCy model: {self.model_name}")
            self.model = spacy.load(self.model_name)
            logger.info(f"Model loaded successfully")

        except OSError as e:
            logger.error(f"Failed to load model '{self.model_name}': {e}")
            logger.error(f"Download with: python -m spacy download {self.model_name}")
            self.model = None

    def extract_entities(
        self,
        text: str,
        min_confidence: float = 0.5,
    ) -> List[Entity]:
        """
        Extract entities from text.

        Args:
            text: Input text
            min_confidence: Minimum confidence threshold

        Returns:
            List of Entity objects
        """
        if not self.model:
            logger.warning("NER model not loaded. Returning empty list.")
            return []

        try:
            doc = self.model(text)
            entities = []

            for ent in doc.ents:
                # Map entity label to our standard types
                entity_type = self.ENTITY_TYPE_MAP.get(ent.label_, ent.label_)

                entities.append(Entity(
                    text=ent.text.strip(),
                    type=entity_type,
                    confidence=1.0,  # spaCy doesn't provide confidence by default
                    metadata={
                        "start": ent.start_char,
                        "end": ent.end_char,
                        "label": ent.label_,
                    }
                ))

            return entities

        except Exception as e:
            logger.error(f"Error extracting entities: {e}")
            return []


class EntityResolver:
    """
    Resolves entities to canonical forms and handles deduplication.
    """

    def __init__(self):
        """Initialize entity resolver."""
        self.entity_index: Dict[str, Entity] = {}
        self.alias_map: Dict[str, str] = {}  # alias -> canonical_form

    def add_entity(self, entity: Entity, timestamp: Optional[datetime] = None) -> str:
        """
        Add entity to the resolver, handling deduplication.

        Args:
            entity: Entity to add
            timestamp: Optional timestamp for tracking

        Returns:
            Canonical form of the entity
        """
        # Generate canonical form
        canonical = self._get_canonical_form(entity.text, entity.type)

        # Check if entity exists
        key = f"{canonical}:{entity.type}"

        if key in self.entity_index:
            # Update existing entity
            existing = self.entity_index[key]
            existing.mentions += 1
            existing.aliases.add(entity.text)

            if timestamp:
                if not existing.first_seen or timestamp < existing.first_seen:
                    existing.first_seen = timestamp
                if not existing.last_seen or timestamp > existing.last_seen:
                    existing.last_seen = timestamp
        else:
            # Add new entity
            entity.canonical_form = canonical
            entity.mentions = 1
            entity.first_seen = timestamp
            entity.last_seen = timestamp
            self.entity_index[key] = entity

        # Update alias map
        self.alias_map[entity.text.lower()] = canonical

        return canonical

    def _get_canonical_form(self, text: str, entity_type: str) -> str:
        """
        Get canonical form of entity text.

        Args:
            text: Original entity text
            entity_type: Entity type

        Returns:
            Canonical form (normalized)
        """
        # Simple normalization (can be enhanced with fuzzy matching, etc.)
        canonical = text.strip()

        # Remove common prefixes/suffixes
        if entity_type == "PER":
            # Remove titles
            for title in ["Mr.", "Mrs.", "Dr.", "President", "Minister"]:
                if canonical.startswith(title):
                    canonical = canonical[len(title):].strip()

        # Normalize case (but preserve proper nouns)
        # For now, just strip whitespace and normalize unicode
        canonical = " ".join(canonical.split())

        return canonical

    def resolve(self, text: str, entity_type: str) -> Optional[str]:
        """
        Resolve entity text to canonical form.

        Args:
            text: Entity text
            entity_type: Entity type

        Returns:
            Canonical form if found, else None
        """
        text_lower = text.lower()

        # Direct lookup
        if text_lower in self.alias_map:
            return self.alias_map[text_lower]

        # Fuzzy match (simple substring matching)
        for alias, canonical in self.alias_map.items():
            if text_lower in alias or alias in text_lower:
                return canonical

        return None

    def get_entity(self, canonical_form: str, entity_type: str) -> Optional[Entity]:
        """Get entity by canonical form."""
        key = f"{canonical_form}:{entity_type}"
        return self.entity_index.get(key)

    def get_all_entities(self, entity_type: Optional[str] = None) -> List[Entity]:
        """Get all entities, optionally filtered by type."""
        if entity_type:
            return [e for e in self.entity_index.values() if e.type == entity_type]
        return list(self.entity_index.values())

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about resolved entities."""
        type_counts = Counter(e.type for e in self.entity_index.values())

        return {
            "total_entities": len(self.entity_index),
            "total_aliases": len(self.alias_map),
            "by_type": dict(type_counts),
        }


class KnowledgeGraph:
    """
    Knowledge graph for entity relationships using NetworkX.
    """

    def __init__(self):
        """Initialize knowledge graph."""
        if not HAS_NETWORKX:
            logger.error("networkx not installed. Knowledge graph disabled.")
            logger.error("Install with: pip install networkx")
            self.graph = None
        else:
            self.graph = nx.MultiDiGraph()

    def add_entity(self, entity: Entity) -> None:
        """Add entity as a node in the graph."""
        if not self.graph:
            return

        node_id = f"{entity.canonical_form or entity.text}:{entity.type}"

        self.graph.add_node(
            node_id,
            text=entity.text,
            canonical=entity.canonical_form or entity.text,
            type=entity.type,
            mentions=entity.mentions,
            first_seen=entity.first_seen.isoformat() if entity.first_seen else None,
            last_seen=entity.last_seen.isoformat() if entity.last_seen else None,
        )

    def add_relationship(self, relationship: Relationship) -> None:
        """Add relationship as an edge in the graph."""
        if not self.graph:
            return

        self.graph.add_edge(
            relationship.source,
            relationship.target,
            type=relationship.relationship_type,
            weight=relationship.weight,
            timestamp=relationship.timestamp.isoformat() if relationship.timestamp else None,
            context=relationship.context,
        )

    def get_entity_network(
        self,
        entity: str,
        max_hops: int = 2,
    ) -> nx.Graph:
        """
        Get subgraph centered on an entity.

        Args:
            entity: Entity canonical form
            max_hops: Maximum number of hops from entity

        Returns:
            Subgraph containing entity and neighbors
        """
        if not self.graph:
            return nx.Graph()

        # Find all nodes within max_hops
        nodes = set()
        queue = [(entity, 0)]
        visited = set()

        while queue:
            node, depth = queue.pop(0)

            if node in visited or depth > max_hops:
                continue

            visited.add(node)
            nodes.add(node)

            if depth < max_hops:
                # Add neighbors
                neighbors = list(self.graph.successors(node)) + list(self.graph.predecessors(node))
                queue.extend((n, depth + 1) for n in neighbors)

        # Return subgraph
        return self.graph.subgraph(nodes)

    def pagerank(self, top_k: int = 100) -> List[Tuple[str, float]]:
        """
        Compute PageRank to find influential entities.

        Args:
            top_k: Number of top entities to return

        Returns:
            List of (entity, score) tuples
        """
        if not self.graph or self.graph.number_of_nodes() == 0:
            return []

        try:
            scores = nx.pagerank(self.graph)
            sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
            return sorted_scores[:top_k]

        except Exception as e:
            logger.error(f"PageRank computation failed: {e}")
            return []

    def detect_communities(self, algorithm: str = "louvain") -> Dict[str, int]:
        """
        Detect communities in the graph.

        Args:
            algorithm: Community detection algorithm ('louvain', 'label_propagation')

        Returns:
            Dictionary mapping node -> community_id
        """
        if not self.graph or self.graph.number_of_nodes() == 0:
            return {}

        try:
            # Convert to undirected for community detection
            undirected = self.graph.to_undirected()

            if algorithm == "louvain":
                try:
                    import community as community_louvain
                    communities = community_louvain.best_partition(undirected)
                except ImportError:
                    logger.warning("python-louvain not installed. Using label propagation.")
                    algorithm = "label_propagation"

            if algorithm == "label_propagation":
                from networkx.algorithms import community
                communities_list = community.label_propagation_communities(undirected)

                # Convert to dict
                communities = {}
                for i, comm in enumerate(communities_list):
                    for node in comm:
                        communities[node] = i

            return communities

        except Exception as e:
            logger.error(f"Community detection failed: {e}")
            return {}

    def export_to_gexf(self, output_file: Path) -> None:
        """Export graph to GEXF format for visualization (Gephi)."""
        if not self.graph:
            logger.error("Cannot export: graph not initialized")
            return

        try:
            nx.write_gexf(self.graph, str(output_file))
            logger.info(f"Graph exported to {output_file}")

        except Exception as e:
            logger.error(f"Failed to export graph: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """Get graph statistics."""
        if not self.graph:
            return {"error": "Graph not initialized"}

        return {
            "nodes": self.graph.number_of_nodes(),
            "edges": self.graph.number_of_edges(),
            "density": nx.density(self.graph),
            "is_connected": nx.is_weakly_connected(self.graph) if self.graph.number_of_nodes() > 0 else False,
        }


class EntityNetworkAnalyzer:
    """
    Complete entity extraction and network analysis system.
    """

    def __init__(
        self,
        ner_model: str = "en_core_web_sm",
        languages: Optional[List[str]] = None,
    ):
        """
        Initialize entity network analyzer.

        Args:
            ner_model: Primary NER model name
            languages: Optional list of language codes for multi-lingual support
        """
        self.ner_model = NERModel(model_name=ner_model)
        self.resolver = EntityResolver()
        self.knowledge_graph = KnowledgeGraph()

        # Multi-lingual models (optional)
        self.language_models: Dict[str, NERModel] = {}
        if languages:
            for lang in languages:
                model_name = self._get_model_for_language(lang)
                if model_name:
                    self.language_models[lang] = NERModel(model_name=model_name)

    @staticmethod
    def _get_model_for_language(lang_code: str) -> Optional[str]:
        """Get spaCy model name for language code."""
        lang_model_map = {
            "en": "en_core_web_sm",
            "ru": "ru_core_news_sm",
            "de": "de_core_news_sm",
            "fr": "fr_core_news_sm",
            "es": "es_core_news_sm",
            "zh": "zh_core_web_sm",
            "ar": "ar_core_news_sm",
        }
        return lang_model_map.get(lang_code)

    def process_message(
        self,
        message: str,
        message_id: int,
        timestamp: Optional[datetime] = None,
        language: str = "en",
    ) -> List[Entity]:
        """
        Process a single message to extract entities.

        Args:
            message: Message text
            message_id: Message ID
            timestamp: Message timestamp
            language: Language code

        Returns:
            List of extracted entities
        """
        # Select appropriate NER model
        ner = self.language_models.get(language, self.ner_model)

        # Extract entities
        entities = ner.extract_entities(message)

        # Add to resolver and knowledge graph
        for entity in entities:
            canonical = self.resolver.add_entity(entity, timestamp=timestamp)
            entity.canonical_form = canonical

            # Add to knowledge graph
            resolved_entity = self.resolver.get_entity(canonical, entity.type)
            if resolved_entity:
                self.knowledge_graph.add_entity(resolved_entity)

        # Detect co-occurrences (entities mentioned together)
        if len(entities) > 1:
            for i, entity1 in enumerate(entities):
                for entity2 in entities[i+1:]:
                    relationship = Relationship(
                        source=f"{entity1.canonical_form}:{entity1.type}",
                        target=f"{entity2.canonical_form}:{entity2.type}",
                        relationship_type="CO_OCCURS",
                        weight=1.0,
                        timestamp=timestamp,
                        context=message[:200],  # First 200 chars as context
                    )
                    self.knowledge_graph.add_relationship(relationship)

        return entities

    def process_messages(
        self,
        messages: List[Dict[str, Any]],
        batch_size: int = 100,
    ) -> Dict[str, Any]:
        """
        Process multiple messages.

        Args:
            messages: List of message dictionaries
            batch_size: Processing batch size

        Returns:
            Statistics about processing
        """
        total_entities = 0
        total_messages = len(messages)

        logger.info(f"Processing {total_messages} messages for entity extraction...")

        for i, msg in enumerate(messages):
            if (i + 1) % batch_size == 0:
                logger.info(f"Processed {i + 1}/{total_messages} messages")

            text = msg.get('content', msg.get('text', ''))
            msg_id = msg.get('id', msg.get('message_id', 0))
            timestamp = None

            if 'date' in msg:
                try:
                    timestamp = datetime.fromisoformat(msg['date'])
                except (ValueError, TypeError):
                    pass

            entities = self.process_message(text, msg_id, timestamp=timestamp)
            total_entities += len(entities)

        stats = {
            "messages_processed": total_messages,
            "total_entities_extracted": total_entities,
            "entity_resolver": self.resolver.get_stats(),
            "knowledge_graph": self.knowledge_graph.get_stats(),
        }

        logger.info(f"Processing complete. Extracted {total_entities} entities.")
        return stats

    def get_influential_entities(self, top_k: int = 50) -> List[Tuple[str, float]]:
        """Get most influential entities by PageRank."""
        return self.knowledge_graph.pagerank(top_k=top_k)

    def get_entity_timeline(
        self,
        entity: str,
        entity_type: str = "PER",
    ) -> Optional[Dict[str, Any]]:
        """Get timeline for a specific entity."""
        resolved = self.resolver.get_entity(entity, entity_type)
        if not resolved:
            return None

        return {
            "entity": resolved.text,
            "canonical": resolved.canonical_form,
            "type": resolved.type,
            "mentions": resolved.mentions,
            "first_seen": resolved.first_seen.isoformat() if resolved.first_seen else None,
            "last_seen": resolved.last_seen.isoformat() if resolved.last_seen else None,
            "aliases": list(resolved.aliases),
        }


__all__ = [
    "Entity",
    "Relationship",
    "NERModel",
    "EntityResolver",
    "KnowledgeGraph",
    "EntityNetworkAnalyzer",
]
