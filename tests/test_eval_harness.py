"""The harness must report perfect scores when 'predictions' equal the oracle,
and degrade correctly when they don't. This is what gates CI (Part 11.8)."""
from regradar.eval.harness import (
    EvalReport,
    score_citation_integrity,
    score_extraction,
    score_gap_detection,
)


def test_perfect_extraction_when_predictions_match_oracle(groundtruth):
    predicted = [g.to_obligation() for g in groundtruth.obligations]
    prf = score_extraction(predicted, groundtruth)
    assert prf.precision == 1.0 and prf.recall == 1.0 and prf.f1 == 1.0


def test_extraction_penalises_misses_and_hallucinations(groundtruth):
    preds = [g.to_obligation() for g in groundtruth.obligations[:8]]  # 3 misses
    # add a hallucinated obligation citing a non-existent article
    extra = groundtruth.obligations[0].to_obligation()
    extra.citation.article_ref = "Article 404"
    preds.append(extra)
    prf = score_extraction(preds, groundtruth)
    assert prf.tp == 8 and prf.fp == 1 and prf.fn == 3


def test_gap_detection_perfect(groundtruth):
    prf = score_gap_detection(groundtruth.gap_ids, groundtruth)
    assert prf.f1 == 1.0


def test_gap_detection_penalises_wrong_gaps(groundtruth):
    wrong = {"GT-DORA-005-1"}  # not actually a gap
    prf = score_gap_detection(wrong, groundtruth)
    assert prf.tp == 0 and prf.fp == 1 and prf.fn == 3


def test_eval_report_gate(groundtruth, parsed_dora):
    predicted = [g.to_obligation() for g in groundtruth.obligations]
    report = EvalReport(
        extraction=score_extraction(predicted, groundtruth),
        citation_integrity=score_citation_integrity(predicted, parsed_dora),
        gap_detection=score_gap_detection(groundtruth.gap_ids, groundtruth),
    )
    assert report.passes(min_f1=0.80, min_citation_integrity=1.0)
