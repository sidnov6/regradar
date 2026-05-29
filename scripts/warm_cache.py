"""Warm the LLM response cache for every article of a regulation, in parallel with
fast backoff so free-tier per-minute limits don't leave gaps.

    python scripts/warm_cache.py --celex 32022R2554 --lang en --workers 4

Cached articles cost nothing (cache hit, no API call). Uncached articles are
extracted across N concurrent workers — overlapping the per-minute rate-limit
backoffs is the speedup. Idempotent: re-run to fill whatever is still missing.
"""
from __future__ import annotations

import argparse
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from regradar.agents.obligation.extract import extract_obligations
from regradar.data.pipeline import ingest_eurlex
from regradar.models.router import SchemaRepairFailed, router

WAIT_S = 12       # backoff when every provider is momentarily throttled
MAX_TRIES = 15
_print_lock = threading.Lock()


def _log(msg: str) -> None:
    with _print_lock:
        print(msg, flush=True)


def warm_one(art, celex, lang) -> bool:
    for attempt in range(MAX_TRIES):
        try:
            obls, llm = extract_obligations(art, celex=celex, language=lang, router=router)
        except SchemaRepairFailed:
            llm = None
        if llm and not llm.is_mock and llm.provider != "mock":
            tag = "cached" if llm.provider == "cache" else f"NEW via {llm.provider}"
            _log(f"  {art.label:<12} {tag} · {len(obls)} obl")
            return True
        time.sleep(WAIT_S)
    _log(f"  {art.label:<12} FAILED after {MAX_TRIES} tries")
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--celex", default="32022R2554")
    ap.add_argument("--lang", default="en")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    _, parsed = ingest_eurlex(args.celex, language=args.lang)
    total = len(parsed.articles)
    _log(f"warming {args.celex}: {total} articles · {args.workers} workers · providers {router.active_providers}")

    ok = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(warm_one, a, parsed.celex, args.lang): a for a in parsed.articles}
        for f in as_completed(futs):
            ok += 1 if f.result() else 0

    _log(f"\ncache complete: {ok}/{total}")
    return 0 if ok == total else 2


if __name__ == "__main__":
    sys.exit(main())
