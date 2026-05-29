"""RegRadar Phase 0+1 keystone demo.

Runs the deterministic pipeline end to end (ingest -> Bronze -> Silver),
grades against the hand-labeled DORA oracle, and — if an LLM provider is live —
does one real extraction through the router and verifies its citations.

    python scripts/keystone_demo.py            # full demo (live extraction if a key is set)
    python scripts/keystone_demo.py --no-live  # deterministic only, no LLM calls
"""
from __future__ import annotations

import sys

from regradar.agents.guardrails.verifier import verify_citation
from regradar.agents.obligation.extract import extract_obligations
from regradar.data.groundtruth.schema import load_groundtruth
from regradar.data.pipeline import ingest_fixture
from regradar.eval.harness import (
    EvalReport,
    score_citation_integrity,
    score_extraction,
    score_gap_detection,
)
from regradar.knowledge.profile.schema import load_profile
from regradar.models.router import SchemaRepairFailed, router

BAR = "=" * 70


def section(title: str) -> None:
    print(f"\n{BAR}\n{title}\n{BAR}")


def main(live: bool = True) -> int:
    section("RegRadar · KOMPASS — Phase 0+1 keystone")
    print(f"LLM failover chain (active first): {router.active_providers}")

    # 1) Ingest -> Bronze (pinned by hash, idempotent)
    section("1 · Ingest → Bronze (immutable, hash-pinned)")
    rec, parsed = ingest_fixture()
    print(f"CELEX {rec.celex} · {rec.manifestation.value} · {rec.language}")
    print(f"content_hash: {rec.content_hash[:24]}…  (the version pin)")
    rec2, _ = ingest_fixture()  # re-ingest identical bytes
    print(f"re-ingest identical bytes → same pin (idempotent): {rec.content_hash == rec2.content_hash}")

    # 2) Bronze -> Silver (article tree)
    section("2 · Bronze → Silver (article-segmented)")
    print(f"{parsed.title[:64]}…")
    for a in parsed.articles:
        pts = sum(len(p.points) for p in a.paragraphs)
        print(f"  Art {a.number:>3}  {a.title[:46]:46}  {len(a.paragraphs)} para, {pts} pts")

    # 3) Grade against the oracle
    section("3 · Evaluation vs hand-labeled DORA oracle (Part 14)")
    gt = load_groundtruth()
    profile = load_profile()
    gold_obs = [g.to_obligation() for g in gt.obligations]
    report = EvalReport(
        extraction=score_extraction(gold_obs, gt),
        citation_integrity=score_citation_integrity(gold_obs, parsed),
        gap_detection=score_gap_detection(gt.gap_ids, gt),
    )
    print(f"labeled obligations : {len(gt.obligations)}  (known gaps: {len(gt.gap_ids)})")
    print(f"citation integrity  : {report.citation_integrity * 100:.0f}%  (every anchor verified against pinned source)")
    print(f"gap detection F1    : {report.gap_detection.f1:.2f}")
    print(f"synthetic bank      : {profile.name}")
    print(f"CI gate would pass  : {report.passes()}")

    # 4) Live loop: real extraction through the router + verification
    if live and "mock" not in router.active_providers:
        section("4 · LIVE: extract obligations via LLM, then verify each citation")
        art = parsed.get_article("Article 17")
        try:
            obls, llm = extract_obligations(art, celex=parsed.celex, language="en")
        except SchemaRepairFailed as e:
            print(f"extraction failed schema repair → would flag + human-gate: {e}")
            return 0
        print(f"provider used: {llm.provider} ({llm.model}) · {round(llm.latency_ms)}ms")
        print(f"extracted {len(obls)} obligation(s) from {art.label}:\n")
        for o in obls:
            v = verify_citation(o.citation, parsed)
            mark = "✓ VERIFIED" if v.ok else f"✗ REJECTED ({v.reason})"
            print(f"  [{mark}] {o.obligation_type.value}: {o.actor} {o.modal_force.value} {o.action[:60]}")
            print(f"      anchor: “{o.citation.anchor_quote[:80]}…”")
        verified = sum(1 for o in obls if verify_citation(o.citation, parsed).ok)
        print(f"\nlive citation integrity: {verified}/{len(obls)} verified against the pinned source")
    else:
        section("4 · LIVE extraction skipped (no provider / --no-live)")

    print(f"\n{BAR}\nkeystone OK\n{BAR}")
    return 0


if __name__ == "__main__":
    sys.exit(main(live="--no-live" not in sys.argv))
