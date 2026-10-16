"""The matching core: spec tokens, signals, classification, determinism."""

from __future__ import annotations

import random
from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.suppliers import matching as m

SUP_A, SUP_B = uuid4(), uuid4()


def boq(desc: str, unit: str | None = "no", item_no: str = "1") -> m.BoqLine:
    return m.BoqLine(uuid4(), item_no, desc, unit)


def quote(
    desc: str,
    unit: str | None = "no",
    sku: str | None = None,
    price: str = "10.00",
    supplier: UUID = SUP_A,
    valid_until: date | None = None,
) -> m.QuoteLine:
    return m.QuoteLine(uuid4(), supplier, uuid4(), desc, sku, unit, Decimal(price), valid_until)


# --- spec tokens -------------------------------------------------------------------------------


def test_spec_tokens_read_electrical_specifics() -> None:
    t = m.spec_tokens("Main distribution board, 400 A, 3-phase, IP65, 100 W, 1200 mm, 6 kA, 12-way")
    assert t["a"] == {"400"} and t["ka"] == {"6"} and t["w"] == {"100"} and t["mm"] == {"1200"}
    assert t["phase"] == {"3"} and t["ip"] == {"65"} and t["way"] == {"12"}


def test_spec_tokens_cores_and_cross_section_with_unicode_and_spacing() -> None:
    t = m.spec_tokens("3C+E 2.5mm² PVC/PVC copper cable")
    assert t["core"] == {"3c+e"} and t["mm2"] == {"2.5"}
    assert m.spec_tokens("3 c + e 2,5 mm2")["mm2"] == {"2.5"}


def test_spec_tokens_pole_and_empty() -> None:
    assert m.spec_tokens("Miniature circuit breaker, 3-pole, 63 A")["pole"] == {"3"}
    assert m.spec_tokens("Site establishment, offices and storage") == {}


# --- signals and classification ----------------------------------------------------------------


def test_identical_description_is_a_clear_match() -> None:
    line, q = (
        boq("Main distribution board, 400 A, 3-phase, wall mounted"),
        quote("Main distribution board, 400 A, 3-phase, wall mounted, with busbars", sku="SKU-1"),
    )
    [s] = m.suggest([line], [q])
    assert (s.classification, s.rank, s.boq_id, s.quote_id) == ("clear", 1, line.id, q.id)
    assert s.supplier_id == SUP_A and 0 < s.score <= 1
    assert s.evidence["unit"]["state"] == "equal"


def test_spec_conflict_is_never_clear_and_usually_dropped() -> None:
    line = boq("Miniature circuit breaker, 1-pole, 20 A, 6 kA")
    wrong = quote("MCB, 1-pole, 32 A, 6 kA")
    assert all(s.classification != "clear" for s in m.suggest([line], [wrong]))


def test_correct_candidate_beats_the_confusable_one() -> None:
    line = boq("3C+E 1.5 mm2 PVC/PVC copper cable, for conduit installation", unit="m")
    right = quote(
        "3C+E 1.5 mm2 PVC/PVC copper cable, for conduit installation [SKU-4453]",
        unit="m",
        price="36",
    )
    wrong = quote(
        "3C+E 2.5 mm2 PVC/PVC copper cable, for conduit installation [SKU-9]", unit="m", price="31"
    )
    out = m.suggest([line], [wrong, right])
    top = next(s for s in out if s.rank == 1)
    assert top.quote_id == right.id and top.classification == "clear"
    assert all(s.classification != "clear" for s in out if s.quote_id == wrong.id)


def test_unit_mismatch_forces_ambiguous_and_is_flagged() -> None:
    line = boq("3C+E 2.5 mm2 PVC/PVC copper cable", unit="m")
    [s] = m.suggest([line], [quote("3C+E 2.5 mm2 PVC/PVC copper cable", unit="roll")])
    assert s.classification == "ambiguous" and "unit_mismatch" in s.evidence["warnings"]


def test_two_near_identical_candidates_from_one_supplier_are_both_ambiguous() -> None:
    line = boq("LED batten light fitting, 1200 mm, 36 W")
    a = quote("LED batten light fitting, 1200 mm, 36 W [SKU-1]")
    b = quote("LED batten light fitting, 1200 mm, 36 W [SKU-2]")
    out = m.suggest([line], [a, b])
    assert len(out) == 2 and {s.classification for s in out} == {"ambiguous"}


def test_candidates_are_ranked_per_supplier_and_limited_to_top_n() -> None:
    line = boq("Emergency light fitting, 3-hour maintained")
    quotes = [quote(f"Emergency light fitting, 3-hour maintained variant {i}") for i in range(6)]
    out = m.suggest([line], quotes)
    assert len(out) <= m.DEFAULT.top_n and [s.rank for s in out] == sorted(s.rank for s in out)


def test_each_supplier_is_judged_separately() -> None:
    line = boq("Single switched socket, 16 A")
    a = quote("Single switched socket, 16 A", supplier=SUP_A)
    b = quote("Single switched socket, 16 A", supplier=SUP_B)
    out = m.suggest([line], [a, b])
    assert {(s.supplier_id, s.classification) for s in out} == {(SUP_A, "clear"), (SUP_B, "clear")}


def test_unrelated_items_produce_no_suggestion() -> None:
    assert (
        m.suggest(
            [boq("Site establishment, offices and storage", unit="sum")],
            [quote("MCB, 1-pole, 32 A, 6 kA")],
        )
        == []
    )


def test_sku_shared_with_the_boq_line_adds_a_code_signal() -> None:
    line = boq("Isolator switch SKU-777 rated 63 A")
    [s] = m.suggest([line], [quote("Isolator 63 A", sku="SKU-777")])
    assert s.evidence["signals"]["code"] is True


def test_price_and_validity_are_evidence_only() -> None:
    line = boq("Single switched socket, 16 A")
    cheap = quote("Single switched socket, 16 A", price="1.00", valid_until=date(2026, 10, 1))
    dear = quote("Single switched socket, 16 A", price="900.00", valid_until=date(2027, 1, 1))
    [a] = m.suggest([line], [cheap], closing_date=date(2026, 11, 1))
    [b] = m.suggest([line], [dear], closing_date=date(2026, 11, 1))
    assert a.score == b.score
    assert "quote_expires_before_closing" in a.evidence["warnings"]
    assert "quote_expires_before_closing" not in b.evidence["warnings"]
    assert a.evidence["price"]["unit_price"] == "1.00"


def test_missing_price_and_unit_do_not_crash() -> None:
    out = m.suggest(
        [boq("Conduit 20 mm", unit=None)],
        [m.QuoteLine(uuid4(), SUP_A, uuid4(), "Conduit 20 mm", None, None, None, None)],
    )
    assert (
        out
        and out[0].evidence["price"]["unit_price"] is None
        and out[0].evidence["unit"]["state"] == "unknown"
    )


def test_degenerate_inputs() -> None:
    assert m.suggest([], []) == []
    assert m.suggest([boq("Cable")], []) == []
    assert m.suggest([boq("")], [quote("")]) == []
    assert m.suggest([boq("!!! ---")], [quote("!!! ---")]) == []


# --- determinism and properties ----------------------------------------------------------------

WORDS = [
    "cable",
    "socket",
    "mcb",
    "board",
    "light",
    "led",
    "conduit",
    "isolator",
    "16",
    "a",
    "20",
    "32",
    "mm2",
    "2.5",
    "3-pole",
    "1-pole",
]
descs = st.lists(st.sampled_from(WORDS), min_size=1, max_size=8).map(" ".join)


@settings(max_examples=60, deadline=None)
@given(
    st.lists(descs, min_size=1, max_size=4),
    st.lists(descs, min_size=1, max_size=6),
    st.integers(0, 10_000),
)
def test_result_does_not_depend_on_input_order(
    boqs: list[str], quotes: list[str], seed: int
) -> None:
    lines = [m.BoqLine(UUID(int=i + 1), str(i), d, "no") for i, d in enumerate(boqs)]
    qs = [
        m.QuoteLine(UUID(int=100 + i), SUP_A, UUID(int=500), d, None, "no", Decimal("1"), None)
        for i, d in enumerate(quotes)
    ]
    first = m.suggest(lines, qs)
    shuffled_q, shuffled_b = qs[:], lines[:]
    random.Random(seed).shuffle(shuffled_q)  # noqa: S311
    random.Random(seed + 1).shuffle(shuffled_b)  # noqa: S311

    def key(out: list[m.Suggestion]) -> list:
        return sorted(
            (str(s.boq_id), str(s.quote_id), s.score, s.classification, s.rank) for s in out
        )

    assert key(first) == key(m.suggest(shuffled_b, shuffled_q))


@settings(max_examples=60, deadline=None)
@given(
    descs,
    descs,
    st.decimals(min_value=0, max_value=100000, places=2),
    st.decimals(min_value=0, max_value=100000, places=2),
)
def test_price_never_changes_the_score(a: str, b: str, p1: Decimal, p2: Decimal) -> None:
    line = m.BoqLine(UUID(int=1), "1", a, "no")
    q1 = m.QuoteLine(UUID(int=2), SUP_A, UUID(int=9), b, None, "no", p1, None)
    q2 = m.QuoteLine(UUID(int=2), SUP_A, UUID(int=9), b, None, "no", p2, None)
    assert [(s.score, s.classification) for s in m.suggest([line], [q1])] == [
        (s.score, s.classification) for s in m.suggest([line], [q2])
    ]


@settings(max_examples=80, deadline=None)
@given(st.lists(descs, min_size=1, max_size=3), st.lists(descs, min_size=1, max_size=6))
def test_a_spec_conflict_is_never_clear(boqs: list[str], quotes: list[str]) -> None:
    lines = [m.BoqLine(UUID(int=i + 1), str(i), d, "no") for i, d in enumerate(boqs)]
    qs = [
        m.QuoteLine(UUID(int=100 + i), SUP_A, UUID(int=500), d, None, "no", None, None)
        for i, d in enumerate(quotes)
    ]
    for s in m.suggest(lines, qs):
        if "spec_conflict" in s.evidence["warnings"]:
            assert s.classification != "clear"
        assert Decimal(0) <= s.score <= Decimal(1)
