"""Contract tests for the Looker connector.

Pins to Looker API 4.0:
  - POST /login → access_token
  - POST /queries/run/json (system__activity / history)
  - POST /queries/run/json (system__activity / pdt_event_log)
  - GET /users?fields=id&is_disabled=false

Re-record::

    cd backend
    LOOKER_CLIENT_ID=xxx LOOKER_CLIENT_SECRET=yyy LOOKER_INSTANCE_URL=https://...
        pytest tests/contract/test_looker.py --record-mode=once
"""
from __future__ import annotations

import httpx
import respx
from app.models.platform import CostCategory
from app.services.connectors.looker_connector import LookerConnector

from tests.contract.conftest import load_fixture

CREDS = {
    "client_id": "looker_client",
    "client_secret": "looker_secret",
    "instance_url": "https://test.looker.com",
}
BASE = "https://test.looker.com/api/4.0"


def _wire_login_and_data():
    respx.post(f"{BASE}/login").mock(
        return_value=httpx.Response(200, json=load_fixture("looker", "login"))
    )
    # Looker calls _get_query_stats first (history view), then _get_user_count
    # (GET /users), then _get_pdt_builds (pdt_event_log). The two POSTs to
    # /queries/run/json are distinguished by their JSON body — but our test
    # uses side_effect to return them in call order.
    respx.post(f"{BASE}/queries/run/json").mock(
        side_effect=[
            httpx.Response(200, json=load_fixture("looker", "query_stats")),
            httpx.Response(200, json=load_fixture("looker", "pdt_builds")),
        ]
    )
    respx.get(url__startswith=f"{BASE}/users").mock(
        return_value=httpx.Response(200, json=load_fixture("looker", "users"))
    )


@respx.mock
def test_fetch_costs_attributes_license_to_query_volume():
    _wire_login_and_data()

    costs = LookerConnector(CREDS).fetch_costs(days=7)

    # 2 query-stat days + 1 PDT day = 3 records
    assert len(costs) == 3
    by_service = {c.service for c in costs}
    assert "looker" in by_service
    assert "looker_pdt" in by_service

    license_records = [c for c in costs if c.service == "looker"]
    assert all(c.category == CostCategory.serving for c in license_records)
    assert all(c.cost_usd > 0 for c in license_records)
    # 10 users × $125 / 30 days ≈ $41.67/day total — distributed across query days
    total_license = sum(c.cost_usd for c in license_records)
    assert 70 < total_license < 90  # ~10*125/30 * 2 days ≈ 83

    pdt_records = [c for c in costs if c.service == "looker_pdt"]
    assert all(c.category == CostCategory.transformation for c in pdt_records)
    assert all(c.cost_usd == 0 for c in pdt_records)  # compute is on warehouse


@respx.mock
def test_test_connection_failure_on_bad_credentials():
    """Negative path: 401 on /login propagates as failed test_connection."""
    respx.post(f"{BASE}/login").mock(
        return_value=httpx.Response(401, json={"message": "Invalid credentials"})
    )
    result = LookerConnector(CREDS).test_connection()
    assert result["success"] is False


@respx.mock
def test_fetch_costs_empty_when_login_fails():
    """If /login fails the connector swallows the exception and returns []."""
    respx.post(f"{BASE}/login").mock(
        return_value=httpx.Response(403, text="forbidden")
    )
    assert LookerConnector(CREDS).fetch_costs(days=7) == []
