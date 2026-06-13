"""Phase 3: ATTACK — The Demolisher destroys weak hypotheses.

Model: Phi-4-Reasoning 14.7B (context capped at 16K)
Input: Contradiction Dossiers from the ContextBuilder
Output: AttackReport with SURVIVED / WOUNDED / KILLED verdicts
"""

from __future__ import annotations

import logging

from crucible.engine.phases.base import BasePhase
from crucible.context import ContextBuilder
from crucible.schemas import (
    AttackReport,
    AttackResult,
    AttackVerdict,
    ContradictionDossier,
)

logger = logging.getLogger(__name__)


class AttackPhase(BasePhase):
    phase_name = "attack"
    persona = "demolisher"

    def __init__(self, cycle_id: str, llm=None, context_builder: ContextBuilder = None):
        super().__init__(cycle_id, llm)
        self.ctx = context_builder or ContextBuilder()

    def execute(self, dossiers: list[dict] = None, **kwargs) -> dict:
        """Run adversarial analysis on contradiction dossiers.

        Args:
            dossiers: List of ContradictionDossier.model_dump() dicts.

        Returns:
            AttackReport.model_dump()
        """
        dossiers = dossiers or []
        system_prompt = self.load_prompt()

        # Reconstruct typed dossiers
        typed_dossiers = []
        for d in dossiers:
            try:
                typed_dossiers.append(ContradictionDossier(**d))
            except Exception as e:
                logger.warning(f"Invalid dossier: {e}")

        if not typed_dossiers:
            logger.info("[attack] No dossiers to attack.")
            return AttackReport(cycle_id=self.cycle_id, results=[]).model_dump()

        user_content = self.ctx.for_demolisher(typed_dossiers)
        raw = self.llm.chat_json(system_prompt, user_content, max_tokens=4096)

        results = []
        for r in raw.get("results", []):
            try:
                results.append(AttackResult(
                    contradiction_id=r["contradiction_id"],
                    verdict=AttackVerdict(r["verdict"]),
                    rationale=r.get("rationale", ""),
                    surviving_claim_id=r.get("surviving_claim_id"),
                ))
            except Exception as e:
                logger.warning(f"Invalid attack result: {e}")

        report = AttackReport(cycle_id=self.cycle_id, results=results)

        survived = sum(1 for r in results if r.verdict == AttackVerdict.SURVIVED)
        wounded = sum(1 for r in results if r.verdict == AttackVerdict.WOUNDED)
        killed = sum(1 for r in results if r.verdict == AttackVerdict.KILLED)
        logger.info(f"[attack] {survived} survived, {wounded} wounded, {killed} killed")

        return report.model_dump()
