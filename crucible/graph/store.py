"""Contradiction-First Knowledge Graph backed by Neo4j.

All writes are idempotent: MERGE (upsert) with deterministic SHA-256 IDs.
Contradictions and Gaps are first-class nodes, not just edges.
"""

from __future__ import annotations

import logging
from typing import Optional

from neo4j import GraphDatabase

from crucible.config import settings
from crucible.schemas import (
    Claim,
    Contradiction,
    Evidence,
    Gap,
)

logger = logging.getLogger(__name__)


class GraphStore:
    """Interface to the Contradiction-First knowledge graph."""

    def __init__(self):
        cfg = settings()["graph"]
        self._driver = GraphDatabase.driver(
            cfg["neo4j_uri"],
            auth=(cfg["neo4j_user"], cfg["neo4j_password"]),
        )
        logger.info(f"Connected to Neo4j at {cfg['neo4j_uri']}")

    def close(self):
        self._driver.close()

    # ── Schema Setup ──────────────────────────────────────────────────────

    def init_schema(self):
        """Create constraints and indexes. Idempotent."""
        queries = [
            "CREATE CONSTRAINT claim_id IF NOT EXISTS FOR (c:Claim) REQUIRE c.claim_id IS UNIQUE",
            "CREATE CONSTRAINT evidence_id IF NOT EXISTS FOR (e:Evidence) REQUIRE e.evidence_id IS UNIQUE",
            "CREATE CONSTRAINT contradiction_id IF NOT EXISTS FOR (x:Contradiction) REQUIRE x.contradiction_id IS UNIQUE",
            "CREATE CONSTRAINT gap_id IF NOT EXISTS FOR (g:Gap) REQUIRE g.gap_id IS UNIQUE",
            # Vector index for entity resolution (requires Neo4j 5.11+)
            """CREATE VECTOR INDEX claim_embedding IF NOT EXISTS
               FOR (c:Claim) ON (c.embedding)
               OPTIONS {indexConfig: {
                 `vector.dimensions`: 384,
                 `vector.similarity_function`: 'cosine'
               }}""",
        ]
        with self._driver.session() as session:
            for q in queries:
                try:
                    session.run(q)
                except Exception as e:
                    logger.warning(f"Schema query skipped (may already exist): {e}")
        logger.info("Graph schema initialized.")

    # ── CRUD — All idempotent via MERGE ───────────────────────────────────

    def upsert_claim(self, claim: Claim, embedding: Optional[list[float]] = None):
        """Insert or update a Claim node."""
        props = claim.model_dump()
        props["last_seen"] = "timestamp()"
        if embedding:
            props["embedding"] = embedding

        query = """
        MERGE (c:Claim {claim_id: $claim_id})
        ON CREATE SET c += $props, c.local_decay = 0, c.last_active_cycle = 0
        ON MATCH SET c.last_seen = timestamp()
        """
        with self._driver.session() as session:
            session.run(query, claim_id=claim.claim_id, props=props)

    def upsert_evidence(self, evidence: Evidence):
        """Insert Evidence and link to its Claim."""
        query = """
        MERGE (e:Evidence {evidence_id: $eid})
        ON CREATE SET e += $props
        WITH e
        MATCH (c:Claim {claim_id: $cid})
        MERGE (e)-[:SUPPORTS]->(c)
        """
        with self._driver.session() as session:
            session.run(
                query,
                eid=evidence.evidence_id,
                props=evidence.model_dump(),
                cid=evidence.claim_id,
            )

    def upsert_contradiction(self, contradiction: Contradiction):
        """Insert Contradiction node and link both Claims."""
        query = """
        MERGE (x:Contradiction {contradiction_id: $xid})
        ON CREATE SET x += $props
        ON MATCH SET x += $props
        WITH x
        MATCH (a:Claim {claim_id: $aid})
        MATCH (b:Claim {claim_id: $bid})
        MERGE (a)-[:CONTRADICTS]->(x)
        MERGE (b)-[:CONTRADICTS]->(x)
        """
        with self._driver.session() as session:
            session.run(
                query,
                xid=contradiction.contradiction_id,
                props=contradiction.model_dump(),
                aid=contradiction.claim_a_id,
                bid=contradiction.claim_b_id,
            )

    def upsert_gap(self, gap: Gap):
        """Insert a Gap node and link to related Claims."""
        query = """
        MERGE (g:Gap {gap_id: $gid})
        ON CREATE SET g += $props
        ON MATCH SET g += $props
        """
        with self._driver.session() as session:
            session.run(query, gid=gap.gap_id, props=gap.model_dump())
            # Link related claims
            for cid in gap.related_claim_ids:
                session.run(
                    """
                    MATCH (g:Gap {gap_id: $gid})
                    MATCH (c:Claim {claim_id: $cid})
                    MERGE (g)-[:RELATED_TO]->(c)
                    """,
                    gid=gap.gap_id,
                    cid=cid,
                )

    # ── Queries ───────────────────────────────────────────────────────────

    def get_active_contradictions(self) -> list[dict]:
        """Get all unresolved contradictions with linked claims."""
        query = """
        MATCH (a:Claim)-[:CONTRADICTS]->(x:Contradiction)<-[:CONTRADICTS]-(b:Claim)
        WHERE x.verdict IS NULL OR x.verdict = 'unresolved'
        RETURN x, a, b
        """
        with self._driver.session() as session:
            result = session.run(query)
            return [
                {
                    "contradiction": dict(r["x"]),
                    "claim_a": dict(r["a"]),
                    "claim_b": dict(r["b"]),
                }
                for r in result
            ]

    def get_claims_by_paper(self, paper_id: str) -> list[dict]:
        query = "MATCH (c:Claim {paper_id: $pid}) RETURN c"
        with self._driver.session() as session:
            return [dict(r["c"]) for r in session.run(query, pid=paper_id)]

    def get_all_claims(self, limit: int = 500) -> list[dict]:
        query = "MATCH (c:Claim) RETURN c LIMIT $limit"
        with self._driver.session() as session:
            return [dict(r["c"]) for r in session.run(query, limit=limit)]

    def get_gaps(self) -> list[dict]:
        query = "MATCH (g:Gap) RETURN g"
        with self._driver.session() as session:
            return [dict(r["g"]) for r in session.run(query)]

    def find_similar_claims(self, embedding: list[float], top_k: int = 3) -> list[dict]:
        """Vector similarity search for entity resolution."""
        query = """
        CALL db.index.vector.queryNodes('claim_embedding', $k, $emb)
        YIELD node, score
        RETURN node, score
        """
        with self._driver.session() as session:
            result = session.run(query, k=top_k, emb=embedding)
            return [{"claim": dict(r["node"]), "score": r["score"]} for r in result]

    def mark_active(self, claim_ids: list[str], cycle: int):
        """Reset local_decay for claims actively used in reasoning."""
        query = """
        UNWIND $ids AS cid
        MATCH (c:Claim {claim_id: cid})
        SET c.local_decay = 0, c.last_active_cycle = $cycle
        """
        with self._driver.session() as session:
            session.run(query, ids=claim_ids, cycle=cycle)

    def increment_decay(self):
        """Increment local_decay for all claims. Run once per cycle."""
        query = "MATCH (c:Claim) SET c.local_decay = COALESCE(c.local_decay, 0) + 1"
        with self._driver.session() as session:
            session.run(query)

    def get_node_count(self) -> dict:
        """Quick stats."""
        query = """
        MATCH (c:Claim) WITH count(c) AS claims
        MATCH (x:Contradiction) WITH claims, count(x) AS contradictions
        MATCH (g:Gap) WITH claims, contradictions, count(g) AS gaps
        RETURN claims, contradictions, gaps
        """
        with self._driver.session() as session:
            r = session.run(query).single()
            return dict(r) if r else {"claims": 0, "contradictions": 0, "gaps": 0}
