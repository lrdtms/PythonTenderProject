"""Aggregate repeated runs: mean, min and max per metric (models are not deterministic)."""

from __future__ import annotations

import json
import statistics
from pathlib import Path

from .score import CRITICAL


def load_runs(run_dirs: list[Path]) -> list[dict]:
    return [json.loads((d / "metrics.json").read_text(encoding="utf-8")) for d in run_dirs]


def aggregate(runs: list[dict]) -> dict:
    """metric -> {mean, min, max, n}. Runs where a metric is None (not scored) are skipped."""
    metrics: dict[str, dict] = {}
    for name in runs[0]["overall"]:
        values = [r["overall"][name] for r in runs if r["overall"].get(name) is not None]
        if values:
            metrics[name] = {
                "mean": statistics.mean(values),
                "min": min(values),
                "max": max(values),
                "n": len(values),
            }
    critical = {k: sum(r["critical"].get(k, 0) for r in runs) for k in CRITICAL}
    return {"runs": len(runs), "metrics": metrics, "critical_total": critical}


def render(label: str, agg: dict) -> str:
    lines = [f"{label}: {agg['runs']} runs", f"  {'metric':30} {'mean':>6} {'min':>6} {'max':>6}"]
    for name, m in agg["metrics"].items():
        lines.append(f"  {name:30} {m['mean']:6.0%} {m['min']:6.0%} {m['max']:6.0%}")
    bad = {k: int(v) for k, v in agg["critical_total"].items() if v}
    lines.append(f"  critical errors across runs: {bad or 'none'}")
    return "\n".join(lines)


def compare_aggregates(a_label: str, a: dict, b_label: str, b: dict) -> str:
    header = f"{'metric':30} {a_label[:12]:>12} {b_label[:12]:>12} {'delta':>8}"
    lines = [header + "   (mean of runs; [min-max] in brackets)"]
    for name, ma in a["metrics"].items():
        mb = b["metrics"].get(name)
        if mb is None:
            continue
        delta = (mb["mean"] - ma["mean"]) * 100
        lines.append(
            f"{name:30} {ma['mean']:12.1%} {mb['mean']:12.1%} {delta:+7.1f}pp"
            f"   [{ma['min']:.0%}-{ma['max']:.0%}] vs [{mb['min']:.0%}-{mb['max']:.0%}]"
        )
    return "\n".join(lines)
