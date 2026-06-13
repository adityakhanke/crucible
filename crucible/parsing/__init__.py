"""PDF → Clean Markdown pipeline via Docling.

Empirically validated as load-bearing: clean section-level input produces
20 precise claims. Raw PDF produces hallucinated garbage.

Docling runs entirely on CPU — never competes with the LLM for VRAM.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from dataclasses import dataclass

from crucible.config import get_paths

logger = logging.getLogger(__name__)


@dataclass
class ParsedSection:
    """A single section from a parsed paper."""

    paper_id: str
    section_title: str
    section_index: int
    text: str
    token_estimate: int  # Rough estimate: len(text) / 4


@dataclass
class ParsedPaper:
    """Complete parsed output for one paper."""

    paper_id: str
    title: str
    authors: list[str]
    sections: list[ParsedSection]
    full_markdown: str


class DoclingParser:
    """Converts PDFs to clean, section-level markdown chunks.

    Pipeline:
        ArXiv PDF → Docling → Clean Markdown → Section chunks → Stored as text files
    """

    def __init__(self):
        self._converter = None

    def _load(self):
        if self._converter is None:
            from docling.document_converter import DocumentConverter

            self._converter = DocumentConverter()
            logger.info("Docling document converter initialized.")

    def parse_pdf(self, pdf_path: str | Path) -> ParsedPaper:
        """Parse a single PDF into structured sections.

        Args:
            pdf_path: Path to the PDF file.

        Returns:
            ParsedPaper with section-level chunks ready for the Prospector.
        """
        self._load()
        pdf_path = Path(pdf_path)
        paper_id = pdf_path.stem  # e.g., "2401.00001"

        logger.info(f"Parsing PDF: {pdf_path}")
        result = self._converter.convert(str(pdf_path))
        markdown = result.document.export_to_markdown()

        # Extract metadata
        title = self._extract_title(markdown)
        authors = self._extract_authors(markdown)

        # Split into sections
        sections = self._split_sections(markdown, paper_id)

        # Store section files
        self._store_sections(sections, paper_id)

        logger.info(f"Parsed {pdf_path.name}: {len(sections)} sections, ~{sum(s.token_estimate for s in sections)} tokens")

        return ParsedPaper(
            paper_id=paper_id,
            title=title,
            authors=authors,
            sections=sections,
            full_markdown=markdown,
        )

    def parse_directory(self, pdf_dir: str | Path | None = None) -> list[ParsedPaper]:
        """Parse all PDFs in a directory."""
        if pdf_dir is None:
            pdf_dir = get_paths()["papers_dir"]
        pdf_dir = Path(pdf_dir)

        papers = []
        for pdf_path in sorted(pdf_dir.glob("*.pdf")):
            try:
                papers.append(self.parse_pdf(pdf_path))
            except Exception as e:
                logger.error(f"Failed to parse {pdf_path.name}: {e}")

        return papers

    def _split_sections(self, markdown: str, paper_id: str) -> list[ParsedSection]:
        """Split markdown into sections by headers."""
        # Split on ## or # headers
        parts = re.split(r"\n(#{1,3}\s+.+)\n", markdown)

        sections = []
        current_title = "Abstract"
        current_text = ""
        idx = 0

        for part in parts:
            if re.match(r"^#{1,3}\s+", part.strip()):
                # Save previous section
                if current_text.strip():
                    sections.append(self._make_section(paper_id, current_title, idx, current_text))
                    idx += 1
                current_title = re.sub(r"^#{1,3}\s+", "", part.strip())
                current_text = ""
            else:
                current_text += part

        # Don't forget the last section
        if current_text.strip():
            sections.append(self._make_section(paper_id, current_title, idx, current_text))

        # Filter out references section
        sections = [s for s in sections if not self._is_references(s.section_title)]

        return sections

    def _make_section(self, paper_id: str, title: str, idx: int, text: str) -> ParsedSection:
        cleaned = text.strip()
        return ParsedSection(
            paper_id=paper_id,
            section_title=title,
            section_index=idx,
            text=cleaned,
            token_estimate=len(cleaned) // 4,
        )

    def _store_sections(self, sections: list[ParsedSection], paper_id: str):
        """Write section files to disk for reproducibility."""
        papers_dir = Path(get_paths()["papers_dir"])
        section_dir = papers_dir / f"{paper_id}_sections"
        section_dir.mkdir(parents=True, exist_ok=True)

        for sec in sections:
            filename = f"{sec.section_index:02d}_{self._slugify(sec.section_title)}.md"
            (section_dir / filename).write_text(
                f"# {sec.section_title}\n\n{sec.text}",
                encoding="utf-8",
            )

    @staticmethod
    def _extract_title(markdown: str) -> str:
        match = re.search(r"^#\s+(.+)$", markdown, re.MULTILINE)
        return match.group(1).strip() if match else "Unknown Title"

    @staticmethod
    def _extract_authors(markdown: str) -> list[str]:
        # Simple heuristic: first non-empty line after title that looks like names
        lines = markdown.split("\n")
        for i, line in enumerate(lines):
            if line.startswith("# "):
                # Check next few non-empty lines
                for j in range(i + 1, min(i + 5, len(lines))):
                    if lines[j].strip() and not lines[j].startswith("#"):
                        # Likely authors if it has commas or "and"
                        if "," in lines[j] or " and " in lines[j]:
                            return [a.strip() for a in re.split(r",| and ", lines[j]) if a.strip()]
        return []

    @staticmethod
    def _is_references(title: str) -> bool:
        return bool(re.match(r"(?i)^(references|bibliography|works cited)", title.strip()))

    @staticmethod
    def _slugify(text: str) -> str:
        return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:50]
