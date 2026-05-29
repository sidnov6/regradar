"""EUR-Lex XHTML parser (the real-data path), tested offline against a fixture."""
from pathlib import Path

import pytest

from regradar.agents.guardrails.verifier import verify_citation
from regradar.agents.parser.xhtml import XHTMLParseError, parse_eurlex_html
from regradar.agents.state import Citation

FIXTURE = (
    Path(__file__).resolve().parent.parent
    / "regradar/data/sources/fixtures/eurlex_sample.html"
)


@pytest.fixture(scope="module")
def parsed():
    return parse_eurlex_html(FIXTURE.read_bytes(), celex="TEST1", language="en", content_hash="h")


def test_articles_and_title(parsed):
    assert parsed.title.startswith("SAMPLE REGULATION")
    assert [a.number for a in parsed.articles] == ["5", "17"]


def test_chapter_and_metadata(parsed):
    art5 = parsed.get_article("Article 5")
    assert art5.title == "Governance and organisation"
    assert "CHAPTER II" in art5.chapter
    assert len(art5.paragraphs) == 2


def test_numbered_paragraphs_and_points(parsed):
    art5 = parsed.get_article("5")
    # paragraph 2 collected its sub-points (a)/(b)
    p2 = next(p for p in art5.paragraphs if p.ref == "2")
    assert any("bear the ultimate responsibility" in pt for pt in p2.points)


def test_subanchor_not_treated_as_article(parsed):
    # the <p id="art_17.tit_1"> noise must not create an article
    assert parsed.get_article("17") is not None
    assert all("noise paragraph" not in a.text for a in parsed.articles)


def test_real_anchor_verifies_against_parsed(parsed):
    c = Citation(celex="TEST1", article_ref="Article 5", language="en",
                 anchor_quote="Financial entities shall have in place an internal governance and control framework")
    assert verify_citation(c, parsed).ok


def test_empty_html_raises():
    with pytest.raises(XHTMLParseError):
        parse_eurlex_html(b"<html><body><p>nothing</p></body></html>",
                          celex="X", language="en", content_hash="h")
