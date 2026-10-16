"""Matching accuracy on the committed packs (PRD target: >= 80% correct, ambiguous cases flagged)."""

from __future__ import annotations

from pathlib import Path

from tests.matching_eval import evaluate

PACKS = sorted((Path(__file__).parent / "fixtures" / "packs").glob("pack0*"))


def test_matcher_meets_the_prd_targets_on_the_committed_packs() -> None:
    report = evaluate(PACKS)
    assert report.top_accuracy >= 0.85, report.render()
    assert report.wrong_clear == 0, report.render()
    assert report.unit_mismatch_unflagged == 0, report.render()
    assert report.ambiguous_cases_clear == 0, report.render()
