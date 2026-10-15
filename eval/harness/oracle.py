"""Reference predictors used to test the harness itself (and as score ceilings/floors)."""

from __future__ import annotations

import copy
import random


def oracle_prediction(gt: dict) -> dict:
    """A perfect extraction: copies the ground truth. Must score 100% with no critical errors."""
    return {
        "pack_id": gt["pack_id"],
        "metadata": {"model": "oracle", "prompt_version": "-", "filter_version": "-"},
        "requirements": [
            {
                "description": r["description"],
                "requirement_type": r["requirement_type"],
                "mandatory_status": r["mandatory_status"],
                "evidence_quote": r["evidence_quote"],
                "document": r["source"]["document"],
                "page": r["source"]["page"],
            }
            for r in gt["requirements"]
        ],
        "boq_items": [
            {
                "item_number": i["item_number"],
                "description": i["description"],
                "unit": i["unit"],
                "quantity": i["quantity"],
                "unit_price": i["unit_price"],
                "document": i["source"]["document"],
                "page": i["source"].get("page"),
                "sheet": i["source"].get("sheet"),
                "cell_range": i["source"].get("cell_range"),
            }
            for i in gt["boq_items"]
        ],
        "matches": [
            {
                "quotation_document": q["document"],
                "description": it["description"],
                "matched_boq_item": it["expected_match"],
                "auto_confirmed": False,
            }
            for q in gt["quotations"]
            for it in q["items"]
        ],
    }


def empty_prediction(gt: dict) -> dict:
    return {"pack_id": gt["pack_id"], "metadata": {"model": "noop"}, "requirements": [],
            "boq_items": [], "matches": []}  # fmt: skip


def perturb(pred: dict, rng: random.Random) -> dict:
    """A realistic bad run: drops, invents, corrupts and over-confirms. Used by the tests."""
    bad = copy.deepcopy(pred)
    if bad["requirements"]:
        bad["requirements"].pop(0)  # a missed requirement
        bad["requirements"].append(
            {  # an invented one
                "description": "General background about the hall",
                "requirement_type": "other",
                "mandatory_status": "informational",
                "evidence_quote": "The hall is a brick building.",
                "document": "tender.pdf",
                "page": 1,
            }
        )
        bad["requirements"][0]["mandatory_status"] = "informational"  # wrong status
    if bad["boq_items"]:
        bad["boq_items"][0]["quantity"] = "999999"  # wrong quantity
        bad["boq_items"][-1]["unit"] = "kg"  # wrong unit
        bad["boq_items"][1]["quantity"] = "0"  # zero where the source may be missing
    for m in bad["matches"]:
        if m["matched_boq_item"] is None:
            m["matched_boq_item"] = bad["boq_items"][0]["item_number"] if bad["boq_items"] else None
            m["auto_confirmed"] = True  # confirming without evidence
            break
    return bad
