"""Persistent semantic memory via Mem0.

Persona-scoped namespaces allow each phase to accumulate
cross-session insights (e.g., the Demolisher learns that Lab X
has a systematic evaluation weakness over weeks of operation).
"""

from __future__ import annotations

import logging
from typing import Optional

from crucible.config import settings

logger = logging.getLogger(__name__)

# Valid persona namespaces
NAMESPACES = ("prospector", "cartographer", "demolisher", "integrator", "meta")


class SemanticMemory:
    """Mem0-backed persistent memory with persona namespaces.

    Usage:
        mem = SemanticMemory()
        mem.add("prospector", "DeepSeek tends to miss qualitative claims about training stability")
        results = mem.search("prospector", "claim extraction patterns", top_k=5)
    """

    def __init__(self):
        self._client = None
        self._cfg = settings().get("memory", {})

    def _load(self):
        if self._client is None:
            from mem0 import Memory

            vector_cfg = settings().get("vector", {})
            config = {
                "vector_store": {
                    "provider": "qdrant",
                    "config": {
                        "host": vector_cfg.get("qdrant_host", "localhost"),
                        "port": vector_cfg.get("qdrant_port", 6333),
                        "collection_name": vector_cfg.get("mem0_collection", "mem0_semantic_memory"),
                    },
                },
            }
            self._client = Memory.from_config(config)
            logger.info("Mem0 semantic memory initialized.")

    def add(self, namespace: str, content: str, metadata: Optional[dict] = None):
        """Store a memory in a persona namespace."""
        self._validate_namespace(namespace)
        self._load()
        self._client.add(
            content,
            user_id=namespace,
            metadata=metadata or {},
        )
        logger.debug(f"[{namespace}] Stored memory: {content[:80]}...")

    def search(self, namespace: str, query: str, top_k: int = 5) -> list[dict]:
        """Search memories in a persona namespace."""
        self._validate_namespace(namespace)
        self._load()
        results = self._client.search(query, user_id=namespace, limit=top_k)
        return results.get("results", []) if isinstance(results, dict) else results

    def get_all(self, namespace: str) -> list[dict]:
        """Get all memories for a namespace."""
        self._validate_namespace(namespace)
        self._load()
        results = self._client.get_all(user_id=namespace)
        return results.get("results", []) if isinstance(results, dict) else results

    @staticmethod
    def _validate_namespace(ns: str):
        if ns not in NAMESPACES:
            raise ValueError(f"Invalid namespace '{ns}'. Must be one of: {NAMESPACES}")
