"""Deadline calendar (Part 3, agent 6 input).

Parsed application/transposition dates per regulation. In production these come
from the regulation's own articles ("shall apply from ...") parsed deterministically;
for the keystone we pin the known DORA application date. Keyed by CELEX, with room
for per-obligation overrides (some obligations phase in on different dates).
"""
from __future__ import annotations

from datetime import date
from typing import Optional

# CELEX -> application date.
APPLICATION_DATES: dict[str, date] = {
    "32022R2554": date(2025, 1, 17),  # DORA applies from 17 January 2025
}


def application_date(celex: str, obligation_id: Optional[str] = None) -> Optional[date]:
    return APPLICATION_DATES.get(celex)


def days_until(deadline: Optional[date], *, today: Optional[date] = None) -> Optional[int]:
    if deadline is None:
        return None
    today = today or date.today()
    return (deadline - today).days
