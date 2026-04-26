"""Contract tests for the dbt Cloud connector.

Pins the connector to the dbt Cloud Admin API v2 ``/runs/`` response shape.
The connector groups completed runs (status 10/20/30) by date+job and emits one
``UnifiedCost`` per (date, job_name) bucket, estimating cost from
``run_duration`` seconds at $0.50/compute-hour.

Re-record fixture::

    cd backend
    DBT_CLOUD_API_TOKEN=xxx DBT_CLOUD_ACCOUNT_ID=12345 \
        pytest tests/contract/test_dbt_cloud.py --record-mode=once
"""
from __future__ import annotations

import httpx
import respx
from app.models.platform import CostCategory
from app.services.connectors.dbt_cloud_connector import DbtCloudConnector

from tests.contract.conftest import load_fixture

CREDS = {"api_token": "dbtc_test_token", "account_id": "12345"}
RUNS_URL = "https://cloud.getdbt.com/api/v2/accounts/12345/runs/"


@respx.mock
def test_fetch_costs_parses_runs_into_unified_costs():
    fixture = load_fixture("dbt_cloud", "runs")
    # Connector paginates by setting offset; second call must return empty data
    # so the loop terminates.
    respx.get(RUNS_URL).mock(
        side_effect=[
            httpx.Response(200, json=fixture),
            httpx.Response(200, json={"data": [], "extra": {"pagination": {"total_count": 0}}}),
        ]
    )

    connector = DbtCloudConnector(CREDS)
    costs = connector.fetch_costs(days=7)

    # Three completed runs (status 10/20/30) → grouped into 2 (date, job) keys
    # for the nightly_transform job (success on Apr 22, cancelled on Apr 21)
    # plus 1 for hourly_snapshot (error on Apr 22). Pending status=1 is excluded.
    assert len(costs) == 3
    for c in costs:
        assert c.platform == "dbt_cloud"
        assert c.service == "dbt_cloud"
        assert c.category == CostCategory.transformation
        assert c.usage_unit == "run_minutes"
        assert c.cost_usd >= 0
        # cost = run_duration / 3600 * 0.50; cost is non-negative
        assert c.metadata["cost_is_estimate"] is True

    # Find the successful nightly run on 2026-04-22 — 480s exec → 8min → cost = 8/60*0.50
    by_key = {(c.date, c.resource): c for c in costs}
    nightly_success = by_key[("2026-04-22", "nightly_transform")]
    assert nightly_success.metadata["runs"] == 1
    assert nightly_success.metadata["errors"] == 0
    # 480 / 3600 * 0.50 = 0.0666...
    assert abs(nightly_success.cost_usd - round(480 / 3600 * 0.50, 6)) < 1e-9

    hourly_error = by_key[("2026-04-22", "hourly_snapshot")]
    assert hourly_error.metadata["errors"] == 1


@respx.mock
def test_test_connection_success():
    respx.get("https://cloud.getdbt.com/api/v2/accounts/12345/").mock(
        return_value=httpx.Response(200, json={"data": {"id": 12345, "name": "Acme"}})
    )
    result = DbtCloudConnector(CREDS).test_connection()
    assert result["success"] is True


@respx.mock
def test_test_connection_auth_failure():
    """Negative path: the Admin API returns 401 on a bad token."""
    fixture = load_fixture("dbt_cloud", "auth_error")
    respx.get("https://cloud.getdbt.com/api/v2/accounts/12345/").mock(
        return_value=httpx.Response(401, json=fixture)
    )
    result = DbtCloudConnector(CREDS).test_connection()
    assert result["success"] is False
    assert "401" in result["message"]


@respx.mock
def test_fetch_costs_swallows_500_and_returns_empty():
    """If dbt Cloud returns 500 (rate limit / outage), connector returns []."""
    respx.get(RUNS_URL).mock(return_value=httpx.Response(500, text="upstream error"))
    costs = DbtCloudConnector(CREDS).fetch_costs(days=7)
    assert costs == []
