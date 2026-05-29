"""Formex -> Silver parser (Part 3, agent 2).

Deterministic, rule-based segmentation of EU Formex XML into a clean
chapter -> article -> paragraph -> point tree. Formex is the preferred input
because it is article-aware, which is exactly what makes a citation map to a
real, addressable unit (Part 7).

Element-name matching is namespace- and case-tolerant (Formex dialects vary).
If no articles are found, we raise so the data-quality gate (Part 11.10) can
fall back to XHTML/PDF or flag, rather than emitting an empty doc that would
poison extraction downstream.
"""
from __future__ import annotations

import re
from typing import Optional

from lxml import etree

from regradar.agents.state import Article, Language, Paragraph, ParsedRegDoc


class FormexParseError(ValueError):
    """Raised when the document has no recognisable article structure."""


def _ln(el) -> str:
    """Lower-cased local name of an element tag (namespace-stripped)."""
    tag = el.tag
    if not isinstance(tag, str):
        return ""
    return etree.QName(tag).localname.lower()


def _text(el) -> str:
    """All descendant text of an element, whitespace-normalised."""
    return " ".join("".join(el.itertext()).split())


def _find_all(root, *local_names: str) -> list:
    wanted = {n.lower() for n in local_names}
    return [el for el in root.iter() if _ln(el) in wanted]


def _article_number(label: str, identifier: Optional[str]) -> str:
    """'Article 5' / 'Artikel 5a' -> '5' / '5a'; fall back to the IDENTIFIER attr."""
    m = re.search(r"(\d+[a-z]?)", label or "", re.IGNORECASE)
    if m:
        return m.group(1)
    if identifier:
        m = re.search(r"(\d+[a-z]?)", identifier)
        if m:
            return m.group(1).lstrip("0") or m.group(1)
    return (label or identifier or "").strip()


def parse_formex(
    xml_bytes: bytes,
    *,
    celex: str,
    language: Language,
    content_hash: str,
) -> ParsedRegDoc:
    root = etree.fromstring(xml_bytes)

    doc_title = ""
    for el in root.iter():
        if _ln(el) in ("ti.doc", "title", "ti"):
            doc_title = _text(el)
            if doc_title:
                break

    articles: list[Article] = []
    current_chapter = ""

    for el in root.iter():
        name = _ln(el)
        # Track the enclosing chapter/division title as we walk.
        if name in ("division", "title", "chapter"):
            for child in el:
                if _ln(child) in ("ti", "ti.doc"):
                    current_chapter = _text(child)
                    break
            continue

        if name != "article":
            continue

        identifier = el.get("IDENTIFIER") or el.get("identifier")
        label = ""
        title = ""
        for child in el:
            cn = _ln(child)
            if cn in ("ti.art", "ti"):
                label = _text(child)
            elif cn in ("sti.art", "sti"):
                title = _text(child)

        number = _article_number(label, identifier)
        paragraphs = _parse_paragraphs(el)
        articles.append(
            Article(
                number=number,
                label=label or f"Article {number}",
                title=title,
                chapter=current_chapter,
                paragraphs=paragraphs,
            )
        )

    if not articles:
        raise FormexParseError(f"no <ARTICLE> elements found in {celex} ({language})")

    return ParsedRegDoc(
        celex=celex,
        language=language,
        title=doc_title,
        content_hash=content_hash,
        articles=articles,
    )


def _parse_paragraphs(article_el) -> list[Paragraph]:
    """Extract PARAG units; each has a number (NO.PARAG) and text, plus list points."""
    paragraphs: list[Paragraph] = []
    parags = [c for c in article_el.iter() if _ln(c) == "parag"]

    if parags:
        for idx, parag in enumerate(parags, start=1):
            ref = ""
            for child in parag:
                if _ln(child) in ("no.parag", "no.p"):
                    ref = _text(child).strip("().") or str(idx)
                    break
            ref = ref or str(idx)
            points = _parse_points(parag)
            # Body text = the parag text minus its enumerated points.
            text = _parag_body_text(parag)
            paragraphs.append(Paragraph(ref=ref, text=text, points=points))
        return paragraphs

    # No explicit PARAG: treat top-level ALINEA/P blocks as a single paragraph.
    blocks = [c for c in article_el if _ln(c) in ("alinea", "p")]
    if blocks:
        text = " ".join(_text(b) for b in blocks)
        paragraphs.append(Paragraph(ref="1", text=text, points=_parse_points(article_el)))
    return paragraphs


def _parag_body_text(parag_el) -> str:
    parts: list[str] = []
    for child in parag_el:
        cn = _ln(child)
        if cn in ("no.parag", "no.p", "list"):
            continue
        parts.append(_text(child))
    return " ".join(p for p in parts if p).strip()


def _parse_points(el) -> list[str]:
    """Enumerated list points: (a), (b), ... from LIST/ITEM structures."""
    points: list[str] = []
    for item in el.iter():
        if _ln(item) != "item":
            continue
        label = ""
        body = ""
        for child in item:
            cn = _ln(child)
            if cn in ("no.p", "np"):
                label = _text(child)
            elif cn in ("txt", "p", "alinea"):
                body = _text(child)
        line = f"{label} {body}".strip() if (label or body) else _text(item)
        if line:
            points.append(line)
    return points
