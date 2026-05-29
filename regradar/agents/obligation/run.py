"""Obligation extraction + guardrail orchestration (Part 3, agents 3 + guardrail).

For each article: extract obligations -> programmatically verify each citation ->
route. The guardrail layer is what makes this trustworthy:

  * verifier PASS + confidence >= gate  -> accepted
  * verifier FAIL                       -> rejected (dropped), flagged, human gate
  * confidence < gate                   -> kept but flagged, human gate
  * schema repair exhausted             -> flagged, human gate (no garbage downstream)

No unverified legal claim is ever accepted. Every step writes an append-only audit
entry. This function is graph-node-shaped (takes inputs, returns an outcome) so it
drops straight into a LangGraph node later.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from regradar import config
from regradar.agents.guardrails.audit import audit, corpus_version_for, flag
from regradar.agents.guardrails.verifier import verify_citation
from regradar.agents.obligation.extract import extract_obligations
from regradar.agents.state import (
    AuditEntry,
    Flag,
    FlagKind,
    HumanApproval,
    Obligation,
    ParsedRegDoc,
)
from regradar.models.router import Router, SchemaRepairFailed, router as default_router


@dataclass
class ExtractionOutcome:
    obligations: list[Obligation] = field(default_factory=list)  # accepted only
    rejected: list[Obligation] = field(default_factory=list)
    flags: list[Flag] = field(default_factory=list)
    audit_trail: list[AuditEntry] = field(default_factory=list)
    corpus_version: str = ""

    @property
    def needs_human_gate(self) -> bool:
        return any(f.severity in ("warning", "error") for f in self.flags)

    @property
    def citation_integrity(self) -> float:
        total = len(self.obligations) + len(self.rejected)
        return 1.0 if not total else len(self.obligations) / total


def _dedup_key(o: Obligation) -> tuple[str, str]:
    art = re.search(r"\d+[a-z]?", o.citation.article_ref.lower())
    anchor = " ".join(o.citation.anchor_quote.lower().split())
    return (art.group(0) if art else o.citation.article_ref, anchor)


def extract_document(
    parsed: ParsedRegDoc,
    *,
    router: Router | None = None,
    confidence_gate: float | None = None,
    max_articles: int | None = None,
) -> ExtractionOutcome:
    router = router or default_router
    gate = config.CONFIDENCE_HUMAN_GATE if confidence_gate is None else confidence_gate
    cv = corpus_version_for(parsed.content_hash)
    out = ExtractionOutcome(corpus_version=cv)
    seen: set[tuple[str, str]] = set()

    articles = parsed.articles if max_articles is None else parsed.articles[:max_articles]
    for article in articles:
        try:
            obls, llm = extract_obligations(
                article, celex=parsed.celex, language=parsed.language, router=router
            )
        except SchemaRepairFailed as e:
            out.flags.append(
                flag(FlagKind.SCHEMA_REPAIR_FAILED,
                     f"{article.label}: structured output failed after retries: {e}",
                     severity="error")
            )
            out.audit_trail.append(
                audit("obligation_extraction", corpus_version=cv,
                      evidence_refs=[article.label])
            )
            continue

        out.audit_trail.append(
            audit(
                "obligation_extraction",
                model=llm.model if llm else None,
                provider=llm.provider if llm else None,
                evidence_refs=[f"{parsed.celex}:{article.label}"],
                corpus_version=cv,
                tokens=llm.tokens if llm else None,
                latency_ms=llm.latency_ms if llm else None,
            )
        )

        for o in obls:
            verdict = verify_citation(o.citation, parsed)
            out.audit_trail.append(
                audit("citation_verifier", evidence_refs=[o.id],
                      confidence=o.confidence, verdict=verdict, corpus_version=cv)
            )

            if not verdict.ok:
                out.rejected.append(o)
                out.flags.append(
                    flag(FlagKind.VERIFIER_REJECTED,
                         f"{o.id}: {verdict.reason}", obligation_id=o.id, severity="error")
                )
                continue  # rejected claims never advance

            key = _dedup_key(o)
            if key in seen:
                continue
            seen.add(key)

            if o.confidence < gate:
                out.flags.append(
                    flag(FlagKind.LOW_CONFIDENCE,
                         f"{o.id}: confidence {o.confidence:.2f} < gate {gate:.2f}",
                         obligation_id=o.id, severity="warning")
                )
            out.obligations.append(o)

    return out


def fold_into_state(state: dict, out: ExtractionOutcome) -> dict:
    """Merge an ExtractionOutcome into a RegRadarState dict (append-only trails)."""
    state["obligations"] = out.obligations
    state["audit_trail"] = state.get("audit_trail", []) + out.audit_trail
    state["flags"] = state.get("flags", []) + out.flags
    state["corpus_version"] = out.corpus_version
    if out.needs_human_gate:
        state["human_gate"] = HumanApproval(status="pending")
        state["status"] = "awaiting_human"
    else:
        state["status"] = "mapping"
    return state
