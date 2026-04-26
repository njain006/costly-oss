"""Contract tests for the Omni Analytics connector.

Pins to Omni REST v0:
  - GET /api/v0/users
  - GET /api/v0/queries
  - GET /api/v0/connections (test_connection)

Re-record::

    cd backend
    OMNI_API_KEY=xxx OMNI_INSTANCE_URL=https://your.omni.co \
        pytest tests/contract/test_omni.py --record-mode=once
"""
from __future__ import annotations

import httpx
import respx
from app.models.platform import CostCategory
from app.services.connectors.omni_connector import OmniConnector

from tests.contract.conftest import load_fixture

CREDS = {"api_key": "omni_key", "instance_url": "https://test.omni.co"}
BASE = "https://test.omni.co/api/v0"


@respx.mock
def test_fetch_costs_returns_daily_seat_records():
    respx.get(f"{BASE}/users").mock(
        return_value=httpx.Response(200, json=load_fixture("omni", "users"))
    )
    respx.get(f"{BASE}/queries").mock(
        return_value=httpx.Response(200, json=load_fixture("omni", "queries"))
    )

    costs = OmniConnector(CREDS).fetch_costs(days=7)

    # 7 daily records (one per day in the days window)
    assert len(costs) == 7
    for c in costs:
        assert c.platform == "omni"
        assert c.service == "omni"
        assert c.category == CostCategory.serving
        # 5 users × $50/mo / 30 days ≈ $8.33/day
        assert abs(c.cost_usd - round(5 * 50.0 / 30, 2)) < 0.01
        assert c.metadata["user_count"] == 5


@respx.mock
def test_test_connection_unauthorized():
    respx.get(f"{BASE}/connections").mock(
        return_value=httpx.Response(403, text="forbidden")
    )
    result = OmniConnector(CREDS).test_connection()
    assert result["success"] is False
    assert "403" in result["message"]
