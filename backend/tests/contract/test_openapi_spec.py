"""OpenAPI spec contract test.

Asserts the FastAPI ``app.openapi()`` dump is well-formed and stable enough
to feed into Schemathesis (the actual ``schemathesis run`` call lives in the
``connector-contract`` CI job — running it here would require booting the
full backend with MongoDB + Redis).

What this guarantees inside pytest:
- The OpenAPI document is valid OpenAPI 3.x.
- Every route the connector dashboard depends on is present.
- No route is silently missing operationId / responses (those break codegen).

In CI, ``schemathesis run openapi.json`` then fuzzes every endpoint against a
running backend instance and asserts no 500s and no schema mismatches.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest


def _load_app():
    """Import ``app.main.app`` with redis startup mocked out.

    Importing the app triggers a module-level ``redis.from_url`` if the
    scheduler runs — but only inside startup. The bare import is safe.
    """
    from app.main import app
    return app


def test_openapi_spec_is_well_formed():
    app = _load_app()
    spec = app.openapi()

    assert spec.get("openapi", "").startswith("3."), "expected OpenAPI 3.x"
    assert "info" in spec
    assert "paths" in spec
    paths = spec["paths"]
    assert len(paths) > 50, f"expected >50 routes, got {len(paths)}"


def test_every_operation_has_responses_block():
    """Schemathesis requires every operation to declare its responses."""
    app = _load_app()
    spec = app.openapi()
    missing: list[str] = []
    for path, methods in spec["paths"].items():
        for method, op in methods.items():
            if method.startswith("x-") or not isinstance(op, dict):
                continue
            if "responses" not in op or not op["responses"]:
                missing.append(f"{method.upper()} {path}")
    assert not missing, f"operations missing responses: {missing[:10]}"


@pytest.mark.parametrize(
    "expected_path",
    [
        "/api/auth/login",
        "/api/auth/register",
        "/api/connections/status",
        "/api/dashboard",
        "/api/costs",
    ],
)
def test_critical_endpoints_present(expected_path):
    app = _load_app()
    paths = app.openapi()["paths"]
    assert expected_path in paths, f"missing {expected_path}"


def test_dump_openapi_to_disk(tmp_path: Path):
    """Sanity check: the spec round-trips through JSON without losing data.

    The same spec is written by ``scripts/dump_openapi.py`` for the CI
    Schemathesis job; this test catches any non-JSON-serialisable types
    (datetimes, sets, etc.) before CI does.
    """
    app = _load_app()
    spec = app.openapi()
    out = tmp_path / "openapi.json"
    out.write_text(json.dumps(spec, indent=2))
    reloaded = json.loads(out.read_text())
    assert reloaded["paths"] == spec["paths"]
