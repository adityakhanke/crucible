"""Genesis Protocol — Day 0 bootstrapping for the knowledge graph.

Given 2-3 seed ArXiv IDs, expands the neighborhood via Semantic Scholar:
1. Foundational Traversal: top-cited upstream papers
2. Contrarian Traversal: papers citing foundations but with divergent reference lists
3. Human approval of the final ~15-paper seed corpus
4. SCOUT pipeline ingests the approved corpus
5. Genesis MAP pass creates Frontier Map v1.0
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from crucible.config import settings, get_paths
from crucible.tools.apis import ArxivClient, SemanticScholarClient, PaperMeta

logger = logging.getLogger(__name__)


class GenesisProtocol:
    """Bootstraps the system from a handful of seed papers."""

    def __init__(self):
        self.arxiv = ArxivClient()
        self.s2 = SemanticScholarClient()
        cfg = settings().get("genesis", {})
        self._foundational_count = cfg.get("foundational_count", 5)
        self._target_size = cfg.get("target_corpus_size", 15)
        self._seed_path = Path(get_paths().get("seed_corpus", "./data/seed_corpus.json"))

    def generate_seed_corpus(self, seed_ids: list[str]) -> list[dict]:
        """Expand seed ArXiv IDs into a ~15-paper seed corpus.

        Args:
            seed_ids: 2-3 ArXiv paper IDs (e.g., ["2001.08361", "2203.15556"])

        Returns:
            List of paper metadata dicts for human review.
        """
        logger.info(f"Genesis: expanding {len(seed_ids)} seeds...")

        seeds = []
        for arxiv_id in seed_ids:
            paper = self.s2.get_paper(f"ArXiv:{arxiv_id}")
            if paper:
                seeds.append(paper)
                logger.info(f"  Seed: {paper.title}")
            else:
                logger.warning(f"  Could not find paper: {arxiv_id}")

        if not seeds:
            raise ValueError("No valid seed papers found.")

        # Step 1: Foundational Traversal
        foundational = self._foundational_traversal(seeds)
        logger.info(f"  Foundational papers: {len(foundational)}")

        # Step 2: Contrarian Traversal
        contrarian = self._contrarian_traversal(seeds, foundational)
        logger.info(f"  Contrarian papers: {len(contrarian)}")

        # Combine and deduplicate
        all_papers = {p.paper_id: p for p in seeds}
        for p in foundational:
            all_papers[p.paper_id] = p
        for p in contrarian:
            all_papers[p.paper_id] = p

        # Trim to target size
        corpus = list(all_papers.values())[:self._target_size]

        # Save for human review
        corpus_data = [self._paper_to_dict(p) for p in corpus]
        self._save_corpus(corpus_data)

        logger.info(f"Genesis: seed corpus of {len(corpus_data)} papers saved to {self._seed_path}")
        logger.info("Review the corpus and run `crucible genesis --approve` to proceed.")

        return corpus_data

    def _foundational_traversal(self, seeds: list[PaperMeta]) -> list[PaperMeta]:
        """Get top-cited upstream references from seed papers."""
        all_refs = []
        for seed in seeds:
            refs = self.s2.get_references(f"ArXiv:{seed.paper_id}", limit=20)
            all_refs.extend(refs)

        # Sort by citation count, take top N
        all_refs.sort(key=lambda p: p.citation_count or 0, reverse=True)

        # Deduplicate
        seen = set()
        unique = []
        for p in all_refs:
            if p.paper_id not in seen:
                seen.add(p.paper_id)
                unique.append(p)

        return unique[:self._foundational_count]

    def _contrarian_traversal(
        self,
        seeds: list[PaperMeta],
        foundational: list[PaperMeta],
    ) -> list[PaperMeta]:
        """Find papers that cite foundational work but diverge in references.

        The cross-community bridging pattern: papers whose reference lists
        have LOW overlap with the foundational papers' combined reference lists.
        """
        # Build the foundational reference set
        foundational_ref_ids = set()
        for paper in foundational:
            refs = self.s2.get_references(paper.paper_id, limit=30)
            for r in refs:
                foundational_ref_ids.add(r.paper_id)

        # Find papers citing foundational work
        citing_papers = []
        for paper in foundational[:3]:  # Limit API calls
            citations = self.s2.get_citations(paper.paper_id, limit=20)
            citing_papers.extend(citations)

        # Score by reference divergence
        scored = []
        for paper in citing_papers:
            try:
                refs = self.s2.get_references(paper.paper_id, limit=30)
                ref_ids = {r.paper_id for r in refs}

                if not ref_ids:
                    continue

                overlap = len(ref_ids & foundational_ref_ids) / len(ref_ids)
                # Low overlap = high contrarian score
                contrarian_score = 1.0 - overlap
                scored.append((contrarian_score, paper))
            except Exception:
                continue

        # Sort by contrarian score (descending)
        scored.sort(key=lambda x: x[0], reverse=True)

        # Take papers with highest divergence
        target = self._target_size - len(foundational) - len(seeds)
        return [p for _, p in scored[:max(target, 3)]]

    def approve_corpus(self, exclude_ids: list[str] = None) -> list[dict]:
        """Load saved corpus, optionally exclude papers, return final list."""
        if not self._seed_path.exists():
            raise FileNotFoundError(f"No seed corpus found at {self._seed_path}. Run genesis first.")

        with open(self._seed_path) as f:
            corpus = json.load(f)

        if exclude_ids:
            corpus = [p for p in corpus if p["paper_id"] not in exclude_ids]

        # Save the approved version
        self._save_corpus(corpus)
        logger.info(f"Approved corpus: {len(corpus)} papers.")
        return corpus

    def download_corpus(self, corpus: list[dict] = None) -> list[Path]:
        """Download PDFs for all papers in the approved corpus."""
        if corpus is None:
            with open(self._seed_path) as f:
                corpus = json.load(f)

        paths = []
        for paper in corpus:
            pid = paper.get("paper_id", "")
            try:
                path = self.arxiv.fetch_pdf(pid)
                paths.append(path)
            except Exception as e:
                logger.warning(f"Failed to download {pid}: {e}")

        logger.info(f"Downloaded {len(paths)} / {len(corpus)} papers.")
        return paths

    def _save_corpus(self, corpus: list[dict]):
        self._seed_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._seed_path, "w") as f:
            json.dump(corpus, f, indent=2)

    @staticmethod
    def _paper_to_dict(paper: PaperMeta) -> dict:
        return {
            "paper_id": paper.paper_id,
            "title": paper.title,
            "authors": paper.authors,
            "abstract": paper.abstract[:500],
            "published": paper.published,
            "citation_count": paper.citation_count,
            "url": paper.url,
        }
