"""Memo-Drafting agent (Part 3, agent 7) — "write the deliverable".

Assembles the gap-assessment / regulatory-impact memo from the pipeline state:
executive summary, the obligations, mapped impacts and gaps, the prioritized
actions with owners and deadlines, and a full citation appendix. Then it STOPS at
a human approval gate — nothing is "issued" without sign-off (Part 3.3).

Assembly is deterministic (a template over verified state); the LLM only writes
the prose executive summary, and only if asked. Every cited line in the appendix
has already passed the programmatic verifier, so the memo is audit-grade by
construction (Part 10).
"""
from __future__ import annotations

from datetime import date

from regradar.agents.state import (
    GapMemo,
    ImpactLink,
    Language,
    Obligation,
    PrioritizedItem,
)
from regradar.models.router import Router, SchemaRepairFailed

# Localized section labels (Part 8 — German is the market differentiator).
LABELS: dict[str, dict[str, str]] = {
    "en": {
        "title": "Gap-Assessment Memo", "drafted": "drafted", "status_draft": "DRAFT (pending approval)",
        "s1": "1. Executive summary", "s2": "2. Obligations & impact", "s3": "3. Prioritized actions",
        "s4": "4. Citation appendix", "appendix_note": "Every claim is pinned to the source article and was programmatically verified.",
        "col_type": "Type", "col_article": "Article", "col_maps": "Maps to", "col_function": "Function",
        "col_priority": "Priority", "col_deadline": "Deadline", "col_owner": "Owner", "col_note": "Note",
        "gap": "**GAP — build control**", "overdue": "OVERDUE", "verified": "verified",
    },
    "de": {
        "title": "Gap-Analyse-Memo", "drafted": "erstellt", "status_draft": "ENTWURF (Freigabe ausstehend)",
        "s1": "1. Zusammenfassung", "s2": "2. Pflichten & Auswirkung", "s3": "3. Priorisierte Maßnahmen",
        "s4": "4. Zitat-Anhang", "appendix_note": "Jede Aussage ist an den Quellartikel gebunden und wurde programmatisch verifiziert. Die Zitate bleiben in der Originalsprache (maßgeblich).",
        "col_type": "Typ", "col_article": "Artikel", "col_maps": "Zuordnung", "col_function": "Funktion",
        "col_priority": "Priorität", "col_deadline": "Frist", "col_owner": "Verantwortlich", "col_note": "Hinweis",
        "gap": "**LÜCKE — Kontrolle aufbauen**", "overdue": "ÜBERFÄLLIG", "verified": "verifiziert",
    },
}


def _exec_summary_deterministic(
    title: str, obligations: list[Obligation], gaps: list[ImpactLink],
    prioritized: list[PrioritizedItem],
) -> str:
    n = len(obligations)
    g = len(gaps)
    overdue = sum(1 for p in prioritized if p.deadline_days is not None and p.deadline_days <= 0)
    top = prioritized[0] if prioritized else None
    lead = (
        f"This assessment covers {n} obligation(s) extracted from {title}. "
        f"{g} obligation(s) have no covering control and represent gaps requiring action. "
    )
    if overdue:
        lead += f"{overdue} obligation(s) are past their application date and are overdue. "
    if top and top.obligation_id:
        lead += (
            f"The highest-priority item is {top.obligation_id} "
            f"({'OVERDUE' if (top.deadline_days or 0) <= 0 else f'{top.deadline_days}d to deadline'}). "
        )
    lead += "Every obligation below is pinned to a verified citation in the source text."
    return lead


def draft_memo(
    state: dict,
    *,
    language: Language = "en",
    router: Router | None = None,
    llm_summary: bool = False,
) -> GapMemo:
    obligations: list[Obligation] = state.get("obligations", [])
    links: list[ImpactLink] = state.get("impact_links", [])
    prioritized: list[PrioritizedItem] = state.get("prioritized", [])
    parsed = state.get("parsed_doc")
    doc_title = (parsed.title if parsed else "") or state.get("raw_doc").celex  # type: ignore
    celex = parsed.celex if parsed else ""
    corpus_version = state.get("corpus_version", "")

    link_by_id = {l.obligation_id: l for l in links}
    prio_by_id = {p.obligation_id: p for p in prioritized}
    gaps = [l for l in links if l.is_gap]

    L = LABELS.get(language, LABELS["en"])

    exec_summary = _exec_summary_deterministic(doc_title, obligations, gaps, prioritized)
    if llm_summary and router is not None:
        try:
            exec_summary = _llm_exec_summary(doc_title, obligations, gaps, prioritized, router) or exec_summary
        except SchemaRepairFailed:
            pass  # keep deterministic summary
    # German prose, original-language citation anchors (Part 8).
    if language == "de" and router is not None:
        try:
            exec_summary = _translate(exec_summary, router) or exec_summary
        except SchemaRepairFailed:
            pass

    md: list[str] = []
    md.append(f"# {L['title']} — {doc_title}")
    md.append(f"_CELEX {celex} · corpus {corpus_version} · {L['drafted']} {date.today().isoformat()} · {L['status_draft']}_\n")

    md.append(f"## {L['s1']}\n")
    md.append(exec_summary + "\n")

    md.append(f"## {L['s2']}\n")
    md.append(f"| ID | {L['col_type']} | {L['col_article']} | {L['col_maps']} | {L['col_function']} |")
    md.append("|---|---|---|---|---|")
    for o in obligations:
        l = link_by_id.get(o.id)
        maps = L["gap"] if (l and l.is_gap) else (l.control_id if l else "—")
        fn = l.function if l else ""
        md.append(f"| {o.id} | {o.obligation_type.value} | {o.citation.article_ref} | {maps} | {fn} |")
    md.append("")

    md.append(f"## {L['s3']}\n")
    md.append(f"| # | ID | {L['col_priority']} | {L['col_deadline']} | {L['col_owner']} | {L['col_note']} |")
    md.append("|---|---|---|---|---|---|")
    for i, p in enumerate(prioritized, 1):
        l = link_by_id.get(p.obligation_id)
        owner = l.function if l else ""
        dl = L["overdue"] if (p.deadline_days is not None and p.deadline_days <= 0) else (
            p.deadline.isoformat() if p.deadline else "—")
        md.append(f"| {i} | {p.obligation_id} | {p.priority_score:.3f} | {dl} | {owner} | {p.rationale} |")
    md.append("")

    md.append(f"## {L['s4']}\n")
    md.append(f"_{L['appendix_note']}_\n")
    appendix: list = []
    for o in obligations:
        appendix.append(o.citation)
        md.append(f"- **{o.id}** — {o.citation.article_ref}"
                  + (f"({o.citation.paragraph_ref})" if o.citation.paragraph_ref else "")
                  + f" [{o.citation.language}] ✓ {L['verified']}\n"
                  + f"  > “{o.citation.anchor_quote}”")
    md.append("")

    return GapMemo(
        title=f"Gap-Assessment Memo — {doc_title}",
        language=language,
        exec_summary=exec_summary,
        body_markdown="\n".join(md),
        citation_appendix=appendix,
        status="draft",
    )


_SUMMARY_PROMPT = """Write a concise (4-6 sentence) executive summary for a bank
compliance gap-assessment memo. Be factual, no hype. JSON: {{"summary": "..."}}.

Regulation: {title}
Obligations: {n}  | Gaps (no covering control): {g}  | Overdue: {overdue}
Top gaps: {gap_list}
"""


def _llm_exec_summary(title, obligations, gaps, prioritized, router: Router) -> str:
    from pydantic import BaseModel

    class _S(BaseModel):
        summary: str

    overdue = sum(1 for p in prioritized if p.deadline_days is not None and p.deadline_days <= 0)
    gap_list = ", ".join(g.obligation_id for g in gaps[:5]) or "none"
    prompt = _SUMMARY_PROMPT.format(
        title=title, n=len(obligations), g=len(gaps), overdue=overdue, gap_list=gap_list
    )
    s, _ = router.call_structured(prompt, _S, temperature=0.0)
    return s.summary


def _translate(text: str, router: Router) -> str:
    """Translate prose to German. Used only for memo prose — never for citation
    anchors, which remain in the authoritative source language (Part 8)."""
    from pydantic import BaseModel

    class _T(BaseModel):
        german: str

    prompt = (
        "Translate this bank compliance text to formal German. "
        'Return JSON: {"german": "..."}.\n\n' + text
    )
    t, _ = router.call_structured(prompt, _T, temperature=0.0)
    return t.german
