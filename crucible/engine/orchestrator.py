"""Orchestrator — the brain of the dialectical engine.

Drives the 5-phase cycle:
  SURVEY → MAP → ATTACK → SYNTHESIZE → META-REVIEW

Each phase runs on a different model. The orchestrator manages:
1. Model swapping via ModelManager
2. Context building via ContextBuilder
3. Graph reads/writes
4. Memory injection from Mem0
5. Anomaly digest computation
6. Checkpoint-based idempotency
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from crucible.config import settings
from crucible.context import ContextBuilder
from crucible.graph.store import GraphStore
from crucible.graph.embeddings import EmbeddingModel
from crucible.graph.entity_resolution import EntityResolver
from crucible.graph.decay import DecayManager
from crucible.memory import SemanticMemory
from crucible.models.manager import ModelManager
from crucible.models.client import LLMClient
from crucible.schemas import (
    AnomalyDigest,
    AttackVerdict,
    Claim,
    Contradiction,
    ContradictionDossier,
    Gap,
    JournalEntry,
)
from crucible.engine.phases import (
    SurveyPhase,
    MapPhase,
    AttackPhase,
    SynthesizePhase,
    MetaReviewPhase,
)

logger = logging.getLogger(__name__)


class Orchestrator:
    """Runs a complete DIALECTIC cycle.

    Usage:
        orch = Orchestrator()
        entry = orch.run_cycle(sections=[...])
        # entry is a JournalEntry dict ready for the Research Journal
    """

    def __init__(
        self,
        model_manager: ModelManager = None,
        graph: GraphStore = None,
        memory: SemanticMemory = None,
    ):
        self.models = model_manager or ModelManager()
        self.graph = graph or GraphStore()
        self.memory = memory or SemanticMemory()
        self.ctx = ContextBuilder()
        self.embedder = EmbeddingModel()
        self.decay = DecayManager(self.graph)

    def run_cycle(self, sections: list[dict] = None, cycle_id: str = None) -> dict:
        """Execute a full DIALECTIC cycle.

        Args:
            sections: Paper sections to process. Each dict has:
                      {"paper_id": str, "section_title": str, "text": str}
            cycle_id: Unique cycle identifier. Auto-generated if not provided.

        Returns:
            JournalEntry.model_dump()
        """
        cycle_id = cycle_id or f"cycle_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        sections = sections or []
        provenance = {}

        logger.info(f"═══ DIALECTIC CYCLE {cycle_id} ═══")

        # ── Phase 1: SURVEY ───────────────────────────────────────────────
        logger.info("── Phase 1: SURVEY (Prospector) ──")
        base_url = self.models.load("prospector")
        provenance["survey"] = "DeepSeek-R1-Distill-Qwen-14B"
        llm = LLMClient(base_url)

        survey = SurveyPhase(cycle_id, llm, self.ctx)
        survey_output = survey.run(sections=sections)

        # Ingest claims into graph
        all_claims = []
        extraction_variance = {}
        for reg in survey_output.get("registries", []):
            claims = reg.get("claims", [])
            extraction_variance[reg["paper_id"]] = len(claims)
            for cd in claims:
                try:
                    claim = Claim(**cd)
                    embedding = self.embedder.embed(claim.claim_text)
                    self.graph.upsert_claim(claim, embedding)
                    all_claims.append(cd)
                except Exception as e:
                    logger.warning(f"Failed to ingest claim: {e}")

        self.models.unload()

        # ── Phase 2: MAP ──────────────────────────────────────────────────
        logger.info("── Phase 2: MAP (Cartographer) ──")
        base_url = self.models.load("cartographer")
        provenance["map"] = "Ministral-3-14B-Instruct"
        llm = LLMClient(base_url)

        # Inject memories
        memories = self.memory.search("cartographer", "recurring themes", top_k=5)

        graph_claims = self.graph.get_all_claims(limit=300)
        map_phase = MapPhase(cycle_id, llm, self.ctx)
        map_output = map_phase.run(claims=graph_claims, frontier_state=None)

        # Ingest contradictions and gaps
        for c_data in map_output.get("contradictions", []):
            try:
                self.graph.upsert_contradiction(Contradiction(**c_data))
            except Exception as e:
                logger.warning(f"Failed to ingest contradiction: {e}")

        for g_data in map_output.get("gaps", []):
            try:
                self.graph.upsert_gap(Gap(**g_data))
            except Exception as e:
                logger.warning(f"Failed to ingest gap: {e}")

        self.models.unload()

        # ── Phase 3: ATTACK ───────────────────────────────────────────────
        logger.info("── Phase 3: ATTACK (Demolisher) ──")
        base_url = self.models.load("demolisher")
        provenance["attack"] = "Phi-4-Reasoning-14.7B"
        llm = LLMClient(base_url)

        # Build contradiction dossiers
        active_contradictions = self.graph.get_active_contradictions()
        dossiers = self._build_dossiers(active_contradictions)

        attack_phase = AttackPhase(cycle_id, llm, self.ctx)
        attack_output = attack_phase.run(dossiers=[d.model_dump() for d in dossiers])

        # Mark active claims
        active_claim_ids = []
        for d in dossiers:
            active_claim_ids.extend([d.claim_a.claim_id, d.claim_b.claim_id])
        if active_claim_ids:
            cycle_num = int(cycle_id.split("_")[1]) if "_" in cycle_id else 0
            self.graph.mark_active(active_claim_ids, cycle_num)

        self.models.unload()

        # ── Phase 4: SYNTHESIZE ───────────────────────────────────────────
        logger.info("── Phase 4: SYNTHESIZE (Integrator) ──")
        base_url = self.models.load("integrator")
        provenance["synthesize"] = "Gemma-3-12B"
        llm = LLMClient(base_url)

        # Gather survived claims
        attack_results = attack_output.get("results", [])
        survived_claims = self._gather_survivors(attack_results, active_contradictions)

        synth_phase = SynthesizePhase(cycle_id, llm, self.ctx)
        synth_output = synth_phase.run(
            attack_results=attack_results,
            survived_claims=survived_claims,
        )

        self.models.unload()

        # ── Phase 5: META-REVIEW ──────────────────────────────────────────
        logger.info("── Phase 5: META-REVIEW (Auditor) ──")
        base_url = self.models.load("auditor")
        provenance["meta_review"] = "Qwen-3.5-4B"
        llm = LLMClient(base_url)

        # Build anomaly digest (no LLM needed)
        survival_rate = None
        if attack_results:
            survived_count = sum(
                1 for r in attack_results if r.get("verdict") == "survived"
            )
            survival_rate = survived_count / len(attack_results)

        anomaly_digest = AnomalyDigest(
            cycle_id=cycle_id,
            extraction_variance=extraction_variance,
            attack_survival_rate=survival_rate,
        )

        # Build cycle abstract
        briefs = synth_output.get("briefs", [])
        cycle_abstract = self.ctx.build_cycle_abstract(
            dossiers=dossiers,
            attack_results=[
                __import__("crucible.schemas", fromlist=["AttackResult"]).AttackResult(**r)
                for r in attack_results
            ] if attack_results else [],
            briefs=[
                __import__("crucible.schemas", fromlist=["ResearchBrief"]).ResearchBrief(**b)
                for b in briefs
            ] if briefs else [],
        )

        meta_phase = MetaReviewPhase(cycle_id, llm, self.ctx)
        meta_output = meta_phase.run(
            cycle_abstract=cycle_abstract,
            anomaly_digest=anomaly_digest.model_dump(),
        )

        self.models.unload()

        # ── Decay & Cleanup ───────────────────────────────────────────────
        self.decay.run_decay_cycle()

        # ── Assemble Journal Entry ────────────────────────────────────────
        entry = JournalEntry(
            cycle_id=cycle_id,
            briefs=[
                __import__("crucible.schemas", fromlist=["ResearchBrief"]).ResearchBrief(**b)
                for b in briefs
            ] if briefs else [],
            meta_review=__import__("crucible.schemas", fromlist=["MetaReview"]).MetaReview(**meta_output) if meta_output else None,
            provenance=provenance,
        )

        logger.info(f"═══ CYCLE {cycle_id} COMPLETE ═══")
        return entry.model_dump()

    def _build_dossiers(self, contradictions: list[dict]) -> list[ContradictionDossier]:
        """Build ContradictionDossier objects from graph data."""
        dossiers = []
        for c in contradictions:
            try:
                claim_a_data = c.get("claim_a", {})
                claim_b_data = c.get("claim_b", {})
                contra_data = c.get("contradiction", {})

                dossier = ContradictionDossier(
                    contradiction_id=contra_data.get("contradiction_id", "unknown"),
                    claim_a=Claim(**claim_a_data),
                    claim_b=Claim(**claim_b_data),
                    citation_context=contra_data.get("nature", ""),
                )
                dossiers.append(dossier)
            except Exception as e:
                logger.warning(f"Failed to build dossier: {e}")
        return dossiers

    def _gather_survivors(
        self,
        attack_results: list[dict],
        contradictions: list[dict],
    ) -> list[dict]:
        """Gather claim dicts that survived or were wounded."""
        surviving_ids = set()
        for r in attack_results:
            if r.get("verdict") in ("survived", "wounded"):
                sid = r.get("surviving_claim_id")
                if sid:
                    surviving_ids.add(sid)

        # If survived, both claims survive
        for r in attack_results:
            if r.get("verdict") == "survived":
                for c in contradictions:
                    contra = c.get("contradiction", {})
                    if contra.get("contradiction_id") == r.get("contradiction_id"):
                        surviving_ids.add(c.get("claim_a", {}).get("claim_id", ""))
                        surviving_ids.add(c.get("claim_b", {}).get("claim_id", ""))

        surviving_ids.discard("")
        claims = []
        for cid in surviving_ids:
            graph_claims = self.graph.get_all_claims(limit=1000)
            for gc in graph_claims:
                if gc.get("claim_id") == cid:
                    claims.append(gc)
                    break

        return claims
