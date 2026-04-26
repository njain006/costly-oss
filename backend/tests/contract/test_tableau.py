"""Contract tests for the Tableau Server/Cloud connector.

Pins to Tableau REST API 3.22:
  - POST /api/3.22/auth/signin → token + site id
  - GET  /api/3.22/sites/{id}/users?pageSize=1 → totalAvailable for license count
  - GET  /api/3.22/sites/{id}/views?includeUsageStatistics=true
  - GET  /api/3.22/sites/{id}/tasks/extractRefreshes

Re-record::

    cd backend
    TABLEAU_SERVER_URL=... TABLEAU_TOKEN_NAME=... TABLEAU_TOKEN_SECRET=... \
        pytest tests/contract/test_tableau.py --record-mode=once
"""
from __future__ import annotations

import httpx
import respx
from app.models.platform import CostCategory
from app.services.connectors.tableau_connector import TableauConnector

from tests.contract.conftest import load_fixture

CREDS = {
    "server_url": "https://test.tableau.com",
    "token_name": "test_token",
    "token_secret": "test_secret",
    "site_id": "test_site",
}
SITE_BASE = "https://test.tableau.com/api/3.22/sites/site-uuid-1234"


@respx.mock
def test_fetch_costs_emits_daily_license_and_extract_records():
    respx.post("https://test.tableau.com/api/3.22/auth/signin").mock(
        return_value=httpx.Response(200, json=load_fixture("tableau", "signin"))
    )
    respx.get(url__startswith=f"{SITE_BASE}/users").mock(
        return_value=httpx.Response(200, json=load_fixture("tableau", "users"))
    )
    respx.get(url__startswith=f"{SITE_BASE}/views").mock(
        return_value=httpx.Response(200, json=load_fixture("tableau", "views"))
    )
    respx.get(url__startswith=f"{SITE_BASE}/tasks/extractRefreshes").mock(
        return_value=httpx.Response(200, json=load_fixture("tableau", "extract_refreshes"))
    )

    costs = TableauConnector(CREDS).fetch_costs(days=7)

    assert any(c.service == "tableau" and c.category == CostCategory.licensing for c in costs)
    assert any(
        c.service == "tableau_extracts" and c.category == CostCategory.serving
        for c in costs
    )

    license_records = [c for c in costs if c.service == "tableau"]
    # 7 daily license records (one per day in the days window)
    assert len(license_records) == 7
    # 25 users × $35/mo / 30 days = $29.17/day
    for c in license_records:
        assert abs(c.cost_usd - round(25 * 35.0 / 30, 2)) < 0.01
        assert c.usage_quantity == 25
        assert c.usage_unit == "users"


@respx.mock
def test_test_connection_signin_failure():
    respx.post("https://test.tableau.com/api/3.22/auth/signin").mock(
        return_value=httpx.Response(401, json={"error": {"code": "401001"}})
    )
    result = TableauConnector(CREDS).test_connection()
    assert result["success"] is False
