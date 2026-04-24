"""Comprehensive tests for the OpenAI connector.

Covers:
  * ``_resolve_pricing`` — prefix-anchored matching, date-suffix stripping,
    pricing_overrides precedence.
  * ``estimate_cost`` — cached-token discount math, reasoning-as-output,
    batch API discount, per-image / per-minute / per-character dimensions.
  * Usage API fetchers for every bucket (completions, embeddings, moderations,
    images, audio_speeches, audio_transcriptions, vector_stores,
    code_interpreter_sessions).
  * Costs API — ``amount.value`` treated as dollars (not cents), pagination.
  * ``test_connection`` — 200/401/403/429/network error paths.
  * End-to-end ``fetch_costs(days=30)`` merge semantics.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.models.platform import CostCategory, UnifiedCost
from app.services.connectors.openai_connector import (
    BATCH_DISCOUNT,
    MODEL_PRICING,
    ModelPricing,
    OpenAIConnector,
    TokenUsage,
    USAGE_ENDPOINTS,
    _estimate_cost,
    _normalize_model,
    _resolve_pricing,
    estimate_cost,
)


FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def _mock_http_response(
    status_code: int = 200, json_body: dict | None = None, text: str = ""
) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json = MagicMock(return_value=json_body or {})
    resp.text = text or (json.dumps(json_body) if json_body else "")
    return resp


# ─── Pricing table completeness ────────────────────────────────────


class TestModelPricingTable:
    @pytest.mark.parametrize(
        "model",
        [
            "gpt-5",
            "gpt-5-mini",
            "gpt-5-nano",
            "gpt-5-chat-latest",
            "gpt-4.1",
            "gpt-4.1-mini",
            "gpt-4.1-nano",
            "gpt-4o",
            "gpt-4o-mini",
            "gpt-4-turbo",
            "gpt-4",
            "gpt-3.5-turbo",
            "o1",
            "o1-mini",
            "o1-pro",
            "o3",
            "o3-mini",
            "o3-pro",
            "o4",
            "o4-mini",
            "computer-use-preview",
            "dall-e-3",
            "whisper-1",
            "tts-1",
            "text-embedding-3-small",
            "text-embedding-3-large",
        ],
    )
    def test_all_key_models_present(self, model):
        assert model in MODEL_PRICING, f"MODEL_PRICING missing {model}"

    def test_dall_e_3_has_nonzero_image_rate(self):
        """Regression: dall-e-3 used to be hard-coded to 0, masking real cost."""
        assert MODEL_PRICING["dall-e-3"].per_image > 0

    def test_gpt5_cached_is_90pct_discount(self):
        """gpt-5 prompt cache is ~90% (cached = 0.1x input)."""
        p = MODEL_PRICING["gpt-5"]
        assert pytest.approx(p.cached_input / p.input, rel=1e-6) == 0.1

    def test_gpt4o_cached_is_50pct_discount(self):
        p = MODEL_PRICING["gpt-4o"]
        assert pytest.approx(p.cached_input / p.input, rel=1e-6) == 0.5

    def test_o3_dropped_80pct_from_o1(self):
        """o3 is ~80% cheaper than o1 (announced mid-2025)."""
        o1 = MODEL_PRICING["o1"]
        o3 = MODEL_PRICING["o3"]
        assert o3.input < o1.input * 0.25  # >75% drop on input
        assert o3.output < o1.output * 0.25


# ─── _resolve_pricing ──────────────────────────────────────────────


class TestResolvePricing:
    def test_exact_match_gpt_5(self):
        assert _resolve_pricing("gpt-5") is MODEL_PRICING["gpt-5"]

    def test_gpt_4o_mini_NOT_matched_by_gpt_4(self):
        """Regression: sorting by length alone, 'gpt-4' would match inside
        'gpt-4o-mini' if the pricing table lacked gpt-4o-mini. Our anchored
        matcher must refuse this even if only 'gpt-4' is present."""
        # With the full table, gpt-4o-mini is an exact match.
        p = _resolve_pricing("gpt-4o-mini")
        assert p is MODEL_PRICING["gpt-4o-mini"]

        # With only gpt-4 in overrides, the matcher must NOT pick it up for
        # gpt-4o-mini.
        overrides = {"gpt-4": {"input": 999.0, "output": 999.0}}
        p2 = _resolve_pricing("gpt-4o-mini", overrides)
        assert p2.input == MODEL_PRICING["gpt-4o-mini"].input

    def test_date_suffix_stripped(self):
        p = _resolve_pricing("gpt-4o-2024-08-06")
        assert p is MODEL_PRICING["gpt-4o"]

    def test_date_suffix_8digit(self):
        p = _resolve_pricing("gpt-4o-mini-20240718")
        assert p is MODEL_PRICING["gpt-4o-mini"]

    def test_anchored_prefix_match(self):
        # "gpt-4o-audio-preview-2024-10-01" → gpt-4o-audio-preview
        p = _resolve_pricing("gpt-4o-audio-preview-2024-10-01")
        assert p is MODEL_PRICING["gpt-4o-audio-preview"]

    def test_unknown_model_falls_back(self):
        p = _resolve_pricing("mystery-model-xyz")
        assert p.input > 0

    @pytest.mark.parametrize(
        "model,expected_key",
        [
            ("gpt-5", "gpt-5"),
            ("gpt-5-mini", "gpt-5-mini"),
            ("gpt-5-chat-latest", "gpt-5-chat-latest"),
            ("gpt-4o", "gpt-4o"),
            ("gpt-4o-mini", "gpt-4o-mini"),
            ("o1", "o1"),
            ("o3", "o3"),
            ("o3-mini", "o3-mini"),
            ("text-embedding-3-small", "text-embedding-3-small"),
            ("dall-e-3", "dall-e-3"),
            ("whisper-1", "whisper-1"),
        ],
    )
    def test_named_models_resolve_to_themselves(self, model, expected_key):
        p = _resolve_pricing(model)
        assert p is MODEL_PRICING[expected_key]

    def test_overrides_exact_wins(self):
        overrides = {"gpt-4o": {"input": 1.0, "output": 2.0}}
        p = _resolve_pricing("gpt-4o", overrides)
        assert p.input == 1.0 and p.output == 2.0

    def test_overrides_with_date_suffix(self):
        overrides = {"gpt-4o": {"input": 1.0, "output": 2.0}}
        p = _resolve_pricing("gpt-4o-2024-08-06", overrides)
        assert p.input == 1.0

    def test_overrides_not_confused_by_prefix_gpt4(self):
        overrides = {"gpt-4": {"input": 99.0, "output": 99.0}}
        p = _resolve_pricing("gpt-4o-mini", overrides)
        # Must fall through to MODEL_PRICING["gpt-4o-mini"]
        assert p.input == MODEL_PRICING["gpt-4o-mini"].input

    def test_overrides_accept_modelpricing_instance(self):
        overrides = {"gpt-4o": ModelPricing(input=7.0, output=8.0)}
        p = _resolve_pricing("gpt-4o", overrides)
        assert p.input == 7.0

    def test_normalize_model_lowercases(self):
        assert _normalize_model("GPT-4O") == "gpt-4o"


# ─── estimate_cost ─────────────────────────────────────────────────


class TestEstimateCost:
    def test_gpt4o_plain_tokens(self):
        # 1M input @ $2.50 + 1M output @ $10 = $12.50
        cost = estimate_cost("gpt-4o", input_tokens=1_000_000, output_tokens=1_000_000)
        assert cost == pytest.approx(12.5, rel=1e-6)

    def test_gpt4o_mini_plain_tokens(self):
        # 1M @ $0.15 + 1M @ $0.60 = $0.75
        cost = estimate_cost(
            "gpt-4o-mini", input_tokens=1_000_000, output_tokens=1_000_000
        )
        assert cost == pytest.approx(0.75, rel=1e-6)

    def test_cached_token_discount_gpt4o(self):
        """GPT-4o: cached @ 50% of input. 1M input all cached = $1.25 (not
        $2.50). 1M input with 200k cached = 800k*$2.50/M + 200k*$1.25/M =
        $2.0 + $0.25 = $2.25."""
        fully_cached = estimate_cost(
            "gpt-4o", input_tokens=1_000_000, cached_input_tokens=1_000_000
        )
        assert fully_cached == pytest.approx(1.25, rel=1e-6)

        partial = estimate_cost(
            "gpt-4o",
            input_tokens=1_000_000,
            cached_input_tokens=200_000,
            output_tokens=0,
        )
        assert partial == pytest.approx(2.25, rel=1e-6)

    def test_cached_token_discount_gpt5(self):
        """GPT-5: cached @ $0.125 (10% of input $1.25). 1M all cached = $0.125."""
        fully_cached = estimate_cost(
            "gpt-5", input_tokens=1_000_000, cached_input_tokens=1_000_000
        )
        assert fully_cached == pytest.approx(0.125, rel=1e-6)

    def test_reasoning_tokens_charged_as_output(self):
        """1M output + 1M reasoning @ $10/M = $20."""
        cost = estimate_cost(
            "o3",
            input_tokens=0,
            output_tokens=1_000_000,
            reasoning_tokens=1_000_000,
        )
        # o3 output = $8/M → 2M × $8 = $16
        assert cost == pytest.approx(16.0, rel=1e-6)

    def test_batch_discount_halves_tokens(self):
        """Batch API = 50% off input + output."""
        normal = estimate_cost(
            "gpt-4o", input_tokens=1_000_000, output_tokens=1_000_000
        )
        batched = estimate_cost(
            "gpt-4o",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            is_batch=True,
        )
        assert batched == pytest.approx(normal * BATCH_DISCOUNT, rel=1e-6)

    def test_batch_discount_applies_to_cached_tokens_too(self):
        full = estimate_cost(
            "gpt-4o",
            input_tokens=1_000_000,
            cached_input_tokens=1_000_000,
            is_batch=True,
        )
        # Cached only ($1.25) then 50% off = $0.625
        assert full == pytest.approx(0.625, rel=1e-6)

    def test_batch_discount_does_not_apply_to_images(self):
        """DALL-E doesn't have a batch rate — per-image cost unchanged."""
        normal = estimate_cost("dall-e-3", images=10)
        batched = estimate_cost("dall-e-3", images=10, is_batch=True)
        assert normal == batched

    def test_dall_e_3_per_image(self):
        cost = estimate_cost("dall-e-3", images=10)
        assert cost == pytest.approx(0.40, rel=1e-6)

    def test_whisper_per_minute(self):
        # 120 seconds = 2 minutes @ $0.006 = $0.012
        cost = estimate_cost("whisper-1", seconds=120)
        assert cost == pytest.approx(0.012, rel=1e-6)

    def test_tts_per_million_chars(self):
        # 1M chars @ $15
        cost = estimate_cost("tts-1", characters=1_000_000)
        assert cost == pytest.approx(15.0, rel=1e-6)

    def test_embeddings_input_only(self):
        # 10M tokens @ $0.02 = $0.20
        cost = estimate_cost(
            "text-embedding-3-small", input_tokens=10_000_000, output_tokens=0
        )
        assert cost == pytest.approx(0.20, rel=1e-6)

    def test_moderation_free(self):
        cost = estimate_cost("omni-moderation-latest", input_tokens=500_000)
        assert cost == 0.0

    def test_mixed_tier_cost_sum(self):
        """GPT-5 family: gpt-5 + gpt-5-mini + gpt-5-nano with various cached/batch."""
        gpt5 = estimate_cost(
            "gpt-5",
            input_tokens=1_000_000,
            cached_input_tokens=500_000,
            output_tokens=500_000,
        )
        # input 500k @ $1.25/M = $0.625
        # cached 500k @ $0.125/M = $0.0625
        # output 500k @ $10/M = $5.0
        # Total = $5.6875
        assert gpt5 == pytest.approx(5.6875, rel=1e-6)

        mini = estimate_cost(
            "gpt-5-mini", input_tokens=2_000_000, output_tokens=500_000
        )
        # input 2M @ $0.25 = $0.50 + output 0.5M @ $2.0 = $1.0 → $1.50
        assert mini == pytest.approx(1.50, rel=1e-6)

    def test_pricing_overrides_replaces_rate(self):
        overrides = {"gpt-4o": {"input": 1.0, "output": 2.0}}
        cost = estimate_cost(
            "gpt-4o",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            pricing_overrides=overrides,
        )
        assert cost == pytest.approx(3.0, rel=1e-6)

    def test_legacy_estimate_cost_wrapper(self):
        """Pre-existing callers (test_connectors.py) use the plain signature."""
        assert _estimate_cost("gpt-4o", 1_000_000, 1_000_000) == pytest.approx(
            12.5, rel=1e-6
        )


# ─── Connector instantiation ───────────────────────────────────────


class TestConnectorInit:
    def test_default_fields(self, openai_credentials):
        conn = OpenAIConnector(openai_credentials)
        assert conn.platform == "openai"
        assert conn.api_key == "sk-test-key-123"
        assert conn.org_id == "org-test-123"
        assert conn.base_url == "https://api.openai.com/v1"
        assert conn.pricing_overrides == {}

    def test_pricing_overrides_in_credentials(self):
        creds = {
            "api_key": "sk-x",
            "pricing_overrides": {"gpt-4o": {"input": 1.0, "output": 2.0}},
        }
        conn = OpenAIConnector(creds)
        assert conn.pricing_overrides == {"gpt-4o": {"input": 1.0, "output": 2.0}}

    def test_custom_base_url(self):
        conn = OpenAIConnector(
            {"api_key": "sk-x", "base_url": "https://proxy.example.com/v1/"}
        )
        assert conn.base_url == "https://proxy.example.com/v1"

    def test_headers_with_org(self, openai_credentials):
        conn = OpenAIConnector(openai_credentials)
        h = conn._headers()
        assert h["Authorization"] == "Bearer sk-test-key-123"
        assert h["OpenAI-Organization"] == "org-test-123"

    def test_headers_without_org(self):
        conn = OpenAIConnector({"api_key": "sk-x"})
        h = conn._headers()
        assert "OpenAI-Organization" not in h


# ─── test_connection ───────────────────────────────────────────────


class TestTestConnection:
    @patch("app.services.connectors.openai_connector.httpx.get")
    def test_success_with_admin(self, mock_get, openai_credentials):
        mock_get.side_effect = [
            _mock_http_response(200, {"data": []}),
            _mock_http_response(200, {"data": []}),
        ]
        result = OpenAIConnector(openai_credentials).test_connection()
        assert result["success"] is True
        assert "successful" in result["message"].lower()

    @patch("app.services.connectors.openai_connector.httpx.get")
    def test_401_invalid_key(self, mock_get, openai_credentials):
        mock_get.return_value = _mock_http_response(401, text="unauthorized")
        result = OpenAIConnector(openai_credentials).test_connection()
        assert result["success"] is False
        assert "401" in result["message"] or "invalid" in result["message"].lower()

    @patch("app.services.connectors.openai_connector.httpx.get")
    def test_429_rate_limited(self, mock_get, openai_credentials):
        mock_get.return_value = _mock_http_response(429, text="rate limited")
        result = OpenAIConnector(openai_credentials).test_connection()
        assert result["success"] is False
        assert "429" in result["message"] or "rate" in result["message"].lower()

    @patch("app.services.connectors.openai_connector.httpx.get")
    def test_403_needs_admin_key(self, mock_get, openai_credentials):
        mock_get.side_effect = [
            _mock_http_response(200, {"data": []}),  # /models OK
            _mock_http_response(403, text="forbidden"),  # usage probe 403
        ]
        result = OpenAIConnector(openai_credentials).test_connection()
        assert result["success"] is False
        assert "admin" in result["message"].lower()

    @patch("app.services.connectors.openai_connector.httpx.get")
    def test_network_error(self, mock_get, openai_credentials):
        mock_get.side_effect = httpx.ConnectError("dns failed")
        result = OpenAIConnector(openai_credentials).test_connection()
        assert result["success"] is False
        assert "network" in result["message"].lower() or "dns" in result["message"].lower()

    @patch("app.services.connectors.openai_connector.httpx.get")
    def test_usage_probe_429_non_fatal(self, mock_get, openai_credentials):
        mock_get.side_effect = [
            _mock_http_response(200, {"data": []}),
            _mock_http_response(429, text="rate"),
        ]
        result = OpenAIConnector(openai_credentials).test_connection()
        assert result["success"] is True


# ─── Usage API — per-bucket ────────────────────────────────────────


class TestUsageAPIBuckets:
    def _patch_get(self, mock_get, response_map: dict[str, dict]):
        """Return fixtures keyed by a substring of the URL."""

        def side_effect(url, headers=None, params=None, timeout=None):
            for key, payload in response_map.items():
                if key in url:
                    return _mock_http_response(200, payload)
            return _mock_http_response(200, {"data": [], "has_more": False})

        mock_get.side_effect = side_effect

    @patch("app.services.connectors.openai_connector.httpx.get")
    def test_fetch_completions(self, mock_get, openai_credentials):
        self._patch_get(mock_get, {"/completions": _fixture("openai_usage_completions.json")})
        conn = OpenAIConnector(openai_credentials)
        records = conn._fetch_usage_bucket(
            "completions",
            start=_start(),
            end=_end(),
        )
        assert len(records) == 3
        by_resource = {r.resource: r for r in records}
        assert "gpt-4o" in by_resource
        assert "o3-mini" in by_resource
        assert "gpt-5-mini" in by_resource
        # Project attribution
        assert by_resource["gpt-4o"].project == "proj_alpha"
        # Batch flag surfaced
        assert by_resource["o3-mini"].metadata["batch"] is True
        # Cached tokens surfaced
        assert by_resource["gpt-4o"].metadata["cached_input_tokens"] == 200_000
        # Reasoning tokens surfaced
        assert by_resource["o3-mini"].metadata["reasoning_tokens"] == 300_000

    def test_completions_cost_math(self, openai_credentials):
        """gpt-4o record from fixture: input=1M, cached=200k, output=500k.
        Uncached = 800k * $2.50 / M = $2.00
        Cached   = 200k * $1.25 / M = $0.25
        Output   = 500k * $10.00 / M = $5.00
        Total    = $7.25
        """
        conn = OpenAIConnector(openai_credentials)
        with patch(
            "app.services.connectors.openai_connector.httpx.get"
        ) as mock_get:
            mock_get.return_value = _mock_http_response(
                200, _fixture("openai_usage_completions.json")
            )
            records = conn._fetch_usage_bucket(
                "completions", start=_start(), end=_end()
            )
        gpt4o = next(r for r in records if r.resource == "gpt-4o")
        assert gpt4o.cost_usd == pytest.approx(7.25, rel=1e-6)

    def test_o3_mini_batch_cost_math(self, openai_credentials):
        """o3-mini: input=2M, output=500k, reasoning=300k, batch=True.
        Non-batch: input 2M*$1.10 + (output+reasoning=800k)*$4.40
        = $2.20 + $3.52 = $5.72. Batched × 0.5 = $2.86.
        """
        conn = OpenAIConnector(openai_credentials)
        with patch(
            "app.services.connectors.openai_connector.httpx.get"
        ) as mock_get:
            mock_get.return_value = _mock_http_response(
                200, _fixture("openai_usage_completions.json")
            )
            records = conn._fetch_usage_bucket(
                "completions", start=_start(), end=_end()
            )
        o3 = next(r for r in records if r.resource == "o3-mini")
        assert o3.cost_usd == pytest.approx(2.86, rel=1e-6)

    @patch("app.services.connectors.openai_connector.httpx.get")
    def test_fetch_embeddings(self, mock_get, openai_credentials):
        mock_get.return_value = _mock_http_response(
            200, _fixture("openai_usage_embeddings.json")
        )
        conn = OpenAIConnector(openai_credentials)
        records = conn._fetch_usage_bucket(
            "embeddings", start=_start(), end=_end()
        )
        assert len(records) == 1
        r = records[0]
        assert r.resource == "text-embedding-3-small"
        # 10M @ $0.02/M = $0.20
        assert r.cost_usd == pytest.approx(0.20, rel=1e-6)

    @patch("app.services.connectors.openai_connector.httpx.get")
    def test_fetch_moderations(self, mock_get, openai_credentials):
        mock_get.return_value = _mock_http_response(
            200, _fixture("openai_usage_moderations.json")
        )
        conn = OpenAIConnector(openai_credentials)
        records = conn._fetch_usage_bucket(
            "moderations", start=_start(), end=_end()
        )
        assert len(records) == 1
        # Moderation is free → cost must be 0 but record still surfaces usage.
        assert records[0].cost_usd == 0.0
        assert records[0].usage_quantity == 500_000
        assert records[0].usage_unit == "tokens"

    @patch("app.services.connectors.openai_connector.httpx.get")
    def test_fetch_images(self, mock_get, openai_credentials):
        mock_get.return_value = _mock_http_response(
            200, _fixture("openai_usage_images.json")
        )
        conn = OpenAIConnector(openai_credentials)
        records = conn._fetch_usage_bucket("images", start=_start(), end=_end())
        assert len(records) == 1
        # 25 dall-e-3 @ $0.04 = $1.00
        assert records[0].cost_usd == pytest.approx(1.0, rel=1e-6)
        assert records[0].usage_quantity == 25
        assert records[0].usage_unit == "images"

    @patch("app.services.connectors.openai_connector.httpx.get")
    def test_fetch_audio_speeches(self, mock_get, openai_credentials):
        mock_get.return_value = _mock_http_response(
            200, _fixture("openai_usage_audio_speeches.json")
        )
        conn = OpenAIConnector(openai_credentials)
        records = conn._fetch_usage_bucket(
            "audio_speeches", start=_start(), end=_end()
        )
        assert len(records) == 1
        # 2M chars @ $15/M = $30
        assert records[0].cost_usd == pytest.approx(30.0, rel=1e-6)
        assert records[0].usage_unit == "characters"

    @patch("app.services.connectors.openai_connector.httpx.get")
    def test_fetch_audio_transcriptions(self, mock_get, openai_credentials):
        mock_get.return_value = _mock_http_response(
            200, _fixture("openai_usage_audio_transcriptions.json")
        )
        conn = OpenAIConnector(openai_credentials)
        records = conn._fetch_usage_bucket(
            "audio_transcriptions", start=_start(), end=_end()
        )
        assert len(records) == 1
        # 3600s = 60min @ $0.006 = $0.36
        assert records[0].cost_usd == pytest.approx(0.36, rel=1e-6)
        assert records[0].usage_unit == "seconds"

    @patch("app.services.connectors.openai_connector.httpx.get")
    def test_fetch_vector_stores(self, mock_get, openai_credentials):
        mock_get.return_value = _mock_http_response(
            200, _fixture("openai_usage_vector_stores.json")
        )
        conn = OpenAIConnector(openai_credentials)
        records = conn._fetch_usage_bucket(
            "vector_stores", start=_start(), end=_end()
        )
        assert len(records) == 1
        # 10 GiB * $0.10 = $1.00 (daily snapshot; rate is per-GB-month in
        # MODEL_PRICING but the Costs API is authoritative anyway).
        assert records[0].cost_usd == pytest.approx(1.0, rel=1e-6)
        assert records[0].usage_unit == "bytes"

    @patch("app.services.connectors.openai_connector.httpx.get")
    def test_fetch_code_interpreter_sessions(self, mock_get, openai_credentials):
        mock_get.return_value = _mock_http_response(
            200, _fixture("openai_usage_code_interpreter.json")
        )
        conn = OpenAIConnector(openai_credentials)
        records = conn._fetch_usage_bucket(
            "code_interpreter_sessions", start=_start(), end=_end()
        )
        assert len(records) == 1
        # 42 sessions @ $0.03 = $1.26
        assert records[0].cost_usd == pytest.approx(1.26, rel=1e-6)
        assert records[0].usage_unit == "sessions"

    def test_all_usage_endpoints_listed(self):
        """Regression: ensure we're hitting every OpenAI usage bucket."""
        expected = {
            "completions",
            "embeddings",
            "moderations",
            "images",
            "audio_speeches",
            "audio_transcriptions",
            "vector_stores",
            "code_interpreter_sessions",
        }
        assert set(USAGE_ENDPOINTS) == expected


# ─── Costs API ─────────────────────────────────────────────────────


class TestCostsAPI:
    @patch("app.services.connectors.openai_connector.httpx.get")
    def test_costs_amount_is_dollars_not_cents(self, mock_get, openai_credentials):
        """Regression: the old connector divided by 100 assuming cents. The
        API actually returns dollars — verify we report 12.35, not 0.12."""
        mock_get.return_value = _mock_http_response(
            200, _fixture("openai_costs.json")
        )
        conn = OpenAIConnector(openai_credentials)
        records = conn._fetch_from_costs_api(_start(), _end())
        total = sum(r.cost_usd for r in records)
        # Fixture sums: 12.345678 + 7.5 + 3.25 = 23.095678
        assert total == pytest.approx(23.095678, rel=1e-6)
        # Spot-check individual rows: NOT divided by 100.
        amounts = [r.cost_usd for r in records]
        assert pytest.approx(12.345678, rel=1e-6) in amounts

    @patch("app.services.connectors.openai_connector.httpx.get")
    def test_costs_extracts_model_from_line_item(self, mock_get, openai_credentials):
        mock_get.return_value = _mock_http_response(
            200, _fixture("openai_costs.json")
        )
        conn = OpenAIConnector(openai_credentials)
        records = conn._fetch_from_costs_api(_start(), _end())
        models = {r.metadata.get("model") for r in records}
        assert "gpt-4o" in models
        assert "gpt-5-mini" in models

    @patch("app.services.connectors.openai_connector.httpx.get")
    def test_costs_preserves_project_id(self, mock_get, openai_credentials):
        mock_get.return_value = _mock_http_response(
            200, _fixture("openai_costs.json")
        )
        conn = OpenAIConnector(openai_credentials)
        records = conn._fetch_from_costs_api(_start(), _end())
        projects = {r.project for r in records}
        assert "proj_alpha" in projects
        assert "proj_beta" in projects

    @patch("app.services.connectors.openai_connector.httpx.get")
    def test_costs_empty_response(self, mock_get, openai_credentials):
        mock_get.return_value = _mock_http_response(
            200, {"data": [], "has_more": False}
        )
        conn = OpenAIConnector(openai_credentials)
        records = conn._fetch_from_costs_api(_start(), _end())
        assert records == []

    @patch("app.services.connectors.openai_connector.httpx.get")
    def test_costs_http_error_returns_empty(self, mock_get, openai_credentials):
        mock_get.return_value = _mock_http_response(500, text="server error")
        conn = OpenAIConnector(openai_credentials)
        records = conn._fetch_from_costs_api(_start(), _end())
        assert records == []


# ─── Pagination ────────────────────────────────────────────────────


class TestPagination:
    @patch("app.services.connectors.openai_connector.httpx.get")
    def test_two_page_response(self, mock_get, openai_credentials):
        mock_get.side_effect = [
            _mock_http_response(200, _fixture("openai_usage_paginated_page1.json")),
            _mock_http_response(200, _fixture("openai_usage_paginated_page2.json")),
        ]
        conn = OpenAIConnector(openai_credentials)
        records = conn._fetch_usage_bucket(
            "completions", start=_start(), end=_end()
        )
        assert len(records) == 2  # one per page
        # Second call carries the next_page cursor.
        second_call = mock_get.call_args_list[1]
        assert second_call.kwargs["params"]["page"] == "cursor_abc"

    @patch("app.services.connectors.openai_connector.httpx.get")
    def test_pagination_hard_cap(self, mock_get, openai_credentials):
        """Never loop forever on a broken API that always returns has_more."""
        forever = {
            "data": [
                {
                    "start_time": 1_700_000_000,
                    "end_time": 1_700_086_400,
                    "results": [
                        {
                            "model": "gpt-4o",
                            "input_tokens": 100,
                            "output_tokens": 50,
                        }
                    ],
                }
            ],
            "has_more": True,
            "next_page": "forever",
        }
        mock_get.return_value = _mock_http_response(200, forever)
        conn = OpenAIConnector(openai_credentials)
        records = conn._fetch_usage_bucket(
            "completions", start=_start(), end=_end()
        )
        # Bounded by _MAX_PAGES (200).
        assert mock_get.call_count <= conn._MAX_PAGES
        assert len(records) <= conn._MAX_PAGES


# ─── fetch_costs end-to-end ────────────────────────────────────────


class TestFetchCostsEnd2End:
    @patch("app.services.connectors.openai_connector.httpx.get")
    def test_happy_path_30_days(self, mock_get, openai_credentials):
        """Every endpoint returns a fixture — verify we merge correctly."""

        def side_effect(url, headers=None, params=None, timeout=None):
            if "/usage/completions" in url:
                return _mock_http_response(
                    200, _fixture("openai_usage_completions.json")
                )
            if "/usage/embeddings" in url:
                return _mock_http_response(
                    200, _fixture("openai_usage_embeddings.json")
                )
            if "/usage/moderations" in url:
                return _mock_http_response(
                    200, _fixture("openai_usage_moderations.json")
                )
            if "/usage/images" in url:
                return _mock_http_response(
                    200, _fixture("openai_usage_images.json")
                )
            if "/usage/audio_speeches" in url:
                return _mock_http_response(
                    200, _fixture("openai_usage_audio_speeches.json")
                )
            if "/usage/audio_transcriptions" in url:
                return _mock_http_response(
                    200, _fixture("openai_usage_audio_transcriptions.json")
                )
            if "/usage/vector_stores" in url:
                return _mock_http_response(
                    200, _fixture("openai_usage_vector_stores.json")
                )
            if "/usage/code_interpreter_sessions" in url:
                return _mock_http_response(
                    200, _fixture("openai_usage_code_interpreter.json")
                )
            if "/organization/costs" in url:
                return _mock_http_response(
                    200, _fixture("openai_costs.json")
                )
            return _mock_http_response(200, {"data": [], "has_more": False})

        mock_get.side_effect = side_effect

        conn = OpenAIConnector(openai_credentials)
        records = conn.fetch_costs(days=30)

        # All records are valid UnifiedCost instances with required fields.
        assert len(records) > 0
        for r in records:
            assert isinstance(r, UnifiedCost)
            assert r.platform == "openai"
            assert r.category == CostCategory.ai_inference
            assert r.cost_usd >= 0
            assert r.date
            assert r.service == "openai"

        # Costs API entries take precedence for gpt-4o + gpt-5-mini
        # (they have matching usage rows). Look for the merged record.
        merged_gpt4o = [
            r for r in records
            if r.metadata.get("source_api") == "costs"
            and r.metadata.get("model") == "gpt-4o"
        ]
        assert merged_gpt4o, "Should surface a costs-sourced gpt-4o record"
        # Merged record carries token dimensions from usage.
        assert merged_gpt4o[0].metadata.get("input_tokens") == 1_000_000
        assert merged_gpt4o[0].metadata.get("cached_input_tokens") == 200_000

    @patch("app.services.connectors.openai_connector.httpx.get")
    def test_costs_api_failure_falls_back_to_usage(
        self, mock_get, openai_credentials
    ):
        def side_effect(url, headers=None, params=None, timeout=None):
            if "/usage/completions" in url:
                return _mock_http_response(
                    200, _fixture("openai_usage_completions.json")
                )
            if "/organization/costs" in url:
                return _mock_http_response(500, text="fail")
            return _mock_http_response(200, {"data": [], "has_more": False})

        mock_get.side_effect = side_effect
        conn = OpenAIConnector(openai_credentials)
        records = conn.fetch_costs(days=7)
        # Usage records still produced.
        assert any(r.resource == "gpt-4o" for r in records)
        assert all(r.metadata.get("source_api") == "usage" for r in records)

    @patch("app.services.connectors.openai_connector.httpx.get")
    def test_complete_api_failure_returns_empty(self, mock_get, openai_credentials):
        mock_get.return_value = _mock_http_response(500, text="server error")
        conn = OpenAIConnector(openai_credentials)
        records = conn.fetch_costs(days=7)
        assert records == []

    @patch("app.services.connectors.openai_connector.httpx.get")
    def test_network_error_returns_empty(self, mock_get, openai_credentials):
        mock_get.side_effect = httpx.ConnectError("boom")
        conn = OpenAIConnector(openai_credentials)
        records = conn.fetch_costs(days=7)
        assert records == []

    @patch("app.services.connectors.openai_connector.httpx.get")
    def test_pricing_overrides_from_credentials(self, mock_get):
        creds = {
            "api_key": "sk-x",
            "pricing_overrides": {"gpt-4o": {"input": 0.5, "output": 1.0}},
        }
        mock_get.side_effect = lambda url, **kw: (
            _mock_http_response(200, _fixture("openai_usage_completions.json"))
            if "/usage/completions" in url
            else _mock_http_response(200, {"data": [], "has_more": False})
        )
        conn = OpenAIConnector(creds)
        records = conn.fetch_costs(days=7)
        gpt4o = next(r for r in records if r.resource == "gpt-4o")
        # With override: uncached 800k × $0.5 + cached 200k × $0.5
        # (no cached rate in override → defaults to input) + output 500k × $1.0
        # = $0.40 + $0.10 + $0.50 = $1.00
        assert gpt4o.cost_usd == pytest.approx(1.0, rel=1e-6)


# ─── TokenUsage dataclass ──────────────────────────────────────────


class TestTokenUsage:
    def test_frozen(self):
        u = TokenUsage(model="gpt-4o", input_tokens=100)
        with pytest.raises(Exception):
            u.model = "gpt-5"  # type: ignore[misc]

    def test_defaults(self):
        u = TokenUsage(model="gpt-4o")
        assert u.input_tokens == 0
        assert u.cached_input_tokens == 0
        assert u.reasoning_tokens == 0
        assert u.batch is False


# ─── Helpers for tests ─────────────────────────────────────────────


def _start():
    from datetime import datetime, timezone

    return datetime(2024, 2, 1, tzinfo=timezone.utc)


def _end():
    from datetime import datetime, timezone

    return datetime(2024, 3, 1, tzinfo=timezone.utc)
