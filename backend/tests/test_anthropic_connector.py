"""Tests for the Anthropic Admin API connector.

Covers:
- Pricing-prefix resolution (longest prefix wins, per-model overrides, fallback).
- Cache-tier multipliers (read / 5m-creation / 1h-creation).
- Service-tier multipliers (standard / batch / priority).
- Mixed-tier cost accumulation.
- ``pricing_overrides`` — both per-model rates and credit-discount percentage.
- Mocked httpx responses for ``usage_report/messages`` and ``cost_report``.
- Pagination handling over ``next_page`` / ``has_more``.
- Error paths — 401 / 403 / 429 / network errors / regular-key detection.
- UnifiedCost assembly — platform, category, service, metadata keys,
  ``team`` derived from ``workspace_id``, ``resource`` derived from model.
- cost_report authority (overrides estimator) and fallback when absent.
"""

from __future__ import annotations

import math
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.models.platform import CostCategory, PlatformType, UnifiedCost
from app.services.connectors import anthropic_connector as ac
from app.services.connectors.anthropic_connector import (
    CACHE_TIER_MULTIPLIERS,
    MODEL_PRICING,
    SERVICE_TIER_MULTIPLIERS,
    AnthropicConnector,
    TokenUsage,
    UsageBucket,
    _estimate_cost,
    _resolve_pricing,
    estimate_cost,
)


# ---------------------------------------------------------------------------
# Helpers — fake httpx.Response factories
# ---------------------------------------------------------------------------
def _fake_response(status: int, json_body: dict | None = None, text: str = "") -> MagicMock:
    """Build a MagicMock that walks & quacks like an httpx.Response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.text = text or ""
    resp.json = MagicMock(return_value=json_body or {})
    resp.request = MagicMock(spec=httpx.Request)
    return resp


class _Sequencer:
    """Return pre-canned responses in order; fail loudly if calls run out."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[tuple[tuple, dict]] = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if not self._responses:
            raise AssertionError(
                f"httpx.post called more times than expected: args={args} kwargs={kwargs}"
            )
        return self._responses.pop(0)


@pytest.fixture
def admin_credentials():
    return {"api_key": "sk-ant-admin-test-abc-123"}


# ===========================================================================
# Pricing resolution
# ===========================================================================
class TestPricingResolution:

    def test_longest_prefix_wins_opus_4_7(self):
        """claude-opus-4-7 should match the Opus 4.7 row, not claude-opus-4."""
        pricing = _resolve_pricing("claude-opus-4-7-20260101")
        assert pricing == {"input": 15.0, "output": 75.0}

    def test_sonnet_4_6_matches_before_sonnet_4(self):
        pricing = _resolve_pricing("claude-sonnet-4-6-experimental")
        assert pricing == {"input": 3.0, "output": 15.0}

    def test_haiku_4_5(self):
        pricing = _resolve_pricing("claude-haiku-4-5")
        assert pricing == {"input": 1.0, "output": 5.0}

    def test_legacy_haiku_3_5_supported(self):
        pricing = _resolve_pricing("claude-haiku-3-5")
        assert pricing == {"input": 0.80, "output": 4.0}

    def test_legacy_3_5_sonnet_dash_pattern(self):
        pricing = _resolve_pricing("claude-3-5-sonnet-20240620")
        assert pricing == {"input": 3.0, "output": 15.0}

    def test_unknown_model_falls_back_to_sonnet_tier(self):
        pricing = _resolve_pricing("imaginary-model-v42")
        # Fallback defaults to Sonnet-tier input/output.
        assert pricing == {"input": 3.0, "output": 15.0}

    def test_none_model_returns_fallback(self):
        pricing = _resolve_pricing(None)
        assert pricing == {"input": 3.0, "output": 15.0}

    def test_pricing_override_wins_over_catalog(self):
        overrides = {"claude-opus-4-7": {"input": 12.0, "output": 60.0}}
        pricing = _resolve_pricing("claude-opus-4-7", overrides)
        assert pricing == {"input": 12.0, "output": 60.0}

    def test_longest_override_key_wins(self):
        overrides = {
            "claude-opus": {"input": 20.0, "output": 100.0},  # should lose
            "claude-opus-4-7": {"input": 12.0, "output": 60.0},  # should win
        }
        pricing = _resolve_pricing("claude-opus-4-7", overrides)
        assert pricing["input"] == 12.0

    def test_non_dict_override_is_ignored(self):
        """credit_discount_pct at the top level must not override pricing."""
        overrides = {"credit_discount_pct": 10}
        pricing = _resolve_pricing("claude-opus-4-7", overrides)
        # Still list price; discount only applied in estimate_cost.
        assert pricing == {"input": 15.0, "output": 75.0}


# ===========================================================================
# Cost estimation
# ===========================================================================
class TestEstimateCost:

    def test_plain_input_output_sonnet(self):
        tokens = TokenUsage(uncached_input_tokens=1_000_000, output_tokens=1_000_000)
        cost = estimate_cost("claude-sonnet-4-6", tokens)
        # 3 + 15
        assert cost == pytest.approx(18.0)

    def test_back_compat_helper_sonnet(self):
        cost = _estimate_cost("claude-sonnet-4", 1_000_000, 1_000_000)
        assert cost == pytest.approx(18.0)

    def test_back_compat_helper_haiku(self):
        cost = _estimate_cost("claude-haiku-3-5", 1_000_000, 1_000_000)
        assert cost == pytest.approx(4.8)

    def test_cache_read_is_one_tenth_of_input(self):
        tokens = TokenUsage(cache_read_input_tokens=1_000_000)
        cost = estimate_cost("claude-opus-4-7", tokens)
        # 15 / M * 1M * 0.10 = 1.5
        assert cost == pytest.approx(1.5)
        assert CACHE_TIER_MULTIPLIERS["cache_read"] == 0.10

    def test_cache_creation_5m_is_125_percent(self):
        tokens = TokenUsage(cache_creation_5m_input_tokens=1_000_000)
        cost = estimate_cost("claude-opus-4-7", tokens)
        # 15 * 1.25 = 18.75
        assert cost == pytest.approx(18.75)
        assert CACHE_TIER_MULTIPLIERS["cache_creation_5m"] == 1.25

    def test_cache_creation_1h_is_200_percent(self):
        tokens = TokenUsage(cache_creation_1h_input_tokens=1_000_000)
        cost = estimate_cost("claude-opus-4-7", tokens)
        # 15 * 2.00 = 30.0
        assert cost == pytest.approx(30.0)
        assert CACHE_TIER_MULTIPLIERS["cache_creation_1h"] == 2.00

    def test_batch_tier_halves_total(self):
        tokens = TokenUsage(uncached_input_tokens=1_000_000, output_tokens=1_000_000)
        base = estimate_cost("claude-sonnet-4-6", tokens, "standard")
        batch = estimate_cost("claude-sonnet-4-6", tokens, "batch")
        assert batch == pytest.approx(base * 0.5)
        assert SERVICE_TIER_MULTIPLIERS["batch"] == 0.5

    def test_priority_tier_125_percent(self):
        tokens = TokenUsage(uncached_input_tokens=1_000_000, output_tokens=1_000_000)
        priority = estimate_cost("claude-sonnet-4-6", tokens, "priority")
        # 18 * 1.25 = 22.5
        assert priority == pytest.approx(22.5)
        assert SERVICE_TIER_MULTIPLIERS["priority"] == 1.25

    def test_unknown_tier_defaults_to_standard(self):
        tokens = TokenUsage(uncached_input_tokens=1_000_000)
        assert estimate_cost("claude-sonnet-4-6", tokens, "bogus") == estimate_cost(
            "claude-sonnet-4-6", tokens, "standard"
        )

    def test_mixed_tiers_sum_correctly(self):
        # 100k uncached input, 50k cache read, 25k 5m-cache creation,
        # 10k 1h-cache creation, 200k output on Opus 4.7.
        tokens = TokenUsage(
            uncached_input_tokens=100_000,
            cache_read_input_tokens=50_000,
            cache_creation_5m_input_tokens=25_000,
            cache_creation_1h_input_tokens=10_000,
            output_tokens=200_000,
        )
        cost = estimate_cost("claude-opus-4-7", tokens)
        # input_rate = 15/M, output_rate = 75/M
        expected = (
            100_000 * 15 / 1_000_000
            + 50_000 * 15 / 1_000_000 * 0.10
            + 25_000 * 15 / 1_000_000 * 1.25
            + 10_000 * 15 / 1_000_000 * 2.00
            + 200_000 * 75 / 1_000_000
        )
        assert cost == pytest.approx(expected)

    def test_per_model_pricing_override_is_applied(self):
        tokens = TokenUsage(uncached_input_tokens=1_000_000, output_tokens=1_000_000)
        overrides = {"claude-opus-4-7": {"input": 12.0, "output": 60.0}}
        cost = estimate_cost("claude-opus-4-7", tokens, "standard", overrides)
        assert cost == pytest.approx(12.0 + 60.0)

    def test_credit_discount_pct_applied_last(self):
        tokens = TokenUsage(uncached_input_tokens=1_000_000, output_tokens=1_000_000)
        overrides = {"credit_discount_pct": 10}
        cost = estimate_cost("claude-sonnet-4-6", tokens, "standard", overrides)
        # 18 * 0.9 = 16.2
        assert cost == pytest.approx(18.0 * 0.9)

    def test_discount_pct_alias_also_applied(self):
        tokens = TokenUsage(uncached_input_tokens=1_000_000, output_tokens=1_000_000)
        overrides = {"discount_pct": 25}
        cost = estimate_cost("claude-sonnet-4-6", tokens, "standard", overrides)
        assert cost == pytest.approx(18.0 * 0.75)

    def test_invalid_discount_is_ignored(self):
        tokens = TokenUsage(uncached_input_tokens=1_000_000)
        overrides = {"credit_discount_pct": "not-a-number"}
        cost = estimate_cost("claude-sonnet-4-6", tokens, "standard", overrides)
        assert cost == pytest.approx(3.0)

    def test_zero_tokens_zero_cost(self):
        assert estimate_cost("claude-opus-4-7", TokenUsage()) == 0.0


# ===========================================================================
# TokenUsage / UsageBucket dataclasses
# ===========================================================================
class TestTokenUsage:

    def test_totals(self):
        t = TokenUsage(
            uncached_input_tokens=100,
            cache_creation_5m_input_tokens=10,
            cache_creation_1h_input_tokens=5,
            cache_read_input_tokens=20,
            output_tokens=200,
        )
        assert t.total_input_tokens == 135
        assert t.total_tokens == 335

    def test_metadata_serialization_contains_every_field(self):
        t = TokenUsage(
            uncached_input_tokens=1,
            cache_creation_5m_input_tokens=2,
            cache_creation_1h_input_tokens=3,
            cache_read_input_tokens=4,
            output_tokens=5,
            web_search_requests=6,
        )
        md = t.as_metadata()
        assert md == {
            "uncached_input_tokens": 1,
            "cache_creation_5m_input_tokens": 2,
            "cache_creation_1h_input_tokens": 3,
            "cache_read_input_tokens": 4,
            "output_tokens": 5,
            "web_search_requests": 6,
        }

    def test_tokenusage_is_frozen(self):
        t = TokenUsage()
        with pytest.raises(Exception):
            t.output_tokens = 5  # type: ignore[misc]


# ===========================================================================
# Connector: instantiation & test_connection
# ===========================================================================
class TestInstantiation:

    def test_default_base_url_and_platform(self, admin_credentials):
        c = AnthropicConnector(admin_credentials)
        assert c.platform == "anthropic"
        assert c.base_url == "https://api.anthropic.com/v1"
        assert c.pricing_overrides == {}

    def test_custom_base_url(self):
        c = AnthropicConnector(
            {"api_key": "sk-ant-admin-x", "base_url": "https://proxy.example.com/v1/"}
        )
        assert c.base_url == "https://proxy.example.com/v1"

    def test_pricing_overrides_read_from_credentials(self):
        c = AnthropicConnector(
            {
                "api_key": "sk-ant-admin-x",
                "pricing_overrides": {"credit_discount_pct": 5},
            }
        )
        assert c.pricing_overrides == {"credit_discount_pct": 5}


class TestTestConnection:

    def test_regular_key_detected_without_network_call(self):
        c = AnthropicConnector({"api_key": "sk-ant-api03-regular-key"})
        result = c.test_connection()
        assert result["success"] is False
        assert "regular API key" in result["message"]
        assert "Admin" in result["message"]

    def test_success(self, admin_credentials):
        with patch.object(ac.httpx, "post") as mock_post:
            mock_post.return_value = _fake_response(200, {"data": []})
            result = AnthropicConnector(admin_credentials).test_connection()
        assert result == {
            "success": True,
            "message": "Anthropic Admin API connection successful",
        }
        # Verify it hit the correct endpoint.
        args, kwargs = mock_post.call_args
        assert args[0].endswith("/organizations/usage_report/messages")
        assert kwargs["json"]["bucket_width"] == "1d"

    def test_401_invalid(self, admin_credentials):
        with patch.object(ac.httpx, "post") as mock_post:
            mock_post.return_value = _fake_response(401, text="unauthorized")
            result = AnthropicConnector(admin_credentials).test_connection()
        assert result["success"] is False
        assert "Invalid admin key" in result["message"]

    def test_403_missing_scope(self, admin_credentials):
        with patch.object(ac.httpx, "post") as mock_post:
            mock_post.return_value = _fake_response(403, text="forbidden")
            result = AnthropicConnector(admin_credentials).test_connection()
        assert result["success"] is False
        assert "usage_report" in result["message"]

    def test_429_rate_limited(self, admin_credentials):
        with patch.object(ac.httpx, "post") as mock_post:
            mock_post.return_value = _fake_response(429, text="rate limit")
            result = AnthropicConnector(admin_credentials).test_connection()
        assert result["success"] is False
        assert "Rate limited" in result["message"]

    def test_network_error(self, admin_credentials):
        with patch.object(ac.httpx, "post") as mock_post:
            mock_post.side_effect = httpx.ConnectError("connection refused")
            result = AnthropicConnector(admin_credentials).test_connection()
        assert result["success"] is False
        assert "Network error" in result["message"]
        assert "connection refused" in result["message"]

    def test_generic_non_200(self, admin_credentials):
        with patch.object(ac.httpx, "post") as mock_post:
            mock_post.return_value = _fake_response(500, text="boom")
            result = AnthropicConnector(admin_credentials).test_connection()
        assert result["success"] is False
        assert "HTTP 500" in result["message"]


# ===========================================================================
# fetch_costs — happy path
# ===========================================================================
def _sample_cost_report_page() -> dict:
    return {
        "data": [
            {
                "starting_at": "2026-04-20T00:00:00Z",
                "results": [
                    {
                        "workspace_id": "ws_alpha",
                        "description": "claude-opus-4-7",
                        "amount": {"value": 42.5, "currency": "USD"},
                    },
                    {
                        "workspace_id": "ws_alpha",
                        "description": "claude-sonnet-4-6",
                        "amount": {"value": 3.25, "currency": "USD"},
                    },
                ],
            },
            {
                "starting_at": "2026-04-21T00:00:00Z",
                "results": [
                    {
                        "workspace_id": "ws_alpha",
                        "description": "claude-opus-4-7",
                        "amount": 8.0,  # plain-float shape
                    }
                ],
            },
        ],
        "has_more": False,
    }


def _sample_usage_report_page() -> dict:
    return {
        "data": [
            {
                "starting_at": "2026-04-20T00:00:00Z",
                "results": [
                    {
                        "workspace_id": "ws_alpha",
                        "api_key_id": "apikey_1",
                        "model": "claude-opus-4-7",
                        "service_tier": "standard",
                        "context_window": "0-200k",
                        "uncached_input_tokens": 1_000_000,
                        "cache_read_input_tokens": 200_000,
                        "cache_creation": {
                            "ephemeral_5m_input_tokens": 50_000,
                            "ephemeral_1h_input_tokens": 10_000,
                        },
                        "output_tokens": 500_000,
                        "server_tool_use": {"web_search_requests": 4},
                        "inference_geo": "us-east",
                        "speed": "standard",
                    },
                    {
                        "workspace_id": "ws_alpha",
                        "api_key_id": "apikey_2",
                        "model": "claude-sonnet-4-6",
                        "service_tier": "batch",
                        "context_window": "0-200k",
                        "uncached_input_tokens": 2_000_000,
                        "output_tokens": 1_000_000,
                    },
                ],
            },
            {
                "starting_at": "2026-04-21T00:00:00Z",
                "results": [
                    {
                        "workspace_id": "ws_alpha",
                        "model": "claude-opus-4-7",
                        "service_tier": "standard",
                        "context_window": "0-200k",
                        "uncached_input_tokens": 400_000,
                        "output_tokens": 80_000,
                    }
                ],
            },
        ],
        "has_more": False,
    }


class TestFetchCosts:

    def test_happy_path_assembles_unified_costs(self, admin_credentials):
        connector = AnthropicConnector(admin_credentials)

        seq = _Sequencer(
            [
                _fake_response(200, _sample_cost_report_page()),
                _fake_response(200, _sample_usage_report_page()),
            ]
        )
        with patch.object(ac.httpx, "post", side_effect=seq):
            costs = connector.fetch_costs(days=7)

        assert all(isinstance(c, UnifiedCost) for c in costs)
        # 3 usage rows — each should be matched to an authoritative cost.
        # No leftover synthetic rows expected.
        assert len(costs) == 3
        # First request went to cost_report, second to usage_report.
        first_url = seq.calls[0][0][0]
        second_url = seq.calls[1][0][0]
        assert "cost_report" in first_url
        assert "usage_report/messages" in second_url

        # Find the Opus 4.7 row for 2026-04-20
        opus = next(
            c for c in costs
            if c.resource == "claude-opus-4-7" and c.date == "2026-04-20"
        )
        assert opus.cost_usd == pytest.approx(42.5)  # from cost_report
        assert opus.metadata["cost_source"] == "cost_report"
        assert opus.metadata["uncached_input_tokens"] == 1_000_000
        assert opus.metadata["cache_read_input_tokens"] == 200_000
        assert opus.metadata["cache_creation_5m_input_tokens"] == 50_000
        assert opus.metadata["cache_creation_1h_input_tokens"] == 10_000
        assert opus.metadata["output_tokens"] == 500_000
        assert opus.metadata["web_search_requests"] == 4
        assert opus.metadata["workspace_id"] == "ws_alpha"
        assert opus.metadata["api_key_id"] == "apikey_1"
        assert opus.metadata["service_tier"] == "standard"
        assert opus.metadata["context_window"] == "0-200k"
        assert opus.metadata["inference_geo"] == "us-east"
        assert opus.metadata["speed"] == "standard"
        assert opus.team == "ws_alpha"
        assert opus.platform == "anthropic"
        assert opus.service == "anthropic"
        assert opus.category == CostCategory.ai_inference
        assert opus.usage_unit == "tokens"
        assert opus.usage_quantity == 1_760_000  # 1M + 200k + 50k + 10k + 500k

    def test_falls_back_to_estimator_when_cost_report_empty(self, admin_credentials):
        connector = AnthropicConnector(admin_credentials)
        seq = _Sequencer(
            [
                _fake_response(200, {"data": [], "has_more": False}),
                _fake_response(200, _sample_usage_report_page()),
            ]
        )
        with patch.object(ac.httpx, "post", side_effect=seq):
            costs = connector.fetch_costs(days=7)

        # No cost_report → every bucket uses estimated cost.
        for c in costs:
            assert c.metadata["cost_source"] == "estimated"

        # Sanity check an estimated figure.
        sonnet_batch = next(c for c in costs if c.resource == "claude-sonnet-4-6")
        # 2M uncached input + 1M output at $3 / $15 * 0.5 (batch) = (6 + 15) * 0.5 = 10.5
        assert sonnet_batch.cost_usd == pytest.approx(10.5)

    def test_unattributed_cost_report_rows_preserved(self, admin_credentials):
        """cost_report rows with no matching usage bucket must still surface."""
        connector = AnthropicConnector(admin_credentials)
        cost_page = {
            "data": [
                {
                    "starting_at": "2026-04-20T00:00:00Z",
                    "results": [
                        {
                            "workspace_id": "ws_alpha",
                            "description": "web_search_surcharge",
                            "amount": {"value": 1.25, "currency": "USD"},
                        }
                    ],
                }
            ],
            "has_more": False,
        }
        seq = _Sequencer(
            [
                _fake_response(200, cost_page),
                _fake_response(200, {"data": [], "has_more": False}),
            ]
        )
        with patch.object(ac.httpx, "post", side_effect=seq):
            costs = connector.fetch_costs(days=1)

        assert len(costs) == 1
        assert costs[0].resource == "web_search_surcharge"
        assert costs[0].cost_usd == pytest.approx(1.25)
        assert costs[0].metadata["cost_source"] == "cost_report"

    def test_pagination_follows_next_page(self, admin_credentials):
        """Two-page usage_report response must yield records from both pages."""
        connector = AnthropicConnector(admin_credentials)
        page1 = {
            "data": [
                {
                    "starting_at": "2026-04-20T00:00:00Z",
                    "results": [
                        {
                            "workspace_id": "ws_alpha",
                            "model": "claude-opus-4-7",
                            "uncached_input_tokens": 1_000,
                            "output_tokens": 1_000,
                        }
                    ],
                }
            ],
            "has_more": True,
            "next_page": "cursor-xyz",
        }
        page2 = {
            "data": [
                {
                    "starting_at": "2026-04-20T00:00:00Z",
                    "results": [
                        {
                            "workspace_id": "ws_beta",
                            "model": "claude-sonnet-4-6",
                            "uncached_input_tokens": 2_000,
                            "output_tokens": 2_000,
                        }
                    ],
                }
            ],
            "has_more": False,
        }
        seq = _Sequencer(
            [
                _fake_response(200, {"data": [], "has_more": False}),  # cost_report
                _fake_response(200, page1),  # usage page 1
                _fake_response(200, page2),  # usage page 2
            ]
        )
        with patch.object(ac.httpx, "post", side_effect=seq):
            costs = connector.fetch_costs(days=3)

        assert len(costs) == 2
        resources = {c.resource for c in costs}
        assert resources == {"claude-opus-4-7", "claude-sonnet-4-6"}
        # Second usage call must have carried the cursor.
        second_usage_call = seq.calls[2]
        assert second_usage_call[1]["json"]["page"] == "cursor-xyz"

    def test_pricing_overrides_applied_to_estimator(self, admin_credentials):
        """When cost_report is empty, pricing_overrides should reshape the estimate."""
        creds = dict(admin_credentials)
        creds["pricing_overrides"] = {
            "claude-opus-4-7": {"input": 12.0, "output": 60.0},
            "credit_discount_pct": 10,
        }
        connector = AnthropicConnector(creds)
        usage = {
            "data": [
                {
                    "starting_at": "2026-04-20T00:00:00Z",
                    "results": [
                        {
                            "model": "claude-opus-4-7",
                            "uncached_input_tokens": 1_000_000,
                            "output_tokens": 1_000_000,
                        }
                    ],
                }
            ],
            "has_more": False,
        }
        seq = _Sequencer(
            [
                _fake_response(200, {"data": [], "has_more": False}),
                _fake_response(200, usage),
            ]
        )
        with patch.object(ac.httpx, "post", side_effect=seq):
            costs = connector.fetch_costs(days=1)

        assert len(costs) == 1
        # (12 + 60) * 0.9 = 64.8
        assert costs[0].cost_usd == pytest.approx(64.8)

    def test_zero_usage_buckets_are_skipped(self, admin_credentials):
        connector = AnthropicConnector(admin_credentials)
        usage = {
            "data": [
                {
                    "starting_at": "2026-04-20T00:00:00Z",
                    "results": [
                        {"model": "claude-opus-4-7"}  # all-zero usage
                    ],
                }
            ],
            "has_more": False,
        }
        seq = _Sequencer(
            [
                _fake_response(200, {"data": [], "has_more": False}),
                _fake_response(200, usage),
            ]
        )
        with patch.object(ac.httpx, "post", side_effect=seq):
            costs = connector.fetch_costs(days=1)
        assert costs == []

    def test_usage_report_failure_returns_empty_list(self, admin_credentials):
        """fetch_costs must swallow usage_report exceptions and return [] if no cost_report either."""
        connector = AnthropicConnector(admin_credentials)
        seq = _Sequencer(
            [
                _fake_response(200, {"data": [], "has_more": False}),
                _fake_response(500, text="oops"),
            ]
        )
        with patch.object(ac.httpx, "post", side_effect=seq):
            costs = connector.fetch_costs(days=1)
        assert costs == []

    def test_non_usd_cost_rows_are_skipped(self, admin_credentials):
        connector = AnthropicConnector(admin_credentials)
        cost_page = {
            "data": [
                {
                    "starting_at": "2026-04-20T00:00:00Z",
                    "results": [
                        {
                            "workspace_id": "ws_alpha",
                            "description": "claude-opus-4-7",
                            "amount": {"value": 100.0, "currency": "EUR"},
                        }
                    ],
                }
            ],
            "has_more": False,
        }
        seq = _Sequencer(
            [
                _fake_response(200, cost_page),
                _fake_response(200, {"data": [], "has_more": False}),
            ]
        )
        with patch.object(ac.httpx, "post", side_effect=seq):
            costs = connector.fetch_costs(days=1)
        assert costs == []

    def test_pagination_guard_max_pages(self, admin_credentials):
        """Infinite next_page loops must terminate at _MAX_PAGES."""
        connector = AnthropicConnector(admin_credentials)
        infinite_page = {
            "data": [],
            "has_more": True,
            "next_page": "loop-forever",
        }

        def always_infinite(*args, **kwargs):
            return _fake_response(200, infinite_page)

        with patch.object(ac.httpx, "post", side_effect=always_infinite) as mock_post:
            # Should return [] and not hang
            costs = connector.fetch_costs(days=1)

        assert costs == []
        # Sanity: post was called a bounded number of times.
        assert mock_post.call_count <= 2 * ac._MAX_PAGES + 4


# ===========================================================================
# Response parsing corner cases
# ===========================================================================
class TestResponseParsing:

    def test_unix_timestamp_bucket_start(self):
        bucket = {"starting_at": 1_714_521_600}  # 2024-05-01 UTC
        assert ac._bucket_start_date(bucket).startswith("2024-05-")

    def test_iso_z_normalised(self):
        bucket = {"starting_at": "2026-04-20T00:00:00Z"}
        assert ac._bucket_start_date(bucket) == "2026-04-20"

    def test_missing_date_returns_empty_string(self):
        assert ac._bucket_start_date({}) == ""

    def test_token_parsing_handles_missing_sections(self):
        t = ac._parse_token_usage({})
        assert t.total_tokens == 0
        assert t.web_search_requests == 0

    def test_safe_int_coerces_strings(self):
        assert ac._safe_int("42") == 42
        assert ac._safe_int(None) == 0
        assert ac._safe_int("not-a-number") == 0


# ===========================================================================
# Registry / UnifiedCost schema conformance
# ===========================================================================
class TestSchemaConformance:

    def test_platform_enum_value(self):
        assert AnthropicConnector.platform == PlatformType.anthropic.value

    def test_unified_cost_fields_match_model(self, admin_credentials):
        """Smoke-test that assembled records round-trip through Pydantic."""
        c = AnthropicConnector(admin_credentials)
        dummy_usage = UsageBucket(
            date="2026-04-20",
            model="claude-opus-4-7",
            tokens=TokenUsage(uncached_input_tokens=1, output_tokens=1),
            workspace_id="ws_x",
        )
        records = c._assemble_unified_costs([dummy_usage], {})
        assert len(records) == 1
        assert records[0].model_dump()["platform"] == "anthropic"
        assert records[0].model_dump()["category"] == "ai_inference"

    def test_model_pricing_2026_catalog_has_current_models(self):
        for key in ("claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5"):
            assert key in MODEL_PRICING

    def test_legacy_pricing_retained(self):
        # Historical 3.x still present for back-fills.
        for key in ("claude-haiku-3-5", "claude-3-5-sonnet"):
            assert key in MODEL_PRICING
