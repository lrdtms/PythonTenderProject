"""Every number and word list the matcher uses, in one place (tuned in Task 2)."""

from __future__ import annotations

from dataclasses import dataclass

ALIASES: dict[str, str] = {
    "mcb": "miniature circuit breaker",
    "mccb": "moulded case circuit breaker",
    "db": "distribution board",
    "rcd": "residual current device",
    "elcb": "earth leakage circuit breaker",
    "pvc": "pvc",
    "cct": "circuit",
}
STOPWORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "and",
        "for",
        "with",
        "the",
        "of",
        "to",
        "in",
        "on",
        "or",
        "incl",
        "including",
        "supply",
        "install",
        "installation",
    }
)

# The values of extraction's UNIT_CANON: the only unit strings the evidence may carry.
CANONICAL_UNITS: frozenset[str] = frozenset(
    {"m", "no", "item", "sum", "m2", "m3", "roll", "kg", "hr", "day", "set", "pair"}
)


@dataclass(frozen=True)
class MatchConfig:
    w_spec: float = 0.5
    w_text: float = 0.4
    w_unit: float = 0.1
    no_spec_factor: float = 0.9  # applied when neither description carries spec tokens
    code_bonus: float = 0.1
    conflict_penalty: float = 0.25
    suggest_min: float = 0.70
    ambiguous_min: float = 0.45
    margin: float = 0.08
    clear_text_min: float = 0.5  # a clear match needs real word overlap, not just matching specs
    top_n: int = 3


DEFAULT = MatchConfig()
