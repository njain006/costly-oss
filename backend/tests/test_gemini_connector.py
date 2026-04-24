"""Tests for the Google Gemini / Vertex AI connector.

Covers:
- TokenUsage arithmetic, billable_input/output, parse_usage_metadata.
- Pricing prefix resolution for every catalog variant (sorted by length).
- Context-tier pricing (2.5 Pro <=200k vs >200k).
- Cached-content discount (75% off input).
- Thinking-token charged as output.
- Billing-table FQN builder + billing-account dash normalisation.
- BigQuery billing-export query builder (date range, project filter,
  service filter).
- HTTP error classification: 401/403/404 + API-disabled + permission parsing.
- Region propagation: Vertex endpoint URL honours non-default regions.
- Pricing overrides: per-model input/output rates override catalog.
- test_connection paths: no creds / AI Studio only / Vertex-no-billing /
  Vertex-with-billing / 401 / 403-missing-permission / 404.
- End-to-end fetch_costs(days=30) with mocked BigQuery response.
- SKU classification (embedding, image, training, inference).
- refresh_pricing_from_catalog best-effort path.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.models.platform import CostCategory, UnifiedCost
from app.services.connectors.base import BaseConnector
from app.services.connectors.gemini_connector import (
    CACHE_READ_MULTIPLIER,
    DEFAULT_REGION,
    FALLBACK_PRICING,
    MODEL_PRICING,
    THINKING_TOKEN_MULTIPLIER,
    GeminiConnector,
    TokenUsage,
    _billing_table_fqn,
    _build_billing_query,
    _classify_http_error,
    _classify_sku,
    _estimate_cost,
    _extract_permission,
    _normalize_billing_account,
    _pricing_for_context,
    _resolve_pricing,
    estimate_cost,
    parse_usage_metadata,
)


# ─── TokenUsage ─────────────────────────────────────────────────────


class TestTokenUsage:
    def test_total_sums_every_field(self):
        u = TokenUsage(
            prompt_tokens=10,
            candidates_tokens=20,
            cached_content_tokens=5,
            thoughts_tokens=3,
            tool_use_prompt_tokens=2,
        )
        assert u.total == 40

    def test_billable_input_excludes_cached(self):
        u = TokenUsage(
            prompt_tokens=100,
            cached_content_tokens=200,
            tool_use_prompt_tokens=30,
        )
        assert u.billable_input_tokens == 130  # prompt + tool only
        assert u.cached_content_tokens == 200

    def test_billable_output_includes_thinking(self):
        u = TokenUsage(candidates_tokens=50, thoughts_tokens=25)
        assert u.billable_output_tokens == 75

    def test_addition_is_immutable(self):
        a = TokenUsage(prompt_tokens=1, candidates_tokens=2)
        b = TokenUsage(prompt_tokens=10, thoughts_tokens=4, cached_content_tokens=3)
        merged = a + b
        assert merged.prompt_tokens == 11
        assert merged.candidates_tokens == 2
        assert merged.cached_content_tokens == 3
        assert merged.thoughts_tokens == 4
        # Originals untouched
        assert a.prompt_tokens == 1
        assert b.candidates_tokens == 0

    def test_addition_rejects_non_tokenusage(self):
        a = TokenUsage()
        assert a.__add__(5) is NotImplemented


# ─── parse_usage_metadata ───────────────────────────────────────────


class TestParseUsageMetadata:
    def test_snake_case_keys(self):
        raw = {
            "prompt_token_count": 100,
            "candidates_token_count": 50,
            "cached_content_token_count": 20,
            "thoughts_token_count": 5,
            "tool_use_prompt_token_count": 3,
        }
        u = parse_usage_metadata(raw)
        assert u.prompt_tokens == 100
        assert u.candidates_tokens == 50
        assert u.cached_content_tokens == 20
        assert u.thoughts_tokens == 5
        assert u.tool_use_prompt_tokens == 3

    def test_camel_case_keys(self):
        raw = {
            "promptTokenCount": 42,
            "candidatesTokenCount": 11,
            "cachedContentTokenCount": 7,
            "thoughtsTokenCount": 2,
            "toolUsePromptTokenCount": 1,
        }
        u = parse_usage_metadata(raw)
        assert u.prompt_tokens == 42
        assert u.candidates_tokens == 11
        assert u.cached_content_tokens == 7

    def test_missing_fields_default_to_zero(self):
        u = parse_usage_metadata({})
        assert u.total == 0

    def test_coerces_strings_to_int(self):
        u = parse_usage_metadata({"prompt_token_count": "123"})
        assert u.prompt_tokens == 123

    def test_bad_types_fall_back_to_zero(self):
        u = parse_usage_metadata({"prompt_token_count": object()})
        assert u.prompt_tokens == 0


# ─── _resolve_pricing (prefix matching) ─────────────────────────────


class TestResolvePricing:
    @pytest.mark.parametrize(
        "model,expected_input",
        [
            ("gemini-2.5-pro", 1.25),
            ("gemini-2.5-pro-latest", 1.25),
            ("gemini-2.5-flash", 0.30),
            ("gemini-2.5-flash-lite", 0.10),
            # flash-lite must win over flash for a name containing both
            ("gemini-2.5-flash-lite-preview", 0.10),
            ("gemini-2.0-flash", 0.10),
            ("gemini-2.0-flash-lite", 0.075),
            ("gemini-2.0-pro", 1.25),
            ("gemini-1.5-pro", 1.25),
            ("gemini-1.5-flash", 0.075),
            ("gemini-1.5-flash-8b", 0.0375),
            ("gemini-1.0-pro", 0.50),
            ("gemini-exp-1206", 1.25),
            ("text-embedding-004", 0.025),
            ("embedding-001", 0.025),
        ],
    )
    def test_catalog_prefix_match(self, model: str, expected_input: float):
        price = _resolve_pricing(model)
        assert price["input"] == expected_input

    def test_strips_models_prefix(self):
        price = _resolve_pricing("models/gemini-2.5-flash-lite")
        assert price["input"] == 0.10

    def test_case_insensitive(self):
        price = _resolve_pricing("Gemini-2.5-Flash")
        assert price["input"] == 0.30

    def test_longer_prefix_wins_over_shorter(self):
        # gemini-2.5-flash-lite must beat gemini-2.5-flash for this input
        price = _resolve_pricing("gemini-2.5-flash-lite-001")
        assert price == MODEL_PRICING["gemini-2.5-flash-lite"]

    def test_unknown_model_falls_back(self):
        price = _resolve_pricing("totally-unknown-model")
        assert price == FALLBACK_PRICING

    def test_empty_model_falls_back(self):
        assert _resolve_pricing("") == FALLBACK_PRICING
        assert _resolve_pricing(None) == FALLBACK_PRICING  # type: ignore[arg-type]

    def test_pricing_overrides_win(self):
        override = {"gemini-2.5-pro": {"input": 99.0, "output": 100.0}}
        price = _resolve_pricing("gemini-2.5-pro", pricing_overrides=override)
        assert price["input"] == 99.0
        assert price["output"] == 100.0

    def test_new_model_via_overrides(self):
        override = {"gemini-3.0": {"input": 5.0, "output": 20.0}}
        price = _resolve_pricing("gemini-3.0-flash", pricing_overrides=override)
        assert price["input"] == 5.0

    def test_custom_table_replaces_catalog(self):
        table = {"my-model": {"input": 1.0, "output": 2.0}}
        price = _resolve_pricing("my-model-123", table=table)
        assert price["input"] == 1.0


# ─── _pricing_for_context (2.5 Pro context tier) ───────────────────


class TestContextTierPricing:
    def test_under_threshold_uses_base_rate(self):
        pro = MODEL_PRICING["gemini-2.5-pro"]
        rate_in, rate_out = _pricing_for_context(pro, prompt_tokens=50_000)
        assert rate_in == 1.25
        assert rate_out == 10.0

    def test_at_threshold_uses_base_rate(self):
        pro = MODEL_PRICING["gemini-2.5-pro"]
        rate_in, rate_out = _pricing_for_context(pro, prompt_tokens=200_000)
        assert rate_in == 1.25

    def test_over_threshold_uses_long_context_rate(self):
        pro = MODEL_PRICING["gemini-2.5-pro"]
        rate_in, rate_out = _pricing_for_context(pro, prompt_tokens=500_000)
        assert rate_in == 2.50
        assert rate_out == 15.0

    def test_flat_priced_model_ignores_tier(self):
        flash = MODEL_PRICING["gemini-2.5-flash"]
        rate_in, _ = _pricing_for_context(flash, prompt_tokens=10_000_000)
        assert rate_in == 0.30


# ─── estimate_cost ──────────────────────────────────────────────────


class TestEstimateCost:
    def test_vanilla_2_0_flash(self):
        # 2.0-flash: $0.10 in / $0.40 out per million
        usage = TokenUsage(prompt_tokens=1_000_000, candidates_tokens=1_000_000)
        cost = estimate_cost("gemini-2.0-flash", usage)
        assert cost == pytest.approx(0.50, rel=1e-6)

    def test_none_usage_returns_zero(self):
        assert estimate_cost("gemini-2.5-flash", None) == 0.0

    def test_zero_usage_returns_zero(self):
        cost = estimate_cost("gemini-2.5-pro", TokenUsage())
        assert cost == 0.0

    def test_cached_content_discount(self):
        # cached = 25% of input rate
        usage = TokenUsage(
            prompt_tokens=0,
            candidates_tokens=0,
            cached_content_tokens=1_000_000,
        )
        # 2.5-flash input rate is $0.30/M; cached at 25% ⇒ $0.075
        cost = estimate_cost("gemini-2.5-flash", usage)
        assert cost == pytest.approx(0.30 * CACHE_READ_MULTIPLIER, rel=1e-6)
        assert cost == pytest.approx(0.075, rel=1e-6)

    def test_thinking_tokens_charged_as_output(self):
        # 1M thoughts tokens on 2.5-flash (output $2.50/M) should cost $2.50
        usage = TokenUsage(thoughts_tokens=1_000_000)
        cost = estimate_cost("gemini-2.5-flash", usage)
        assert cost == pytest.approx(2.50 * THINKING_TOKEN_MULTIPLIER, rel=1e-6)

    def test_tool_use_prompt_charged_as_input(self):
        usage = TokenUsage(tool_use_prompt_tokens=1_000_000)
        cost = estimate_cost("gemini-2.5-flash", usage)  # input $0.30/M
        assert cost == pytest.approx(0.30, rel=1e-6)

    def test_context_tier_long_prompt(self):
        # 300k prompt on 2.5-pro: uses $2.50/M input, $15/M output
        usage = TokenUsage(prompt_tokens=300_000, candidates_tokens=100_000)
        cost = estimate_cost("gemini-2.5-pro", usage)
        expected = 300_000 * 2.50 / 1_000_000 + 100_000 * 15.0 / 1_000_000
        assert cost == pytest.approx(expected, rel=1e-6)

    def test_context_tier_short_prompt(self):
        usage = TokenUsage(prompt_tokens=100_000, candidates_tokens=100_000)
        cost = estimate_cost("gemini-2.5-pro", usage)
        expected = 100_000 * 1.25 / 1_000_000 + 100_000 * 10.0 / 1_000_000
        assert cost == pytest.approx(expected, rel=1e-6)

    def test_mixed_tiers_and_caching(self):
        usage = TokenUsage(
            prompt_tokens=50_000,
            candidates_tokens=10_000,
            cached_content_tokens=20_000,
            thoughts_tokens=5_000,
            tool_use_prompt_tokens=1_000,
        )
        cost = estimate_cost("gemini-2.5-flash", usage)
        # input: (50_000 + 1_000) × 0.30/M
        # output: (10_000 + 5_000) × 2.50/M
        # cached: 20_000 × 0.30 × 0.25 / M
        expected = (
            51_000 * 0.30 / 1_000_000
            + 15_000 * 2.50 / 1_000_000
            + 20_000 * 0.30 * CACHE_READ_MULTIPLIER / 1_000_000
        )
        assert cost == pytest.approx(expected, rel=1e-6)

    def test_pricing_overrides_applied(self):
        usage = TokenUsage(prompt_tokens=1_000_000, candidates_tokens=1_000_000)
        overrides = {"gemini-2.0-flash": {"input": 0.05, "output": 0.20}}
        cost = estimate_cost("gemini-2.0-flash", usage, pricing_overrides=overrides)
        assert cost == pytest.approx(0.25, rel=1e-6)


# ─── _estimate_cost (back-compat) ──────────────────────────────────


class TestBackCompatEstimateCost:
    def test_2_0_flash_round_trip(self):
        cost = _estimate_cost("gemini-2.0-flash", 1_000_000, 1_000_000)
        assert cost == pytest.approx(0.5, rel=1e-6)

    def test_unknown_model_falls_back(self):
        cost = _estimate_cost("unknown-xyz", 1_000_000, 0)
        # Flash-tier fallback $0.10/M input ⇒ $0.10
        assert cost == pytest.approx(0.10, rel=1e-6)

    def test_zero_tokens(self):
        assert _estimate_cost("gemini-2.5-pro", 0, 0) == 0.0


# ─── _billing_table_fqn / _normalize_billing_account ──────────────


class TestBillingTableFqn:
    def test_normalize_dashes_and_dots(self):
        assert _normalize_billing_account("01ABCD-234567-89EFGH") == "01ABCD_234567_89EFGH"
        assert _normalize_billing_account("A.B.C") == "A_B_C"

    def test_fqn_structure(self):
        fqn = _billing_table_fqn("bp", "ds", "01-02-03")
        assert fqn == "`bp.ds.gcp_billing_export_v1_01_02_03`"

    def test_empty_inputs_do_not_crash(self):
        # Still returns a backticked string with empty segments — the query will
        # obviously fail downstream, but we don't blow up during construction.
        fqn = _billing_table_fqn("", "", "")
        assert fqn.startswith("`")
        assert fqn.endswith("`")


# ─── _build_billing_query ───────────────────────────────────────────


class TestBuildBillingQuery:
    def test_contains_date_range(self):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        end = datetime(2026, 2, 1, tzinfo=timezone.utc)
        sql = _build_billing_query("`p.d.t`", start, end, project_id="proj-1")
        assert "DATE('2026-01-01')" in sql
        assert "DATE('2026-02-01')" in sql

    def test_filters_on_service_description(self):
        sql = _build_billing_query("`p.d.t`", datetime.now(), datetime.now())
        assert "Vertex AI" in sql
        assert "Generative Language API" in sql

    def test_project_filter_when_given(self):
        sql = _build_billing_query("`p.d.t`", datetime.now(), datetime.now(), "my-proj")
        assert "project.id = 'my-proj'" in sql

    def test_no_project_filter_when_none(self):
        sql = _build_billing_query("`p.d.t`", datetime.now(), datetime.now(), None)
        assert "project.id =" not in sql

    def test_groups_by_sku_and_day(self):
        sql = _build_billing_query("`p.d.t`", datetime.now(), datetime.now())
        assert "GROUP BY usage_date" in sql
        assert "sku_description" in sql


# ─── _classify_http_error + _extract_permission ────────────────────


class TestErrorClassification:
    def test_401(self):
        assert "Invalid" in _classify_http_error(401, "any body")

    def test_404(self):
        assert "not found" in _classify_http_error(404, "missing")

    def test_403_missing_permission_parsed(self):
        body = json.dumps({
            "error": {
                "code": 403,
                "message": "Permission 'bigquery.jobs.create' denied on resource ...",
            }
        })
        msg = _classify_http_error(403, body)
        assert "bigquery.jobs.create" in msg
        assert "Missing permission" in msg

    def test_403_api_disabled(self):
        body = json.dumps({
            "error": {
                "code": 403,
                "message": "BigQuery API has not been used in project X ...",
            }
        })
        msg = _classify_http_error(403, body)
        assert "API disabled" in msg or "has not been used" in msg.lower()

    def test_403_generic(self):
        msg = _classify_http_error(403, "nothing useful")
        assert "403" in msg or "Permission denied" in msg

    def test_500_generic(self):
        msg = _classify_http_error(500, "boom")
        assert msg.startswith("HTTP 500")

    def test_extract_permission_from_message(self):
        body = json.dumps({
            "error": {"message": "Required 'cloudbilling.services.list' permission"}
        })
        assert _extract_permission(body) == "cloudbilling.services.list"

    def test_extract_permission_returns_none_for_plain_text(self):
        assert _extract_permission("not json") is None
        assert _extract_permission("") is None


# ─── _classify_sku ──────────────────────────────────────────────────


class TestClassifySku:
    def test_embedding_sku(self):
        cat, model = _classify_sku("Text Embeddings (text-embedding-004) input")
        assert cat == CostCategory.ai_inference
        assert model == "text-embedding-004"

    def test_image_sku(self):
        cat, _ = _classify_sku("Gemini 2.0 Flash Image Generation output")
        assert cat == CostCategory.ai_inference

    def test_training_sku(self):
        cat, _ = _classify_sku("Vertex AI Training custom-container")
        assert cat == CostCategory.ml_training

    def test_inference_sku(self):
        cat, model = _classify_sku("Gemini 2.5 Pro generate content input")
        assert cat == CostCategory.ai_inference
        assert "gemini-2.5-pro" in model

    def test_unknown_defaults_to_vertex_ai(self):
        cat, model = _classify_sku("weird unknown sku")
        assert cat == CostCategory.ai_inference


# ─── GeminiConnector — base-contract + construction ─────────────────


class TestGeminiConnectorBasics:
    def test_is_base_connector(self):
        assert issubclass(GeminiConnector, BaseConnector)

    def test_platform_attribute(self):
        assert GeminiConnector.platform == "gemini"

    def test_construct_ai_studio_only(self):
        conn = GeminiConnector({"api_key": "k"})
        assert conn.use_vertex is False
        assert conn.has_billing_export is False
        assert conn.region == DEFAULT_REGION

    def test_construct_vertex_without_billing(self):
        conn = GeminiConnector({
            "service_account_json": '{"type":"service_account"}',
            "project_id": "p",
        })
        assert conn.use_vertex is True
        assert conn.has_billing_export is False

    def test_construct_full_vertex_plus_billing(self):
        conn = GeminiConnector({
            "service_account_json": '{"type":"service_account"}',
            "project_id": "p",
            "billing_project": "bp",
            "billing_dataset": "ds",
            "billing_account_id": "01-02-03",
        })
        assert conn.use_vertex is True
        assert conn.has_billing_export is True

    def test_region_honours_credentials(self):
        conn = GeminiConnector({"service_account_json": "{}", "project_id": "p", "region": "europe-west4"})
        assert conn.region == "europe-west4"

    def test_region_blank_falls_back_to_default(self):
        conn = GeminiConnector({"service_account_json": "{}", "project_id": "p", "region": "   "})
        assert conn.region == DEFAULT_REGION

    def test_billing_project_defaults_to_project_id(self):
        conn = GeminiConnector({
            "service_account_json": "{}",
            "project_id": "proj-a",
            "billing_dataset": "ds",
            "billing_account_id": "01-02-03",
        })
        assert conn.billing_project == "proj-a"
        assert conn.has_billing_export is True

    def test_pricing_overrides_captured(self):
        conn = GeminiConnector({
            "service_account_json": "{}",
            "project_id": "p",
            "pricing_overrides": {"gemini-2.5-flash": {"input": 0.01, "output": 0.02}},
        })
        assert conn.pricing_overrides == {"gemini-2.5-flash": {"input": 0.01, "output": 0.02}}

    def test_bad_pricing_overrides_shape_ignored(self):
        conn = GeminiConnector({
            "service_account_json": "{}",
            "project_id": "p",
            "pricing_overrides": "not-a-dict",
        })
        assert conn.pricing_overrides == {}


# ─── test_connection — AI Studio / Vertex / billing-export paths ───


@pytest.fixture
def vertex_creds_with_billing():
    return {
        "service_account_json": '{"type":"service_account"}',
        "project_id": "proj",
        "billing_project": "bp",
        "billing_dataset": "ds",
        "billing_account_id": "01-02-03",
    }


class TestTestConnection:
    def test_no_credentials(self):
        conn = GeminiConnector({})
        result = conn.test_connection()
        assert result["success"] is False
        assert "No credentials" in result["message"]

    def test_ai_studio_key_accepted_but_flagged(self):
        with patch("app.services.connectors.gemini_connector.httpx.get") as mock_get:
            mock_get.return_value = MagicMock(status_code=200, text="{}")
            conn = GeminiConnector({"api_key": "k"})
            result = conn.test_connection()
        assert result["success"] is False  # honest: no usage API
        assert "AI Studio" in result["message"]

    def test_ai_studio_bad_key(self):
        with patch("app.services.connectors.gemini_connector.httpx.get") as mock_get:
            mock_get.return_value = MagicMock(status_code=401, text="bad")
            conn = GeminiConnector({"api_key": "k"})
            result = conn.test_connection()
        assert result["success"] is False
        assert "Invalid" in result["message"] or "401" in result["message"]

    def test_vertex_no_billing_export_degrades_gracefully(self):
        with patch.object(GeminiConnector, "_get_access_token", return_value="tok"), \
             patch("app.services.connectors.gemini_connector.httpx.get") as mock_get:
            mock_get.return_value = MagicMock(status_code=200, text="{}")
            conn = GeminiConnector({
                "service_account_json": "{}",
                "project_id": "proj",
            })
            result = conn.test_connection()
        # Success stays true (SA is valid), but message warns about billing export.
        assert result["success"] is True
        assert "billing export" in result["message"].lower()

    def test_vertex_billing_export_ok(self, vertex_creds_with_billing):
        with patch.object(GeminiConnector, "_get_access_token", return_value="tok"), \
             patch("app.services.connectors.gemini_connector.httpx.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=200, text="{}")
            conn = GeminiConnector(vertex_creds_with_billing)
            result = conn.test_connection()
        assert result["success"] is True
        assert "billing export" in result["message"].lower()

    def test_vertex_billing_export_403_missing_permission(self, vertex_creds_with_billing):
        body = json.dumps({
            "error": {"message": "Permission 'bigquery.jobs.create' denied"}
        })
        with patch.object(GeminiConnector, "_get_access_token", return_value="tok"), \
             patch("app.services.connectors.gemini_connector.httpx.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=403, text=body)
            conn = GeminiConnector(vertex_creds_with_billing)
            result = conn.test_connection()
        assert result["success"] is False
        assert "bigquery.jobs.create" in result["message"]

    def test_vertex_billing_export_404_dataset_missing(self, vertex_creds_with_billing):
        with patch.object(GeminiConnector, "_get_access_token", return_value="tok"), \
             patch("app.services.connectors.gemini_connector.httpx.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=404, text="missing")
            conn = GeminiConnector(vertex_creds_with_billing)
            result = conn.test_connection()
        assert result["success"] is False
        assert "not found" in result["message"].lower()

    def test_vertex_billing_export_401_bad_sa(self, vertex_creds_with_billing):
        with patch.object(GeminiConnector, "_get_access_token", return_value="tok"), \
             patch("app.services.connectors.gemini_connector.httpx.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=401, text="nope")
            conn = GeminiConnector(vertex_creds_with_billing)
            result = conn.test_connection()
        assert result["success"] is False
        assert "Invalid" in result["message"]

    def test_vertex_billing_export_api_disabled(self, vertex_creds_with_billing):
        body = json.dumps({
            "error": {"message": "BigQuery API has not been used in project ..."}
        })
        with patch.object(GeminiConnector, "_get_access_token", return_value="tok"), \
             patch("app.services.connectors.gemini_connector.httpx.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=403, text=body)
            conn = GeminiConnector(vertex_creds_with_billing)
            result = conn.test_connection()
        assert result["success"] is False
        assert "api disabled" in result["message"].lower() or "has not been used" in result["message"].lower()

    def test_sa_auth_failure(self, vertex_creds_with_billing):
        with patch.object(GeminiConnector, "_get_access_token", side_effect=RuntimeError("bad key")):
            conn = GeminiConnector(vertex_creds_with_billing)
            result = conn.test_connection()
        assert result["success"] is False
        assert "auth" in result["message"].lower() or "bad key" in result["message"]


# ─── Region propagation ─────────────────────────────────────────────


class TestRegionPropagation:
    def test_vertex_models_endpoint_uses_region(self):
        """The models probe URL must include the configured region."""
        captured_urls: list[str] = []

        def capture_get(url, **kwargs):
            captured_urls.append(url)
            return MagicMock(status_code=200, text="{}")

        with patch.object(GeminiConnector, "_get_access_token", return_value="tok"), \
             patch("app.services.connectors.gemini_connector.httpx.get", side_effect=capture_get):
            conn = GeminiConnector({
                "service_account_json": "{}",
                "project_id": "proj",
                "region": "europe-west4",
            })
            conn.test_connection()

        assert any("europe-west4" in u for u in captured_urls)
        assert all("us-central1" not in u for u in captured_urls)


# ─── fetch_costs — end-to-end with mocked BigQuery ──────────────────


def _bq_row(
    usage_date: str,
    sku_description: str,
    sku_id: str,
    service_description: str,
    project_id: str,
    region: str,
    usage_amount: float,
    usage_unit: str,
    cost: float,
    currency: str = "USD",
    credits_amount: float = 0.0,
) -> dict:
    """Build one row in the shape the BigQuery ``queries`` REST endpoint returns."""
    values = [
        usage_date, sku_description, sku_id, service_description,
        project_id, region, str(usage_amount), usage_unit,
        str(cost), currency, str(credits_amount),
    ]
    return {"f": [{"v": v} for v in values]}


class TestFetchCosts:
    def test_ai_studio_returns_empty(self):
        conn = GeminiConnector({"api_key": "k"})
        assert conn.fetch_costs(days=30) == []

    def test_vertex_without_billing_returns_empty(self):
        conn = GeminiConnector({"service_account_json": "{}", "project_id": "p"})
        assert conn.fetch_costs(days=30) == []

    def test_auth_failure_returns_empty(self, vertex_creds_with_billing):
        with patch.object(GeminiConnector, "_get_access_token", side_effect=RuntimeError("x")):
            conn = GeminiConnector(vertex_creds_with_billing)
            assert conn.fetch_costs(days=30) == []

    def test_http_failure_returns_empty(self, vertex_creds_with_billing):
        with patch.object(GeminiConnector, "_get_access_token", return_value="tok"), \
             patch("app.services.connectors.gemini_connector.httpx.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=500, text="oops")
            conn = GeminiConnector(vertex_creds_with_billing)
            assert conn.fetch_costs(days=30) == []

    def test_happy_path_maps_rows_to_unified_costs(self, vertex_creds_with_billing):
        fake_response = {
            "rows": [
                _bq_row(
                    usage_date="2026-04-01",
                    sku_description="Gemini 2.5 Pro generate content input",
                    sku_id="SKU-1",
                    service_description="Vertex AI",
                    project_id="proj",
                    region="us-central1",
                    usage_amount=12345,
                    usage_unit="tokens",
                    cost=1.234567,
                ),
                _bq_row(
                    usage_date="2026-04-01",
                    sku_description="Gemini 2.5 Flash generate content output",
                    sku_id="SKU-2",
                    service_description="Vertex AI",
                    project_id="proj",
                    region="us-central1",
                    usage_amount=5000,
                    usage_unit="tokens",
                    cost=0.10,
                    credits_amount=-0.02,
                ),
                _bq_row(
                    usage_date="2026-04-02",
                    sku_description="Text Embeddings text-embedding-004 input",
                    sku_id="SKU-3",
                    service_description="Generative Language API",
                    project_id="proj",
                    region="us-central1",
                    usage_amount=1000,
                    usage_unit="characters",
                    cost=0.001,
                ),
            ]
        }

        with patch.object(GeminiConnector, "_get_access_token", return_value="tok"), \
             patch("app.services.connectors.gemini_connector.httpx.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=200, json=lambda: fake_response, text="")
            conn = GeminiConnector(vertex_creds_with_billing)
            costs = conn.fetch_costs(days=30)

        assert len(costs) == 3
        assert all(isinstance(c, UnifiedCost) for c in costs)
        assert all(c.platform == "gemini" for c in costs)
        assert costs[0].date == "2026-04-01"
        assert costs[0].category == CostCategory.ai_inference
        assert costs[0].cost_usd == pytest.approx(1.234567)
        # Credits reduce the net cost: 0.10 + (-0.02) = 0.08
        assert costs[1].cost_usd == pytest.approx(0.08, rel=1e-4)
        # Embedding SKU routes to Generative Language API → gemini_api service slug
        assert costs[2].service == "gemini_api"

    def test_skips_rows_with_no_cost_and_no_usage(self, vertex_creds_with_billing):
        fake_response = {
            "rows": [
                _bq_row(
                    usage_date="2026-04-01",
                    sku_description="x",
                    sku_id="s",
                    service_description="Vertex AI",
                    project_id="proj",
                    region="us-central1",
                    usage_amount=0,
                    usage_unit="",
                    cost=0,
                )
            ]
        }
        with patch.object(GeminiConnector, "_get_access_token", return_value="tok"), \
             patch("app.services.connectors.gemini_connector.httpx.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=200, json=lambda: fake_response, text="")
            conn = GeminiConnector(vertex_creds_with_billing)
            assert conn.fetch_costs(days=30) == []

    def test_sends_project_id_filter(self, vertex_creds_with_billing):
        captured: dict = {}

        def capture_post(url, **kwargs):
            captured["url"] = url
            captured["json"] = kwargs.get("json", {})
            return MagicMock(status_code=200, json=lambda: {"rows": []}, text="")

        with patch.object(GeminiConnector, "_get_access_token", return_value="tok"), \
             patch("app.services.connectors.gemini_connector.httpx.post", side_effect=capture_post):
            conn = GeminiConnector(vertex_creds_with_billing)
            conn.fetch_costs(days=7)

        # Must target the billing project (not the data project).
        assert "bp" in captured["url"]
        assert "project.id = 'proj'" in captured["json"]["query"]

    def test_custom_billing_table_respected(self, vertex_creds_with_billing):
        vertex_creds_with_billing["billing_table"] = "other_p.other_d.custom_table"
        captured: dict = {}

        def capture_post(url, **kwargs):
            captured["json"] = kwargs.get("json", {})
            return MagicMock(status_code=200, json=lambda: {"rows": []}, text="")

        with patch.object(GeminiConnector, "_get_access_token", return_value="tok"), \
             patch("app.services.connectors.gemini_connector.httpx.post", side_effect=capture_post):
            conn = GeminiConnector(vertex_creds_with_billing)
            conn.fetch_costs(days=7)

        assert "other_p.other_d.custom_table" in captured["json"]["query"]

    def test_days_parameter_bounds_query_range(self, vertex_creds_with_billing):
        captured: dict = {}

        def capture_post(url, **kwargs):
            captured["json"] = kwargs.get("json", {})
            return MagicMock(status_code=200, json=lambda: {"rows": []}, text="")

        with patch.object(GeminiConnector, "_get_access_token", return_value="tok"), \
             patch("app.services.connectors.gemini_connector.httpx.post", side_effect=capture_post):
            conn = GeminiConnector(vertex_creds_with_billing)
            conn.fetch_costs(days=14)

        q = captured["json"]["query"]
        # 14-day span — we can't know the exact date without mocking datetime,
        # but both dates should be present.
        assert q.count("DATE('") == 2

    def test_malformed_json_returns_empty(self, vertex_creds_with_billing):
        resp = MagicMock(status_code=200, text="not json")
        resp.json = MagicMock(side_effect=ValueError("bad"))
        with patch.object(GeminiConnector, "_get_access_token", return_value="tok"), \
             patch("app.services.connectors.gemini_connector.httpx.post", return_value=resp):
            conn = GeminiConnector(vertex_creds_with_billing)
            assert conn.fetch_costs(days=30) == []


# ─── refresh_pricing_from_catalog ──────────────────────────────────


class TestRefreshPricingFromCatalog:
    def test_no_service_account_returns_static_table(self):
        conn = GeminiConnector({"api_key": "k"})
        merged = conn.refresh_pricing_from_catalog()
        assert merged == MODEL_PRICING

    def test_auth_failure_returns_static_table(self):
        conn = GeminiConnector({"service_account_json": "{}", "project_id": "p"})
        with patch.object(GeminiConnector, "_get_access_token", side_effect=RuntimeError("x")):
            merged = conn.refresh_pricing_from_catalog()
        assert merged == MODEL_PRICING

    def test_merges_matching_sku_output_rate(self):
        """A SKU named 'Gemini 2.5 Flash ... output' with $0.000002/token
        (=$2/M) should override the output rate."""
        fake_skus = {
            "skus": [
                {
                    "description": "Gemini 2.5 Flash generate content output",
                    "pricingInfo": [{
                        "pricingExpression": {
                            "usageUnit": "1 tokens",
                            "tieredRates": [{
                                "unitPrice": {"units": 0, "nanos": 2_000},
                            }],
                        },
                    }],
                }
            ]
        }
        with patch.object(GeminiConnector, "_get_access_token", return_value="tok"), \
             patch("app.services.connectors.gemini_connector.httpx.get") as mock_get:
            mock_get.return_value = MagicMock(status_code=200, json=lambda: fake_skus)
            conn = GeminiConnector({"service_account_json": "{}", "project_id": "p"})
            merged = conn.refresh_pricing_from_catalog()
        # 2_000 nanos / 1e9 = 2e-6 per token → 2.0 per million
        assert merged["gemini-2.5-flash"]["output"] == pytest.approx(2.0, rel=1e-6)
        # Input rate still matches static catalog (was not in the SKU).
        assert merged["gemini-2.5-flash"]["input"] == MODEL_PRICING["gemini-2.5-flash"]["input"]

    def test_catalog_http_error_is_swallowed(self):
        with patch.object(GeminiConnector, "_get_access_token", return_value="tok"), \
             patch("app.services.connectors.gemini_connector.httpx.get") as mock_get:
            mock_get.return_value = MagicMock(status_code=403, json=lambda: {})
            conn = GeminiConnector({"service_account_json": "{}", "project_id": "p"})
            merged = conn.refresh_pricing_from_catalog()
        assert merged == MODEL_PRICING


# ─── Module-level pricing-table sanity checks ───────────────────────


class TestPricingTableCompleteness:
    REQUIRED_MODELS = [
        "gemini-2.5-pro",
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
        "gemini-1.5-pro",
        "gemini-1.5-flash",
        "embedding-001",
        "text-embedding-004",
    ]

    @pytest.mark.parametrize("model", REQUIRED_MODELS)
    def test_required_models_present(self, model: str):
        assert model in MODEL_PRICING, f"Missing pricing for {model}"

    def test_pro_has_context_tier(self):
        pro = MODEL_PRICING["gemini-2.5-pro"]
        assert "context_tier_tokens" in pro
        assert pro["context_tier_tokens"] == 200_000
        assert pro["input_over_200k"] > pro["input"]
        assert pro["output_over_200k"] > pro["output"]

    def test_fallback_is_conservative(self):
        # Flash-level defaults — cheapest safe fallback.
        assert FALLBACK_PRICING["input"] <= 0.50
        assert FALLBACK_PRICING["output"] <= 1.50
