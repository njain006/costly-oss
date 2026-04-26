"""Contract tests for the Monte Carlo data observability connector.

Pins to the GraphQL endpoint at https://api.getmontecarlo.com/graphql.
The connector dispatches three queries:
  1. test_connection: ``{ getUser { email } }``
  2. ``getTablesMonitoredInfo`` (table count)
  3. ``getIncidents`` (incidents in window)

Re-record::

    cd backend
    MC_API_KEY_ID=xxx MC_API_TOKEN=yyy \
        pytest tests/contract/test_monte_carlo.py --record-mode=once
"""
from __future__ import annotations

import httpx
import respx
from app.models.platform import CostCategory
from app.services.connectors.monte_carlo_connector import MonteCarloConnector

from tests.contract.conftest import load_fixture

CREDS = {"api_key_id": "mc_key_id", "api_token": "mc_token"}
URL = "https://api.getmontecarlo.com/graphql"


@respx.mock
def test_fetch_costs_emits_daily_data_quality_records():
    # The GraphQL endpoint receives 3 POSTs in this order:
    # tables_monitored → incidents (test_connection is NOT called by fetch_costs)
    respx.post(URL).mock(
        side_effect=[
            httpx.Response(200, json=load_fixture("monte_carlo", "tables_monitored")),
            httpx.Response(200, json=load_fixture("monte_carlo", "incidents")),
        ]
    )

    costs = MonteCarloConnector(CREDS).fetch_costs(days=7)

    # 7 daily records
    assert len(costs) == 7
    for c in costs:
        assert c.platform == "monte_carlo"
        assert c.category == CostCategory.data_quality
        assert c.usage_unit == "tables"
        assert c.usage_quantity == 150
        # 150 tables × $50 / 30 days = $250/day
        assert abs(c.cost_usd - round(150 * 50.0 / 30, 4)) < 0.01


@respx.mock
def test_test_connection_success():
    respx.post(URL).mock(
        return_value=httpx.Response(200, json=load_fixture("monte_carlo", "get_user"))
    )
    result = MonteCarloConnector(CREDS).test_connection()
    assert result["success"] is True


@respx.mock
def test_test_connection_returns_graphql_error_message():
    """Negative path: GraphQL responds 200 with errors[] for auth failures."""
    respx.post(URL).mock(
        return_value=httpx.Response(200, json=load_fixture("monte_carlo", "auth_error"))
    )
    result = MonteCarloConnector(CREDS).test_connection()
    assert result["success"] is False
    assert "Authentication" in result["message"] or "auth" in result["message"].lower()
