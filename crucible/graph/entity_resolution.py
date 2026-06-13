"""Entity Resolution Engine.

Before inserting any node, checks for existing semantically equivalent nodes.
Prevents fragmentation ("MoE" vs "Mixture of Experts" vs "conditional computation").
"""

from __future__ import annotations

import logging
from typing import Optional

from crucible.config import settings
from crucible.graph.store import GraphStore
from crucible.models.client import LLMClient
from crucible.graph.embeddings import EmbeddingModel

logger = logging.getLogger(__name__)


class EntityResolver:
    """Three-step entity resolution: extract → search → align."""

    def __init__(self, graph: GraphStore, llm: Optional[LLMClient] = None):
        self._graph = graph
        self._llm = llm
        self._embedder = EmbeddingModel()
        self._cfg = settings().get("entity_resolution", {})
        self._threshold = self._cfg.get("similarity_threshold", 0.85)
        self._max_candidates = self._cfg.get("max_candidates", 3)

    def resolve_claim(self, claim_text: str, paper_id: str) -> dict:
        """Determine whether a claim should merge with an existing node or create new.

        Returns:
            {"action": "MERGE", "target_id": "..."} or {"action": "CREATE_NEW"}
        """
        # Step 1: Embed
        embedding = self._embedder.embed(claim_text)

        # Step 2: Search for candidates
        candidates = self._graph.find_similar_claims(embedding, top_k=self._max_candidates)

        # Filter by threshold
        candidates = [c for c in candidates if c["score"] >= self._threshold]

        if not candidates:
            return {"action": "CREATE_NEW", "embedding": embedding}

        # Step 3: LLM alignment (if LLM available)
        if self._llm:
            return self._llm_align(claim_text, candidates, embedding)

        # Without LLM, use top candidate if score is very high
        top = candidates[0]
        if top["score"] >= 0.95:
            return {"action": "MERGE", "target_id": top["claim"]["claim_id"], "embedding": embedding}

        return {"action": "CREATE_NEW", "embedding": embedding}

    def _llm_align(self, claim_text: str, candidates: list[dict], embedding: list[float]) -> dict:
        """Use the active LLM to decide merge vs create."""
        candidates_text = "\n".join(
            f"  ID: {c['claim']['claim_id']} | Score: {c['score']:.3f} | Text: {c['claim'].get('claim_text', 'N/A')}"
            for c in candidates
        )

        system = (
            "You are an entity resolution system. Decide whether a new claim should MERGE "
            "with an existing claim or CREATE_NEW. Respond ONLY with JSON: "
            '{"action": "MERGE", "target_id": "..."} or {"action": "CREATE_NEW"}'
        )
        user = f"New claim: {claim_text}\n\nCandidate matches:\n{candidates_text}"

        try:
            result = self._llm.chat_json(system, user, max_tokens=128)
            result["embedding"] = embedding
            return result
        except Exception as e:
            logger.warning(f"LLM alignment failed: {e}. Defaulting to CREATE_NEW.")
            return {"action": "CREATE_NEW", "embedding": embedding}
