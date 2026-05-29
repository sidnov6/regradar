"""Memo drafting + export + approval gate (Part 3 agent 7, Part 3.3)."""
from regradar.agents.impact.map import map_obligations
from regradar.agents.memo.draft import draft_memo
from regradar.agents.memo.export import approve, reject, to_html
from regradar.agents.prioritize.score import prioritize


def _state(groundtruth, bank_profile, parsed_dora):
    obls = [g.to_obligation() for g in groundtruth.obligations]
    links = map_obligations(obls, bank_profile)
    return {
        "parsed_doc": parsed_dora,
        "obligations": obls,
        "impact_links": links,
        "prioritized": prioritize(obls, links),
        "corpus_version": "cv:test",
    }


def test_memo_structure(groundtruth, bank_profile, parsed_dora):
    memo = draft_memo(_state(groundtruth, bank_profile, parsed_dora), language="en")
    assert memo.status == "draft"
    assert len(memo.citation_appendix) == len(groundtruth.obligations)
    for section in ["Executive summary", "Obligations & impact", "Prioritized actions", "Citation appendix"]:
        assert section in memo.body_markdown
    assert "GAP" in memo.body_markdown            # gaps surfaced
    assert "3 obligation(s) have no covering control" in memo.exec_summary


def test_memo_html_export_has_table(groundtruth, bank_profile, parsed_dora):
    memo = draft_memo(_state(groundtruth, bank_profile, parsed_dora), language="en")
    html = to_html(memo)
    assert "<table>" in html and "Citation appendix" in html


def test_german_labels_present_without_router(groundtruth, bank_profile, parsed_dora):
    # No router -> prose stays English, but section labels localise to German.
    memo = draft_memo(_state(groundtruth, bank_profile, parsed_dora), language="de")
    assert memo.language == "de"
    assert "Zusammenfassung" in memo.body_markdown
    assert "Zitat-Anhang" in memo.body_markdown


def test_approval_gate(groundtruth, bank_profile, parsed_dora):
    memo = draft_memo(_state(groundtruth, bank_profile, parsed_dora), language="en")
    approved, gate = approve(memo, "reviewer", "ok")
    assert approved.status == "approved" and gate.status == "approved" and gate.approver == "reviewer"
    rejected, gate2 = reject(memo, "reviewer", "needs work")
    assert rejected.status == "rejected" and gate2.status == "rejected"
