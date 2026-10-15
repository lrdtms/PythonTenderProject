"""Build synthetic tender packs (documents + ground truth) from a seed."""

from __future__ import annotations

import math
import random
import re
import shutil
from decimal import Decimal
from pathlib import Path

import pymupdf

from . import catalogue as cat
from .degrade import scan_pdf
from .model import (
    BoqItem,
    Document,
    NonRequirement,
    Pack,
    Quotation,
    QuotationItem,
    Requirement,
    Source,
)
from .render_pdf import render_quotation, render_tender
from .render_xlsx import write_boq, write_quotation
from .verify import check_pdf_quotes, norm

SECTION_ORDER = [
    "Preliminaries and General",
    "Distribution Boards",
    "Containment",
    "Cables",
    "Lighting",
    "Small Power",
    "Earthing and Testing",
]
UNIT_ALIASES = {
    "m": ["Metre", "mtr", "m"],
    "no": ["No.", "Nr", "each", "no"],
    "item": ["Item", "item"],
    "sum": ["Sum", "LS", "sum"],
}

# The standard set of eight packs (PRD section 13). `scan`: tender document is image-only.
SPECS = [
    dict(
        id="pack01",
        style="clean",
        boq="pdf",
        messy=False,
        scan=False,
        filler=60,
        items=18,
        n_req=9,
        quotes=["pdf"],
    ),
    dict(
        id="pack02",
        style="clean",
        boq="xlsx",
        messy=False,
        scan=False,
        filler=72,
        items=20,
        n_req=10,
        quotes=["pdf", "xlsx"],
    ),
    dict(
        id="pack03",
        style="dense",
        boq="pdf",
        messy=True,
        scan=False,
        filler=96,
        items=24,
        n_req=9,
        quotes=["pdf"],
    ),
    dict(
        id="pack04",
        style="dense",
        boq="xlsx",
        messy=True,
        scan=False,
        filler=84,
        items=22,
        n_req=9,
        quotes=["xlsx"],
    ),
    dict(
        id="pack05",
        style="clean",
        boq="pdf",
        messy=False,
        scan=True,
        filler=60,
        items=16,
        n_req=8,
        quotes=["pdf"],
    ),
    dict(
        id="pack06",
        style="dense",
        boq="xlsx",
        messy=True,
        scan=True,
        filler=72,
        items=20,
        n_req=9,
        quotes=["xlsx"],
    ),
    dict(
        id="pack07",
        style="dense",
        boq="pdf",
        messy=True,
        scan=False,
        filler=240,
        items=28,
        n_req=10,
        quotes=["pdf", "xlsx"],
    ),
    dict(
        id="pack08",
        style="clean",
        boq="xlsx",
        messy=False,
        scan=False,
        filler=60,
        items=18,
        n_req=8,
        quotes=["pdf", "xlsx"],
        injection=True,
        decoys=5,
    ),
]

# Optional stress pack (~100 pages, sparse requirements): python -m synthgen generate --stress
STRESS_SPECS = [
    dict(
        id="pack09_xl",
        style="dense",
        boq="pdf",
        messy=True,
        scan=False,
        filler=1050,
        items=44,
        n_req=12,
        quotes=["pdf"],
    ),
]


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _money(value: int | Decimal) -> str:
    return f"{Decimal(value):.2f}"


def _pick_requirements(rng: random.Random, n: int) -> list[cat.Template]:
    always = [t for t in cat.TEMPLATES if t.always]
    others = [t for t in cat.TEMPLATES if not t.always]
    return always + rng.sample(others, k=max(0, n - len(always)))


def _build_boq(rng: random.Random, spec: dict) -> list[dict]:
    pool = cat.all_catalogue()
    chosen = rng.sample(pool, k=spec["items"])
    chosen.sort(key=lambda e: (SECTION_ORDER.index(e[4]), pool.index(e)))
    letters = {s: i + 1 for i, s in enumerate(dict.fromkeys(e[4] for e in chosen))}
    counters: dict[str, int] = {}
    rows: list[dict] = []
    messy = spec["messy"]
    for desc, unit, (qlo, qhi), (plo, phi), section in chosen:
        counters[section] = counters.get(section, 0) + 1
        sec_no = letters[section]
        number = (
            f"{chr(64 + sec_no)}{counters[section]}"
            if not messy
            else f"{sec_no}.{counters[section]}"
        )
        qty = rng.randint(qlo, qhi)
        flags: list[str] = []
        description = desc
        price = rng.randint(plo, phi)
        provisional = description.lower().startswith("provisional sum")
        unit_price = _money(price) if provisional else None
        quantity: str | None = str(qty)
        raw_quantity: str | None = str(qty)
        raw_unit = unit
        if provisional:
            flags.append("provisional_sum")
        if messy:
            roll = rng.random()
            if unit != "sum" and roll < 0.10:
                quantity, raw_quantity = None, None
                flags.append("missing_quantity")
            elif unit != "sum" and roll < 0.18:
                quantity, raw_quantity = None, None
                description += " (rate only)"
                flags.append("rate_only")
            elif qty >= 1000 and roll < 0.60:
                raw_quantity = f"{qty:,}".replace(",", " ")
            elif unit == "m" and roll < 0.75:
                raw_quantity = f"{qty},00" if spec["boq"] == "xlsx" else f"{qty}.00"
            raw_unit = rng.choice(UNIT_ALIASES.get(unit, [unit]))
            if raw_unit != unit:
                flags.append("unit_alias")
        rows.append(
            dict(
                item_number=number,
                section=section,
                description=description,
                unit=unit,
                quantity=quantity,
                raw_unit=raw_unit,
                raw_quantity=raw_quantity,
                unit_price=unit_price,
                unit_price_text=(f"R {price:,}.00".replace(",", " ") if provisional else None),
                flags=flags,
                price=price,
                catalogue_desc=desc,
            )
        )
    return rows


def _quotation_items(rng: random.Random, boq: list[dict], n_decoys: int) -> list[dict]:
    items: list[dict] = []
    have_qty = [r for r in boq if r["quantity"] is not None]
    matched = rng.sample(have_qty, k=max(3, int(len(have_qty) * 0.55)))
    for r in matched:
        unit, qty = r["unit"], int(r["quantity"])
        mismatch = unit == "m" and rng.random() < 0.25
        if mismatch:
            unit, qty = "roll", max(1, math.ceil(qty / 100))
        price = int(r["price"] * rng.uniform(0.85, 1.15)) or r["price"]
        items.append(
            dict(
                description=cat.reword(r["catalogue_desc"], rng),
                unit=unit,
                quantity=str(qty),
                unit_price=_money(price),
                expected_match=r["item_number"],
                confusable_with=None,
                unit_mismatch=mismatch,
                ambiguous=False,
            )
        )
    decoy_pool = [r for r in boq if cat.decoy(r["catalogue_desc"])]
    for r in rng.sample(decoy_pool, k=min(n_decoys, len(decoy_pool))):
        price = int(r["price"] * rng.uniform(0.9, 1.2))
        items.append(
            dict(
                description=cat.reword(cat.decoy(r["catalogue_desc"]) or "", rng),
                unit=r["unit"],
                quantity=r["quantity"] or "1",
                unit_price=_money(price),
                expected_match=None,
                confusable_with=r["item_number"],
                unit_mismatch=False,
                ambiguous=True,
            )
        )
    used = {r["catalogue_desc"] for r in boq}
    extras = [e for e in cat.all_catalogue() if e[0] not in used]
    for desc, unit, (qlo, qhi), (plo, phi), _ in rng.sample(extras, k=2):
        items.append(
            dict(
                description=cat.reword(desc, rng),
                unit=unit,
                quantity=str(rng.randint(qlo, qhi)),
                unit_price=_money(rng.randint(plo, phi)),
                expected_match=None,
                confusable_with=None,
                unit_mismatch=False,
                ambiguous=False,
            )
        )
    rng.shuffle(items)
    for i, it in enumerate(items, start=1):
        it["row"] = i
    return items


def build_pack(spec: dict, index: int, seed: int, out_root: Path) -> Pack:
    pack_id = spec["id"]
    rng = random.Random(f"{seed}-{pack_id}")
    facts = cat.make_facts(rng, index)
    out = out_root / pack_id
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    pack = Pack(
        pack_id=pack_id,
        title=f"Electrical works at {facts['site']}",
        reference=facts["reference"],
        client=facts["client"],
        location=facts["town"],
        closing_at=facts["close_iso"],
        tags=[spec["style"], f"boq-{spec['boq']}", "messy" if spec["messy"] else "clean"]
        + (["scanned"] if spec["scan"] else [])
        + (["adversarial"] if spec.get("injection") else []),
    )

    # Requirements
    reqs: list[dict] = []
    for n, tpl in enumerate(_pick_requirements(rng, spec["n_req"]), start=1):
        sentence, description, keyword = cat.render_template(tpl.key, facts)
        reqs.append(
            dict(
                id=f"{pack_id}-R{n:02d}",
                clause=f"3.{n}",
                sentence=sentence,
                description=description,
                keyword=keyword,
                type=tpl.requirement_type,
                mandatory=tpl.mandatory_status,
            )
        )
    non_reqs = [dict(id=f"{pack_id}-N01", text=cat.INJECTION_TEXT)] if spec.get("injection") else []

    # BoQ
    boq = _build_boq(rng, spec)

    # Tender PDF (native first; scanned copy replaces it afterwards)
    tender_name = "tender.pdf"
    native_path = out / ("_native.pdf" if spec["scan"] else tender_name)
    label_offset = rng.choice([1, 2])
    result = render_tender(
        native_path,
        facts,
        reqs,
        non_reqs,
        boq if spec["boq"] == "pdf" else None,
        rng,
        spec["style"],
        spec["messy"],
        spec["filler"],
        label_offset,
    )

    # Fail early if the ground truth does not match the rendered text.
    failures = check_pdf_quotes(
        native_path, [(r["id"], r["sentence"], result.page_of.get(r["id"])) for r in reqs]
    )
    if failures:
        raise RuntimeError(f"{pack_id}: ground truth mismatch: {failures[:3]}")
    if spec["scan"]:
        scan_pdf(native_path, out / tender_name, rng)
        native_path.unlink()
    pdf_pages = pymupdf.open(out / tender_name).page_count
    pack.documents.append(
        Document(tender_name, "tender_document", "pdf", scanned=spec["scan"], pages=pdf_pages)
    )

    for r in reqs:
        page = result.page_of[r["id"]]
        pack.requirements.append(
            Requirement(
                id=r["id"],
                description=r["description"],
                requirement_type=r["type"],
                mandatory_status=r["mandatory"],
                evidence_quote=r["sentence"],
                keyword=r["keyword"],
                source=Source(tender_name, page=page, printed_page=result.printed(page)),
            )
        )
    for n in non_reqs:
        page = result.page_of[n["id"]]
        pack.non_requirements.append(
            NonRequirement("prompt_injection", n["text"], Source(tender_name, page=page))
        )

    # BoQ document + items
    if spec["boq"] == "xlsx":
        locs = write_boq(
            out / "boq.xlsx", f"Bill of Quantities - {pack.title}", boq, spec["messy"], rng
        )
        pack.documents.append(Document("boq.xlsx", "boq", "xlsx"))
        boq_doc = "boq.xlsx"
    else:
        locs = {}
        boq_doc = tender_name
    for r in boq:
        if spec["boq"] == "xlsx":
            sheet, cell_range = locs[r["item_number"]]
            src = Source(boq_doc, sheet=sheet, cell_range=cell_range)
        else:
            page = result.item_page[r["item_number"]]
            src = Source(boq_doc, page=page, printed_page=result.printed(page))
        pack.boq_items.append(
            BoqItem(
                item_number=r["item_number"],
                section=r["section"],
                description=r["description"],
                unit=r["unit"],
                quantity=r["quantity"],
                unit_price=r["unit_price"],
                raw_unit=r["raw_unit"],
                raw_quantity=r["raw_quantity"],
                flags=r["flags"],
                source=src,
            )
        )

    # Quotations
    for qi, fmt in enumerate(spec["quotes"]):
        supplier = cat.SUPPLIERS[(index + qi) % len(cat.SUPPLIERS)]
        reference = f"Q{rng.randint(10000, 99999)}"
        date, valid_until = (
            f"2026-10-{rng.randint(15, 28):02d}",
            f"2026-11-{rng.randint(10, 28):02d}",
        )
        items = _quotation_items(rng, boq, spec.get("decoys", 2))
        filename = f"quotation_{qi + 1}_{_slug(supplier)}.{fmt}"
        if fmt == "pdf":
            _, row_page = render_quotation(
                out / filename, supplier, reference, date, valid_until, items
            )
            sources = {i["row"]: Source(filename, page=row_page[str(i["row"])]) for i in items}
        else:
            qlocs = write_quotation(out / filename, supplier, reference, date, valid_until, items)
            sources = {
                i["row"]: Source(filename, sheet=qlocs[i["row"]][0], cell_range=qlocs[i["row"]][1])
                for i in items
            }
        pack.documents.append(Document(filename, "quotation", fmt))
        pack.quotations.append(
            Quotation(
                supplier=supplier,
                reference=reference,
                date=date,
                valid_until=valid_until,
                currency="ZAR",
                document=filename,
                items=[
                    QuotationItem(
                        description=i["description"],
                        unit=i["unit"],
                        quantity=i["quantity"],
                        unit_price=i["unit_price"],
                        expected_match=i["expected_match"],
                        confusable_with=i["confusable_with"],
                        unit_mismatch=i["unit_mismatch"],
                        ambiguous=i["ambiguous"],
                        source=sources[i["row"]],
                    )
                    for i in items
                ],
            )
        )

    pack.write(out / "ground_truth.json")
    return pack


def build_all(
    out_root: Path, seed: int = 42, only: list[str] | None = None, stress: bool = False
) -> list[Pack]:
    out_root.mkdir(parents=True, exist_ok=True)
    packs = []
    for index, spec in enumerate(SPECS + (STRESS_SPECS if stress else [])):
        if only and spec["id"] not in only:
            continue
        packs.append(build_pack(spec, index, seed, out_root))
    return packs


__all__ = ["SPECS", "STRESS_SPECS", "build_all", "build_pack", "norm"]
