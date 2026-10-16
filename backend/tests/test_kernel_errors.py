"""Error code override and the shared requirement vocabulary."""

from __future__ import annotations

from app.kernel import Conflict, NotFound, vocab
from app.modules.extraction import prompts


def test_a_domain_error_can_override_its_code() -> None:
    assert Conflict("x").code == "conflict"
    err = Conflict("replaced", code="row_replaced")
    assert (err.code, err.message) == ("row_replaced", "replaced")
    assert NotFound().code == "not_found"


def test_the_prompt_schema_uses_the_shared_vocabulary() -> None:
    assert prompts.REQUIREMENT_TYPES == list(vocab.REQUIREMENT_TYPES)
    assert prompts.MANDATORY_STATUSES == list(vocab.MANDATORY_STATUSES)
