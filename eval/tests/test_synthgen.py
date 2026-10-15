import json
import shutil
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from synthgen.packs import SPECS, build_all
from synthgen.verify import verify_all, verify_pack

SCHEMA = json.loads(
    (Path(__file__).parents[1] / "schema" / "ground_truth.schema.json").read_text(encoding="utf-8")
)


@pytest.fixture(scope="module")
def generated(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("packs")
    build_all(root, seed=7)
    return root


def _load(root: Path, pack: str) -> dict:
    return json.loads((root / pack / "ground_truth.json").read_text(encoding="utf-8"))


def test_standard_set_size(generated: Path) -> None:
    packs = [_load(generated, p.name) for p in generated.iterdir()]
    assert len(packs) == len(SPECS) == 8
    assert sum(len(p["requirements"]) for p in packs) >= 60  # PRD section 13
    assert sum(len(p["boq_items"]) for p in packs) >= 150
    assert sum(len(p["quotations"]) for p in packs) >= 5
    assert any("scanned" in p["tags"] for p in packs)
    assert any("adversarial" in p["tags"] for p in packs)


def test_ground_truth_matches_schema(generated: Path) -> None:
    validator = Draft202012Validator(SCHEMA)
    for gt in generated.glob("*/ground_truth.json"):
        errors = list(validator.iter_errors(json.loads(gt.read_text(encoding="utf-8"))))
        assert not errors, f"{gt.parent.name}: {errors[0].message}"


def test_files_match_ground_truth(generated: Path) -> None:
    assert all(not failures for failures in verify_all(generated).values())


def test_generation_is_deterministic(tmp_path: Path) -> None:
    build_all(tmp_path / "a", seed=3, only=["pack03"])
    build_all(tmp_path / "b", seed=3, only=["pack03"])
    first = (tmp_path / "a" / "pack03" / "ground_truth.json").read_text(encoding="utf-8")
    second = (tmp_path / "b" / "pack03" / "ground_truth.json").read_text(encoding="utf-8")
    assert first == second


def test_different_seed_changes_content(tmp_path: Path) -> None:
    build_all(tmp_path / "a", seed=1, only=["pack01"])
    build_all(tmp_path / "b", seed=2, only=["pack01"])
    first = (tmp_path / "a" / "pack01" / "ground_truth.json").read_text(encoding="utf-8")
    second = (tmp_path / "b" / "pack01" / "ground_truth.json").read_text(encoding="utf-8")
    assert first != second


def test_verify_detects_tampered_ground_truth(generated: Path, tmp_path: Path) -> None:
    copy = tmp_path / "pack01"
    shutil.copytree(generated / "pack01", copy)
    gt_path = copy / "ground_truth.json"
    gt = json.loads(gt_path.read_text(encoding="utf-8"))
    gt["requirements"][0]["evidence_quote"] = "This sentence is not in the document."
    gt_path.write_text(json.dumps(gt), encoding="utf-8")
    assert verify_pack(copy), "verify should report the tampered quote"


def test_scanned_pack_has_no_text_layer(generated: Path) -> None:
    gt = _load(generated, "pack05")
    tender = next(d for d in gt["documents"] if d["kind"] == "tender_document")
    assert tender["scanned"] is True
    assert verify_pack(generated / "pack05") == []


def test_injection_is_not_a_requirement(generated: Path) -> None:
    gt = _load(generated, "pack08")
    kinds = [n["kind"] for n in gt["non_requirements"]]
    assert kinds.count("prompt_injection") == 1
    assert all(
        "disregard all previous instructions" not in r["evidence_quote"] for r in gt["requirements"]
    )


def test_quotations_include_confusable_items(generated: Path) -> None:
    gt = _load(generated, "pack08")
    items = [i for q in gt["quotations"] for i in q["items"]]
    assert any(
        i["confusable_with"] and i["expected_match"] is None and i["ambiguous"] for i in items
    )
    assert any(i["expected_match"] for i in items)


def test_distractors_are_labelled_and_not_requirements(generated: Path) -> None:
    for pack in ("pack03", "pack07"):
        gt = _load(generated, pack)
        boiler = [n for n in gt["non_requirements"] if n["kind"] == "boilerplate"]
        assert boiler, f"{pack} should contain obligation-worded boilerplate"
        quotes = {r["evidence_quote"] for r in gt["requirements"]}
        assert all(n["text"] not in quotes for n in boiler)
