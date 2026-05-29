"""Obligation-Extraction agent — "pull the shalls" (Part 3, agent 3).

The highest-value reasoning step. Runs at temperature 0, emits JSON validated
against a Pydantic schema with repair-retry (Part 11.2), and every obligation
carries an anchor_quote the citation verifier (Part 11.3) checks against the
pinned source before it is trusted. The LLM extracts; code decides (Part 11.1).

This is a focused first cut of the Phase 2 agent — enough to prove the live loop
(extract -> verify) end to end on real legal text.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from regradar.agents.state import (
    Article,
    Citation,
    Language,
    ModalForce,
    Obligation,
    ObligationType,
)
from regradar.models.router import LLMResult, Router, SchemaRepairFailed, router as default_router

_PROMPT = """You are a regulatory obligation extractor for EU financial regulation.
From the article text below, extract every DISCRETE obligation — each "the entity shall/must..."
unit of required action. Do not invent obligations and do not merge separate ones.

For each obligation return:
- actor: who must act (e.g. "Financial entities", "The management body")
- modal_force: one of shall | must | should | may
- action: the required action, concise
- conditions: any conditions/scope (or "")
- obligation_type: one of reporting | governance | ict-control | disclosure | capital | conduct | record-keeping
- paragraph_ref: the paragraph number this obligation comes from (e.g. "1", "2"), or "" if unclear
- anchor_quote: a VERBATIM span copied EXACTLY from the paragraph text that grounds this obligation
  (copy the characters precisely, and DO NOT include the "Paragraph N." label —
   this is checked programmatically against the source)

Return ONLY JSON of the form: {{"obligations": [ {{...}}, ... ]}}

CELEX: {celex}
{article_label}{article_title}
ARTICLE TEXT (paragraphs are numbered for reference only):
\"\"\"
{article_text}
\"\"\"
"""


def _numbered_text(article) -> str:
    """Render the article with paragraph labels so the model can cite a paragraph,
    while anchor quotes remain verbatim against the unlabelled paragraph text."""
    lines: list[str] = []
    if article.title:
        lines.append(article.title)
    for p in article.paragraphs:
        lines.append(f"Paragraph {p.ref}. {p.text}")
        lines.extend(p.points)
    return "\n".join(lines)


class _RawObligation(BaseModel):
    actor: str
    modal_force: ModalForce
    action: str
    conditions: str = ""
    obligation_type: ObligationType
    paragraph_ref: str = ""
    anchor_quote: str


class _ExtractionResult(BaseModel):
    obligations: list[_RawObligation] = Field(default_factory=list)


def extract_obligations(
    article: Article,
    *,
    celex: str,
    language: Language,
    router: Router | None = None,
) -> tuple[list[Obligation], LLMResult | None]:
    """Extract typed, citation-bearing obligations from one article.

    Raises nothing on LLM failure: a SchemaRepairFailed bubbles up to the caller,
    which flags it and routes to a human gate (never silently passes garbage)."""
    router = router or default_router
    prompt = _PROMPT.format(
        celex=celex,
        article_label=article.label,
        article_title=f" — {article.title}" if article.title else "",
        article_text=_numbered_text(article),
    )
    result, llm = router.call_structured(prompt, _ExtractionResult, temperature=0.0)

    obligations: list[Obligation] = []
    for i, raw in enumerate(result.obligations, start=1):
        obligations.append(
            Obligation(
                id=f"{celex}-{article.number}-{i}",
                actor=raw.actor,
                modal_force=raw.modal_force,
                action=raw.action,
                conditions=raw.conditions,
                obligation_type=raw.obligation_type,
                language=language,
                confidence=1.0,
                citation=Citation(
                    celex=celex,
                    article_ref=article.label,
                    paragraph_ref=raw.paragraph_ref or None,
                    language=language,
                    anchor_quote=raw.anchor_quote,
                ),
            )
        )
    return obligations, llm
