"""Phase 1: SURVEY — The Prospector extracts claims from paper sections.

Model: DeepSeek-R1-Distill-Qwen-14B
Input: Clean markdown sections from Docling
Output: ClaimsRegistry per paper
"""

from __future__ import annotations

import logging
from pathlib import Path

from crucible.engine.phases.base import BasePhase
from crucible.context import ContextBuilder
from crucible.schemas import Claim, ClaimsRegistry

logger = logging.getLogger(__name__)


class SurveyPhase(BasePhase):
    phase_name = "survey"
    persona = "prospector"

    def __init__(self, cycle_id: str, llm=None, context_builder: ContextBuilder = None):
        super().__init__(cycle_id, llm)
        self.ctx = context_builder or ContextBuilder()

    def execute(self, sections: list[dict] = None, **kwargs) -> dict:
        """Extract claims from all provided paper sections.

        Args:
            sections: List of {"paper_id": str, "section_title": str, "text": str}

        Returns:
            {"registries": [ClaimsRegistry.model_dump(), ...]}
        """
        sections = sections or []
        system_prompt = self.load_prompt()
        registries = []

        # Group sections by paper
        papers: dict[str, list[dict]] = {}
        for sec in sections:
            papers.setdefault(sec["paper_id"], []).append(sec)

        for paper_id, paper_sections in papers.items():
            paper_claims = []
            for sec in paper_sections:
                user_content = self.ctx.for_prospector(sec["text"], paper_id)

                try:
                    raw = self.llm.chat_json(system_prompt, user_content, max_tokens=4096)
                    claims_data = raw.get("claims", []) if isinstance(raw, dict) else raw
                    for cd in claims_data:
                        cd["paper_id"] = paper_id
                        cd.setdefault("source_section", sec.get("section_title", ""))
                        try:
                            paper_claims.append(Claim(**cd))
                        except Exception as e:
                            logger.warning(f"Invalid claim from {paper_id}: {e}")
                except Exception as e:
                    logger.error(f"Extraction failed for {paper_id}/{sec.get('section_title')}: {e}")

            registry = ClaimsRegistry(paper_id=paper_id, claims=paper_claims)
            registries.append(registry.model_dump())
            logger.info(f"[{paper_id}] Extracted {len(paper_claims)} claims.")

        return {"registries": registries}
