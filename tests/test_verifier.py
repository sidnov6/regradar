from regradar.agents.guardrails.verifier import fuzzy_contains, verify_citation
from regradar.agents.state import Citation


def _cite(**kw):
    base = dict(
        celex="32022R2554",
        article_ref="Article 5",
        language="en",
        anchor_quote="The management body of the financial entity shall define, approve, oversee",
    )
    base.update(kw)
    return Citation(**base)


def test_verifies_real_anchor(parsed_dora):
    assert verify_citation(_cite(), parsed_dora).ok


def test_fails_when_article_absent(parsed_dora):
    v = verify_citation(_cite(article_ref="Article 999"), parsed_dora)
    assert not v.ok and "not in source" in v.reason


def test_fails_on_fabricated_quote(parsed_dora):
    v = verify_citation(_cite(anchor_quote="banks must paint their servers blue every Tuesday"), parsed_dora)
    assert not v.ok and "anchor quote not found" in v.reason


def test_fails_on_celex_mismatch(parsed_dora):
    v = verify_citation(_cite(celex="32022R9999"), parsed_dora)
    assert not v.ok and "CELEX" in v.reason


def test_fails_on_language_mismatch(parsed_dora):
    # Never cite a translation as the source text (Part 8).
    v = verify_citation(_cite(language="de"), parsed_dora)
    assert not v.ok and "language" in v.reason


def test_fuzzy_tolerates_whitespace_and_minor_noise():
    article = "Financial entities shall report major ICT-related incidents to the relevant competent authority."
    assert fuzzy_contains(article, "Financial   entities shall report major ICT-related incidents", 0.92)
    assert not fuzzy_contains(article, "entities shall delete all incident records", 0.92)
