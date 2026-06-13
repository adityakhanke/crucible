"""Frontier Map — persistent JSON-LD research state.

Encodes what is known (settled), what is contested, and what is unknown
(terra incognita) in the research domain. Updated after every DIALECTIC cycle.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from crucible.config import get_paths
from crucible.schemas import TerritoryType

logger = logging.getLogger(__name__)


class FrontierMap:
    """Manages the persistent Frontier Map.

    The map is a JSON-LD document backed by the Neo4j graph:
    - Settled Territory: strong evidence, no contradictions → de-prioritized
    - Contested Territory: active contradictions → high priority
    - Terra Incognita: identified gaps → highest priority
    """

    def __init__(self, path: str = None):
        self._path = Path(path or get_paths()["frontier_map"])
        self._state = self._load()

    def _load(self) -> dict:
        if self._path.exists():
            with open(self._path) as f:
                return json.load(f)
        return self._empty_map()

    def _empty_map(self) -> dict:
        return {
            "@context": "https://schema.org/",
            "@type": "FrontierMap",
            "version": "1.0",
            "last_updated": None,
            "settled": [],
            "contested": [],
            "terra_incognita": [],
            "themes": [],
            "cycle_history": [],
        }

    def save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w") as f:
            json.dump(self._state, f, indent=2, default=str)
        logger.info(f"Frontier Map saved: {self._path}")

    @property
    def state(self) -> dict:
        return self._state

    def update_from_cycle(
        self,
        cycle_id: str,
        themes: list[dict] = None,
        contradictions: list[dict] = None,
        gaps: list[dict] = None,
        convergences: list[dict] = None,
        attack_results: list[dict] = None,
    ):
        """Apply a DIALECTIC cycle's results to the Frontier Map.

        Logic:
        - Contradictions with SURVIVED verdict → contested territory
        - Contradictions with KILLED verdict → winner goes to settled
        - Gaps → terra incognita
        - Convergences from independent lines → settled territory
        """
        now = datetime.now(timezone.utc).isoformat()
        self._state["last_updated"] = now

        # Build attack verdict lookup
        verdicts = {}
        for ar in (attack_results or []):
            verdicts[ar.get("contradiction_id")] = ar

        # Process contradictions
        for c in (contradictions or []):
            cid = c.get("contradiction_id", "")
            entry = {
                "contradiction_id": cid,
                "claim_a_id": c.get("claim_a_id"),
                "claim_b_id": c.get("claim_b_id"),
                "nature": c.get("nature", ""),
                "added_cycle": cycle_id,
            }

            verdict_data = verdicts.get(cid, {})
            verdict = verdict_data.get("verdict", "unresolved")

            if verdict == "survived":
                entry["status"] = "active"
                self._upsert_territory("contested", entry, key="contradiction_id")
            elif verdict == "killed":
                entry["status"] = "resolved"
                winner_id = verdict_data.get("surviving_claim_id")
                if winner_id:
                    self._upsert_territory("settled", {
                        "claim_id": winner_id,
                        "settled_by": "attack",
                        "cycle": cycle_id,
                    }, key="claim_id")
            elif verdict == "wounded":
                entry["status"] = "weakened"
                self._upsert_territory("contested", entry, key="contradiction_id")

        # Process gaps
        for g in (gaps or []):
            self._upsert_territory("terra_incognita", {
                "gap_id": g.get("gap_id"),
                "question": g.get("question"),
                "related_claim_ids": g.get("related_claim_ids", []),
                "added_cycle": cycle_id,
            }, key="gap_id")

        # Process themes
        if themes:
            self._state["themes"] = themes

        # Record cycle
        self._state["cycle_history"].append({
            "cycle_id": cycle_id,
            "timestamp": now,
            "new_contradictions": len(contradictions or []),
            "new_gaps": len(gaps or []),
            "convergences": len(convergences or []),
        })

        self.save()
        logger.info(
            f"Frontier Map updated: {len(self._state['settled'])} settled, "
            f"{len(self._state['contested'])} contested, "
            f"{len(self._state['terra_incognita'])} unknown"
        )

    def _upsert_territory(self, territory: str, entry: dict, key: str):
        """Insert or update an entry in a territory list."""
        items = self._state[territory]
        for i, existing in enumerate(items):
            if existing.get(key) == entry.get(key):
                items[i] = {**existing, **entry}
                return
        items.append(entry)

    def get_summary(self) -> dict:
        return {
            "settled_count": len(self._state["settled"]),
            "contested_count": len(self._state["contested"]),
            "terra_incognita_count": len(self._state["terra_incognita"]),
            "theme_count": len(self._state["themes"]),
            "total_cycles": len(self._state["cycle_history"]),
            "last_updated": self._state.get("last_updated"),
        }

    def get_high_priority_targets(self) -> list[dict]:
        """Get contested + terra incognita items, sorted by priority."""
        targets = []
        for item in self._state["terra_incognita"]:
            targets.append({**item, "priority": "highest", "type": "gap"})
        for item in self._state["contested"]:
            if item.get("status") == "active":
                targets.append({**item, "priority": "high", "type": "contradiction"})
        return targets
