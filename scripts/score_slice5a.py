"""Score supplier matching on the synthetic packs (offline).

    cd backend && uv run python ../scripts/score_slice5a.py                       # committed packs
    cd backend && uv run python ../scripts/score_slice5a.py --packs ../eval/generated_s43/pack01 ...
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from tests.matching_eval import evaluate  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--packs", nargs="*", type=Path)
    args = parser.parse_args()
    packs = args.packs or sorted((BACKEND / "tests" / "fixtures" / "packs").glob("pack0*"))
    print(evaluate(packs).render())


if __name__ == "__main__":
    main()
