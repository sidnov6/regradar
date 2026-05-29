"""Prioritization: deterministic f(deadline, effort, risk), gaps + overdue rank high."""
from datetime import date

from regradar.agents.impact.map import map_obligations
from regradar.agents.prioritize.deadlines import application_date, days_until
from regradar.agents.prioritize.score import prioritize, score_item
from regradar.agents.state import ImpactLink


def _obls(groundtruth):
    return [g.to_obligation() for g in groundtruth.obligations]


def test_dora_deadline_known():
    assert application_date("32022R2554") == date(2025, 1, 17)
    assert days_until(date(2025, 1, 17), today=date(2026, 5, 29)) < 0  # overdue


def test_gap_scores_higher_than_covered_same_type(groundtruth):
    obls = {g.id: g.to_obligation() for g in groundtruth.obligations}
    o = obls["GT-DORA-006-1"]
    covered = ImpactLink(obligation_id=o.id, function="ICT", system="x", control_id="CTL-001", is_gap=False)
    gap = ImpactLink(obligation_id=o.id, function="ICT", system="", control_id=None, is_gap=True)
    today = date(2026, 5, 29)
    assert score_item(o, gap, today=today).priority_score > score_item(o, covered, today=today).priority_score


def test_overdue_gap_ranks_first(groundtruth, bank_profile):
    obls = _obls(groundtruth)
    links = map_obligations(obls, bank_profile)
    items = prioritize(obls, links, today=date(2026, 5, 29))
    # Highest-priority item should be an overdue reporting gap (Art 19).
    top = items[0]
    assert top.deadline_days is not None and top.deadline_days < 0
    assert top.obligation_id.startswith("GT-DORA-019")


def test_priority_is_deterministic(groundtruth):
    obls = _obls(groundtruth)
    from regradar.knowledge.profile.schema import load_profile
    links = map_obligations(obls, load_profile())
    a = prioritize(obls, links, today=date(2026, 5, 29))
    b = prioritize(obls, links, today=date(2026, 5, 29))
    assert [i.priority_score for i in a] == [i.priority_score for i in b]
