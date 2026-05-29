"""Impact mapping: dominant-theme matcher, gap detection, and graded accuracy."""
from regradar.agents.impact.map import map_obligations
from regradar.agents.impact.matcher import best_theme, infer_themes, propose_controls
from regradar.eval.harness import score_gap_detection, score_mapping


def _gold_obls(groundtruth):
    return [g.to_obligation() for g in groundtruth.obligations]


def test_theme_inference(groundtruth):
    by_id = {g.id: g.to_obligation() for g in groundtruth.obligations}
    assert best_theme(by_id["GT-DORA-005-1"]) == "ict-governance"
    assert best_theme(by_id["GT-DORA-017-1"]) == "incident-management"
    assert best_theme(by_id["GT-DORA-019-1"]) == "incident-reporting"
    assert best_theme(by_id["GT-DORA-024-1"]) == "resilience-testing"
    assert best_theme(by_id["GT-DORA-028-1"]) == "third-party-risk"


def test_uncovered_dominant_theme_is_gap(groundtruth, bank_profile):
    by_id = {g.id: g.to_obligation() for g in groundtruth.obligations}
    # Art 24 references the framework but its dominant theme (testing) is uncovered.
    assert propose_controls(by_id["GT-DORA-024-1"], bank_profile) == []
    # Art 19 reporting has no covering control either.
    assert propose_controls(by_id["GT-DORA-019-1"], bank_profile) == []
    # Art 5 governance is covered.
    assert propose_controls(by_id["GT-DORA-005-1"], bank_profile)[0].control.id == "CTL-001"


def test_mapping_accuracy_perfect_on_oracle(groundtruth, bank_profile):
    links = map_obligations(_gold_obls(groundtruth), bank_profile)
    assert score_mapping(links, groundtruth) == 1.0


def test_gap_detection_perfect_on_oracle(groundtruth, bank_profile):
    links = map_obligations(_gold_obls(groundtruth), bank_profile)
    pred_gaps = {l.obligation_id for l in links if l.is_gap}
    assert pred_gaps == groundtruth.gap_ids
    assert score_gap_detection(pred_gaps, groundtruth).f1 == 1.0


def test_status_three_way(groundtruth, bank_profile):
    by_id = {g.id: g.to_obligation() for g in groundtruth.obligations}
    from regradar.agents.impact.map import map_obligation
    from regradar.agents.state import (Citation, ModalForce, Obligation, ObligationType)
    # covered
    assert map_obligation(by_id["GT-DORA-005-1"], bank_profile).status == "covered"
    # gap (themed, uncovered: resilience-testing)
    assert map_obligation(by_id["GT-DORA-024-1"], bank_profile).status == "gap"
    # unmapped (no ICT theme at all — a procedural/definitional statement)
    noise = Obligation(
        id="X", actor="This Regulation", modal_force=ModalForce.SHALL,
        action="lay down uniform requirements and enter into force", obligation_type=ObligationType.GOVERNANCE,
        language="en", citation=Citation(celex="C", article_ref="Article 1", language="en", anchor_quote="x"))
    link = map_obligation(noise, bank_profile)
    assert link.status == "unmapped" and not link.is_gap and link.control_id is None


def test_gap_link_has_owner_but_no_control(groundtruth, bank_profile):
    links = map_obligations(_gold_obls(groundtruth), bank_profile)
    gap = next(l for l in links if l.obligation_id == "GT-DORA-019-1")
    assert gap.is_gap and gap.control_id is None and gap.function
