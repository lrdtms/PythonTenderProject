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
    # Excused trap items are labelling artefacts; a rise in them means more traps turn clear.
    for name, result in report.per_pack.items():
        assert result["exact_spec_on_trap_items"] <= 1, (name, report.render())


def test_quotation_items_are_keyed_by_file_and_sku() -> None:
    from tests.matching_eval import load_pack

    pack = load_pack(PACKS[1])
    assert pack.by_sku and all(isinstance(k, tuple) and len(k) == 2 for k in pack.by_sku)
    files = {name for name, _sku in pack.by_sku}
    assert len(files) == 2  # both quotations, keyed apart
    report = evaluate(PACKS)
    assert report.clear_suggestions == sum(r["clear_suggestions"] for r in report.per_pack.values())
