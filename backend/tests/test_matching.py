"""The matching core: spec tokens, signals, classification, determinism."""

from __future__ import annotations

import random
from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.suppliers import matching as m
from app.modules.suppliers.matching_config import MatchConfig

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


def test_n_core_is_the_same_core_kind_as_nc_plus_e() -> None:
    for text in ("4-core 1.5 mm2 cable", "4 core 1.5 mm2 cable", "4Core cable"):
        assert m.spec_tokens(text)["core"] == {"4c+e"}
    assert m.spec_tokens("4C+E cable")["core"] == m.spec_tokens("4-core cable")["core"]
    assert m.spec_tokens("multicore cable") == {}


def test_core_count_separates_otherwise_identical_cables() -> None:
    line = boq("4-core 1.5 mm2 PVC insulated copper cable, installed in conduit", unit="m")
    right = quote("4C+E 1.5 mm2 PVC/PVC copper cable, for conduit installation", unit="m")
    wrong = quote("2C+E 1.5 mm2 PVC/PVC copper cable, for conduit installation", unit="m")
    out = m.suggest([line], [wrong, right])
    top = max(out, key=lambda s: s.score)
    assert top.quote_id == right.id
    assert all(s.classification != "clear" for s in out if s.quote_id == wrong.id)


def test_qualifier_words_that_exclude_each_other_conflict() -> None:
    line = boq("Single switched socket outlet, 16 A")
    q = quote("Double switched socket outlet, 16 A")
    assert all(s.classification != "clear" for s in m.suggest([line], [q]))  # usually dropped
    out = m.suggest([line], [q], config=MatchConfig(ambiguous_min=0.0))
    assert out and "spec_conflict" in out[0].evidence["warnings"]
    assert "gang" in out[0].evidence["spec"]["conflicts"]
    [steel] = m.suggest(
        [boq("PVC conduit, 20 mm, surface mounted", unit="m")],
        [quote("Steel conduit, 20 mm, surface mounted", unit="m")],
        config=MatchConfig(ambiguous_min=0.0),
    )
    assert steel.classification == "ambiguous" and "material" in steel.evidence["spec"]["conflicts"]
    [flush] = m.suggest(
        [boq("LED panel, 18 W, recessed")],
        [quote("LED panel, 18 W, surface")],
        config=MatchConfig(ambiguous_min=0.0),
    )
    assert "mounting" in flush.evidence["spec"]["conflicts"]


def test_a_qualifier_on_one_side_only_is_not_a_conflict() -> None:
    line = boq("Conduit, 20 mm, surface mounted", unit="m")
    [s] = m.suggest([line], [quote("PVC conduit, 20 mm, surface mounted", unit="m")])
    assert s.evidence["spec"]["conflicts"] == [] and s.classification == "clear"
    # one side naming two materials still matches when they share one
    [t] = m.suggest(
        [boq("PVC insulated copper cable, 2.5 mm2", unit="m")],
        [quote("Copper cable PVC insulated, 2.5 mm2", unit="m")],
    )
    assert t.evidence["spec"]["conflicts"] == []


def test_a_quote_that_fits_two_boq_lines_equally_is_not_clear_for_either() -> None:
    a = boq("Socket outlet, 16 A", item_no="1")
    b = boq("Socket outlet, 16 A", item_no="2")
    out = m.suggest([a, b], [quote("Socket outlet, 16 A")])
    assert len(out) == 2 and all(s.classification == "ambiguous" for s in out)
    assert all("quote_shared" in s.evidence["warnings"] for s in out)


def test_a_quote_belongs_to_its_better_boq_line_only() -> None:
    better = boq("Single switched socket outlet, 16 A", item_no="1")
    worse = boq("Switched socket outlet, 16 A, with weatherproof cover", item_no="2")
    q = quote("Single switched socket outlet, 16 A")
    out = {s.boq_id: s for s in m.suggest([better, worse], [q])}
    assert out[better.id].classification == "clear"
    assert out[worse.id].classification == "ambiguous"
    assert "quote_shared" in out[worse.id].evidence["warnings"]
    assert "quote_shared" not in out[better.id].evidence["warnings"]


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
    right = quote("MCB, 1-pole, 20 A, 6 kA")
    out = m.suggest([line], [wrong])
    assert out == [] or all(s.classification != "clear" for s in out)
    for s in out:
        assert "spec_conflict" in s.evidence["warnings"]
    both = m.suggest([line], [wrong, right])
    top = next(s for s in both if s.rank == 1)
    assert top.quote_id == right.id and top.classification == "clear"
    assert all(s.classification != "clear" for s in both if s.quote_id == wrong.id)


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


def test_a_rival_that_differs_only_by_unit_still_blocks_a_clear_match() -> None:
    line = boq("3C+E 2.5 mm2 PVC/PVC copper cable", unit="m")
    by_metre = quote("3C+E 2.5 mm2 PVC/PVC copper cable [SKU-1]", unit="m")
    by_roll = quote("3C+E 2.5 mm2 PVC/PVC copper cable [SKU-2]", unit="roll")
    out = m.suggest([line], [by_metre, by_roll])
    assert {s.quote_id for s in out} == {by_metre.id, by_roll.id}
    assert all(s.classification == "ambiguous" for s in out)
    alone = m.suggest([line], [by_metre])
    assert [s.classification for s in alone] == ["clear"]


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
    assert len(out) == m.DEFAULT.top_n and [s.rank for s in out] == [1, 2, 3]


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
    out = m.suggest([line], [cheap, dear], closing_date=date(2026, 11, 1))
    a = next(s for s in out if s.quote_id == cheap.id)
    b = next(s for s in out if s.quote_id == dear.id)
    assert a.score == b.score
    assert "quote_expires_before_closing" in a.evidence["warnings"]
    assert "quote_expires_before_closing" not in b.evidence["warnings"]
    assert a.evidence["price"]["unit_price"] == "1.00"
    assert b.evidence["price"]["unit_price"] == "900.00"


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
        m.QuoteLine(
            UUID(int=100 + i),
            (SUP_A, SUP_B)[i % 2],
            UUID(int=500),
            d,
            None,
            "no",
            Decimal("1"),
            None,
        )
        for i, d in enumerate(quotes)
    ]
    first = m.suggest(lines, qs)
    shuffled_q, shuffled_b = qs[:], lines[:]
    random.Random(seed).shuffle(shuffled_q)  # noqa: S311
    random.Random(seed + 1).shuffle(shuffled_b)  # noqa: S311

    def key(out: list[m.Suggestion]) -> list:
        return sorted(
            (str(s.boq_id), str(s.quote_id), s.score, s.classification, s.rank, repr(s.evidence))
            for s in out
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


# --- review fixes ------------------------------------------------------------------------------


def test_shared_spec_number_alone_is_not_a_code_or_a_clear_match() -> None:
    for a, b in [
        ("Isolator, 63 A", "Contactor, 63 A"),
        ("MCB 400 A", "Busbar 400 A"),
        ("Isolator, 400 A", "Contactor, 400 A"),
    ]:
        out = m.suggest([boq(a)], [quote(b)])
        assert all(s.classification != "clear" for s in out), (a, b)
        assert all(s.evidence["signals"]["code"] is False for s in out), (a, b)


def test_genuine_pair_with_the_same_spec_stays_clear() -> None:
    [s] = m.suggest([boq("Isolator switch, 63 A")], [quote("Isolator switch, 63 A, IP65")])
    assert s.classification == "clear" and s.evidence["signals"]["text"] >= m.DEFAULT.clear_text_min


def test_codes_need_letters_and_digits_or_an_explicit_prefix() -> None:
    assert m._codes("400 A, 1200 mm, 2.5 mm2, 3C+E, 3-pole, IP65") == frozenset()
    assert m._codes("Widget AB12 and SKU-777 part 9") == {"ab12", "777", "9"}


def test_multi_value_quote_is_never_clear() -> None:
    for a, b in [("MCB 20 A", "MCB 20 A 32 A"), ("Cable 1.5 mm2", "Cable 1.5 mm2 2.5 mm2")]:
        out = m.suggest([boq(a)], [quote(b)])
        assert out and all(s.classification != "clear" for s in out), (a, b)
        assert all("spec_multi_value" in s.evidence["warnings"] for s in out)
        assert "spec_conflict" not in out[0].evidence["warnings"]


def test_free_text_never_reaches_the_evidence() -> None:
    line = boq("Conduit 20 mm secret-boq-words", unit="m")
    [s] = m.suggest([line], [quote("Conduit 20 mm secret-quote-words", unit="supplier acme roll")])
    assert s.evidence["unit"] == {"boq": "m", "quote": None, "state": "mismatch"}
    blob = repr(s.evidence)
    assert "acme" not in blob and "secret" not in blob and "Conduit" not in blob


VOCAB = [
    "cable",
    "socket",
    "mcb",
    "board",
    "light",
    "led",
    "conduit",
    "16",
    "a",
    "20",
    "32",
    "mm2",
    "2.5",
    "3-pole",
    "sku-123",
    "ab12",
    "m",
    "mm",
    "1.5",
]


def _reference_all_pairs(line: m._Prepared, index: m._Index) -> list[int]:
    return list(range(index.size))


def test_narrowing_never_drops_a_pair_that_reaches_ambiguous_min(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    rng = random.Random(7)  # noqa: S311

    def desc() -> str:
        return " ".join(rng.choice(VOCAB) for _ in range(rng.randint(1, 6)))

    cases = []
    for _ in range(300):
        lines = [
            m.BoqLine(UUID(int=i + 1), str(i), desc(), rng.choice(["no", "m", None]))
            for i in range(3)
        ]
        qs = [
            m.QuoteLine(
                UUID(int=100 + i),
                SUP_A,
                UUID(int=500),
                desc(),
                rng.choice([None, "SKU-123"]),
                rng.choice(["no", "m", None]),
                None,
                None,
            )
            for i in range(8)
        ]
        cases.append((lines, qs))
    narrowed = [m.suggest(*c) for c in cases]
    monkeypatch.setattr(m, "_candidate_indices", _reference_all_pairs)
    full = [m.suggest(*c) for c in cases]
    assert narrowed == full
    assert any(full)


def test_three_hundred_by_three_hundred_is_fast() -> None:
    import time

    rng = random.Random(3)  # noqa: S311
    words = [f"item{i}" for i in range(60)] + ["cable", "board", "led", "light", "conduit"]
    lines = [
        m.BoqLine(
            UUID(int=i + 1),
            str(i),
            " ".join(rng.sample(words, 5)) + f" {rng.choice([16, 20, 32, 63])} A",
            "no",
        )
        for i in range(300)
    ]
    qs = [
        m.QuoteLine(
            UUID(int=1000 + i),
            SUP_A,
            UUID(int=9),
            " ".join(rng.sample(words, 5)) + f" {rng.choice([16, 20, 32, 63])} A",
            None,
            "no",
            Decimal("1"),
            None,
        )
        for i in range(300)
    ]
    start = time.perf_counter()
    m.suggest(lines, qs)
    assert time.perf_counter() - start < 5


@settings(max_examples=80, deadline=None)
@given(st.lists(descs, min_size=1, max_size=3), st.lists(descs, min_size=1, max_size=6))
def test_a_multi_value_pair_is_never_clear(boqs: list[str], quotes: list[str]) -> None:
    lines = [m.BoqLine(UUID(int=i + 1), str(i), d, "no") for i, d in enumerate(boqs)]
    qs = [
        m.QuoteLine(UUID(int=100 + i), SUP_A, UUID(int=500), d, None, "no", None, None)
        for i, d in enumerate(quotes)
    ]
    for s in m.suggest(lines, qs):
        if "spec_multi_value" in s.evidence["warnings"]:
            assert s.classification != "clear"
