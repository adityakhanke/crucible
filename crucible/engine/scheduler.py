"""Scheduler — coordinates the three operational modes.

SCOUT: Nightly paper ingestion (search → download → parse → extract → graph update)
DIALECTIC: Full 5-phase cycle (triggered by schedule or paper accumulation)
REVIEW: Human-triggered interactive review of Research Briefs
"""

from __future__ import annotations

import logging
from pathlib import Path

from crucible.config import settings, get_paths
from crucible.parsing import DoclingParser
from crucible.tools.apis import ArxivClient, SemanticScholarClient
from crucible.engine.orchestrator import Orchestrator
from crucible.graph.store import GraphStore
from crucible.models.manager import ModelManager

logger = logging.getLogger(__name__)


class Scheduler:
    """Coordinates SCOUT, DIALECTIC, and REVIEW modes."""

    def __init__(self):
        self.graph = GraphStore()
        self.model_manager = ModelManager()
        self.parser = DoclingParser()
        self.arxiv = ArxivClient()
        self.s2 = SemanticScholarClient()
        self._cfg = settings().get("scheduler", {})

    def scout(self, keywords: list[str] = None):
        """SCOUT mode: discover, download, parse, and ingest new papers.

        1. Search ArXiv + Semantic Scholar for tracked keywords
        2. Download new PDFs
        3. Parse via Docling (CPU)
        4. Load Prospector, extract claims, update graph
        5. Unload model
        """
        keywords = keywords or ["transformer scaling laws", "LLM efficiency"]

        logger.info("═══ SCOUT MODE ═══")

        # Step 1: Search
        all_papers = []
        for kw in keywords:
            logger.info(f"Searching ArXiv for: {kw}")
            all_papers.extend(self.arxiv.search(kw, max_results=5))

        logger.info(f"Found {len(all_papers)} papers.")

        # Step 2: Download
        pdf_paths = []
        for paper in all_papers:
            try:
                path = self.arxiv.fetch_pdf(paper.paper_id)
                pdf_paths.append(path)
            except Exception as e:
                logger.warning(f"Failed to download {paper.paper_id}: {e}")

        # Step 3: Parse (CPU — no GPU needed)
        all_sections = []
        for pdf_path in pdf_paths:
            try:
                parsed = self.parser.parse_pdf(pdf_path)
                for sec in parsed.sections:
                    all_sections.append({
                        "paper_id": parsed.paper_id,
                        "section_title": sec.section_title,
                        "text": sec.text,
                    })
            except Exception as e:
                logger.error(f"Failed to parse {pdf_path}: {e}")

        # Step 4: Extract claims (GPU — load Prospector)
        if all_sections:
            from crucible.models.client import LLMClient
            from crucible.engine.phases.survey import SurveyPhase
            from crucible.context import ContextBuilder

            base_url = self.model_manager.load("prospector")
            llm = LLMClient(base_url)
            survey = SurveyPhase(cycle_id="scout", llm=llm, context_builder=ContextBuilder())
            survey_output = survey.execute(sections=all_sections)

            # Ingest into graph
            from crucible.graph.embeddings import EmbeddingModel
            from crucible.schemas import Claim

            embedder = EmbeddingModel()
            total_claims = 0
            for reg in survey_output.get("registries", []):
                for cd in reg.get("claims", []):
                    try:
                        claim = Claim(**cd)
                        embedding = embedder.embed(claim.claim_text)
                        self.graph.upsert_claim(claim, embedding)
                        total_claims += 1
                    except Exception as e:
                        logger.warning(f"Ingest failed: {e}")

            self.model_manager.unload()
            logger.info(f"SCOUT complete: ingested {total_claims} claims from {len(pdf_paths)} papers.")
        else:
            logger.info("SCOUT complete: no new sections to process.")

    def dialectic(self, sections: list[dict] = None, cycle_id: str = None) -> dict:
        """DIALECTIC mode: run a full 5-phase cycle.

        Args:
            sections: Optional new sections to process. If None, uses existing graph.
            cycle_id: Optional cycle identifier.

        Returns:
            JournalEntry dict.
        """
        logger.info("═══ DIALECTIC MODE ═══")
        orch = Orchestrator(
            model_manager=self.model_manager,
            graph=self.graph,
        )
        return orch.run_cycle(sections=sections, cycle_id=cycle_id)

    def review(self):
        """REVIEW mode: interactive human review of Research Briefs.

        Reads accumulated briefs, collects ratings, stores in Mem0.
        """
        logger.info("═══ REVIEW MODE ═══")

        from crucible.journal import JournalWriter

        journal = JournalWriter()
        entries = journal.list_entries()

        if not entries:
            logger.info("No journal entries to review.")
            return

        # Interactive review (simple stdin-based)
        from crucible.memory import SemanticMemory
        from crucible.schemas import ReviewRating

        memory = SemanticMemory()

        for entry_path in entries:
            entry = journal.load_entry(entry_path)
            briefs = entry.get("briefs", [])

            for brief in briefs:
                print(f"\n{'='*60}")
                print(f"Hypothesis: {brief.get('hypothesis', 'N/A')}")
                print(f"Experiment: {brief.get('minimum_viable_experiment', 'N/A')}")
                print(f"Assumptions: {brief.get('assumptions', [])}")
                print(f"{'='*60}")

                rating = input("Rate [s]trong / [i]nteresting / [w]eak / [x]wrong / [skip]: ").strip().lower()

                rating_map = {"s": "strong", "i": "interesting", "w": "weak", "x": "wrong"}
                if rating in rating_map:
                    # Store rating in memory for future calibration
                    memory.add(
                        "integrator",
                        f"Brief rated '{rating_map[rating]}': {brief.get('hypothesis', '')}",
                        metadata={"rating": rating_map[rating], "cycle_id": entry.get("cycle_id")},
                    )
                    print(f"  → Rated: {rating_map[rating]}")

        logger.info("REVIEW complete.")
