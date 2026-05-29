"""Eval-as-CI-gate (Part 11.8). Exit non-zero if quality drops below threshold,
so a regression literally cannot be merged.

    python -m regradar.eval.run

Today it grades the deterministic pipeline + oracle self-consistency (citation
integrity must be 100%). As the live extraction agent matures, swap `gold_obs`
for the agent's predictions to gate extraction F1 the same way.
"""
from __future__ import annotations

import sys

from regradar.agents.impact.map import map_obligations
from regradar.data.groundtruth.schema import load_groundtruth
from regradar.data.pipeline import ingest_fixture
from regradar.eval.harness import (
    EvalReport,
    score_citation_integrity,
    score_extraction,
    score_gap_detection,
    score_mapping,
)
from regradar.knowledge.profile.schema import load_profile

MIN_F1 = 0.80
MIN_CITATION_INTEGRITY = 1.0
MIN_MAPPING_ACCURACY = 0.90


def main() -> int:
    _, parsed = ingest_fixture()
    gt = load_groundtruth()
    profile = load_profile()
    gold_obs = [g.to_obligation() for g in gt.obligations]

    links = map_obligations(gold_obs, profile)
    mapping_acc = score_mapping(links, gt)
    pred_gaps = {l.obligation_id for l in links if l.is_gap}

    report = EvalReport(
        extraction=score_extraction(gold_obs, gt),
        citation_integrity=score_citation_integrity(gold_obs, parsed),
        gap_detection=score_gap_detection(pred_gaps, gt),
    )
    print(f"extraction F1      : {report.extraction.f1:.3f}  (min {MIN_F1})")
    print(f"citation integrity : {report.citation_integrity:.3f}  (min {MIN_CITATION_INTEGRITY})")
    print(f"mapping accuracy   : {mapping_acc:.3f}  (min {MIN_MAPPING_ACCURACY})")
    print(f"gap detection F1   : {report.gap_detection.f1:.3f}")

    passes = (
        report.passes(min_f1=MIN_F1, min_citation_integrity=MIN_CITATION_INTEGRITY)
        and mapping_acc >= MIN_MAPPING_ACCURACY
    )
    if passes:
        print("EVAL GATE: PASS")
        return 0
    print("EVAL GATE: FAIL — regression blocked")
    return 1


if __name__ == "__main__":
    sys.exit(main())
