"""LIVE real-data ingestion: fetch a regulation from EUR-Lex, parse it, and run
the full agentic pipeline on genuine article text.

    python scripts/ingest_real.py                      # DORA, first 8 articles extracted
    python scripts/ingest_real.py --celex 32022R2554 --lang en --articles 12
    python scripts/ingest_real.py --articles 0         # all articles (slow; uses quota)

Parses ALL articles into Silver; extraction is capped (free-tier friendly, cached).
Citation integrity is measured against the REAL fetched text.
"""
from __future__ import annotations

import argparse
import sys

from regradar.agents.impact.map import map_obligations
from regradar.agents.obligation.run import extract_document
from regradar.agents.prioritize.score import prioritize
from regradar.data.pipeline import ingest_eurlex
from regradar.knowledge.profile.schema import load_profile
from regradar.models.router import router

BAR = "=" * 72


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--celex", default="32022R2554")
    ap.add_argument("--lang", default="en")
    ap.add_argument("--articles", type=int, default=8, help="cap extraction (0 = all)")
    args = ap.parse_args()

    print(f"{BAR}\nLIVE ingestion from EUR-Lex — CELEX {args.celex} ({args.lang})\n{BAR}")
    print("fetching real document …")
    rec, parsed = ingest_eurlex(args.celex, language=args.lang)
    print(f"pinned to Bronze: hash {rec.content_hash[:16]} · manifestation {rec.manifestation.value}")
    print(f"parsed REAL articles → Silver: {len(parsed.articles)}")
    print(f"title: {parsed.title[:88]}")

    cap = None if args.articles == 0 else args.articles
    n = len(parsed.articles) if cap is None else min(cap, len(parsed.articles))
    print(f"\nextracting obligations from {n} article(s) via {router.active_providers} (temp 0)…")
    out = extract_document(parsed, router=router, max_articles=cap)

    integrity = (len(out.obligations) / (len(out.obligations) + len(out.rejected))) if (out.obligations or out.rejected) else 1.0
    print(f"\nobligations accepted : {len(out.obligations)}  (verifier-rejected: {len(out.rejected)})")
    print(f"citation integrity   : {integrity * 100:.0f}%  (verified against REAL EUR-Lex text)")
    print(f"flags / human gate   : {len(out.flags)} / {out.needs_human_gate}")

    profile = load_profile()
    links = map_obligations(out.obligations, profile)
    gaps = [l for l in links if l.is_gap]
    prio = prioritize(out.obligations, links)
    print(f"impact mapped        : {len(links)} obligations · {len(gaps)} gaps")

    print("\nsample obligations (real text):")
    for o in out.obligations[:6]:
        print(f"  ✓ {o.citation.article_ref:11} [{o.obligation_type.value}] {o.action[:58]}")

    print("\ntop priorities:")
    for it in prio[:5]:
        print(f"  [{it.priority_score:.3f}] {it.obligation_id:20} {it.rationale}")

    print(f"\n{BAR}\nreal-data run complete\n{BAR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
