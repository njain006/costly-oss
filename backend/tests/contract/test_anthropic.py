"""Contract tests for the Anthropic Admin API connector.

Pins to the Admin API report endpoints:
  - POST /v1/organizations/usage_report/messages — token-tier breakdown
  - POST /v1/organizations/cost_report — authoritative USD per (workspace, description)

Re-record::

    cd backend
    ANTHROPIC_ADMIN_KEY=sk-ant-admin... \
        pytest tests/contract/test_anthropic.py --record-mode=once
"""
from __future__ import annotations

import httpx
import respx
from app.services.connectors.anthropic_connector import AnthropicConnector

from tests.contract.conftest import load_fixture

CREDS = {"api_key": "sk-ant-admin-test-key-123"}
USAGE_URL = "https://api.anthropic.com/v1/organizations/usage_report/messages"
COST_URL = "https://api.anthropic.com/v1/organizations/cost_report"


@respx.mock
def test_fetch_costs_merges_usage_and_cost_reports():
    respx.post(USAGE_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("anthropic", "usage_report_messages"))
    )
    respx.post(COST_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("anthropic", "cost_report"))
    )

    costs = AnthropicConnector(CREDS).fetch_costs(days=7)

    # 2 usage rows + workspace rollup → at least 2 unified records
    assert len(costs) >= 2
    for c in costs:
        assert c.platform == "anthropic"
        assert c.usage_unit == "tokens"
        # cost should be non-negative
        assert c.cost_usd >= 0

    # Find the sonnet record and verify its token metadata is populated
    sonnet_records = [c for c in costs if "sonnet" in c.metadata.get("model", "")]
    assert sonnet_records, "expected at least one sonnet usage record"
    s = sonnet_records[0]
    assert s.metadata["uncached_input_tokens"] == 50000
    assert s.metadata["cache_read_input_tokens"] == 200000
    assert s.metadata["output_tokens"] == 12000


@respx.mock
def test_test_connection_rejects_non_admin_key():
    """Negative path: connector flags non-admin key prefix before any HTTP call."""
    result = AnthropicConnector({"api_key": "sk-ant-api03-not-admin"}).test_connection()
    assert result["success"] is False
    assert "Admin" in result["message"]


@respx.mock
def test_test_connection_401_authentication_error():
    respx.post(USAGE_URL).mock(
        return_value=httpx.Response(401, json=load_fixture("anthropic", "auth_error"))
    )
    result = AnthropicConnector(CREDS).test_connection()
    assert result["success"] is False
    assert "401" in result["message"]


@respx.mock
def test_test_connection_429_rate_limited():
    respx.post(USAGE_URL).mock(return_value=httpx.Response(429, text="rate limit"))
    result = AnthropicConnector(CREDS).test_connection()
    assert result["success"] is False
    assert "429" in result["message"] or "Rate limited" in result["message"]
