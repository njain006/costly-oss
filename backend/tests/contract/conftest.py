"""Shared helpers for connector contract tests.

Loads JSON fixtures from ``backend/tests/fixtures/<platform>/`` and exposes
``load_fixture`` + ``FIXTURES_DIR`` to the contract test modules. Keeps the
individual test files focused on the vendor's API shape rather than IO.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


def load_fixture(platform: str, name: str) -> Any:
    """Load a JSON fixture from ``tests/fixtures/<platform>/<name>``.

    ``name`` may include or omit the ``.json`` suffix.
    """
    if not name.endswith(".json"):
        name = f"{name}.json"
    path = FIXTURES_DIR / platform / name
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture
def fixture_loader():
    """Return ``load_fixture`` so tests can request it as a fixture."""
    return load_fixture
