from pathlib import Path

import pytest

from regradar.agents.parser.formex import parse_formex
from regradar.data.groundtruth.schema import load_groundtruth
from regradar.knowledge.profile.schema import load_profile

FIXTURE = (
    Path(__file__).resolve().parent.parent
    / "regradar/data/sources/fixtures/dora_32022R2554_en.formex.xml"
)


@pytest.fixture(scope="session")
def dora_formex_bytes() -> bytes:
    return FIXTURE.read_bytes()


@pytest.fixture(scope="session")
def parsed_dora(dora_formex_bytes):
    return parse_formex(
        dora_formex_bytes, celex="32022R2554", language="en", content_hash="testhash"
    )


@pytest.fixture(scope="session")
def groundtruth():
    return load_groundtruth()


@pytest.fixture(scope="session")
def bank_profile():
    return load_profile()
