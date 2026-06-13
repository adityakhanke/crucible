"""Phase-Aware Context Builder.

Formats graph data specifically for each phase's cognitive task.
Manages token budgets against the active model's tokenizer.

Token Budget (32K cap):
  System prompt + phase instructions:  1,500
  Mem0 retrieved memories:             2,000
  Graph-retrieved structured context:  8,000-12,000
  Prior phase output:                  6,000-10,000
  Working space for generation:       10,000-14,000
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from crucible.config import settings
from crucible.schemas import (
    Claim,
    Contradiction,
    ContradictionDossier,
    AttackResult,
    ResearchBrief,
    AnomalyDigest,
)

logger = logging.getLogger(__name__)


class ContextBuilder:
    """Builds phase-specific context within token budgets.

    Each phase gets a different view of the knowledge graph:
    - Prospector: Raw markdown text
    - Cartographer: Flat claim lists grouped by similarity
    - Demolisher: Structured contradiction dossiers
    - Integrator: Survived hypotheses with evidence chains
    - Auditor: Compressed Cycle Abstract + Anomaly Digest
    """

    def __init__(self, max_tokens: int = 32000):
        cfg = settings().get("engine", {})
        self._max_tokens = cfg.get("max_context_tokens", max_tokens)
        self._budgets = {
            "system": cfg.get("system_prompt_tokens", 1500),
            "memory": cfg.get("memory_tokens", 2000),
            "graph": cfg.get("graph_context_tokens", 10000),
            "prior": cfg.get("prior_phase_tokens", 8000),
            "generation": cfg.get("generation_tokens", 12000),
        }
        # Tokenizer: defaults to char/4 estimate. Override with set_tokenizer().
        self._tokenizer = None

    def set_tokenizer(self, tokenizer_fn):
        """Set an exact tokenizer function (str → int)."""
        self._tokenizer = tokenizer_fn

    def count_tokens(self, text: str) -> int:
        """Count tokens using the active tokenizer or estimate."""
        if self._tokenizer:
            return self._tokenizer(text)
        return len(text) // 4  # Conservative estimate

    def truncate_to_budget(self, text: str, budget_key: str) -> str:
        """Truncate text to fit within a budget slice."""
        budget = self._budgets.get(budget_key, 4000)
        tokens = self.count_tokens(text)
        if tokens <= budget:
            return text

        # Rough truncation by character ratio
        ratio = budget / max(tokens, 1)
        cutoff = int(len(text) * ratio * 0.95)
        return text[:cutoff] + "\n\n[... truncated to fit token budget ...]"

    # ── Phase-Specific Formatters ─────────────────────────────────────────

    def for_prospector(self, section_text: str, paper_id: str) -> str:
        """Phase 1: Raw markdown text from a single paper section."""
        header = f"Paper ID: {paper_id}\n\n"
        return self.truncate_to_budget(header + section_text, "graph")

    def for_cartographer(self, claims: list[dict], frontier_state: Optional[dict] = None) -> str:
        """Phase 2: Flat claim list grouped by paper, plus frontier state."""
        parts = ["=== CURRENT CLAIMS ===\n"]
        for c in claims:
            parts.append(
                f"[{c.get('claim_id', '?')[:8]}] ({c.get('evidence_type', '?')}/{c.get('specificity', '?')}) "
                f"{c.get('claim_text', 'N/A')}  — Paper: {c.get('paper_id', '?')}"
            )

        if frontier_state:
            parts.append("\n=== FRONTIER MAP STATE ===\n")
            parts.append(json.dumps(frontier_state, indent=2, default=str))

        return self.truncate_to_budget("\n".join(parts), "graph")

    def for_demolisher(self, dossiers: list[ContradictionDossier]) -> str:
        """Phase 3: Structured contradiction dossiers (~150-300 tokens each)."""
        parts = ["=== CONTRADICTION DOSSIERS ===\n"]
        for d in dossiers:
            parts.append(f"--- Contradiction: {d.contradiction_id} ---")
            parts.append(f"Claim A [{d.claim_a.paper_id}]: {d.claim_a.claim_text}")
            parts.append(f"Claim B [{d.claim_b.paper_id}]: {d.claim_b.claim_text}")
            if d.evidence_a:
                parts.append(f"Evidence A: {d.evidence_a}")
            if d.evidence_b:
                parts.append(f"Evidence B: {d.evidence_b}")
            if d.citation_context:
                parts.append(f"Citation Context: {d.citation_context}")
            parts.append("")

        return self.truncate_to_budget("\n".join(parts), "graph")

    def for_integrator(self, survived: list[dict], attack_results: list[AttackResult]) -> str:
        """Phase 4: Survived hypotheses with full evidence chains."""
        parts = ["=== SURVIVED HYPOTHESES ===\n"]
        for item in survived:
            parts.append(f"Claim: {item.get('claim_text', 'N/A')}")
            parts.append(f"Paper: {item.get('paper_id', '?')}")
            parts.append(f"Type: {item.get('evidence_type', '?')}")
            parts.append("")

        parts.append("=== ATTACK RESULTS ===\n")
        for ar in attack_results:
            parts.append(f"[{ar.verdict.value.upper()}] Contradiction {ar.contradiction_id}: {ar.rationale[:200]}")
            parts.append("")

        return self.truncate_to_budget("\n".join(parts), "graph")

    def for_auditor(
        self,
        cycle_abstract: str,
        anomaly_digest: AnomalyDigest,
    ) -> str:
        """Phase 5: Compressed Cycle Abstract + Anomaly Digest.

        The Cycle Abstract is 6-8K tokens. The Anomaly Digest is ~500 tokens.
        Together they fit within the Auditor's 8K context window.
        """
        digest_text = self._format_anomaly_digest(anomaly_digest)
        combined = f"{cycle_abstract}\n\n=== ANOMALY DIGEST ===\n{digest_text}"
        return self.truncate_to_budget(combined, "graph")

    def build_cycle_abstract(
        self,
        dossiers: list[ContradictionDossier],
        attack_results: list[AttackResult],
        briefs: list[ResearchBrief],
    ) -> str:
        """Build the compressed Cycle Abstract for the Auditor.

        Retains: contradiction dossiers, attack rulings + rationales, research briefs.
        Strips: raw evidence text, claim metadata.
        """
        parts = ["=== CYCLE ABSTRACT ===\n"]

        parts.append("-- Contradictions Examined --")
        for d in dossiers:
            parts.append(f"  {d.contradiction_id}: {d.claim_a.claim_text[:100]} vs {d.claim_b.claim_text[:100]}")

        parts.append("\n-- Attack Rulings --")
        for ar in attack_results:
            parts.append(f"  [{ar.verdict.value}] {ar.contradiction_id}: {ar.rationale[:150]}")

        parts.append("\n-- Research Briefs --")
        for b in briefs:
            parts.append(f"  Hypothesis: {b.hypothesis[:200]}")
            parts.append(f"  Experiment: {b.minimum_viable_experiment[:150]}")
            parts.append("")

        return "\n".join(parts)

    def _format_anomaly_digest(self, digest: AnomalyDigest) -> str:
        parts = [f"Cycle: {digest.cycle_id}"]

        if digest.extraction_variance:
            parts.append("Extraction variance:")
            for pid, count in digest.extraction_variance.items():
                parts.append(f"  {pid}: {count} claims")

        if digest.attack_survival_rate is not None:
            parts.append(f"Attack survival rate: {digest.attack_survival_rate:.1%}")

        if digest.merge_confidence_flags:
            parts.append("Merge confidence flags:")
            for flag in digest.merge_confidence_flags:
                parts.append(f"  - {flag}")

        if digest.outliers:
            parts.append("Outliers:")
            for o in digest.outliers:
                parts.append(f"  - {o}")

        return "\n".join(parts)

    def format_memories(self, memories: list[dict]) -> str:
        """Format Mem0 memories for injection into context."""
        if not memories:
            return ""
        parts = ["=== ACCUMULATED INSIGHTS ===\n"]
        for m in memories:
            text = m.get("memory", m.get("text", str(m)))
            parts.append(f"- {text}")
        return self.truncate_to_budget("\n".join(parts), "memory")
