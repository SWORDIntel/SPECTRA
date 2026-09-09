"""
SPECTRA Agent Tool Surface
==========================

A small, clean tool surface exposing SPECTRA's retrieval and intelligence
capabilities as plain functions that an LLM agent can call.

SPECTRA does deterministic retrieval and evidence construction; the LLM
reasons over the results.  Each tool is a thin wrapper around existing
SPECTRA services and returns a JSON-serializable dict.

The five tools:

    search(query, limit, subsystems)    — unified search across all subsystems
    expand(object_id, depth, ...)       — graph expansion from a known object
    timeline(entity_id, start, end, ...)— chronological activity for an entity
    resolve(query_or_id)                — entity reference → identity clusters
    evidence(object_id)                 — full evidence/provenance chain

Usage (library)::

    from tgarchive.agent.tools import search, expand, timeline, resolve, evidence

    results = search("archive.zip", limit=10)
    net = expand("media:123", depth=2)

Usage (CLI)::

    spectra agent search "query"
    spectra agent expand "media:123" --depth 2
    spectra agent timeline "user:456" --start 2026-01-01
    spectra agent resolve "@username"
    spectra agent evidence "conclusion:789"
"""

from .tools import (
    search,
    expand,
    timeline,
    resolve,
    evidence,
    set_db_path,
    get_db_path,
    AGENT_TOOLS,
)
from .tool_schema import TOOL_SCHEMAS, get_tool_schema

__all__ = [
    "search",
    "expand",
    "timeline",
    "resolve",
    "evidence",
    "set_db_path",
    "get_db_path",
    "AGENT_TOOLS",
    "TOOL_SCHEMAS",
    "get_tool_schema",
]
