"""Programmatic citation verification — the killer feature (Part 11.3).

The model never gets to be trusted on law. After extraction, this deterministic
verifier checks each citation:
  1. the cited article must exist in the pinned source, and
  2. the anchoring quote must actually appear in that article's text (fuzzy match).

Fail -> obligation rejected, flagged, human gate opened. Citation integrity is
thus 100% by construction, not by vibe.
"""
from __future__ import annotations

from rapidfuzz import fuzz

from regradar import config
from regradar.agents.state import (
    Citation,
    Obligation,
    ParsedRegDoc,
    VerifierVerdict,
)


def fuzzy_contains(haystack: str, needle: str, threshold: float) -> bool:
    """True if `needle` appears in `haystack` at >= threshold similarity.

    Legal text carries inconsistent whitespace/quotes between manifestations, so
    an exact substring test is too brittle; a windowed fuzzy partial-ratio is the
    robust choice. `threshold` is on a 0..1 scale (config default 0.92)."""
    if not needle.strip():
        return False
    h = _normalize_ws(haystack)
    n = _normalize_ws(needle)
    if n in h:
        return True
    # partial_ratio finds the best-matching substring window of h against n.
    score = fuzz.partial_ratio(n, h) / 100.0
    return score >= threshold


def _normalize_ws(s: str) -> str:
    return " ".join(s.split()).replace(" ", " ")


def verify_citation(
    citation: Citation,
    pinned_doc: ParsedRegDoc,
    threshold: float | None = None,
) -> VerifierVerdict:
    """Verify a single citation against the pinned, parsed source document."""
    threshold = config.CITATION_FUZZY_THRESHOLD if threshold is None else threshold

    if citation.celex != pinned_doc.celex:
        return VerifierVerdict.fail(
            f"citation CELEX {citation.celex} != pinned doc {pinned_doc.celex}"
        )

    # 1) the cited article must exist in the pinned source
    article = pinned_doc.get_article(citation.article_ref)
    if article is None:
        return VerifierVerdict.fail(
            f"cited article '{citation.article_ref}' not in source {pinned_doc.celex}"
        )

    # 2) the anchoring quote must actually appear in that article (language-aware)
    if citation.language != pinned_doc.language:
        return VerifierVerdict.fail(
            f"citation language '{citation.language}' != doc language "
            f"'{pinned_doc.language}' (never cite a translation as the source — Part 8)"
        )

    if fuzzy_contains(article.text, citation.anchor_quote, threshold):
        return VerifierVerdict.pass_()
    return VerifierVerdict.fail(
        f"anchor quote not found in {citation.article_ref} (threshold {threshold})"
    )


def verify_obligation(
    obligation: Obligation, pinned_doc: ParsedRegDoc
) -> VerifierVerdict:
    """Convenience wrapper: verify the obligation's citation."""
    return verify_citation(obligation.citation, pinned_doc)
