"""Topological Decay — iterative belief propagation for graph pruning.

Foundational claims stay alive as long as active frontier claims depend on them.
Archived nodes' embeddings go to Qdrant for potential resurrection.
"""

from __future__ import annotations

import logging

from crucible.config import settings
from crucible.graph.store import GraphStore

logger = logging.getLogger(__name__)


class DecayManager:
    """Manages the topological decay and archival process."""

    def __init__(self, graph: GraphStore):
        self._graph = graph
        cfg = settings().get("decay", {})
        self._threshold = cfg.get("archive_threshold", 12)
        self._max_iterations = cfg.get("max_propagation_iterations", 5)

    def run_decay_cycle(self):
        """Increment decay counters for all claims."""
        self._graph.increment_decay()
        logger.info("Decay counters incremented.")

    def run_belief_propagation(self) -> list[str]:
        """Run iterative belief propagation and archive stale nodes.

        Algorithm:
        1. Initialize: effective_decay = local_decay for all nodes
        2. Repeat until stable (max iterations):
           For each node N with incoming DEPENDS_ON edges from D:
             N.effective_decay = min(N.effective_decay, D.effective_decay)
        3. Archive nodes where effective_decay > threshold

        Returns list of archived node IDs.
        """
        query_init = """
        MATCH (c:Claim)
        SET c.effective_decay = COALESCE(c.local_decay, 0)
        """

        query_propagate = """
        MATCH (d:Claim)-[:DEPENDS_ON]->(n:Claim)
        WHERE d.effective_decay < n.effective_decay
        SET n.effective_decay = d.effective_decay
        RETURN count(n) AS updates
        """

        query_archive = """
        MATCH (c:Claim)
        WHERE c.effective_decay > $threshold
        SET c:Archived
        REMOVE c:Claim
        RETURN c.claim_id AS archived_id
        """

        with self._graph._driver.session() as session:
            # Step 1: Initialize
            session.run(query_init)

            # Step 2: Propagate
            for i in range(self._max_iterations):
                result = session.run(query_propagate).single()
                updates = result["updates"] if result else 0
                logger.debug(f"Propagation iteration {i+1}: {updates} updates")
                if updates == 0:
                    break

            # Step 3: Archive
            result = session.run(query_archive, threshold=self._threshold)
            archived = [r["archived_id"] for r in result]

        if archived:
            logger.info(f"Archived {len(archived)} stale nodes.")
        else:
            logger.info("No nodes archived.")

        return archived
