"""Exact response cache (Part 11.6) — stretch quota + buy determinism.

Keyed by a hash of (prompt, temperature). Re-running the same regulation reuses
the stored completion instead of re-spending free-tier quota or re-rolling the
dice. Only successful, non-mock responses are cached, so a rate-limited floor
response never poisons future runs. (A semantic cache can layer on later.)
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Optional

from regradar import config

_DEFAULT_DIR = config.DATA_ROOT / ".llm_cache"
_ENABLED = os.getenv("REGRADAR_CACHE_ENABLED", "1") not in ("0", "false", "False")


class ResponseCache:
    def __init__(self, root: Optional[Path] = None, enabled: bool = _ENABLED):
        self.enabled = enabled
        self.root = root or _DEFAULT_DIR
        if self.enabled:
            self.root.mkdir(parents=True, exist_ok=True)

    def _key(self, prompt: str, temperature: float) -> str:
        return hashlib.sha256(f"{temperature}\x00{prompt}".encode()).hexdigest()

    def get(self, prompt: str, temperature: float) -> Optional[dict]:
        if not self.enabled:
            return None
        p = self.root / f"{self._key(prompt, temperature)}.json"
        if p.exists():
            return json.loads(p.read_text())
        return None

    def put(self, prompt: str, temperature: float, payload: dict) -> None:
        if not self.enabled:
            return
        p = self.root / f"{self._key(prompt, temperature)}.json"
        p.write_text(json.dumps(payload))


cache = ResponseCache()
