from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from src.sources.navcen import BASE, INDEX_URL

FIXTURES = Path(__file__).parent / "fixtures" / "navcen"
NOW = datetime(2026, 10, 7, 21, 0, tzinfo=UTC)


def load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


def index_fixture() -> dict[str, Any]:
    return load("fileIndexNew.json")


def feature(name: str, uid: int) -> dict[str, Any]:
    return next(f for f in load(f"{name}.geojson")["features"] if f["properties"].get("MSI_UID") == uid)


@pytest.fixture
def navcen():
    """Serve every fixture file; tests may override individual routes."""
    with respx.mock(assert_all_called=False) as router:
        router.get(url__startswith=INDEX_URL).mock(return_value=httpx.Response(200, json=index_fixture()))
        for path in FIXTURES.glob("*.geojson"):
            router.get(BASE + path.name).mock(return_value=httpx.Response(200, content=path.read_bytes()))
        yield router


@pytest.fixture
async def client():
    async with httpx.AsyncClient() as c:
        yield c
