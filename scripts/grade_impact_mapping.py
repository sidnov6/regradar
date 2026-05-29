"""Phase 3: impact mapping + prioritization, graded against the oracle.

    python scripts/grade_impact_mapping.py

Maps the labeled DORA obligations onto Synthetic Bank AG, grades mapping accuracy
and gap detection, then prints the prioritized action list (deadline/effort/risk).
Deterministic — no LLM tokens spent.
"""
from __future__ import annotations

import sys
from datetime import date

from regradar.agents.impact.map import map_obligations
from regradar.agents.prioritize.score import prioritize
from regradar.data.groundtruth.schema import load_groundtruth
from regradar.eval.harness import score_gap_detection, score_mapping
from regradar.knowledge.profile.schema import load_profile

BAR = "=" * 74


def main() -> int:
    gt = load_groundtruth()
    profile = load_profile()
    obls = [g.to_obligation() for g in gt.obligations]

    print(f"{BAR}\nPhase 3 · Impact mapping + prioritization — {gt.celex}\n{BAR}")
    print(f"synthetic bank: {profile.name}\n")

    links = map_obligations(obls, profile)  # deterministic core
    acc = score_mapping(links, gt)
    pred_gaps = {l.obligation_id for l in links if l.is_gap}
    gprf = score_gap_detection(pred_gaps, gt)

    print(f"mapping accuracy : {acc * 100:.0f}%   (vs labeled control mappings)")
    print(f"gap detection    : P={gprf.precision:.2f} R={gprf.recall:.2f} F1={gprf.f1:.2f}")

    print(f"\n{'obligation':16} {'-> control':12} {'function':24} conf")
    print("-" * 74)
    for l in links:
        tag = "GAP (build)" if l.is_gap else l.control_id
        print(f"{l.obligation_id:16} {tag:12} {l.function:24} {l.confidence:.2f}")

    items = prioritize(obls, links, today=date.today())
    print(f"\nprioritized action list (today={date.today()}, highest first):")
    print("-" * 74)
    for rank, it in enumerate(items, 1):
        flag = "⚠" if (it.deadline_days is not None and it.deadline_days <= 0) else " "
        print(f"{rank:2}. {flag} [{it.priority_score:.3f}] {it.obligation_id:16} {it.rationale}")

    print(f"\n{BAR}\nPhase 3 OK\n{BAR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
