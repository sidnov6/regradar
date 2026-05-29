"""HTTP client with exponential backoff + jitter (Part 11.5).

The Source-Monitor and bulk jobs must respect CELLAR's limits and survive
transient 429/5xx without hard-failing. Retries are bounded by config.
"""
from __future__ import annotations

import random
import time
from typing import Optional

import httpx

from regradar import config

_RETRYABLE = {429, 500, 502, 503, 504}


def get(
    url: str,
    *,
    headers: Optional[dict[str, str]] = None,
    params: Optional[dict[str, str]] = None,
    accept: Optional[str] = None,
    max_retries: Optional[int] = None,
) -> httpx.Response:
    """GET with bounded exponential backoff + jitter on retryable failures."""
    max_retries = config.HTTP_MAX_RETRIES if max_retries is None else max_retries
    hdrs = dict(headers or {})
    if accept:
        hdrs["Accept"] = accept
    hdrs.setdefault("User-Agent", "RegRadar/0.1 (compliance research; contact via repo)")

    last_exc: Optional[Exception] = None
    for attempt in range(max_retries + 1):
        try:
            resp = httpx.get(
                url, headers=hdrs, params=params,
                timeout=config.HTTP_TIMEOUT_S, follow_redirects=True,
            )
            if resp.status_code in _RETRYABLE and attempt < max_retries:
                _sleep_backoff(attempt, retry_after=resp.headers.get("Retry-After"))
                continue
            resp.raise_for_status()
            return resp
        except (httpx.TransportError, httpx.HTTPStatusError) as e:
            last_exc = e
            if attempt < max_retries:
                _sleep_backoff(attempt)
                continue
            raise
    raise last_exc  # pragma: no cover


def _sleep_backoff(attempt: int, retry_after: Optional[str] = None) -> None:
    if retry_after and retry_after.isdigit():
        time.sleep(float(retry_after))
        return
    base = config.HTTP_BACKOFF_BASE_S * (2 ** attempt)
    time.sleep(base + random.uniform(0, base * 0.25))  # full jitter cap at 25%
