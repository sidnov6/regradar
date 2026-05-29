"""Phase 2: run the extraction+guardrail engine LIVE across all DORA articles and
grade it against the hand-labeled oracle.

    python scripts/grade_live_extraction.py

Prints extraction precision/recall/F1, live citation integrity, a per-obligation-type
breakdown, and the guardrail summary (flags, audit entries, human-gate status).
Writes the report to regradar/data/gold/live_extraction_report.json.
"""
from __future__ import annotations

import json
import sys
from collections import Counter

from regradar import config
from regradar.agents.obligation.run import extract_document
from regradar.data.groundtruth.schema import load_groundtruth
from regradar.data.pipeline import ingest_fixture
from regradar.eval.harness import score_citation_integrity, score_extraction
from regradar.models.router import router

BAR = "=" * 70


def main() -> int:
    if "mock" in router.active_providers:
        print("No live LLM provider available (set GROQ_API_KEY). Aborting live grade.")
        return 1

    rec, parsed = ingest_fixture()
    gt = load_groundtruth()

    print(f"{BAR}\nPhase 2 · LIVE graded extraction — {parsed.celex} ({parsed.language})\n{BAR}")
    print(f"provider chain: {router.active_providers}\n")

    out = extract_document(parsed, router=router)

    prf = score_extraction(out.obligations, gt)
    integrity = score_citation_integrity(out.obligations, parsed)

    print(f"obligations accepted : {len(out.obligations)}  (rejected by verifier: {len(out.rejected)})")
    print(f"extraction precision : {prf.precision:.3f}")
    print(f"extraction recall    : {prf.recall:.3f}")
    print(f"extraction F1        : {prf.f1:.3f}   (tp={prf.tp} fp={prf.fp} fn={prf.fn})")
    print(f"citation integrity   : {integrity * 100:.0f}%  (accepted obligations verified against pinned source)")
    print(f"guardrail engine integrity : {out.citation_integrity * 100:.0f}%  (accepted / (accepted+rejected))")

    by_type = Counter(o.obligation_type.value for o in out.obligations)
    print("\nby obligation type:")
    for t, n in sorted(by_type.items()):
        print(f"  {t:14} {n}")

    if any(f.kind.value == "schema_repair_failed" for f in out.flags):
        print("\n⚠ NOTE: some articles fell through to the mock floor (likely free-tier"
              " quota). Those metrics are partial — re-run after quota resets; cached"
              " articles will not re-spend tokens (Part 11.6).")

    print(f"\nflags raised        : {len(out.flags)}")
    for f in out.flags:
        print(f"  [{f.severity}] {f.kind.value}: {f.message[:70]}")
    print(f"audit entries       : {len(out.audit_trail)}")
    print(f"corpus version      : {out.corpus_version}")
    print(f"human gate needed   : {out.needs_human_gate}")

    report = {
        "celex": parsed.celex,
        "language": parsed.language,
        "corpus_version": out.corpus_version,
        "providers": router.active_providers,
        "extraction": {
            "precision": prf.precision, "recall": prf.recall, "f1": prf.f1,
            "tp": prf.tp, "fp": prf.fp, "fn": prf.fn,
        },
        "citation_integrity": integrity,
        "accepted": len(out.obligations),
        "rejected": len(out.rejected),
        "by_type": dict(by_type),
        "flags": [f.model_dump(mode="json") for f in out.flags],
        "audit_entries": len(out.audit_trail),
    }
    config.GOLD_STORE.mkdir(parents=True, exist_ok=True)
    path = config.GOLD_STORE / "live_extraction_report.json"
    path.write_text(json.dumps(report, indent=2))
    print(f"\nreport written: {path}")
    print(f"{BAR}\ndone\n{BAR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
