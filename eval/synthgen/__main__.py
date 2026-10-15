"""CLI: python -m synthgen generate|verify [--out DIR] [--seed N] [--only pack01 ...]"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .packs import build_all
from .verify import verify_all


def summary(root: Path) -> str:
    packs = [
        json.loads((p / "ground_truth.json").read_text(encoding="utf-8"))
        for p in sorted(root.iterdir())
        if (p / "ground_truth.json").exists()
    ]
    lines = [
        f"{'pack':8} {'tags':42} {'docs':>4} {'req':>4} {'boq':>4} {'quotes':>6} {'q-items':>7}"
    ]
    for g in packs:
        lines.append(
            f"{g['pack_id']:8} {','.join(g['tags']):42} {len(g['documents']):4} "
            f"{len(g['requirements']):4} {len(g['boq_items']):4} {len(g['quotations']):6} "
            f"{sum(len(q['items']) for q in g['quotations']):7}"
        )
    docs = sum(len(g["documents"]) for g in packs)
    reqs = sum(len(g["requirements"]) for g in packs)
    boq = sum(len(g["boq_items"]) for g in packs)
    quotes = sum(len(g["quotations"]) for g in packs)
    q_items = sum(len(q["items"]) for g in packs for q in g["quotations"])
    lines.append(f"{'TOTAL':8} {'':42} {docs:4} {reqs:4} {boq:4} {quotes:6} {q_items:7}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(prog="synthgen")
    ap.add_argument("command", choices=["generate", "verify"], nargs="?", default="generate")
    ap.add_argument("--out", default="generated", type=Path)
    ap.add_argument("--seed", default=42, type=int)
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--stress", action="store_true", help="also build the ~100-page stress pack")
    args = ap.parse_args()

    if args.command == "generate":
        build_all(args.out, args.seed, args.only, args.stress)
        print(summary(args.out))
    results = verify_all(args.out)
    bad = {k: v for k, v in results.items() if v}
    for name, failures in bad.items():
        print(f"VERIFY FAILED {name}:", *failures[:5], sep="\n  ")
    print(f"verified {len(results)} packs, {len(bad)} with problems")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
