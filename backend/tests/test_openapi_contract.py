"""The frontend's generated types come from frontend/openapi.json; it must match the live API."""

from __future__ import annotations

import json

from app.api.export_openapi import TARGET, render


def test_committed_openapi_matches_the_running_api() -> None:
    committed = json.loads(TARGET.read_text(encoding="utf-8"))
    assert committed == json.loads(render()), (
        "frontend/openapi.json is stale. From backend/ run "
        "`uv run python -m app.api.export_openapi`, then `npm run gen:api` in frontend/, "
        "and commit both files."
    )


def test_the_review_routes_are_in_the_contract() -> None:
    paths = json.loads(render())["paths"]
    for path in (
        "/api/v1/me",
        "/api/v1/auth/login",
        "/api/v1/boq-items/{boq_item_id}",
        "/api/v1/requirements/{requirement_id}/confirm",
        "/api/v1/tenders/{tender_id}/requirements",
    ):
        assert path in paths, path
