"""EUR-Lex XHTML -> Silver parser (Part 3, agent 2 — the XHTML fallback path).

CELLAR's Formex content requires resolving manifestation URIs; the EUR-Lex
"legal-content" XHTML endpoint returns the full, structured act directly and is
the reliable path to real article text. The modern EUR-Lex HTML (CONVEX/ELI)
marks articles up cleanly:

    <div id="art_5">
      <p class="oj-ti-art">Article 5</p>
      <p class="oj-sti-art">Governance and organisation</p>
      <p class="oj-normal">1.   Financial entities shall ...</p>
      <p class="oj-normal">(a)</p><p class="oj-normal">bear the ultimate ...</p>

This parser segments that into the same chapter -> article -> paragraph -> point
tree the rest of the pipeline (and the citation verifier) expects.
"""
from __future__ import annotations

import re

from lxml import html as LH

from regradar.agents.state import Article, Language, Paragraph, ParsedRegDoc

_ART_ID = re.compile(r"^art_(\d+[a-z]?)$")
_PARA_START = re.compile(r"^(\d+[a-z]?)\.\s+")
_BARE_LABEL = re.compile(r"^\(([0-9]+|[a-z]+|[ivxlcdm]+)\)$", re.IGNORECASE)


class XHTMLParseError(ValueError):
    pass


def _txt(el) -> str:
    return " ".join((el.text_content() or "").split())


def parse_eurlex_html(
    raw: bytes, *, celex: str, language: Language, content_hash: str
) -> ParsedRegDoc:
    root = LH.fromstring(raw)

    title = ""
    for el in root.iter():
        if (el.get("class") or "").startswith("oj-doc-ti"):
            title = _txt(el)
            if title:
                break
    if not title:
        t = root.find(".//title")
        title = _txt(t) if t is not None else celex

    articles: list[Article] = []
    for div in root.xpath("//*[starts-with(@id,'art_')]"):
        m = _ART_ID.match(div.get("id") or "")
        if not m:
            continue  # skip sub-anchors like art_5.tit_1
        number = m.group(1)

        label = title_text = ""
        normals: list[str] = []
        for p in div.iter():
            cls = p.get("class") or ""
            if cls == "oj-ti-art" and not label:
                label = _txt(p)
            elif cls == "oj-sti-art" and not title_text:
                title_text = _txt(p)
            elif cls == "oj-normal":
                t = _txt(p)
                if t:
                    normals.append(t)

        chapter = _nearest_chapter(div)
        articles.append(
            Article(
                number=number,
                label=label or f"Article {number}",
                title=title_text,
                chapter=chapter,
                paragraphs=_group_paragraphs(normals),
            )
        )

    if not articles:
        raise XHTMLParseError(f"no articles found in EUR-Lex HTML for {celex}")

    return ParsedRegDoc(
        celex=celex, language=language, title=title,
        content_hash=content_hash, articles=articles,
    )


def _nearest_chapter(div) -> str:
    prev = div.xpath("preceding::*[contains(@class,'oj-ti-section-1')][1]")
    return _txt(prev[0]) if prev else ""


def _group_paragraphs(normals: list[str]) -> list[Paragraph]:
    """Group the flat oj-normal lines into numbered paragraphs with lettered points.
    All text is preserved so the citation verifier can find any anchor quote."""
    paragraphs: list[Paragraph] = []
    current: Paragraph | None = None
    pending_label: str | None = None

    def ensure_current() -> Paragraph:
        nonlocal current
        if current is None:
            current = Paragraph(ref=str(len(paragraphs) + 1), text="", points=[])
            paragraphs.append(current)
        return current

    for t in normals:
        if _PARA_START.match(t):
            num = _PARA_START.match(t).group(1)
            body = _PARA_START.sub("", t)
            current = Paragraph(ref=num, text=body, points=[])
            paragraphs.append(current)
            pending_label = None
        elif _BARE_LABEL.match(t):
            pending_label = t  # a list marker on its own line; content follows
        else:
            if pending_label is not None:
                ensure_current().points.append(f"{pending_label} {t}")
                pending_label = None
            elif current is not None and current.text:
                current.text += " " + t  # continuation of the paragraph
            else:
                p = ensure_current()
                p.text = (p.text + " " + t).strip()
    return paragraphs
