"""Prioritization agent (Part 3, agent 6) — "what first, and how bad".

Priority = f(deadline, effort, risk), computed in Python (the determinism boundary,
Part 11.1). The LLM only supplies qualitative inputs it can justify; the math is
here, unit-tested, and reproducible. Weights live in config.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from regradar import config
from regradar.agents.prioritize.deadlines import application_date, days_until
from regradar.agents.state import ImpactLink, Obligation, ObligationType, PrioritizedItem

# Supervisory/enforcement exposure by obligation type (0..1).
_RISK_BY_TYPE: dict[ObligationType, float] = {
    ObligationType.REPORTING: 0.9,
    ObligationType.CAPITAL: 0.9,
    ObligationType.ICT_CONTROL: 0.8,
    ObligationType.GOVERNANCE: 0.7,
    ObligationType.RECORD_KEEPING: 0.6,
    ObligationType.DISCLOSURE: 0.6,
    ObligationType.CONDUCT: 0.5,
}


def _deadline_urgency(days: Optional[int]) -> float:
    """1.0 if overdue/now, decaying linearly to 0 over the configured horizon."""
    if days is None:
        return 0.3  # unknown deadline -> mild urgency
    if days <= 0:
        return 1.0
    horizon = config.PRIORITY_DEADLINE_HORIZON_DAYS
    return max(0.0, 1.0 - days / horizon)


def _effort(link: ImpactLink) -> float:
    """Gap = build a control from scratch (high effort); covered = adapt (low)."""
    return 0.9 if link.is_gap else 0.3


def _risk(obligation: Obligation, link: ImpactLink) -> float:
    base = _RISK_BY_TYPE.get(obligation.obligation_type, 0.6)
    return min(1.0, base + 0.1 if link.is_gap else base)


def score_item(
    obligation: Obligation,
    link: ImpactLink,
    *,
    today: Optional[date] = None,
) -> PrioritizedItem:
    deadline = application_date(obligation.citation.celex, obligation.id)
    days = days_until(deadline, today=today)

    deadline_u = _deadline_urgency(days)
    effort = _effort(link)
    risk = _risk(obligation, link)

    priority = round(
        config.PRIORITY_WEIGHT_DEADLINE * deadline_u
        + config.PRIORITY_WEIGHT_EFFORT * effort
        + config.PRIORITY_WEIGHT_RISK * risk,
        4,
    )
    overdue = days is not None and days <= 0
    rationale = (
        f"{'OVERDUE' if overdue else f'{days}d to deadline' if days is not None else 'no deadline'}; "
        f"{'GAP — control to build' if link.is_gap else 'control exists'}; "
        f"{obligation.obligation_type.value} risk"
    )
    return PrioritizedItem(
        obligation_id=obligation.id,
        deadline=deadline,
        deadline_days=days,
        effort_score=effort,
        risk_score=risk,
        priority_score=priority,
        rationale=rationale,
    )


def prioritize(
    obligations: list[Obligation],
    links: list[ImpactLink],
    *,
    today: Optional[date] = None,
) -> list[PrioritizedItem]:
    """Rank obligations by computed priority, highest first."""
    by_id = {o.id: o for o in obligations}
    items: list[PrioritizedItem] = []
    for link in links:
        obl = by_id.get(link.obligation_id)
        if obl is None:
            continue
        items.append(score_item(obl, link, today=today))
    items.sort(key=lambda i: i.priority_score, reverse=True)
    return items
