"""Phase 5: META-REVIEW — The Auditor catches systemic blind spots.

Model: Qwen 3.5 4B/9B (via SGLang)
Input: Compressed Cycle Abstract + Anomaly Digest
Output: MetaReview identifying shared assumptions, logical leaps, and blind spots
"""

from __future__ import annotations

import logging

from crucible.engine.phases.base import BasePhase
from crucible.context import ContextBuilder
from crucible.schemas import AnomalyDigest, MetaReview

logger = logging.getLogger(__name__)


class MetaReviewPhase(BasePhase):
    phase_name = "meta_review"
    persona = "auditor"

    def __init__(self, cycle_id: str, llm=None, context_builder: ContextBuilder = None):
        super().__init__(cycle_id, llm)
        self.ctx = context_builder or ContextBuilder()

    def execute(
        self,
        cycle_abstract: str = "",
        anomaly_digest: dict = None,
        **kwargs,
    ) -> dict:
        """Run meta-review on the entire cycle's output.

        Args:
            cycle_abstract: Compressed summary of the cycle (6-8K tokens).
            anomaly_digest: AnomalyDigest.model_dump() dict.

        Returns:
            MetaReview.model_dump()
        """
        system_prompt = self.load_prompt()

        digest = AnomalyDigest(**(anomaly_digest or {"cycle_id": self.cycle_id}))
        user_content = self.ctx.for_auditor(cycle_abstract, digest)

        raw = self.llm.chat_json(system_prompt, user_content, max_tokens=2048)

        review = MetaReview(
            cycle_id=self.cycle_id,
            shared_assumptions=raw.get("shared_assumptions", []),
            logical_leaps=raw.get("logical_leaps", []),
            disciplinary_blind_spots=raw.get("disciplinary_blind_spots", []),
            recommendations=raw.get("recommendations", []),
        )

        logger.info(
            f"[meta_review] {len(review.shared_assumptions)} assumptions, "
            f"{len(review.recommendations)} recommendations"
        )
        return review.model_dump()
