"""Tests for ``app.services.connectors.errors`` — the unified error taxonomy."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services.connectors.errors import (
    APIDisabledError,
    CostlyConnectorError,
    DataLaggedError,
    DEFAULT_DOCS_BASE,
    InvalidCredentialsError,
    QuotaExceededError,
    RateLimitedError,
    ScopeMissingError,
    SchemaDriftError,
    VendorDownError,
    WarehouseNotFoundError,
    _render_json_response,
    is_retryable,
    register_connector_exception_handler,
)


class TestHierarchy:
    """Every concrete class must inherit from ``CostlyConnectorError``."""

    @pytest.mark.parametrize(
        "cls",
        [
            InvalidCredentialsError,
            ScopeMissingError,
            WarehouseNotFoundError,
            RateLimitedError,
            APIDisabledError,
            DataLaggedError,
            VendorDownError,
            SchemaDriftError,
            QuotaExceededError,
        ],
    )
    def test_is_subclass(self, cls: type) -> None:
        assert issubclass(cls, CostlyConnectorError)
        assert issubclass(cls, Exception)

    def test_can_raise_and_catch_as_base(self) -> None:
        with pytest.raises(CostlyConnectorError):
            raise RateLimitedError(platform="aws", endpoint="/ce")


class TestDefaultRendering:
    def test_default_codes_are_stable(self) -> None:
        """Wire codes are public API — they MUST NOT change without a migration."""
        assert CostlyConnectorError().code == "connector_error"
        assert InvalidCredentialsError().code == "invalid_credentials"
        assert ScopeMissingError().code == "scope_missing"
        assert WarehouseNotFoundError().code == "warehouse_not_found"
        assert RateLimitedError().code == "rate_limited"
        assert APIDisabledError().code == "api_disabled"
        assert DataLaggedError().code == "data_lagged"
        assert VendorDownError().code == "vendor_down"
        assert SchemaDriftError().code == "schema_drift"
        assert QuotaExceededError().code == "quota_exceeded"

    def test_http_status_codes(self) -> None:
        assert InvalidCredentialsError().http_status == 401
        assert ScopeMissingError().http_status == 403
        assert WarehouseNotFoundError().http_status == 404
        assert APIDisabledError().http_status == 409
        assert RateLimitedError().http_status == 429
        assert QuotaExceededError().http_status == 429
        assert DataLaggedError().http_status == 503
        assert VendorDownError().http_status == 502
        assert SchemaDriftError().http_status == 502

    def test_remediation_url_points_at_code(self) -> None:
        err = RateLimitedError(platform="anthropic", endpoint="/x")
        assert err.remediation_url == f"{DEFAULT_DOCS_BASE}/rate_limited"

    def test_default_message_includes_vendor_message(self) -> None:
        err = RateLimitedError(
            platform="anthropic",
            endpoint="/x",
            vendor_message="slow down buddy",
        )
        assert "slow down buddy" in str(err)
        assert "anthropic" in str(err)

    def test_default_message_without_vendor_message(self) -> None:
        err = RateLimitedError(platform="anthropic")
        assert "rate_limited" in str(err)
        assert "anthropic" in str(err)


class TestToDict:
    def test_base_envelope(self) -> None:
        err = RateLimitedError(
            platform="anthropic",
            endpoint="/v1/usage",
            vendor_code="429",
            vendor_message="slow down",
        )
        d = err.to_dict()
        assert d["code"] == "rate_limited"
        assert d["platform"] == "anthropic"
        assert d["endpoint"] == "/v1/usage"
        assert d["vendor_code"] == "429"
        assert d["vendor_message"] == "slow down"
        assert d["remediation_url"].endswith("/rate_limited")

    def test_rate_limited_includes_retry_after(self) -> None:
        err = RateLimitedError(retry_after=45)
        d = err.to_dict()
        assert d["retry_after"] == 45

    def test_rate_limited_omits_retry_after_when_zero(self) -> None:
        err = RateLimitedError(retry_after=0)
        assert "retry_after" not in err.to_dict()

    def test_scope_missing_includes_required_scope(self) -> None:
        err = ScopeMissingError(required_scope="ce:GetCostAndUsage")
        assert err.to_dict()["required_scope"] == "ce:GetCostAndUsage"

    def test_scope_missing_omits_required_scope_when_blank(self) -> None:
        assert "required_scope" not in ScopeMissingError().to_dict()

    def test_warehouse_not_found_includes_resource(self) -> None:
        err = WarehouseNotFoundError(resource_name="ANALYTICS_WH")
        assert err.to_dict()["resource_name"] == "ANALYTICS_WH"

    def test_schema_drift_includes_missing_field(self) -> None:
        err = SchemaDriftError(missing_field="usage.input_tokens")
        assert err.to_dict()["missing_field"] == "usage.input_tokens"

    def test_quota_exceeded_includes_reset(self) -> None:
        err = QuotaExceededError(reset_at="2026-04-24T00:00:00Z")
        assert err.to_dict()["reset_at"] == "2026-04-24T00:00:00Z"

    def test_remediation_hint_included_when_present(self) -> None:
        err = RateLimitedError(remediation_hint="increase tier")
        assert err.to_dict()["remediation_hint"] == "increase tier"

    def test_remediation_hint_omitted_by_default(self) -> None:
        assert "remediation_hint" not in RateLimitedError().to_dict()


class TestIsRetryable:
    def test_retryable_set(self) -> None:
        assert is_retryable(RateLimitedError())
        assert is_retryable(DataLaggedError())
        assert is_retryable(VendorDownError())

    def test_non_retryable(self) -> None:
        assert not is_retryable(InvalidCredentialsError())
        assert not is_retryable(ScopeMissingError())
        assert not is_retryable(WarehouseNotFoundError())
        assert not is_retryable(APIDisabledError())
        assert not is_retryable(SchemaDriftError())
        assert not is_retryable(QuotaExceededError())

    def test_arbitrary_exception_not_retryable(self) -> None:
        assert not is_retryable(ValueError("x"))
        assert not is_retryable(RuntimeError("x"))


class TestRenderJsonResponse:
    def test_status_code(self) -> None:
        resp = _render_json_response(RateLimitedError(retry_after=30))
        assert resp.status_code == 429

    def test_retry_after_header_set(self) -> None:
        resp = _render_json_response(RateLimitedError(retry_after=30))
        assert resp.headers.get("retry-after") == "30"

    def test_no_retry_after_header_when_zero(self) -> None:
        resp = _render_json_response(RateLimitedError())
        assert "retry-after" not in {k.lower() for k in resp.headers.keys()}

    def test_other_errors_have_no_retry_after_header(self) -> None:
        resp = _render_json_response(ScopeMissingError())
        assert "retry-after" not in {k.lower() for k in resp.headers.keys()}


class TestRouterIntegration:
    def _build_app(self) -> FastAPI:
        app = FastAPI()
        register_connector_exception_handler(app)

        @app.get("/boom/{code}")
        def boom(code: str):
            if code == "rate":
                raise RateLimitedError(
                    platform="anthropic",
                    endpoint="/usage",
                    vendor_code="429",
                    vendor_message="too fast",
                    retry_after=17,
                )
            if code == "scope":
                raise ScopeMissingError(
                    platform="aws",
                    endpoint="/ce",
                    required_scope="ce:GetCostAndUsage",
                )
            if code == "auth":
                raise InvalidCredentialsError(platform="openai", endpoint="/v1/usage")
            if code == "lag":
                raise DataLaggedError(platform="aws", endpoint="/ce")
            if code == "down":
                raise VendorDownError(platform="snowflake", endpoint="/query")
            if code == "disabled":
                raise APIDisabledError(platform="gcp", endpoint="/bq/jobs")
            if code == "drift":
                raise SchemaDriftError(
                    platform="anthropic",
                    missing_field="usage.cache_read_input_tokens",
                )
            if code == "quota":
                raise QuotaExceededError(
                    platform="github", reset_at="2026-04-24T00:00:00Z"
                )
            if code == "whnotfound":
                raise WarehouseNotFoundError(
                    platform="snowflake", resource_name="MISSING_WH"
                )
            raise CostlyConnectorError(platform="x", endpoint="/x")

        return app

    def test_rate_limited_response(self) -> None:
        client = TestClient(self._build_app())
        r = client.get("/boom/rate")
        assert r.status_code == 429
        assert r.headers.get("retry-after") == "17"
        body = r.json()["error"]
        assert body["code"] == "rate_limited"
        assert body["platform"] == "anthropic"
        assert body["endpoint"] == "/usage"
        assert body["retry_after"] == 17
        assert body["remediation_url"].endswith("/rate_limited")

    def test_scope_missing_response(self) -> None:
        client = TestClient(self._build_app())
        r = client.get("/boom/scope")
        assert r.status_code == 403
        body = r.json()["error"]
        assert body["code"] == "scope_missing"
        assert body["required_scope"] == "ce:GetCostAndUsage"

    def test_invalid_credentials_response(self) -> None:
        client = TestClient(self._build_app())
        r = client.get("/boom/auth")
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "invalid_credentials"

    def test_data_lagged_response(self) -> None:
        client = TestClient(self._build_app())
        r = client.get("/boom/lag")
        assert r.status_code == 503
        assert r.json()["error"]["code"] == "data_lagged"

    def test_vendor_down_response(self) -> None:
        client = TestClient(self._build_app())
        r = client.get("/boom/down")
        assert r.status_code == 502
        assert r.json()["error"]["code"] == "vendor_down"

    def test_api_disabled_response(self) -> None:
        client = TestClient(self._build_app())
        r = client.get("/boom/disabled")
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "api_disabled"

    def test_schema_drift_response(self) -> None:
        client = TestClient(self._build_app())
        r = client.get("/boom/drift")
        assert r.status_code == 502
        body = r.json()["error"]
        assert body["code"] == "schema_drift"
        assert body["missing_field"] == "usage.cache_read_input_tokens"

    def test_quota_exceeded_response(self) -> None:
        client = TestClient(self._build_app())
        r = client.get("/boom/quota")
        assert r.status_code == 429
        body = r.json()["error"]
        assert body["code"] == "quota_exceeded"
        assert body["reset_at"] == "2026-04-24T00:00:00Z"

    def test_warehouse_not_found_response(self) -> None:
        client = TestClient(self._build_app())
        r = client.get("/boom/whnotfound")
        assert r.status_code == 404
        body = r.json()["error"]
        assert body["code"] == "warehouse_not_found"
        assert body["resource_name"] == "MISSING_WH"

    def test_base_class_response(self) -> None:
        client = TestClient(self._build_app())
        r = client.get("/boom/unknown")
        assert r.status_code == 502
        assert r.json()["error"]["code"] == "connector_error"
