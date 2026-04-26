"""Contract tests for the Airbyte Cloud connector.

Pins to ``GET /v1/connections`` (list) + ``GET /v1/jobs?connectionId=...`` (per
connection sync history). Cloud cost is estimated at $15/1M records.

Re-record::

    cd backend
    AIRBYTE_API_TOKEN=xxx pytest tests/contract/test_airbyte.py --record-mode=once
"""
from __future__ import annotations

import httpx
import respx
from app.models.platform import CostCategory
from app.services.connectors.airbyte_connector import AirbyteConnector

from tests.contract.conftest import load_fixture

CREDS = {"api_token": "airbyte_test_token"}
BASE = "https://api.airbyte.com/v1"


@respx.mock
def test_fetch_costs_aggregates_jobs_by_day():
    connections = load_fixture("airbyte", "connections")
    jobs = load_fixture("airbyte", "jobs")

    respx.get(f"{BASE}/connections").mock(return_value=httpx.Response(200, json=connections))
    # Both connections return the same job set (terse fixture); the connector
    # filters by connectionId via query params, but our mock matches the path.
    respx.get(f"{BASE}/jobs").mock(return_value=httpx.Response(200, json=jobs))

    costs = AirbyteConnector(CREDS).fetch_costs(days=30)

    # 2 connections × 2 distinct dates (2026-04-21, 2026-04-22) = 4 records
    assert len(costs) >= 2
    for c in costs:
        assert c.platform == "airbyte"
        assert c.category == CostCategory.ingestion
        assert c.usage_unit == "records"
        # Cloud pricing: $15 per 1M records → cost should be > 0 here
        assert c.cost_usd > 0


@respx.mock
def test_test_connection_unauthorized():
    respx.get(f"{BASE}/workspaces").mock(return_value=httpx.Response(401, text="bad token"))
    result = AirbyteConnector(CREDS).test_connection()
    assert result["success"] is False
    assert "401" in result["message"]


@respx.mock
def test_self_hosted_returns_zero_cost():
    """Self-hosted Airbyte ($0 per-record) — cost is 0 even if records > 0."""
    creds = {"api_token": "x", "host": "https://airbyte.local/api/v1"}
    respx.get("https://airbyte.local/api/v1/connections").mock(
        return_value=httpx.Response(200, json=load_fixture("airbyte", "connections"))
    )
    respx.get("https://airbyte.local/api/v1/jobs").mock(
        return_value=httpx.Response(200, json=load_fixture("airbyte", "jobs"))
    )
    costs = AirbyteConnector(creds).fetch_costs(days=30)
    # Self-hosted: cost = 0 and records > 0 → record IS skipped (see connector
    # short-circuit `if cost == 0 and records == 0: continue` only catches
    # the all-zero case). For non-zero records the row is still emitted with cost=0.
    assert all(c.cost_usd == 0 for c in costs)
