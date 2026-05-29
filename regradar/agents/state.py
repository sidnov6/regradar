"""RegRadarState + the Pydantic schemas every agent reads and writes (Part 3.1).

Design rule (Part 11.1, the determinism boundary): these models are the contract.
LLM agents emit JSON validated against them; deterministic code (parser, verifier,
prioritizer) constructs them directly. Anything that "leaves the building"
(an Obligation, a memo line) carries a Citation the Guardrail layer must verify
against the pinned source before the state advances.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from typing import Literal, Optional, TypedDict

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Enums / controlled vocabularies
# ---------------------------------------------------------------------------
Language = Literal["en", "de"]


class SourceSystem(str, Enum):
    EUR_LEX = "EUR-LEX"
    EBA = "EBA"
    ESMA = "ESMA"
    BAFIN = "BaFin"
    ECB = "ECB"


class Manifestation(str, Enum):
    """Content format fetched from CELLAR, in order of parsing preference (Part 5)."""
    FORMEX = "formex"
    XHTML = "xhtml"
    PDF = "pdf"


class ModalForce(str, Enum):
    SHALL = "shall"
    MUST = "must"
    SHOULD = "should"
    MAY = "may"


class ObligationType(str, Enum):
    REPORTING = "reporting"
    GOVERNANCE = "governance"
    ICT_CONTROL = "ict-control"
    DISCLOSURE = "disclosure"
    CAPITAL = "capital"
    CONDUCT = "conduct"
    RECORD_KEEPING = "record-keeping"


class ChangeKind(str, Enum):
    ADDED = "added"
    MODIFIED = "modified"
    REMOVED = "removed"


class FlagKind(str, Enum):
    VERIFIER_REJECTED = "verifier_rejected"
    LOW_CONFIDENCE = "low_confidence"
    SCHEMA_REPAIR_FAILED = "schema_repair_failed"
    MISSING_DATA = "missing_data"
    DATA_QUALITY = "data_quality"
    STALE_SOURCE = "stale_source"


# ---------------------------------------------------------------------------
# Source / Bronze
# ---------------------------------------------------------------------------
class SourceEvent(BaseModel):
    """What the Source-Monitor caught off a feed (Part 3, agent 1)."""
    celex: Optional[str] = None
    eli: Optional[str] = None
    uri: str
    source: SourceSystem
    title: str = ""
    doc_type: str = ""  # regulation / directive / RTS / ITS / guideline / Q&A
    published: Optional[date] = None
    languages: list[Language] = Field(default_factory=list)
    in_scope: bool = True
    scope_reason: str = ""


class RawRegDoc(BaseModel):
    """A pinned Bronze record — immutable, addressed by (celex, manifestation, hash)."""
    celex: str
    manifestation: Manifestation
    language: Language
    source_uri: str
    content_hash: str  # sha256 of raw bytes — the version pin
    content_path: str  # path in the Bronze object store
    fetched_at: datetime = Field(default_factory=_now)
    version_label: Optional[str] = None  # CELLAR consolidation date, if known

    @property
    def bronze_key(self) -> str:
        return f"{self.celex}:{self.manifestation.value}:{self.language}:{self.content_hash[:12]}"


# ---------------------------------------------------------------------------
# Silver — parsed, article-segmented document
# ---------------------------------------------------------------------------
class Paragraph(BaseModel):
    ref: str          # e.g. "1", "2", "3a"
    text: str
    points: list[str] = Field(default_factory=list)  # (a), (b), ... sub-points


class Article(BaseModel):
    number: str       # e.g. "5" — bare article number
    label: str        # e.g. "Article 5"
    title: str = ""
    chapter: str = ""
    paragraphs: list[Paragraph] = Field(default_factory=list)

    @property
    def text(self) -> str:
        """Full flattened article text — what the verifier searches."""
        parts: list[str] = []
        if self.title:
            parts.append(self.title)
        for p in self.paragraphs:
            parts.append(p.text)
            parts.extend(p.points)
        return "\n".join(parts)


class ParsedRegDoc(BaseModel):
    """Article-segmented, language-tagged document in Silver (Part 3, agent 2)."""
    celex: str
    language: Language
    title: str = ""
    content_hash: str  # carried from the Bronze record it was parsed from
    articles: list[Article] = Field(default_factory=list)

    def get_article(self, article_ref: str) -> Optional[Article]:
        """Resolve a citation's article_ref to an Article. Accepts 'Article 5',
        'Art. 5', '5', or 'Article 5(2)' (paragraph is ignored at article level).
        Used by the citation verifier (Part 11.3)."""
        wanted = _normalize_article_number(article_ref)
        for art in self.articles:
            if _normalize_article_number(art.number) == wanted:
                return art
        return None

    def text_in(self, language: Language) -> str:
        """Full document text in a language. This doc is single-language; the
        parameter exists so callers can be language-explicit per Part 8."""
        return "\n\n".join(a.text for a in self.articles)


def _normalize_article_number(ref: str) -> str:
    """'Article 5(2)' / 'Art. 5' / 'Artikel 5' -> '5'. Tolerant, deterministic."""
    import re
    s = ref.lower()
    for token in ("article", "artikel", "art.", "art"):
        s = s.replace(token, " ")
    m = re.search(r"\d+[a-z]?", s)
    return m.group(0) if m else ref.strip()


# ---------------------------------------------------------------------------
# Citations + Obligations (Gold)
# ---------------------------------------------------------------------------
class Citation(BaseModel):
    """The provenance pin. Every claim that leaves the building carries one."""
    celex: str
    article_ref: str             # e.g. "Article 5"
    paragraph_ref: Optional[str] = None
    language: Language
    anchor_quote: str            # verbatim span the verifier must find in the article
    eli: Optional[str] = None


class Obligation(BaseModel):
    """A discrete 'the entity shall...' unit (Part 3, agent 3)."""
    id: str
    actor: str
    modal_force: ModalForce
    action: str
    conditions: str = ""
    obligation_type: ObligationType
    citation: Citation
    language: Language
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)


class ChangeSet(BaseModel):
    """Output of the Change-Diff agent on amendments (Part 3, agent 4)."""
    added: list[Obligation] = Field(default_factory=list)
    modified: list[Obligation] = Field(default_factory=list)
    removed: list[Obligation] = Field(default_factory=list)
    prior_version_hash: Optional[str] = None


# ---------------------------------------------------------------------------
# Impact + prioritization
# ---------------------------------------------------------------------------
class ImpactLink(BaseModel):
    """obligation -> function / system / process / control (Part 3, agent 5).

    status distinguishes a real gap (an ICT obligation with no covering control)
    from an unmapped obligation (no ICT control theme at all — typically a
    procedural/definitional provision to review, not a control to build)."""
    obligation_id: str
    function: str
    system: str
    process: str = ""
    control_id: Optional[str] = None
    is_gap: bool = False               # True only for status == "gap"
    status: Literal["covered", "gap", "unmapped"] = "covered"
    rationale: str = ""
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)


class PrioritizedItem(BaseModel):
    """Ranked action (Part 3, agent 6). Scores computed in Python; LLM only
    supplies qualitative inputs it can justify."""
    obligation_id: str
    deadline: Optional[date] = None
    deadline_days: Optional[int] = None
    effort_score: float = Field(ge=0.0, le=1.0)
    risk_score: float = Field(ge=0.0, le=1.0)
    priority_score: float
    rationale: str = ""


# ---------------------------------------------------------------------------
# Memo
# ---------------------------------------------------------------------------
class GapMemo(BaseModel):
    title: str
    language: Language
    exec_summary: str
    body_markdown: str
    citation_appendix: list[Citation] = Field(default_factory=list)
    status: Literal["draft", "approved", "rejected"] = "draft"


# ---------------------------------------------------------------------------
# Guardrail / audit / human-gate
# ---------------------------------------------------------------------------
class VerifierVerdict(BaseModel):
    ok: bool
    reason: str = ""

    @classmethod
    def pass_(cls) -> "VerifierVerdict":
        return cls(ok=True, reason="verified")

    @classmethod
    def fail(cls, reason: str) -> "VerifierVerdict":
        return cls(ok=False, reason=reason)


class Flag(BaseModel):
    kind: FlagKind
    message: str
    obligation_id: Optional[str] = None
    severity: Literal["info", "warning", "error"] = "warning"
    raised_at: datetime = Field(default_factory=_now)


class AuditEntry(BaseModel):
    """Append-only provenance record (Part 10). Same substrate as observability."""
    node: str
    model: Optional[str] = None
    provider: Optional[str] = None
    prompt_hash: Optional[str] = None
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: Optional[float] = None
    verifier_verdict: Optional[VerifierVerdict] = None
    corpus_version: Optional[str] = None
    tokens: Optional[int] = None
    latency_ms: Optional[float] = None
    timestamp: datetime = Field(default_factory=_now)


class HumanApproval(BaseModel):
    status: Literal["pending", "approved", "edited", "rejected"] = "pending"
    approver: Optional[str] = None
    decided_at: Optional[datetime] = None
    notes: str = ""


# ---------------------------------------------------------------------------
# The shared graph state (Part 3.1)
# ---------------------------------------------------------------------------
RunStatus = Literal[
    "monitoring", "parsing", "extracting", "diffing", "mapping",
    "prioritizing", "drafting", "awaiting_human", "done", "failed",
]


class RegRadarState(TypedDict, total=False):
    run_id: str
    source_event: SourceEvent
    raw_doc: Optional[RawRegDoc]
    parsed_doc: Optional[ParsedRegDoc]
    is_amendment: bool
    change_set: Optional[ChangeSet]
    obligations: list[Obligation]
    impact_links: list[ImpactLink]
    prioritized: list[PrioritizedItem]
    memo: Optional[GapMemo]
    corpus_version: str
    audit_trail: list[AuditEntry]
    flags: list[Flag]
    human_gate: Optional[HumanApproval]
    status: RunStatus
