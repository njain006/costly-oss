"""Contract tests for the GitLab CI connector.

Pins to GitLab REST v4:
  - GET /api/v4/user (test_connection)
  - GET /api/v4/projects?membership=true (project list)
  - GET /api/v4/projects/{id}/pipelines (per-project pipelines)

Re-record::

    cd backend
    GITLAB_TOKEN=glpat-xxx GITLAB_INSTANCE_URL=https://gitlab.com \
        pytest tests/contract/test_gitlab.py --record-mode=once
"""
from __future__ import annotations

import httpx
import respx
from app.models.platform import CostCategory
from app.services.connectors.gitlab_connector import GitLabConnector

from tests.contract.conftest import load_fixture

CREDS = {"token": "glpat-test-token", "instance_url": "https://gitlab.com"}
BASE = "https://gitlab.com/api/v4"


@respx.mock
def test_fetch_costs_aggregates_pipelines_into_daily_records():
    respx.get(f"{BASE}/projects").mock(
        return_value=httpx.Response(200, json=load_fixture("gitlab", "projects"))
    )
    # Both projects return the same pipeline payload — the connector keys
    # records by project name × date so we still get distinct records.
    respx.get(f"{BASE}/projects/11/pipelines").mock(
        return_value=httpx.Response(200, json=load_fixture("gitlab", "pipelines"))
    )
    respx.get(f"{BASE}/projects/12/pipelines").mock(
        return_value=httpx.Response(200, json=[])
    )

    costs = GitLabConnector(CREDS).fetch_costs(days=7)

    # Project 11 has pipelines on 2 days = 2 records; project 12 has none.
    assert len(costs) == 2
    by_date = {c.date: c for c in costs}
    assert "2026-04-22" in by_date
    assert "2026-04-21" in by_date

    apr22 = by_date["2026-04-22"]
    assert apr22.platform == "gitlab"
    assert apr22.service == "gitlab_ci"
    assert apr22.category == CostCategory.ci_cd
    assert apr22.usage_unit == "minutes"
    assert apr22.metadata["pipelines"] == 2
    # 360s + 240s = 600s = 10 min × $0.008/min = $0.08
    assert abs(apr22.cost_usd - round(10 * 0.008, 4)) < 1e-6


@respx.mock
def test_test_connection_invalid_token():
    respx.get(f"{BASE}/user").mock(
        return_value=httpx.Response(401, json={"message": "401 Unauthorized"})
    )
    result = GitLabConnector(CREDS).test_connection()
    assert result["success"] is False
    assert "401" in result["message"]


@respx.mock
def test_test_connection_success():
    respx.get(f"{BASE}/user").mock(
        return_value=httpx.Response(200, json=load_fixture("gitlab", "user"))
    )
    assert GitLabConnector(CREDS).test_connection()["success"] is True
