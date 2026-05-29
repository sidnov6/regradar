"""Source-Monitor agent — "watch the firehose" (Part 3, agent 1).

Mostly deterministic: poll the feed, dedup against a local seen-store by CELEX,
keep only in-scope, genuinely-new work. Content-hash dedup happens downstream in
Bronze (idempotency, Part 11.7), so this layer only needs CELEX-level dedup to
avoid re-queuing.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from regradar import config
from regradar.agents.state import SourceEvent
from regradar.data.sources.cellar import CellarClient


class SeenStore:
    """Tiny persistent set of CELEX numbers already queued."""

    def __init__(self, path: Optional[Path] = None):
        self.path = path or (config.DATA_ROOT / "sources" / "seen_celex.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._seen: set[str] = set()
        if self.path.exists():
            self._seen = set(json.loads(self.path.read_text()))

    def __contains__(self, celex: str) -> bool:
        return celex in self._seen

    def add(self, celex: str) -> None:
        self._seen.add(celex)
        self.path.write_text(json.dumps(sorted(self._seen), indent=2))


class SourceMonitor:
    def __init__(self, client: Optional[CellarClient] = None, seen: Optional[SeenStore] = None):
        self.client = client or CellarClient()
        self.seen = seen or SeenStore()

    def poll(self, feed_url: Optional[str] = None, *, mark_seen: bool = True) -> list[SourceEvent]:
        """Return genuinely-new, in-scope events. Dedups by CELEX against the seen-store."""
        events = self.client.fetch_feed(feed_url)
        new: list[SourceEvent] = []
        for ev in events:
            if not ev.in_scope:
                continue
            if ev.celex and ev.celex in self.seen:
                continue
            new.append(ev)
            if mark_seen and ev.celex:
                self.seen.add(ev.celex)
        return new
