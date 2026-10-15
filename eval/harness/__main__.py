"""CLI: python -m harness oracle|score|compare ...

python -m harness oracle  --gen generated --out preds_oracle
python -m harness score   --gen generated --pred preds_oracle --label oracle
python -m harness compare eval/runs/<a> eval/runs/<b>
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import pymupdf

from .oracle import oracle_prediction
from .score import CRITICAL, TARGETS, Counts, derive, score_pack
from .textutil import norm

RUNS_DIR = Path(__file__).resolve().parents[1] / "runs"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def tender_text(pack_dir: Path, gt: dict) -> dict[str, str] | None:
    """Normalised text of the native tender PDF, for the verbatim-quote check. None if scanned."""
    tender = next(d for d in gt["documents"] if d["kind"] == "tender_document")
    if tender["scanned"]:
        return None
    with pymupdf.open(pack_dir / tender["filename"]) as doc:
        return {"all": norm(" ".join(page.get_text() for page in doc))}


def run_score(gen: Path, pred_dir: Path, label: str, out_root: Path) -> Path:
    packs, missing = {}, []
    for pack_dir in sorted(p for p in gen.iterdir() if (p / "ground_truth.json").exists()):
        gt = load_json(pack_dir / "ground_truth.json")
        pred_file = pred_dir / f"{gt['pack_id']}.json"
        if not pred_file.exists():
            missing.append(gt["pack_id"])
            continue
        pred = load_json(pred_file)
        counts = score_pack(gt, pred, tender_text(pack_dir, gt))
        packs[gt["pack_id"]] = {
            "counts": counts.values,
            "derived": derive(counts),
            "tags": gt["tags"],
            "metadata": pred.get("metadata", {}),
        }
    if not packs:
        raise SystemExit("no predictions matched any pack")

    total = Counts()
    for p in packs.values():
        total.merge(Counts(dict(p["counts"])))
    overall = derive(total)
    result = {
        "label": label,
        "created": datetime.now().isoformat(timespec="seconds"),
        "metadata": next(iter(packs.values()))["metadata"],
        "packs_scored": sorted(packs),
        "packs_missing_predictions": missing,
        "counts": total.values,
        "overall": overall,
        "critical": {k: total.get(k) for k in CRITICAL},
        "per_pack": packs,
    }
    run_dir = out_root / f"{datetime.now():%Y%m%d-%H%M%S}-{label}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "metrics.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    (run_dir / "report.md").write_text(render_report(result), encoding="utf-8")
    return run_dir


def pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.0%}"


def render_report(r: dict) -> str:
    lines = [
        f"# Evaluation run: {r['label']}",
        "",
        f"Created {r['created']}. Metadata: `{json.dumps(r['metadata'])}`.",
        f"Packs scored: {', '.join(r['packs_scored'])}.",
    ]
    if r["packs_missing_predictions"]:
        lines.append(f"**No predictions for:** {', '.join(r['packs_missing_predictions'])}.")
    lines += [
        "",
        "## Overall (micro-averaged)",
        "",
        "| Metric | Value | PRD target | Status |",
        "|---|---|---|---|",
    ]
    for name, value in r["overall"].items():
        target = TARGETS.get(name)
        status = (
            "" if target is None or value is None else ("pass" if value >= target else "**FAIL**")
        )
        lines.append(f"| {name} | {pct(value)} | {pct(target) if target else ''} | {status} |")
    lines += ["", "## Critical errors (must be 0)", "", "| Counter | Count |", "|---|---|"]
    lines += [f"| {k} | {int(v)} |" for k, v in r["critical"].items()]
    c = r["counts"]
    lines += [
        "",
        "## Requirement outcomes",
        "",
        f"Labelled: {int(c.get('req_gt', 0))}. Predicted: {int(c.get('req_pred', 0))}. "
        f"Correct: {int(c.get('req_tp', 0))}. Duplicates: {int(c.get('req_duplicate', 0))}. "
        f"False positives: {int(c.get('req_fp_other', 0))} other, "
        f"{int(c.get('req_fp_boilerplate', 0))} boilerplate, "
        f"{int(c.get('req_injection_followed', 0))} injection followed.",
    ]
    lines += [
        "",
        "## Per pack",
        "",
        "| Pack | Tags | Req recall | Req precision | Facts | Page | BoQ qty | BoQ unit | Match |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for pid, p in r["per_pack"].items():
        d = p["derived"]
        lines.append(
            f"| {pid} | {','.join(p['tags'])} | {pct(d['requirement_recall'])} | "
            f"{pct(d['requirement_precision'])} | {pct(d['requirement_fact_accuracy'])} | "
            f"{pct(d['citation_page_accuracy'])} | {pct(d['boq_quantity_accuracy'])} | "
            f"{pct(d['boq_unit_accuracy'])} | {pct(d['supplier_match_accuracy'])} |"
        )
    lines += [
        "",
        "Recall counts a requirement as found when the quote overlaps the labelled "
        "sentence or contains its keyword. Fact accuracy additionally requires every "
        "number, time, grade and month in the labelled sentence to appear in the "
        "prediction. Precision counts duplicates against the run.",
    ]
    return "\n".join(lines) + "\n"


def compare(a: Path, b: Path) -> str:
    ra, rb = load_json(a / "metrics.json"), load_json(b / "metrics.json")
    lines = [f"{'metric':32} {ra['label'][:14]:>14} {rb['label'][:14]:>14} {'delta':>8}"]
    for k in ra["overall"]:
        x, y = ra["overall"][k], rb["overall"].get(k)
        delta = "" if x is None or y is None else f"{(y - x) * 100:+.1f}pp"
        lines.append(f"{k:32} {pct(x):>14} {pct(y):>14} {delta:>8}")
    for k in CRITICAL:
        lines.append(f"{k:32} {int(ra['critical'][k]):>14} {int(rb['critical'][k]):>14}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(prog="harness")
    sub = ap.add_subparsers(dest="cmd", required=True)
    o = sub.add_parser("oracle")
    o.add_argument("--gen", type=Path, default=Path("generated"))
    o.add_argument("--out", type=Path, required=True)
    s = sub.add_parser("score")
    s.add_argument("--gen", type=Path, default=Path("generated"))
    s.add_argument("--pred", type=Path, required=True)
    s.add_argument("--label", default="run")
    s.add_argument("--out", type=Path, default=RUNS_DIR)
    c = sub.add_parser("compare")
    c.add_argument("a", type=Path)
    c.add_argument("b", type=Path)
    args = ap.parse_args()

    if args.cmd == "oracle":
        args.out.mkdir(parents=True, exist_ok=True)
        for pack_dir in sorted(p for p in args.gen.iterdir() if (p / "ground_truth.json").exists()):
            gt = load_json(pack_dir / "ground_truth.json")
            (args.out / f"{gt['pack_id']}.json").write_text(
                json.dumps(oracle_prediction(gt), indent=2), encoding="utf-8"
            )
        print(f"wrote oracle predictions to {args.out}")
    elif args.cmd == "score":
        run = run_score(args.gen, args.pred, args.label, args.out)
        print((run / "report.md").read_text(encoding="utf-8"))
        print(f"saved: {run}")
    else:
        print(compare(args.a, args.b))
    return 0


if __name__ == "__main__":
    sys.exit(main())
