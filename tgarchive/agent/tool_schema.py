"""
SPECTRA Agent Tool Schemas — JSON Schema descriptions for LLM function calling
==============================================================================

Provides JSON Schema (OpenAI function-calling compatible) descriptions for
each of the 5 agent tools.  These schemas describe the input parameters and
output shape so an LLM agent can call the tools correctly.

Usage::

    from tgarchive.agent.tool_schema import TOOL_SCHEMAS, get_tool_schema

    schema = get_tool_schema("search")
    # schema == {"type": "function", "function": {"name": "search", ...}}
"""

from __future__ import annotations

from typing import Any, Dict


def _input_schema(properties: Dict[str, Any], required: list[str]) -> Dict[str, Any]:
    """Build a standard JSON Schema object for tool input."""
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


# ─── search ─────────────────────────────────────────────────────────────────

SEARCH_SCHEMA: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "search",
        "description": (
            "Unified search across all SPECTRA retrieval subsystems: file/media "
            "search, semantic/message search, graph, entity, and hash lookup. "
            "Use this to find messages, media files, or entities matching a "
            "query string."
        ),
        "parameters": _input_schema(
            {
                "query": {
                    "type": "string",
                    "description": (
                        "Search query — a filename, keyword, file hash, or "
                        "natural-language phrase."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of candidates to return.",
                    "default": 50,
                    "minimum": 1,
                    "maximum": 500,
                },
                "subsystems": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["file", "semantic", "graph", "entity", "hash"],
                    },
                    "description": (
                        "Optional list of subsystems to query. If omitted, all "
                        "subsystems are queried."
                    ),
                },
            },
            required=["query"],
        ),
    },
}


SEARCH_OUTPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "object_id": {"type": "string"},
                    "object_type": {"type": "string"},
                    "score": {"type": "number"},
                    "matched_by": {"type": "array", "items": {"type": "string"}},
                    "summary": {"type": "string"},
                    "context": {"type": "array"},
                    "provenance": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "total_found": {"type": "integer"},
        "subsystems_queried": {"type": "array", "items": {"type": "string"}},
        "elapsed_ms": {"type": "number"},
        "summary": {"type": "string"},
        "error": {"type": "string"},
    },
}


# ─── expand ─────────────────────────────────────────────────────────────────

EXPAND_SCHEMA: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "expand",
        "description": (
            "Expand from a known object to find related objects via graph "
            "edges. Traverses the entity graph (hypothesis links, campaign "
            "memberships, contact networks) up to the requested depth."
        ),
        "parameters": _input_schema(
            {
                "object_id": {
                    "type": "string",
                    "description": (
                        "Object identifier, e.g. 'media:123', 'user:456', or "
                        "canonical 'telegram:user:123'."
                    ),
                },
                "depth": {
                    "type": "integer",
                    "description": "How many hops to traverse (1 = direct neighbours).",
                    "default": 1,
                    "minimum": 1,
                    "maximum": 5,
                },
                "relationship_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Optional filter on edge types, e.g. "
                        "['same_actor', 'associated_with']."
                    ),
                },
            },
            required=["object_id"],
        ),
    },
}


EXPAND_OUTPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "root": {
            "type": "object",
            "properties": {
                "object_id": {"type": "string"},
                "object_type": {"type": "string"},
                "canonical_id": {"type": "string"},
            },
        },
        "neighbors": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "object_id": {"type": "string"},
                    "object_type": {"type": "string"},
                    "relationship": {"type": "string"},
                    "confidence": {"type": "number"},
                    "direction": {"type": "string"},
                },
            },
        },
        "edges": {"type": "array"},
        "depth_reached": {"type": "integer"},
        "summary": {"type": "string"},
        "error": {"type": "string"},
    },
}


# ─── timeline ───────────────────────────────────────────────────────────────

TIMELINE_SCHEMA: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "timeline",
        "description": (
            "Get chronological activity for an entity (user, channel). Returns "
            "time-ordered events, an activity pattern (peak hours, inferred "
            "timezone), and detected behavioral change points."
        ),
        "parameters": _input_schema(
            {
                "entity_id": {
                    "type": "string",
                    "description": (
                        "Entity identifier, e.g. 'user:456' or bare '456'."
                    ),
                },
                "start": {
                    "type": "string",
                    "description": "Optional ISO date lower bound (inclusive), e.g. '2026-01-01'.",
                },
                "end": {
                    "type": "string",
                    "description": "Optional ISO date upper bound (inclusive), e.g. '2026-12-31'.",
                },
                "event_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Optional filter on event types, e.g. ['message', 'media']."
                    ),
                },
            },
            required=["entity_id"],
        ),
    },
}


TIMELINE_OUTPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "entity_id": {"type": "string"},
        "entity_type": {"type": "string"},
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "timestamp": {"type": "string"},
                    "event_type": {"type": "string"},
                    "channel_id": {"type": ["integer", "null"]},
                    "message_id": {"type": ["integer", "null"]},
                    "summary": {"type": "string"},
                },
            },
        },
        "activity_pattern": {
            "type": "object",
            "properties": {
                "peak_hours": {"type": "array", "items": {"type": "integer"}},
                "inferred_timezone": {"type": ["string", "null"]},
                "total_events": {"type": "integer"},
                "hour_histogram": {"type": "object"},
            },
        },
        "change_points": {"type": "array"},
        "summary": {"type": "string"},
        "error": {"type": "string"},
    },
}


# ─── resolve ────────────────────────────────────────────────────────────────

RESOLVE_SCHEMA: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "resolve",
        "description": (
            "Resolve an entity reference (username, display name, or user ID) "
            "to identity clusters. Returns candidate identities with "
            "confidence scores and supporting/contradicting evidence."
        ),
        "parameters": _input_schema(
            {
                "query_or_id": {
                    "type": "string",
                    "description": (
                        "A username ('@alice' or 'alice'), display name, or "
                        "numeric user ID ('123' or 'user:123')."
                    ),
                },
            },
            required=["query_or_id"],
        ),
    },
}


RESOLVE_OUTPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {"type": "string"},
        "clusters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "cluster_id": {"type": "string"},
                    "confidence": {"type": "number"},
                    "candidates": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string"},
                                "value": {"type": "string"},
                            },
                        },
                    },
                    "evidence": {"type": "array"},
                    "contradicting_evidence": {"type": "array"},
                },
            },
        },
        "explanation": {"type": "string"},
        "error": {"type": "string"},
    },
}


# ─── evidence ───────────────────────────────────────────────────────────────

EVIDENCE_SCHEMA: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "evidence",
        "description": (
            "Get the full provenance and evidence chain for an object or "
            "conclusion. Returns the provenance chain (algorithms, versions, "
            "confidences), supporting and contradicting evidence, and fused "
            "conclusions with Bayesian probabilities."
        ),
        "parameters": _input_schema(
            {
                "object_id": {
                    "type": "string",
                    "description": (
                        "An entity ID ('user:123', 'telegram:user:123'), a "
                        "conclusion ID ('conclusion:789'), or bare numeric ID."
                    ),
                },
            },
            required=["object_id"],
        ),
    },
}


EVIDENCE_OUTPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "object_id": {"type": "string"},
        "object_type": {"type": "string"},
        "canonical_id": {"type": "string"},
        "provenance_chain": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "node_id": {"type": "string"},
                    "algorithm": {"type": "string"},
                    "version": {"type": "string"},
                    "confidence": {"type": "number"},
                },
            },
        },
        "supporting_evidence": {"type": "array"},
        "contradicting_evidence": {"type": "array"},
        "conclusions": {"type": "array"},
        "hypotheses": {"type": "array"},
        "campaigns": {"type": "array"},
        "graph_neighbors": {"type": "array"},
        "explanation": {"type": "string"},
        "error": {"type": "string"},
    },
}


# ─── Registry ───────────────────────────────────────────────────────────────

#: Input schemas (OpenAI function-calling format) for each tool.
TOOL_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "search": SEARCH_SCHEMA,
    "expand": EXPAND_SCHEMA,
    "timeline": TIMELINE_SCHEMA,
    "resolve": RESOLVE_SCHEMA,
    "evidence": EVIDENCE_SCHEMA,
}

#: Output schemas (plain JSON Schema) for each tool.
TOOL_OUTPUT_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "search": SEARCH_OUTPUT_SCHEMA,
    "expand": EXPAND_OUTPUT_SCHEMA,
    "timeline": TIMELINE_OUTPUT_SCHEMA,
    "resolve": RESOLVE_OUTPUT_SCHEMA,
    "evidence": EVIDENCE_OUTPUT_SCHEMA,
}


def get_tool_schema(name: str) -> Dict[str, Any]:
    """Return the input schema (function-calling format) for a tool.

    Raises:
        KeyError: if the tool name is unknown.
    """
    return TOOL_SCHEMAS[name]


def get_output_schema(name: str) -> Dict[str, Any]:
    """Return the output schema (plain JSON Schema) for a tool.

    Raises:
        KeyError: if the tool name is unknown.
    """
    return TOOL_OUTPUT_SCHEMAS[name]


def all_tool_names() -> list[str]:
    """Return a list of all registered tool names."""
    return list(TOOL_SCHEMAS.keys())


__all__ = [
    "TOOL_SCHEMAS",
    "TOOL_OUTPUT_SCHEMAS",
    "get_tool_schema",
    "get_output_schema",
    "all_tool_names",
    "SEARCH_SCHEMA",
    "EXPAND_SCHEMA",
    "TIMELINE_SCHEMA",
    "RESOLVE_SCHEMA",
    "EVIDENCE_SCHEMA",
]
