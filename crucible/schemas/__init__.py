"""Pydantic schemas for all CRUCIBLE data structures.

Deterministic IDs via SHA-256 hashing. Every node in the knowledge graph
has a content-addressable identity — same content always produces the same ID.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, computed_field


# ── Enums ──────────────────────────────────────────────────────────────────

class EvidenceType(str, Enum):
    EMPIRICAL = "empirical"
    THEORETICAL = "theoretical"
    SPECULATIVE = "speculative"


class Specificity(str, Enum):
    QUANTITATIVE = "quantitative"
    DIRECTIONAL = "directional"
    QUALITATIVE = "qualitative"


class ContradictionVerdict(str, Enum):
    GENUINE = "genuine"
    SUPERFICIAL = "superficial"
    UNRESOLVED = "unresolved"


class AttackVerdict(str, Enum):
    SURVIVED = "survived"
    WOUNDED = "wounded"
    KILLED = "killed"


class TerritoryType(str, Enum):
    SETTLED = "settled"
    CONTESTED = "contested"
    TERRA_INCOGNITA = "terra_incognita"


class ReviewRating(str, Enum):
    STRONG = "strong"
    INTERESTING = "interesting"
    WEAK = "weak"
    WRONG = "wrong"


# ── Helpers ────────────────────────────────────────────────────────────────

def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


# ── Core Schemas ───────────────────────────────────────────────────────────

class Claim(BaseModel):
    """A specific, attributed scientific assertion."""

    claim_text: str
    evidence_type: EvidenceType
    specificity: Specificity
    falsifiable: bool
    source_section: str
    key_numbers: Optional[list[float]] = None
    paper_id: str
    is_authors_own: bool = True

    @computed_field
    @property
    def claim_id(self) -> str:
        return _sha256(f"{self.paper_id}:{_normalize(self.claim_text)}")


class Evidence(BaseModel):
    """Empirical backing for a claim."""

    claim_id: str
    description: str
    data_points: Optional[list[str]] = None
    figures: Optional[list[str]] = None
    paper_id: str

    @computed_field
    @property
    def evidence_id(self) -> str:
        return _sha256(f"{self.claim_id}:{_normalize(self.description)}")


class Contradiction(BaseModel):
    """First-class node linking two mutually exclusive claims."""

    claim_a_id: str
    claim_b_id: str
    nature: str  # Description of the disagreement
    verdict: Optional[ContradictionVerdict] = None
    rationale: Optional[str] = None

    @computed_field
    @property
    def contradiction_id(self) -> str:
        pair = sorted([self.claim_a_id, self.claim_b_id])
        return _sha256(f"contra:{pair[0]}:{pair[1]}")


class Gap(BaseModel):
    """A question the knowledge graph cannot yet answer."""

    question: str
    related_claim_ids: list[str] = Field(default_factory=list)
    territory: TerritoryType = TerritoryType.TERRA_INCOGNITA

    @computed_field
    @property
    def gap_id(self) -> str:
        return _sha256(f"gap:{_normalize(self.question)}")


# ── Phase Output Schemas ──────────────────────────────────────────────────

class ClaimsRegistry(BaseModel):
    """Output of Phase 1 (Prospector)."""

    paper_id: str
    claims: list[Claim]
    extraction_timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Theme(BaseModel):
    name: str
    claim_ids: list[str]
    description: str


class Convergence(BaseModel):
    claim_ids: list[str]
    description: str


class MapUpdate(BaseModel):
    """Output of Phase 2 (Cartographer)."""

    cycle_id: str
    themes: list[Theme] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
    gaps: list[Gap] = Field(default_factory=list)
    convergences: list[Convergence] = Field(default_factory=list)


class ContradictionDossier(BaseModel):
    """Input package for Phase 3 (Demolisher)."""

    contradiction_id: str
    claim_a: Claim
    claim_b: Claim
    evidence_a: Optional[str] = None
    evidence_b: Optional[str] = None
    citation_context: Optional[str] = None


class AttackResult(BaseModel):
    """Single attack verdict from Phase 3."""

    contradiction_id: str
    verdict: AttackVerdict
    rationale: str
    surviving_claim_id: Optional[str] = None


class AttackReport(BaseModel):
    """Output of Phase 3 (Demolisher)."""

    cycle_id: str
    results: list[AttackResult]


class ResearchBrief(BaseModel):
    """Output of Phase 4 (Integrator)."""

    brief_id: str
    hypothesis: str
    exploited_gap_or_contradiction: str
    minimum_viable_experiment: str
    key_citations: list[str]
    assumptions: list[str]
    falsification_criteria: list[str]
    cycle_id: str

    @computed_field
    @property
    def computed_brief_id(self) -> str:
        return _sha256(f"brief:{self.cycle_id}:{_normalize(self.hypothesis)}")


class SynthesisReport(BaseModel):
    """Output of Phase 4 (Integrator)."""

    cycle_id: str
    briefs: list[ResearchBrief]


class MetaReview(BaseModel):
    """Output of Phase 5 (Auditor)."""

    cycle_id: str
    shared_assumptions: list[str]
    logical_leaps: list[str]
    disciplinary_blind_spots: list[str]
    recommendations: list[str]


class AnomalyDigest(BaseModel):
    """Statistical anomalies computed without LLM."""

    cycle_id: str
    extraction_variance: dict[str, int] = Field(default_factory=dict)  # paper_id → claim_count
    merge_confidence_flags: list[str] = Field(default_factory=list)
    attack_survival_rate: Optional[float] = None
    outliers: list[str] = Field(default_factory=list)


# ── Journal Entry ─────────────────────────────────────────────────────────

class JournalEntry(BaseModel):
    """A single entry in the Research Journal."""

    cycle_id: str
    date: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    briefs: list[ResearchBrief] = Field(default_factory=list)
    meta_review: Optional[MetaReview] = None
    frontier_delta: Optional[dict] = None
    provenance: dict[str, str] = Field(default_factory=dict)  # phase → model_name
    annotations: Optional[str] = None
    ratings: dict[str, ReviewRating] = Field(default_factory=dict)  # brief_id → rating


# ── Entity Resolution ─────────────────────────────────────────────────────

class EntityResolutionAction(BaseModel):
    action: str  # "MERGE" or "CREATE_NEW"
    target_id: Optional[str] = None
