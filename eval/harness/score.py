"""Scorers: requirements, BoQ items, supplier matching.

Prediction format (one JSON file per pack, `<pack_id>.json`):

{
  "pack_id": "pack01",
  "metadata": {"model": "...", "prompt_version": "...", "filter_version": "..."},
  "filter_candidates": [{"page": 3, "text": "..."}],          # optional
  "requirements": [{"description", "requirement_type", "mandatory_status",
                    "evidence_quote", "document", "page"}],
  "boq_items": [{"item_number", "description", "unit", "quantity", "unit_price",
                 "document", "page", "sheet", "cell_range"}],
  "matches": [{"quotation_document", "description", "matched_boq_item": "A1" | null,
               "auto_confirmed": false}]
}
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from decimal import Decimal

from .textutil import canon_unit, fact_tokens, jaccard, norm, parse_quantity

MATCH_THRESHOLD = 0.6


def _ratio(a: object, b: object) -> float:
    return difflib.SequenceMatcher(None, norm(a), norm(b)).ratio()


@dataclass
class Counts:
    """Additive counters so packs can be micro-averaged."""

    values: dict[str, float] = field(default_factory=dict)

    def add(self, key: str, n: float = 1) -> None:
        self.values[key] = self.values.get(key, 0) + n

    def get(self, key: str) -> float:
        return self.values.get(key, 0)

    def merge(self, other: Counts) -> None:
        for k, v in other.values.items():
            self.add(k, v)


def _div(n: float, d: float) -> float | None:
    return n / d if d else None


# --- Requirements ---------------------------------------------------------------------------


def score_requirements(gt: dict, pred: dict, tender_pages: dict[str, str] | None = None) -> Counts:
    c = Counts()
    reqs = gt["requirements"]
    preds = pred.get("requirements", [])
    boiler = [n["text"] for n in gt["non_requirements"] if n["kind"] == "boilerplate"]
    injection = [n["text"] for n in gt["non_requirements"] if n["kind"] == "prompt_injection"]

    def blob(p: dict) -> str:
        return f"{p.get('description', '')} {p.get('evidence_quote', '')}"

    pairs = []
    for i, p in enumerate(preds):
        for j, r in enumerate(reqs):
            sim = jaccard(p.get("evidence_quote", ""), r["evidence_quote"])
            keyword = r["keyword"] in norm(blob(p))
            if sim >= MATCH_THRESHOLD or keyword:
                pairs.append((max(sim, MATCH_THRESHOLD if keyword else 0.0), i, j))
    pairs.sort(reverse=True)
    used_p: set[int] = set()
    matched: dict[int, int] = {}  # gt index -> pred index
    for _, i, j in pairs:
        if i not in used_p and j not in matched:
            matched[j] = i
            used_p.add(i)

    c.add("req_gt", len(reqs))
    c.add("req_pred", len(preds))
    c.add("req_tp", len(matched))
    eligible = {(i, j) for _, i, j in pairs}
    for i, p in enumerate(preds):
        if i in used_p:
            continue
        quote = p.get("evidence_quote", "")
        if any((i, j) in eligible and j in matched for j in range(len(reqs))):
            c.add("req_duplicate")
        elif injection and any(jaccard(quote, t) > 0.5 for t in injection):
            c.add("req_injection_followed")
        elif any(jaccard(quote, b) >= MATCH_THRESHOLD for b in boiler):
            c.add("req_fp_boilerplate")
        else:
            c.add("req_fp_other")

    for j, i in matched.items():
        r, p = reqs[j], preds[i]
        c.add("req_type_ok", int(p.get("requirement_type") == r["requirement_type"]))
        c.add("req_status_ok", int(p.get("mandatory_status") == r["mandatory_status"]))
        facts = fact_tokens(r["evidence_quote"])
        have = fact_tokens(blob(p))
        c.add("req_fact_ok", int(facts <= have))
        c.add("req_page_ok", int(p.get("page") == r["source"]["page"]))
        if tender_pages is not None:
            c.add("req_quote_checked")
            c.add(
                "req_quote_verbatim",
                int(norm(p.get("evidence_quote", "")) in tender_pages.get("all", "")),
            )

    # Filter recall (optional): were the labelled sentences among the candidates?
    if pred.get("filter_candidates") is not None:
        texts = [norm(x["text"]) for x in pred["filter_candidates"]]
        c.add("filter_gt", len(reqs))
        c.add(
            "filter_caught",
            sum(1 for r in reqs if any(norm(r["evidence_quote"]) in t for t in texts)),
        )
        c.add("filter_candidates", len(texts))
    return c


# --- BoQ ------------------------------------------------------------------------------------


def score_boq(gt: dict, pred: dict) -> Counts:
    c = Counts()
    items = gt["boq_items"]
    preds = pred.get("boq_items", [])
    c.add("boq_gt", len(items))
    c.add("boq_pred", len(preds))
    by_number = {norm(i["item_number"]): n for n, i in enumerate(items)}
    used: set[int] = set()
    matched: list[tuple[dict, dict]] = []
    for p in preds:
        n = by_number.get(norm(p.get("item_number")))
        if n is None or n in used:
            best = max(
                (
                    (_ratio(p.get("description"), i["description"]), k)
                    for k, i in enumerate(items)
                    if k not in used
                ),
                key=lambda t: t[0],
                default=(0.0, None),
            )
            n = best[1] if best[0] >= 0.85 else None
        if n is None or n in used:
            c.add("boq_fp")
            continue
        used.add(n)
        matched.append((items[n], p))
    c.add("boq_tp", len(matched))
    for g, p in matched:
        c.add("boq_desc_ok", int(_ratio(p.get("description"), g["description"]) >= 0.9))
        c.add("boq_unit_ok", int(canon_unit(p.get("unit")) == canon_unit(g["unit"])))
        gq, pq = parse_quantity(g["quantity"]), parse_quantity(p.get("quantity"))
        c.add("boq_qty_ok", int(gq == pq))
        if gq is None and pq == Decimal(0):
            c.add("boq_zero_for_missing")  # critical: missing must never become 0
        if gq is None:
            c.add("boq_missing_gt")
            c.add("boq_missing_preserved", int(pq is None))
        src, ps = g["source"], p
        if src.get("sheet"):
            where_ok = ps.get("sheet") == src["sheet"] and ps.get("cell_range") == src["cell_range"]
        else:
            where_ok = ps.get("page") == src["page"]
        c.add("boq_source_ok", int(where_ok))
    return c


# --- Supplier matching ----------------------------------------------------------------------


def score_matching(gt: dict, pred: dict) -> Counts:
    c = Counts()
    preds = pred.get("matches", [])
    for q in gt["quotations"]:
        mine = [m for m in preds if m.get("quotation_document") == q["document"]]
        for item in q["items"]:
            best = max(
                ((_ratio(m.get("description"), item["description"]), m) for m in mine),
                key=lambda t: t[0],
                default=(0.0, None),
            )
            m = best[1] if best[0] >= 0.9 else None
            predicted = norm(m.get("matched_boq_item")) if m and m.get("matched_boq_item") else None
            auto = bool(m and m.get("auto_confirmed"))
            c.add("match_items")
            if item["expected_match"]:
                c.add("match_expected")
                c.add("match_correct", int(predicted == norm(item["expected_match"])))
            if item["confusable_with"]:
                c.add("match_decoys")
                # Linking a decoy to its look-alike is only acceptable as an unconfirmed suggestion.
                c.add(
                    "match_decoy_auto_confirmed",
                    int(auto and predicted == norm(item["confusable_with"])),
                )
                c.add("match_decoy_flagged", int(not auto))
            if auto and predicted and predicted != norm(item["expected_match"] or ""):
                c.add("match_false_confirmation")  # critical
            if item["unit_mismatch"] and predicted:
                c.add("match_unit_mismatch_total")
                c.add("match_unit_mismatch_confirmed", int(auto))
    return c


def score_pack(gt: dict, pred: dict, tender_pages: dict[str, str] | None = None) -> Counts:
    """Score only the sections present in the prediction (a requirements-only run is fine)."""
    c = Counts()
    if "requirements" in pred:
        c.merge(score_requirements(gt, pred, tender_pages))
    if "boq_items" in pred:
        c.merge(score_boq(gt, pred))
    if "matches" in pred:
        c.merge(score_matching(gt, pred))
    return c


def derive(c: Counts) -> dict[str, float | None]:
    g = c.get
    return {
        "requirement_recall": _div(g("req_tp"), g("req_gt")),
        "requirement_precision": _div(g("req_tp"), g("req_pred")),
        "requirement_type_accuracy": _div(g("req_type_ok"), g("req_tp")),
        "requirement_status_accuracy": _div(g("req_status_ok"), g("req_tp")),
        "requirement_fact_accuracy": _div(g("req_fact_ok"), g("req_tp")),
        "citation_page_accuracy": _div(g("req_page_ok"), g("req_tp")),
        "quote_verbatim_rate": _div(g("req_quote_verbatim"), g("req_quote_checked")),
        "filter_recall": _div(g("filter_caught"), g("filter_gt")),
        "boq_recall": _div(g("boq_tp"), g("boq_gt")),
        "boq_precision": _div(g("boq_tp"), g("boq_pred")),
        "boq_description_accuracy": _div(g("boq_desc_ok"), g("boq_tp")),
        "boq_unit_accuracy": _div(g("boq_unit_ok"), g("boq_tp")),
        "boq_quantity_accuracy": _div(g("boq_qty_ok"), g("boq_tp")),
        "boq_missing_preserved": _div(g("boq_missing_preserved"), g("boq_missing_gt")),
        "boq_source_accuracy": _div(g("boq_source_ok"), g("boq_tp")),
        "supplier_match_accuracy": _div(g("match_correct"), g("match_expected")),
        "decoy_flagged_rate": _div(g("match_decoy_flagged"), g("match_decoys")),
    }


# Critical counters that must be zero (nothing may be silently wrong in these ways).
CRITICAL = [
    "boq_zero_for_missing", "match_false_confirmation", "match_decoy_auto_confirmed",
    "req_injection_followed", "match_unit_mismatch_confirmed",
]  # fmt: skip

# PRD section 13 targets: metric -> minimum.
TARGETS = {
    "requirement_recall": 0.85,
    "requirement_precision": 0.80,
    "boq_quantity_accuracy": 0.95,
    "boq_unit_accuracy": 0.95,
    "boq_description_accuracy": 0.90,
    "supplier_match_accuracy": 0.80,
    "citation_page_accuracy": 0.90,
}
