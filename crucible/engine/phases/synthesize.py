"""Phase 4: SYNTHESIZE — The Integrator forges survivors into research directions.

Model: Gemma 3 12B
Input: SURVIVED and WOUNDED items + original claims
Output: SynthesisReport containing Research Briefs
"""

from __future__ import annotations

import logging

from crucible.engine.phases.base import BasePhase
from crucible.context import ContextBuilder
from crucible.schemas import (
    AttackResult,
    AttackVerdict,
    ResearchBrief,
    SynthesisReport,
)

logger = logging.getLogger(__name__)


class SynthesizePhase(BasePhase):
    phase_name = "synthesize"
    persona = "integrator"

    def __init__(self, cycle_id: str, llm=None, context_builder: ContextBuilder = None):
        super().__init__(cycle_id, llm)
        self.ctx = context_builder or ContextBuilder()

    def execute(
        self,
        attack_results: list[dict] = None,
        survived_claims: list[dict] = None,
        **kwargs,
    ) -> dict:
        """Generate research briefs from surviving hypotheses.

        Args:
            attack_results: List of AttackResult.model_dump() dicts.
            survived_claims: Claim dicts that survived or were wounded.

        Returns:
            SynthesisReport.model_dump()
        """
        attack_results = attack_results or []
        survived_claims = survived_claims or []
        system_prompt = self.load_prompt()

        # Filter to survived + wounded
        typed_results = []
        for r in attack_results:
            try:
                ar = AttackResult(**r)
                if ar.verdict in (AttackVerdict.SURVIVED, AttackVerdict.WOUNDED):
                    typed_results.append(ar)
            except Exception:
                pass

        if not typed_results and not survived_claims:
            logger.info("[synthesize] Nothing survived to synthesize.")
            return SynthesisReport(cycle_id=self.cycle_id, briefs=[]).model_dump()

        user_content = self.ctx.for_integrator(survived_claims, typed_results)
        raw = self.llm.chat_json(system_prompt, user_content, max_tokens=4096)

        briefs = []
        for b in raw.get("briefs", []):
            try:
                b["cycle_id"] = self.cycle_id
                b.setdefault("brief_id", f"{self.cycle_id}_{len(briefs)}")
                briefs.append(ResearchBrief(**b))
            except Exception as e:
                logger.warning(f"Invalid brief: {e}")

        report = SynthesisReport(cycle_id=self.cycle_id, briefs=briefs)
        logger.info(f"[synthesize] Generated {len(briefs)} research briefs.")
        return report.model_dump()
