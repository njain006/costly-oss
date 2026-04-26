"""Contract tests for the Fivetran connector.

Pins the connector to the Fivetran REST v1 list+usage shape:
``GET /v1/groups`` → list of groups, then per-group
``GET /v1/groups/{id}/connectors`` → list of connectors, then
``GET /v1/usage/connectors/{id}`` → daily MAR + cost.

Re-record fixtures::

    cd backend
    FIVETRAN_API_KEY=xxx FIVETRAN_API_SECRET=yyy \
        pytest tests/contract/test_fivetran.py --record-mode=once
"""
from __future__ import annotations

import httpx
import respx
from app.models.platform import CostCategory
from app.services.connectors.fivetran_connector import FivetranConnector

from tests.contract.conftest import load_fixture

CREDS = {"api_key": "fivetran_key", "api_secret": "fivetran_secret"}
BASE = "https://api.fivetran.com/v1"


@respx.mock
def test_fetch_costs_parses_groups_connectors_and_usage():
    groups = load_fixture("fivetran", "groups")
    connectors = load_fixture("fivetran", "connectors")
    usage = load_fixture("fivetran", "usage")

    respx.get(f"{BASE}/groups").mock(return_value=httpx.Response(200, json=groups))
    respx.get(f"{BASE}/groups/group_warehouse/connectors").mock(
        return_value=httpx.Response(200, json=connectors)
    )
    # Both connectors get the same usage payload — keeps fixtures terse.
    respx.get(f"{BASE}/usage/connectors/salesforce_main").mock(
        return_value=httpx.Response(200, json=usage)
    )
    respx.get(f"{BASE}/usage/connectors/stripe_main").mock(
        return_value=httpx.Response(200, json=usage)
    )

    costs = FivetranConnector(CREDS).fetch_costs(days=30)

    # 2 connectors × 2 daily usage rows = 4 cost records
    assert len(costs) == 4
    for c in costs:
        assert c.platform == "fivetran"
        assert c.service.startswith("fivetran_")
        assert c.category == CostCategory.ingestion
        assert c.usage_unit == "rows"
        assert c.cost_usd > 0
        assert c.metadata["monthly_active_rows"] == c.usage_quantity


@respx.mock
def test_test_connection_unauthorized():
    """Negative path: 401 from /groups bubbles into a failed test_connection."""
    respx.get(f"{BASE}/groups").mock(
        return_value=httpx.Response(401, text="Invalid API key")
    )
    result = FivetranConnector(CREDS).test_connection()
    assert result["success"] is False
    assert "401" in result["message"]


@respx.mock
def test_fetch_costs_returns_empty_when_groups_call_fails():
    respx.get(f"{BASE}/groups").mock(return_value=httpx.Response(500))
    assert FivetranConnector(CREDS).fetch_costs(days=30) == []
