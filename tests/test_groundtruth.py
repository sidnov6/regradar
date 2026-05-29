"""The oracle must be self-consistent: every anchor verifies (100% citation
integrity), and every mapping/gap label agrees with the synthetic profile.
If this breaks, every downstream metric is meaningless."""
from regradar.eval.harness import score_citation_integrity


def test_oracle_has_expected_shape(groundtruth):
    assert groundtruth.celex == "32022R2554"
    assert len(groundtruth.obligations) == 11
    assert groundtruth.gap_ids == {"GT-DORA-019-1", "GT-DORA-019-3", "GT-DORA-024-1"}


def test_oracle_citation_integrity_is_100pct(groundtruth, parsed_dora):
    obligations = [g.to_obligation() for g in groundtruth.obligations]
    assert score_citation_integrity(obligations, parsed_dora) == 1.0


def test_oracle_mappings_consistent_with_profile(groundtruth, bank_profile):
    for g in groundtruth.obligations:
        if g.is_gap:
            assert not bank_profile.controls_for_theme(g.expected_theme), (
                f"{g.id} marked gap but theme is covered"
            )
        else:
            ctl = bank_profile.control(g.expected_control_id)
            assert ctl is not None, f"{g.id} -> missing control {g.expected_control_id}"
            assert g.expected_theme in ctl.covers_themes
