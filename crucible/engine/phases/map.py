"""Phase 2: MAP — The Cartographer organizes claims into an intellectual landscape.

Model: Ministral 3 14B Instruct
Input: Claims Registry + current Frontier Map state
Output: MapUpdate (themes, contradictions, gaps, convergences)
"""

from __future__ import annotations

import logging

from crucible.engine.phases.base import BasePhase
from crucible.context import ContextBuilder
from crucible.schemas import MapUpdate, Contradiction, Gap, Theme, Convergence

logger = logging.getLogger(__name__)


class MapPhase(BasePhase):
    phase_name = "map"
    persona = "cartographer"

    def __init__(self, cycle_id: str, llm=None, context_builder: ContextBuilder = None):
        super().__init__(cycle_id, llm)
        self.ctx = context_builder or ContextBuilder()

    def execute(self, claims: list[dict] = None, frontier_state: dict = None, **kwargs) -> dict:
        """Map claims into themes, contradictions, gaps, and convergences.

        Args:
            claims: List of claim dicts from the graph or prior phase.
            frontier_state: Current Frontier Map state.

        Returns:
            MapUpdate.model_dump()
        """
        claims = claims or []
        system_prompt = self.load_prompt()
        user_content = self.ctx.for_cartographer(claims, frontier_state)

        raw = self.llm.chat_json(system_prompt, user_content, max_tokens=4096)

        # Parse into structured types
        themes = [Theme(**t) for t in raw.get("themes", [])]
        contradictions = [Contradiction(**c) for c in raw.get("contradictions", [])]
        gaps = [Gap(**g) for g in raw.get("gaps", [])]
        convergences = [Convergence(**c) for c in raw.get("convergences", [])]

        update = MapUpdate(
            cycle_id=self.cycle_id,
            themes=themes,
            contradictions=contradictions,
            gaps=gaps,
            convergences=convergences,
        )

        logger.info(
            f"[map] {len(themes)} themes, {len(contradictions)} contradictions, "
            f"{len(gaps)} gaps, {len(convergences)} convergences"
        )
        return update.model_dump()
