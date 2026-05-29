import pytest

from regradar.agents.parser.formex import FormexParseError, parse_formex


def test_parses_all_articles(parsed_dora):
    assert [a.number for a in parsed_dora.articles] == ["5", "6", "17", "19", "24", "28"]


def test_article_metadata(parsed_dora):
    art5 = parsed_dora.get_article("Article 5")
    assert art5.title == "Governance and organisation"
    assert "CHAPTER II" in art5.chapter
    assert len(art5.paragraphs) == 2


def test_points_parsed(parsed_dora):
    art19 = parsed_dora.get_article("19")
    points = [p for para in art19.paragraphs for p in para.points]
    assert len(points) == 3
    assert any("initial notification" in p for p in points)


def test_get_article_ref_normalization(parsed_dora):
    assert parsed_dora.get_article("Article 17(2)").number == "17"
    assert parsed_dora.get_article("Art. 24").number == "24"
    assert parsed_dora.get_article("28") is not None
    assert parsed_dora.get_article("Article 999") is None


def test_article_text_includes_paragraphs(parsed_dora):
    text = parsed_dora.get_article("5").text
    assert "management body" in text
    assert "internal governance and control framework" in text


def test_empty_doc_raises():
    with pytest.raises(FormexParseError):
        parse_formex(b"<ACT><TI.DOC>empty</TI.DOC></ACT>", celex="X", language="en", content_hash="h")
