"""Score the real stack on the synthetic packs (manual; needs Docker stack + host Ollama).

    uv run --project backend python scripts/score_slice3.py \
        --base http://127.0.0.1:8080 --gen eval/generated --packs pack01 pack02 --out preds_slice3
    cd eval && uv run python -m harness score --gen generated --pred ../preds_slice3 --label slice3

Uploads each pack's documents through the API, waits for the extract jobs, reads the GET endpoints
and writes harness-format predictions (one file per pack). Quotations are not extracted in
Slice 3, so packs are scored on requirements and BoQ only.
"""

from __future__ import annotations

import argparse
import json
import time
import uuid
from pathlib import Path

import httpx

CSRF = {"X-Requested-With": "IntelTPS"}
TERMINAL = {"succeeded", "succeeded_with_warnings", "failed", "cancelled"}


def login(client: httpx.Client, email: str | None) -> None:
    """Register a fresh account, or with --email log in (registering it first if unknown).

    Registration is limited to 5 per hour per IP, so reuse one --email across runs.
    """
    password = "correct-horse-battery"  # noqa: S105 (throwaway scoring account)
    if email:
        r = client.post(
            "/api/v1/auth/login", json={"email": email, "password": password}, headers=CSRF
        )
        if r.status_code == 200:
            return
    email = email or f"score-{uuid.uuid4().hex[:8]}@example.com"
    body = {
        "organisation_name": "Scoring Org", "name": "Scorer", "email": email,
        "password": password,
    }  # fmt: skip
    r = client.post("/api/v1/auth/register", json=body, headers=CSRF)
    r.raise_for_status()  # the session cookie is kept by the client (COOKIE_SECURE=false on http)


def wait(client: httpx.Client, version_id: str, timeout_s: int) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        status = client.get(f"/api/v1/document-versions/{version_id}/extraction").json()
        jobs = [k["job"] for k in status["kinds"] if k["job"]]
        # Ingest enqueues every extraction job for the document's kind in one transaction
        # (a BoQ workbook gets only extract_boq), so any job present means all are present.
        if jobs and all(j["status"] in TERMINAL for j in jobs):
            return status
        time.sleep(3)
    raise SystemExit(f"timed out waiting for {version_id}")


def score_pack(client: httpx.Client, gen: Path, pack: str, timeout_s: int) -> dict:
    gt = json.loads((gen / pack / "ground_truth.json").read_text(encoding="utf-8"))
    tender = client.post("/api/v1/tenders", json={"title": f"{pack} scoring"}, headers=CSRF).json()
    prediction: dict = {
        "pack_id": pack,
        "metadata": {"model": "qwen3:4b", "prompt_version": "v3", "filter_version": "pf-1"},
        "requirements": [],
        "boq_items": [],
        "run_info": [],  # extra key, ignored by the harness: per-document run status and warnings
    }
    for doc in gt["documents"]:
        if doc["kind"] == "quotation":
            continue
        path = gen / pack / doc["filename"]
        r = client.post(
            f"/api/v1/tenders/{tender['id']}/documents",
            files={"file": (doc["filename"], path.read_bytes(), "application/octet-stream")},
            data={"kind": doc["kind"]},
            headers=CSRF,
        )
        r.raise_for_status()
        version_id = r.json()["version"]["id"]
        doc_started = time.time()
        # The ingest job must finish first; extraction jobs appear once it has.
        deadline = time.time() + timeout_s
        v = {"processing_status": "pending"}
        while time.time() < deadline:
            versions = client.get(f"/api/v1/documents/{r.json()['document']['id']}/versions")
            v = versions.json()[0]
            if v["processing_status"] in ("ready", "ready_with_warnings", "failed"):
                break
            time.sleep(2)
        info: dict = {"document": doc["filename"], "ingest": v["processing_status"]}
        prediction["run_info"].append(info)
        if v["processing_status"] not in ("ready", "ready_with_warnings"):
            continue
        status = wait(client, version_id, timeout_s)
        info["seconds"] = round(time.time() - doc_started)
        info["runs"] = [
            {
                "kind": k["kind"],
                "job_status": k["job"]["status"] if k["job"] else None,
                "error_code": k["job"].get("error_code") if k["job"] else None,
                "run_status": k["run"]["status"] if k["run"] else None,
                "warnings": k["run"]["warnings"] if k["run"] else [],
                "counts": k["run"]["counts"] if k["run"] else {},
            }
            for k in status["kinds"]
        ]
        base = f"/api/v1/document-versions/{version_id}"
        for q in client.get(f"{base}/requirements", params={"limit": 1000}).json():
            prediction["requirements"].append({
                "description": q["description"], "requirement_type": q["requirement_type"],
                "mandatory_status": q["mandatory_status"], "evidence_quote": q["evidence_quote"],
                "document": doc["filename"], "page": q["page_number"],
            })  # fmt: skip
        for b in client.get(f"{base}/boq-items", params={"limit": 1000}).json():
            prediction["boq_items"].append({
                "item_number": b["item_no"], "description": b["description"], "unit": b["unit"],
                "quantity": b["quantity"], "unit_price": b["rate"], "document": doc["filename"],
                "page": b["page_number"], "sheet": b["sheet"], "cell_range": b["cell_range"],
            })  # fmt: skip
    return prediction


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8080")
    ap.add_argument("--gen", default="eval/generated")
    ap.add_argument("--packs", nargs="+", required=True)
    ap.add_argument("--out", default="preds_slice3")
    ap.add_argument("--email", help="reuse this account (log in, or register once)")
    ap.add_argument("--timeout", type=int, default=1800)
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with httpx.Client(base_url=args.base, timeout=60) as client:
        login(client, args.email)
        for pack in args.packs:
            started = time.time()
            prediction = score_pack(client, Path(args.gen), pack, args.timeout)
            (out / f"{pack}.json").write_text(json.dumps(prediction, indent=2), encoding="utf-8")
            n_req, n_boq = len(prediction["requirements"]), len(prediction["boq_items"])
            print(
                f"{pack}: {n_req} requirements, {n_boq} BoQ items in {time.time() - started:.0f}s"
            )


if __name__ == "__main__":
    main()
