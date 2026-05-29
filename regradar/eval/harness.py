"""Evaluation harness — graded, not vibes (Part 14).

Grades agent output against the hand-labeled ground-truth oracle. Designed to be
wired as a CI gate (Part 11.8): if extraction F1, citation integrity, or mapping
accuracy drops below threshold, the build fails.

These functions are pure and take predictions as arguments, so they work the same
whether predictions come from a live LLM agent or a fixture — CI never needs keys.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from regradar.agents.guardrails.verifier import verify_citation
from regradar.agents.state import ImpactLink, Obligation, ParsedRegDoc
from regradar.data.groundtruth.schema import GroundTruthSet


@dataclass
class PRF:
    precision: float
    recall: float
    f1: float
    tp: int
    fp: int
    fn: int


def _prf(tp: int, fp: int, fn: int) -> PRF:
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return PRF(precision, recall, f1, tp, fp, fn)


def _norm_art(ref: str) -> str:
    import re
    m = re.search(r"\d+[a-z]?", (ref or "").lower())
    return m.group(0) if m else ref


def score_extraction(predicted: list[Obligation], gold: GroundTruthSet) -> PRF:
    """Precision/recall/F1 of extracted obligations vs the labeled set.

    Matching is article-level (each gold item claimed at most once), because the
    extractor is not required to emit paragraph refs. When a prediction *does*
    carry a paragraph ref, an exact (article, paragraph) pairing is preferred so
    finer-grained predictions match the right gold item. Two passes: exact
    paragraph matches first, then article-level for the remainder."""
    claimed: set[str] = set()
    tp = 0

    def gold_in_article(art: str):
        return [g for g in gold.obligations if g.id not in claimed and _norm_art(g.article_ref) == art]

    # Pass 1: exact (article, paragraph) pairings.
    leftover: list[Obligation] = []
    for p in predicted:
        art = _norm_art(p.citation.article_ref)
        para = (p.citation.paragraph_ref or "").strip()
        if para:
            exact = next((g for g in gold_in_article(art)
                          if (g.paragraph_ref or "").strip() == para), None)
            if exact is not None:
                claimed.add(exact.id)
                tp += 1
                continue
        leftover.append(p)

    # Pass 2: article-level for predictions without an exact paragraph hit.
    fp = 0
    for p in leftover:
        art = _norm_art(p.citation.article_ref)
        cand = gold_in_article(art)
        if cand:
            claimed.add(cand[0].id)
            tp += 1
        else:
            fp += 1

    fn = len(gold.obligations) - len(claimed)
    return _prf(tp, fp, fn)


def score_citation_integrity(
    obligations: list[Obligation], pinned_doc: ParsedRegDoc
) -> float:
    """% of citations that pass the programmatic verifier. Target 100% (gated)."""
    if not obligations:
        return 1.0
    ok = sum(1 for o in obligations if verify_citation(o.citation, pinned_doc).ok)
    return ok / len(obligations)


def score_gap_detection(predicted_gap_ids: set[str], gold: GroundTruthSet) -> PRF:
    """Precision/recall/F1 of which obligations were flagged as gaps."""
    gold_gaps = gold.gap_ids
    all_ids = {o.id for o in gold.obligations}
    pred = predicted_gap_ids & all_ids
    tp = len(pred & gold_gaps)
    fp = len(pred - gold_gaps)
    fn = len(gold_gaps - pred)
    return _prf(tp, fp, fn)


def score_mapping(links: list[ImpactLink], gold: GroundTruthSet) -> float:
    """Mapping accuracy: of obligations mapped, the fraction where the predicted
    control (or gap) matches the labeled correct mapping. Links are matched to gold
    by obligation_id (gold obligations carry their gold id)."""
    by_id = {link.obligation_id: link for link in links}
    gold_by_id = {g.id: g for g in gold.obligations}
    graded = correct = 0
    for gid, g in gold_by_id.items():
        link = by_id.get(gid)
        if link is None:
            continue
        graded += 1
        if g.is_gap:
            correct += int(link.is_gap)
        else:
            correct += int(not link.is_gap and link.control_id == g.expected_control_id)
    return correct / graded if graded else 0.0


@dataclass
class EvalReport:
    extraction: PRF
    citation_integrity: float
    gap_detection: PRF | None = None
    notes: list[str] = field(default_factory=list)

    def passes(
        self,
        *,
        min_f1: float = 0.80,
        min_citation_integrity: float = 1.0,
    ) -> bool:
        return (
            self.extraction.f1 >= min_f1
            and self.citation_integrity >= min_citation_integrity
        )
