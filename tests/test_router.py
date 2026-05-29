"""Router tests run with no network: an empty provider chain falls to the mock
floor, proving the system never hard-fails on missing providers (Part 11.4)."""
import pytest
from pydantic import BaseModel

from regradar.models.router import (
    Router,
    SchemaRepairFailed,
    _extract_json,
    prompt_hash,
)


class Toy(BaseModel):
    name: str
    count: int


def test_mock_floor_when_no_providers():
    r = Router(chain=())
    assert r.active_providers == ["mock"]
    res = r.complete("hello")
    assert res.is_mock and res.provider == "mock"


def test_structured_repair_failure_routes_up():
    # Mock floor returns non-conforming JSON; repair retries exhaust -> raise.
    r = Router(chain=())
    with pytest.raises(SchemaRepairFailed):
        r.call_structured("give me a Toy", Toy, max_repair=1)


def test_extract_json_handles_code_fences():
    assert _extract_json('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert _extract_json('here you go: {"a": 1} thanks') == '{"a": 1}'


def test_prompt_hash_is_stable():
    assert prompt_hash("x") == prompt_hash("x")
    assert prompt_hash("x") != prompt_hash("y")
