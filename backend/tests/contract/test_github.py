"""Contract tests for the GitHub Actions connector.

Pins to:
  - GET /user (test_connection)
  - GET /orgs/{org}/settings/billing/actions (Enhanced Billing API)

Re-record::

    cd backend
    GITHUB_TOKEN=ghp_xxx GITHUB_ORG=your-org \
        pytest tests/contract/test_github.py --record-mode=once
"""
from __future__ import annotations

import httpx
import respx
from app.models.platform import CostCategory
from app.services.connectors.github_connector import GitHubConnector

from tests.contract.conftest import load_fixture

CREDS = {"token": "ghp_test_token", "org": "test-org"}


@respx.mock
def test_fetch_costs_uses_org_billing_breakdown():
    respx.get("https://api.github.com/orgs/test-org/settings/billing/actions").mock(
        return_value=httpx.Response(200, json=load_fixture("github", "billing_actions"))
    )

    costs = GitHubConnector(CREDS).fetch_costs(days=30)

    # 4 OS lines in the breakdown, all > 0
    assert len(costs) == 4
    by_service = {c.service: c for c in costs}
    assert "github_actions_ubuntu" in by_service
    assert "github_actions_macos" in by_service
    assert "github_actions_windows" in by_service
    for c in costs:
        assert c.platform == "github"
        assert c.category == CostCategory.ci_cd
        assert c.usage_unit == "minutes"
        assert c.cost_usd > 0

    # Linux: 4000 min × $0.008 = $32
    assert abs(by_service["github_actions_ubuntu"].cost_usd - 32.0) < 0.01
    # macOS: 1000 min × $0.08 = $80
    assert abs(by_service["github_actions_macos"].cost_usd - 80.0) < 0.01


@respx.mock
def test_test_connection_success():
    respx.get("https://api.github.com/user").mock(
        return_value=httpx.Response(200, json=load_fixture("github", "user"))
    )
    result = GitHubConnector(CREDS).test_connection()
    assert result["success"] is True


@respx.mock
def test_test_connection_token_invalid():
    respx.get("https://api.github.com/user").mock(
        return_value=httpx.Response(401, json={"message": "Bad credentials"})
    )
    result = GitHubConnector(CREDS).test_connection()
    assert result["success"] is False
    assert "401" in result["message"]


@respx.mock
def test_fetch_costs_falls_back_to_empty_when_billing_404():
    """No org billing access → connector falls back to repo crawl. With no
    repo list it just returns []."""
    respx.get("https://api.github.com/orgs/test-org/settings/billing/actions").mock(
        return_value=httpx.Response(404, json={"message": "Not Found"})
    )
    respx.get("https://api.github.com/orgs/test-org/repos").mock(
        return_value=httpx.Response(200, json=[])
    )
    costs = GitHubConnector(CREDS).fetch_costs(days=30)
    assert costs == []
