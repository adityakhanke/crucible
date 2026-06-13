"""Research API clients — ArXiv, Semantic Scholar, Papers With Code.

All clients are async-capable but provide sync wrappers for simplicity.
"""

from __future__ import annotations

import logging
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx

from crucible.config import get_paths

logger = logging.getLogger(__name__)

_ARXIV_API = "https://export.arxiv.org/api/query"
_ARXIV_PDF = "https://export.arxiv.org/pdf"
_S2_API = "https://api.semanticscholar.org/graph/v1"


# ── Data Classes ──────────────────────────────────────────────────────────

@dataclass
class PaperMeta:
    paper_id: str
    title: str
    authors: list[str]
    abstract: str
    published: str
    url: str
    citation_count: Optional[int] = None
    references: Optional[list[str]] = None


# ── ArXiv Client ──────────────────────────────────────────────────────────

class ArxivClient:
    """Search and download papers from ArXiv."""

    def __init__(self):
        self._client = httpx.Client(timeout=30)

    def search(self, query: str, max_results: int = 10) -> list[PaperMeta]:
        """Search ArXiv by query string."""
        params = {
            "search_query": f"all:{query}",
            "start": 0,
            "max_results": max_results,
            "sortBy": "relevance",
        }
        resp = self._client.get(_ARXIV_API, params=params)
        resp.raise_for_status()
        return self._parse_feed(resp.text)

    def fetch_pdf(self, paper_id: str) -> Path:
        """Download a paper's PDF to the papers directory."""
        # Normalize ID (remove version suffix if present)
        clean_id = paper_id.split("v")[0]
        url = f"{_ARXIV_PDF}/{clean_id}"

        output_dir = Path(get_paths()["papers_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{clean_id.replace('/', '_')}.pdf"

        if output_path.exists():
            logger.info(f"PDF already exists: {output_path}")
            return output_path

        logger.info(f"Downloading: {url}")
        resp = self._client.get(url, follow_redirects=True)
        resp.raise_for_status()
        output_path.write_bytes(resp.content)
        logger.info(f"Saved: {output_path}")

        # Respect rate limit
        time.sleep(3)
        return output_path

    def _parse_feed(self, xml_text: str) -> list[PaperMeta]:
        root = ET.fromstring(xml_text)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        papers = []

        for entry in root.findall("atom:entry", ns):
            paper_id_url = entry.find("atom:id", ns).text
            paper_id = paper_id_url.split("/abs/")[-1]

            title = entry.find("atom:title", ns).text.strip().replace("\n", " ")
            abstract = entry.find("atom:summary", ns).text.strip().replace("\n", " ")
            published = entry.find("atom:published", ns).text[:10]

            authors = [
                a.find("atom:name", ns).text
                for a in entry.findall("atom:author", ns)
            ]

            papers.append(PaperMeta(
                paper_id=paper_id,
                title=title,
                authors=authors,
                abstract=abstract,
                published=published,
                url=paper_id_url,
            ))

        return papers


# ── Semantic Scholar Client ───────────────────────────────────────────────

class SemanticScholarClient:
    """Query the Semantic Scholar Academic Graph API."""

    def __init__(self, api_key: Optional[str] = None):
        headers = {}
        if api_key:
            headers["x-api-key"] = api_key
        self._client = httpx.Client(
            base_url=_S2_API,
            headers=headers,
            timeout=30,
        )

    def search(self, query: str, limit: int = 10) -> list[PaperMeta]:
        """Search for papers by keyword."""
        resp = self._client.get(
            "/paper/search",
            params={
                "query": query,
                "limit": limit,
                "fields": "title,authors,abstract,year,citationCount,url,externalIds",
            },
        )
        resp.raise_for_status()
        data = resp.json().get("data", [])
        return [self._to_meta(p) for p in data]

    def get_paper(self, paper_id: str) -> Optional[PaperMeta]:
        """Get details for a specific paper."""
        resp = self._client.get(
            f"/paper/{paper_id}",
            params={"fields": "title,authors,abstract,year,citationCount,url,references,externalIds"},
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return self._to_meta(resp.json())

    def get_references(self, paper_id: str, limit: int = 50) -> list[PaperMeta]:
        """Get papers referenced by this paper."""
        resp = self._client.get(
            f"/paper/{paper_id}/references",
            params={"fields": "title,authors,abstract,year,citationCount,url", "limit": limit},
        )
        resp.raise_for_status()
        data = resp.json().get("data", [])
        return [self._to_meta(r["citedPaper"]) for r in data if r.get("citedPaper", {}).get("title")]

    def get_citations(self, paper_id: str, limit: int = 50) -> list[PaperMeta]:
        """Get papers that cite this paper."""
        resp = self._client.get(
            f"/paper/{paper_id}/citations",
            params={"fields": "title,authors,abstract,year,citationCount,url", "limit": limit},
        )
        resp.raise_for_status()
        data = resp.json().get("data", [])
        return [self._to_meta(r["citingPaper"]) for r in data if r.get("citingPaper", {}).get("title")]

    def _to_meta(self, data: dict) -> PaperMeta:
        arxiv_id = (data.get("externalIds") or {}).get("ArXiv", data.get("paperId", "unknown"))
        return PaperMeta(
            paper_id=arxiv_id or data.get("paperId", "unknown"),
            title=data.get("title", ""),
            authors=[a.get("name", "") for a in (data.get("authors") or [])],
            abstract=data.get("abstract") or "",
            published=str(data.get("year", "")),
            url=data.get("url") or "",
            citation_count=data.get("citationCount"),
            references=[
                r.get("paperId") for r in (data.get("references") or []) if r.get("paperId")
            ] if data.get("references") else None,
        )
