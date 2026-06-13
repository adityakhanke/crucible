"""Research Journal — persistent, append-only record of all DIALECTIC cycles.

Each entry contains research briefs, meta-review, provenance (which model
did what), frontier map deltas, and human annotations.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from crucible.config import get_paths

logger = logging.getLogger(__name__)


class JournalWriter:
    """Manages the append-only Research Journal."""

    def __init__(self, journal_dir: str = None):
        self._dir = Path(journal_dir or get_paths()["journal_dir"])
        self._dir.mkdir(parents=True, exist_ok=True)

    def write_entry(self, entry: dict):
        """Append a new journal entry.

        Args:
            entry: JournalEntry.model_dump() dict.
        """
        cycle_id = entry.get("cycle_id", "unknown")
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"{date_str}_{cycle_id}.json"
        filepath = self._dir / filename

        with open(filepath, "w") as f:
            json.dump(entry, f, indent=2, default=str)

        logger.info(f"Journal entry written: {filepath}")

        # Also write a human-readable markdown summary
        self._write_markdown(entry, filepath.with_suffix(".md"))

    def _write_markdown(self, entry: dict, path: Path):
        """Write a human-readable markdown version of the journal entry."""
        lines = []
        cycle_id = entry.get("cycle_id", "unknown")
        date = entry.get("date", datetime.now(timezone.utc).isoformat())

        lines.append(f"# Research Journal — {cycle_id}")
        lines.append(f"**Date:** {date}")
        lines.append("")

        # Provenance
        prov = entry.get("provenance", {})
        if prov:
            lines.append("## Model Provenance")
            for phase, model in prov.items():
                lines.append(f"- **{phase}:** {model}")
            lines.append("")

        # Research Briefs
        briefs = entry.get("briefs", [])
        if briefs:
            lines.append(f"## Research Briefs ({len(briefs)})")
            lines.append("")
            for i, brief in enumerate(briefs, 1):
                lines.append(f"### Brief {i}")
                lines.append(f"**Hypothesis:** {brief.get('hypothesis', 'N/A')}")
                lines.append(f"**Exploits:** {brief.get('exploited_gap_or_contradiction', 'N/A')}")
                lines.append(f"**Minimum Viable Experiment:** {brief.get('minimum_viable_experiment', 'N/A')}")

                assumptions = brief.get("assumptions", [])
                if assumptions:
                    lines.append("**Assumptions:**")
                    for a in assumptions:
                        lines.append(f"  - {a}")

                falsification = brief.get("falsification_criteria", [])
                if falsification:
                    lines.append("**Falsification Criteria:**")
                    for f_item in falsification:
                        lines.append(f"  - {f_item}")

                citations = brief.get("key_citations", [])
                if citations:
                    lines.append(f"**Key Citations:** {', '.join(citations)}")
                lines.append("")

        # Meta-Review
        meta = entry.get("meta_review")
        if meta:
            lines.append("## Meta-Review (Auditor)")
            lines.append("")

            for section, key in [
                ("Shared Assumptions", "shared_assumptions"),
                ("Logical Leaps", "logical_leaps"),
                ("Disciplinary Blind Spots", "disciplinary_blind_spots"),
                ("Recommendations", "recommendations"),
            ]:
                items = meta.get(key, [])
                if items:
                    lines.append(f"### {section}")
                    for item in items:
                        lines.append(f"- {item}")
                    lines.append("")

        # Annotations placeholder
        lines.append("## Your Annotations")
        lines.append("*(Add your notes here during REVIEW mode)*")
        lines.append("")

        path.write_text("\n".join(lines), encoding="utf-8")

    def list_entries(self) -> list[Path]:
        """List all journal entry JSON files, sorted by date."""
        return sorted(self._dir.glob("*.json"))

    def load_entry(self, path: Path) -> dict:
        """Load a single journal entry."""
        with open(path) as f:
            return json.load(f)

    def get_latest(self) -> Optional[dict]:
        """Get the most recent journal entry."""
        entries = self.list_entries()
        if not entries:
            return None
        return self.load_entry(entries[-1])

    def get_confidence_trajectory(self, hypothesis_substring: str) -> list[dict]:
        """Track how a hypothesis was assessed across cycles.

        Searches all entries for briefs matching the substring and
        returns the trajectory of ratings and survival.
        """
        trajectory = []
        for entry_path in self.list_entries():
            entry = self.load_entry(entry_path)
            for brief in entry.get("briefs", []):
                hyp = brief.get("hypothesis", "")
                if hypothesis_substring.lower() in hyp.lower():
                    trajectory.append({
                        "cycle_id": entry.get("cycle_id"),
                        "date": entry.get("date"),
                        "hypothesis": hyp,
                        "rating": entry.get("ratings", {}).get(brief.get("brief_id")),
                    })
        return trajectory
