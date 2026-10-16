"""Evaluate the deterministic matcher against a pack's ground truth (offline, no DB)."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from uuid import UUID, uuid5

from app.modules.extraction import public as extraction
from app.modules.knowledge.parsers import parse_document
from app.modules.suppliers import matching
from app.modules.suppliers.matching_config import DEFAULT, MatchConfig

_NS = UUID("6f1f0c2e-3c1b-4b0a-9d5e-0a7a1c5e5b11")
_SKU = re.compile(r"\[(SKU-[\w-]+)\]", re.IGNORECASE)


def is_spec_exact(evidence: dict, text_min: float) -> bool:
    """Every spec kind on both sides agrees, with real word overlap: nothing distinguishes the pair."""
    spec = evidence["spec"]
    return bool(
        spec["matched"]
        and not spec["conflicts"]
        and not spec["multi_value"]
        and not spec["boq_only"]
        and not spec["quote_only"]
        and evidence["signals"]["text"] >= text_min
    )


@dataclass
class Pack:
    name: str
    truth: dict
    boq: list[matching.BoqLine]
    quotes: list[matching.QuoteLine]
    closing: date | None = None
    # lower-cased SKU -> (quote line, ground-truth item)
    by_sku: dict[str, tuple[matching.QuoteLine, dict]] = field(default_factory=dict)


@dataclass
class EvalReport:
    top_accuracy: float
    wrong_clear: int
    unit_mismatch_unflagged: int
    ambiguous_cases_clear: int
    per_pack: dict[str, dict]
    misses: list[str]
    exact_spec_on_trap_items: int = 0
    excused: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # packs with no machine-readable BoQ

    def render(self) -> str:
        cols = ("scored", "top_ok", "accuracy", "wrong_clear", "unit_unflagged", "amb_clear")
        lines = ["pack      " + "  ".join(f"{c:>14}" for c in cols)]
        for name, r in self.per_pack.items():
            lines.append(
                f"{name:<9} "
                + "  ".join(
                    f"{v:>14}"
                    for v in (
                        r["scored"],
                        r["top_ok"],
                        f"{r['accuracy']:.3f}",
                        r["wrong_clear"],
                        r["unit_mismatch_unflagged"],
                        r["ambiguous_cases_clear"],
                    )
                )
            )
        lines.append(
            f"overall: top_accuracy={self.top_accuracy:.3f} wrong_clear={self.wrong_clear} "
            f"unit_mismatch_unflagged={self.unit_mismatch_unflagged} "
            f"ambiguous_cases_clear={self.ambiguous_cases_clear}"
        )
        lines.append(
            f"exact_spec_on_trap_items={self.exact_spec_on_trap_items} (excused from the counts "
            "above: a clear offered for a ground-truth trap item whose text and every spec kind "
            "equal a real BoQ line, so the trap label is an artefact): "
            + (", ".join(self.excused) if self.excused else "none")
        )
        if self.skipped:
            lines.append("skipped (no readable BoQ, e.g. scanned): " + ", ".join(self.skipped))
        lines.append("misses: " + (", ".join(self.misses) if self.misses else "none"))
        return "\n".join(lines)


def _pages(doc: dict, root: Path) -> list[extraction.PageInput]:
    return [
        extraction.PageInput(p.page_number, p.label, p.text, p.text_source, p.status, p.tables)
        for p in parse_document(doc["format"], (root / doc["filename"]).read_bytes())
    ]


def _sku(description: str) -> str | None:
    found = _SKU.search(description)
    return found.group(1).lower() if found else None


def load_pack(pack_dir: Path) -> Pack:
    truth = json.loads((pack_dir / "ground_truth.json").read_text(encoding="utf-8"))
    ns = uuid5(_NS, truth["pack_id"])
    boq: list[matching.BoqLine] = []
    for doc in truth["documents"]:
        if doc["kind"] in ("boq", "tender_document") and not doc["scanned"]:
            for item in extraction.parse_boq(_pages(doc, pack_dir)).items:
                boq.append(
                    matching.BoqLine(
                        uuid5(ns, item.item_no), item.item_no, item.description, item.unit
                    )
                )
    quotes: list[matching.QuoteLine] = []
    by_sku: dict[str, tuple[matching.QuoteLine, dict]] = {}
    for doc in truth["documents"]:
        if doc["kind"] != "quotation":
            continue
        result = extraction.parse_quotation(_pages(doc, pack_dir))
        quote = next(q for q in truth["quotations"] if q["document"] == doc["filename"])
        supplier_id = uuid5(ns, "supplier:" + quote["supplier"])
        quotation_id = uuid5(ns, "quotation:" + doc["filename"])
        truth_by_sku = {_sku(i["description"]): i for i in quote["items"]}
        for n, item in enumerate(result.items):
            line = matching.QuoteLine(
                uuid5(ns, f"quote:{doc['filename']}:{n}"),
                supplier_id,
                quotation_id,
                item.description,
                item.sku,
                item.unit,
                item.unit_price,
                result.header.valid_until,
            )
            quotes.append(line)
            sku = (item.sku or "").lower()
            if sku in truth_by_sku:
                by_sku[sku] = (line, truth_by_sku[sku])
    closing = None
    if truth.get("closing_at"):
        closing = date.fromisoformat(truth["closing_at"][:10])
    return Pack(pack_dir.name, truth, boq, quotes, closing, by_sku)


def _score_pack(pack: Pack, config: MatchConfig) -> tuple[dict, list[str]]:
    suggestions = matching.suggest(pack.boq, pack.quotes, pack.closing, config)
    item_no = {b.id: b.item_no for b in pack.boq}
    by_quote: dict = {}
    for s in suggestions:
        by_quote.setdefault(s.quote_id, []).append(s)
    scored = top_ok = wrong_clear = unit_unflagged = amb_clear = 0
    misses: list[str] = []
    excused_ids: list[str] = []
    for sku, (line, gt) in sorted(pack.by_sku.items()):
        mine = by_quote.get(line.id, [])
        tag = f"{pack.name}/{sku.upper()}"
        expected = gt["expected_match"]
        clear = [s for s in mine if s.classification == "clear"]
        trap = expected is None or gt["ambiguous"]
        excused = [s for s in clear if trap and is_spec_exact(s.evidence, config.clear_text_min)]
        for s in excused:
            excused_ids.append(f"{tag}->{item_no[s.boq_id]}")
        bad = [
            s
            for s in clear
            if s not in excused and (expected is None or item_no[s.boq_id] != expected)
        ]
        if bad:
            wrong_clear += len(bad)
            misses.append(f"{tag} wrong_clear->{','.join(str(item_no[s.boq_id]) for s in bad)}")
        if gt["ambiguous"] and [s for s in clear if s not in excused]:
            amb_clear += 1
            misses.append(f"{tag} ambiguous_offered_clear")
        if gt["unit_mismatch"]:
            right = [s for s in mine if item_no[s.boq_id] == expected]
            ok = bool(right) and all(
                s.classification != "clear" and "unit_mismatch" in s.evidence["warnings"]
                for s in right
            )
            if not ok:
                unit_unflagged += 1
                misses.append(f"{tag} unit_mismatch_unflagged")
        if expected is not None and not gt["ambiguous"]:
            scored += 1
            best = max(mine, key=lambda s: (s.score, -s.rank), default=None)
            if best is not None and item_no[best.boq_id] == expected:
                top_ok += 1
            else:
                got = item_no[best.boq_id] if best else "none"
                misses.append(f"{tag} top_miss expected={expected} got={got}")
    result = {
        "scored": scored,
        "top_ok": top_ok,
        "accuracy": top_ok / scored if scored else 1.0,
        "wrong_clear": wrong_clear,
        "unit_mismatch_unflagged": unit_unflagged,
        "ambiguous_cases_clear": amb_clear,
        "exact_spec_on_trap_items": len(excused_ids),
        "excused": excused_ids,
    }
    return result, misses


def evaluate(packs: Sequence[Path], config: MatchConfig = DEFAULT) -> EvalReport:
    per_pack: dict[str, dict] = {}
    misses: list[str] = []
    skipped: list[str] = []
    for path in packs:
        pack = load_pack(path)
        if not pack.boq:
            skipped.append(path.name)
            continue
        result, pack_misses = _score_pack(pack, config)
        per_pack[path.name] = result
        misses += pack_misses
    scored = sum(r["scored"] for r in per_pack.values())
    top_ok = sum(r["top_ok"] for r in per_pack.values())
    return EvalReport(
        top_accuracy=top_ok / scored if scored else 1.0,
        wrong_clear=sum(r["wrong_clear"] for r in per_pack.values()),
        unit_mismatch_unflagged=sum(r["unit_mismatch_unflagged"] for r in per_pack.values()),
        ambiguous_cases_clear=sum(r["ambiguous_cases_clear"] for r in per_pack.values()),
        per_pack=per_pack,
        misses=misses,
        exact_spec_on_trap_items=sum(r["exact_spec_on_trap_items"] for r in per_pack.values()),
        excused=[e for r in per_pack.values() for e in r["excused"]],
        skipped=skipped,
    )


__all__ = ["EvalReport", "Pack", "evaluate", "load_pack"]
