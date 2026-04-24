"""Tests for the System-Tables Databricks connector.

Verifies:
  * Structured error codes from test_connection (SCOPE_MISSING, PERMISSION_DENIED,
    TABLE_ACCESS_DENIED, WAREHOUSE_NOT_FOUND, CONNECTION_FAILED).
  * Parameterized SKU → category matrix (JOBS, ALL_PURPOSE, SQL, DLT,
    MODEL_SERVING, AGENT_BRICKS, APPS, VECTOR_SEARCH, DATABASE, FOUNDATION).
  * pricing_overrides (per-SKU and global dbu_discount_pct).
  * Photon flag preserved in metadata.
  * Per-job / per-notebook / per-warehouse / per-user attribution populated.
  * Cloud / tier SKU selection surfaces the right list price.
  * Fallback to empty list when warehouse_http_path missing (no fantasy math).
  * No usage of deprecated `/accounts/{id}/usage/download` endpoint.
  * datetime.utcnow() not used.
"""

from __future__ import annotations

import re
from unittest.mock import MagicMock, patch

import pytest

from app.models.platform import CostCategory, UnifiedCost
from app.services.connectors.base import BaseConnector
from app.services.connectors.databricks_connector import (
    BILLING_PRODUCT_CATEGORY,
    CLOUD_INFRA_NOTE,
    CONNECTION_FAILED,
    DatabricksConnector,
    PERMISSION_DENIED,
    SCOPE_MISSING,
    TABLE_ACCESS_DENIED,
    WAREHOUSE_NOT_FOUND,
    _apply_pricing_overrides,
    _classify,
    _coerce_mapping,
    _is_photon,
    _resolve_project,
    _resolve_resource,
    _resolve_team,
    _validate_credentials,
)
from tests.fixtures.databricks_usage import (
    AGENT_BRICKS_ROW,
    ALL_PURPOSE_ROW,
    APPS_ROW,
    DATABASE_ROW,
    DLT_ROW,
    FOUNDATION_ROW,
    JOBS_ROW,
    MODEL_SERVING_ROW,
    PHOTON_ROW,
    SQL_ROW,
    UNKNOWN_PRODUCT_ROW,
    VECTOR_SEARCH_ROW,
    ZERO_ROW,
    make_row,
)


# ─── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def full_credentials() -> dict:
    return {
        "access_token": "dapi-test-token",
        "server_hostname": "dbc-abc.cloud.databricks.com",
        "warehouse_http_path": "/sql/1.0/warehouses/abc123",
        "cloud": "AWS",
    }


@pytest.fixture
def legacy_only_credentials() -> dict:
    """Old-school credentials without warehouse_http_path — should fall back."""
    return {
        "access_token": "dapi-test-token",
        "account_id": "acc-1",
        "workspace_url": "https://test.cloud.databricks.com",
    }


def _mock_connection(rows: list[dict]) -> MagicMock:
    """Build a `databricks.sql.connect()` mock that yields `rows` on fetchall()."""
    cursor = MagicMock(name="cursor")
    cursor.fetchall.return_value = rows
    cursor.__enter__ = MagicMock(return_value=cursor)
    cursor.__exit__ = MagicMock(return_value=False)

    conn = MagicMock(name="conn")
    conn.cursor.return_value = cursor
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    return conn


def _patch_sql_connect(connector: DatabricksConnector, conn: MagicMock) -> patch:
    return patch.object(connector, "_sql_connect", return_value=conn)


# ─── BaseConnector / contract ──────────────────────────────────────────────


class TestContract:
    def test_is_base_connector_subclass(self):
        assert issubclass(DatabricksConnector, BaseConnector)

    def test_platform_string(self):
        assert DatabricksConnector.platform == "databricks"

    def test_instantiation(self, full_credentials):
        conn = DatabricksConnector(full_credentials)
        assert conn.server_hostname == "dbc-abc.cloud.databricks.com"
        assert conn.warehouse_http_path == "/sql/1.0/warehouses/abc123"
        assert conn.cloud == "AWS"
        assert conn.pricing_overrides == {}

    def test_instantiation_backward_compat(self, legacy_only_credentials):
        """Old credentials dict without server_hostname must still instantiate.

        We only fail at connect-time, not at construction.
        """
        conn = DatabricksConnector(legacy_only_credentials)
        assert conn.server_hostname == ""
        assert conn.warehouse_http_path == ""
        assert conn.account_id == "acc-1"


# ─── Credential validation + error codes ───────────────────────────────────


class TestCredentials:
    def test_validate_rejects_missing_token(self):
        result = _validate_credentials({"server_hostname": "x", "warehouse_http_path": "/y"})
        assert result.ok is False
        assert result.error_code == SCOPE_MISSING
        assert "access_token" in result.message

    def test_validate_rejects_missing_hostname(self):
        result = _validate_credentials({"access_token": "x", "warehouse_http_path": "/y"})
        assert result.ok is False
        assert result.error_code == SCOPE_MISSING
        assert "server_hostname" in result.message

    def test_validate_rejects_missing_warehouse_path(self):
        result = _validate_credentials({"access_token": "x", "server_hostname": "h"})
        assert result.ok is False
        assert result.error_code == SCOPE_MISSING
        assert "warehouse_http_path" in result.message

    def test_validate_accepts_all_three(self, full_credentials):
        result = _validate_credentials(full_credentials)
        assert result.ok is True


class TestTestConnection:
    def test_scope_missing_when_no_warehouse_path(self, legacy_only_credentials):
        conn = DatabricksConnector(legacy_only_credentials)
        result = conn.test_connection()
        assert result["success"] is False
        assert result["error_code"] == SCOPE_MISSING

    def test_success(self, full_credentials):
        conn = DatabricksConnector(full_credentials)
        mock_conn = _mock_connection([])
        with _patch_sql_connect(conn, mock_conn):
            result = conn.test_connection()
        assert result["success"] is True
        # Two probe queries were executed: SELECT 1 + SELECT 1 FROM system.billing.usage
        cursor = mock_conn.cursor.return_value
        executed = [call.args[0] for call in cursor.execute.call_args_list]
        assert any("SELECT 1" == sql or "SELECT 1\n" == sql for sql in executed) or \
               any(sql.strip().startswith("SELECT 1") for sql in executed)
        assert any("system.billing.usage" in sql for sql in executed)

    def test_permission_denied_classification(self, full_credentials):
        conn = DatabricksConnector(full_credentials)
        mock_conn = _mock_connection([])
        mock_conn.cursor.return_value.execute.side_effect = RuntimeError(
            "[PERMISSION_DENIED] User not authorized to execute query on system.billing.usage"
        )
        with _patch_sql_connect(conn, mock_conn):
            result = conn.test_connection()
        assert result["success"] is False
        # either TABLE_ACCESS_DENIED (specific) or PERMISSION_DENIED — both acceptable
        assert result["error_code"] in (TABLE_ACCESS_DENIED, PERMISSION_DENIED)

    def test_warehouse_not_found_classification(self, full_credentials):
        conn = DatabricksConnector(full_credentials)
        mock_conn = _mock_connection([])
        mock_conn.cursor.return_value.execute.side_effect = RuntimeError(
            "Warehouse abc123 does not exist"
        )
        with _patch_sql_connect(conn, mock_conn):
            result = conn.test_connection()
        assert result["success"] is False
        assert result["error_code"] == WAREHOUSE_NOT_FOUND

    def test_unauthorized_classification(self, full_credentials):
        conn = DatabricksConnector(full_credentials)

        def _boom(*_a, **_k):
            raise RuntimeError("HTTP 401 Unauthorized — invalid token")

        with patch.object(conn, "_sql_connect", side_effect=_boom):
            result = conn.test_connection()
        assert result["success"] is False
        assert result["error_code"] == PERMISSION_DENIED

    def test_generic_connection_failure(self, full_credentials):
        conn = DatabricksConnector(full_credentials)
        with patch.object(
            conn, "_sql_connect", side_effect=RuntimeError("Connection reset by peer")
        ):
            result = conn.test_connection()
        assert result["success"] is False
        assert result["error_code"] == CONNECTION_FAILED


# ─── fetch_costs: happy path with parameterized SKUs ───────────────────────


SKU_CASES = [
    pytest.param(JOBS_ROW,             CostCategory.compute,        10.0 * 0.15, id="JOBS"),
    pytest.param(ALL_PURPOSE_ROW,      CostCategory.compute,         4.0 * 0.55, id="ALL_PURPOSE"),
    pytest.param(SQL_ROW,              CostCategory.compute,        20.0 * 0.22, id="SQL"),
    pytest.param(DLT_ROW,              CostCategory.transformation,  5.0 * 0.36, id="DLT"),
    pytest.param(MODEL_SERVING_ROW,    CostCategory.ml_serving,    100.0 * 0.07, id="MODEL_SERVING"),
    pytest.param(FOUNDATION_ROW,       CostCategory.ml_training,     2.0 * 1.60, id="FOUNDATION_MODEL_TRAINING"),
    pytest.param(AGENT_BRICKS_ROW,     CostCategory.ai_inference,    3.0 * 0.30, id="AGENT_BRICKS"),
    pytest.param(APPS_ROW,             CostCategory.serving,         6.5 * 0.10, id="APPS"),
    pytest.param(VECTOR_SEARCH_ROW,    CostCategory.serving,         1.5 * 0.55, id="VECTOR_SEARCH"),
    pytest.param(DATABASE_ROW,         CostCategory.storage,        12.0 * 0.10, id="DATABASE"),
]


class TestFetchCostsPerSku:

    @pytest.mark.parametrize("row,expected_category,expected_cost", SKU_CASES)
    def test_sku_family(self, full_credentials, row, expected_category, expected_cost):
        conn = DatabricksConnector(full_credentials)
        mock_conn = _mock_connection([row])
        with _patch_sql_connect(conn, mock_conn):
            costs = conn.fetch_costs(days=7)

        assert len(costs) == 1
        c = costs[0]
        assert isinstance(c, UnifiedCost)
        assert c.platform == "databricks"
        assert c.category == expected_category
        assert c.cost_usd == pytest.approx(expected_cost, rel=1e-6)
        assert c.usage_unit == "DBU"
        assert c.metadata["sku"] == row["sku_name"]
        assert c.metadata["billing_origin_product"] == row["billing_origin_product"]
        assert c.metadata["note"] == CLOUD_INFRA_NOTE
        assert c.metadata["currency_code"] == "USD"

    def test_multiple_skus_in_one_fetch(self, full_credentials):
        rows = [JOBS_ROW, DLT_ROW, MODEL_SERVING_ROW, APPS_ROW]
        conn = DatabricksConnector(full_credentials)
        mock_conn = _mock_connection(rows)
        with _patch_sql_connect(conn, mock_conn):
            costs = conn.fetch_costs(days=30)
        assert len(costs) == 4
        # Ensure each category shows up exactly as expected (no second-pass overwrite bug)
        categories = {c.category for c in costs}
        assert CostCategory.compute in categories
        assert CostCategory.transformation in categories
        assert CostCategory.ml_serving in categories
        assert CostCategory.serving in categories

    def test_zero_quantity_rows_skipped(self, full_credentials):
        conn = DatabricksConnector(full_credentials)
        mock_conn = _mock_connection([ZERO_ROW, JOBS_ROW])
        with _patch_sql_connect(conn, mock_conn):
            costs = conn.fetch_costs(days=7)
        assert len(costs) == 1
        assert costs[0].metadata["sku"] == "STANDARD_JOBS_COMPUTE"

    def test_unknown_product_falls_back_to_compute(self, full_credentials):
        conn = DatabricksConnector(full_credentials)
        mock_conn = _mock_connection([UNKNOWN_PRODUCT_ROW])
        with _patch_sql_connect(conn, mock_conn):
            costs = conn.fetch_costs(days=7)
        assert len(costs) == 1
        assert costs[0].category == CostCategory.compute
        assert costs[0].metadata["billing_origin_product"] == "BRAND_NEW_2027_PRODUCT"


# ─── Attribution: job / notebook / user / warehouse ────────────────────────


class TestAttribution:
    def test_job_attribution(self, full_credentials):
        conn = DatabricksConnector(full_credentials)
        mock_conn = _mock_connection([JOBS_ROW])
        with _patch_sql_connect(conn, mock_conn):
            costs = conn.fetch_costs(days=7)

        c = costs[0]
        assert c.resource == "daily-etl"  # job_name preferred over job_id
        assert c.metadata["job_id"] == "987"
        assert c.metadata["job_run_id"] == "run-42"
        assert c.metadata["cluster_id"] == "0423-abc"
        assert c.team == "data-platform"
        # custom_tags.env is carried through for downstream filtering
        assert c.metadata["custom_tags"]["env"] == "prod"

    def test_notebook_attribution(self, full_credentials):
        conn = DatabricksConnector(full_credentials)
        mock_conn = _mock_connection([ALL_PURPOSE_ROW])
        with _patch_sql_connect(conn, mock_conn):
            costs = conn.fetch_costs(days=7)
        c = costs[0]
        assert c.metadata["notebook_id"] == "n-1"
        assert c.metadata["notebook_path"] == "/Users/ada/analysis"
        # owner from custom_tags surfaces as team when team/cost_center absent
        assert c.team == "ada@example.com"

    def test_warehouse_attribution(self, full_credentials):
        conn = DatabricksConnector(full_credentials)
        mock_conn = _mock_connection([SQL_ROW])
        with _patch_sql_connect(conn, mock_conn):
            costs = conn.fetch_costs(days=7)
        c = costs[0]
        assert c.metadata["warehouse_id"] == "wh-xyz"
        assert c.resource == "wh-xyz"

    def test_run_as_user_attribution(self, full_credentials):
        conn = DatabricksConnector(full_credentials)
        mock_conn = _mock_connection([JOBS_ROW])
        with _patch_sql_connect(conn, mock_conn):
            costs = conn.fetch_costs(days=7)
        assert costs[0].metadata["run_as"] == "etl@example.com"

    def test_project_from_custom_tags(self, full_credentials):
        conn = DatabricksConnector(full_credentials)
        mock_conn = _mock_connection([MODEL_SERVING_ROW])
        with _patch_sql_connect(conn, mock_conn):
            costs = conn.fetch_costs(days=7)
        assert costs[0].project == "chatbot"


# ─── Photon tagging ────────────────────────────────────────────────────────


class TestPhoton:
    def test_photon_flag_preserved(self, full_credentials):
        conn = DatabricksConnector(full_credentials)
        mock_conn = _mock_connection([PHOTON_ROW])
        with _patch_sql_connect(conn, mock_conn):
            costs = conn.fetch_costs(days=7)
        c = costs[0]
        assert c.metadata["photon_enabled"] is True
        # Cost should be exactly quantity * list price — Databricks pre-doubled usage_quantity.
        assert c.cost_usd == pytest.approx(8.0 * 0.55, rel=1e-6)

    def test_photon_flag_absent_is_false(self, full_credentials):
        conn = DatabricksConnector(full_credentials)
        mock_conn = _mock_connection([JOBS_ROW])  # No photon_enabled key
        with _patch_sql_connect(conn, mock_conn):
            costs = conn.fetch_costs(days=7)
        assert costs[0].metadata["photon_enabled"] is False


# ─── pricing_overrides ─────────────────────────────────────────────────────


class TestPricingOverrides:
    def test_per_sku_override_replaces_list_price(self, full_credentials):
        creds = {**full_credentials, "pricing_overrides": {"STANDARD_JOBS_COMPUTE": 0.10}}
        conn = DatabricksConnector(creds)
        mock_conn = _mock_connection([JOBS_ROW])
        with _patch_sql_connect(conn, mock_conn):
            costs = conn.fetch_costs(days=7)
        c = costs[0]
        assert c.cost_usd == pytest.approx(10.0 * 0.10, rel=1e-6)
        assert c.metadata["effective_price_per_unit"] == pytest.approx(0.10)
        assert c.metadata["list_price_per_unit"] == pytest.approx(0.15)

    def test_case_insensitive_sku_override(self, full_credentials):
        creds = {**full_credentials, "pricing_overrides": {"standard_jobs_compute": 0.08}}
        conn = DatabricksConnector(creds)
        mock_conn = _mock_connection([JOBS_ROW])
        with _patch_sql_connect(conn, mock_conn):
            costs = conn.fetch_costs(days=7)
        assert costs[0].cost_usd == pytest.approx(10.0 * 0.08, rel=1e-6)

    def test_dbu_discount_pct_applies_to_all(self, full_credentials):
        creds = {**full_credentials, "pricing_overrides": {"dbu_discount_pct": 30}}
        conn = DatabricksConnector(creds)
        mock_conn = _mock_connection([JOBS_ROW, DLT_ROW])
        with _patch_sql_connect(conn, mock_conn):
            costs = conn.fetch_costs(days=7)
        # Each SKU gets list_price * 0.7
        by_sku = {c.metadata["sku"]: c.cost_usd for c in costs}
        assert by_sku["STANDARD_JOBS_COMPUTE"] == pytest.approx(10 * 0.15 * 0.7, rel=1e-6)
        assert by_sku["PREMIUM_DLT_ADVANCED_COMPUTE"] == pytest.approx(5 * 0.36 * 0.7, rel=1e-6)

    def test_per_sku_beats_global_discount(self, full_credentials):
        creds = {
            **full_credentials,
            "pricing_overrides": {
                "STANDARD_JOBS_COMPUTE": 0.05,  # explicit per-SKU wins
                "dbu_discount_pct": 50,
            },
        }
        conn = DatabricksConnector(creds)
        mock_conn = _mock_connection([JOBS_ROW])
        with _patch_sql_connect(conn, mock_conn):
            costs = conn.fetch_costs(days=7)
        assert costs[0].cost_usd == pytest.approx(10.0 * 0.05, rel=1e-6)

    def test_generic_discount_pct(self, full_credentials):
        creds = {**full_credentials, "pricing_overrides": {"discount_pct": 20}}
        conn = DatabricksConnector(creds)
        mock_conn = _mock_connection([JOBS_ROW])
        with _patch_sql_connect(conn, mock_conn):
            costs = conn.fetch_costs(days=7)
        assert costs[0].cost_usd == pytest.approx(10.0 * 0.15 * 0.8, rel=1e-6)

    def test_invalid_override_value_ignored(self, full_credentials):
        creds = {**full_credentials, "pricing_overrides": {"STANDARD_JOBS_COMPUTE": "free"}}
        conn = DatabricksConnector(creds)
        mock_conn = _mock_connection([JOBS_ROW])
        with _patch_sql_connect(conn, mock_conn):
            costs = conn.fetch_costs(days=7)
        assert costs[0].cost_usd == pytest.approx(10.0 * 0.15, rel=1e-6)


# ─── Cloud / tier SKU matrix ───────────────────────────────────────────────


class TestCloudAndTier:
    def test_cloud_surfaces_in_metadata(self, full_credentials):
        conn = DatabricksConnector(full_credentials)
        mock_conn = _mock_connection([JOBS_ROW])
        with _patch_sql_connect(conn, mock_conn):
            costs = conn.fetch_costs(days=7)
        assert costs[0].metadata["cloud"] == "AWS"

    def test_different_tier_picks_its_own_price(self, full_credentials):
        """Premium All-Purpose vs Standard Jobs — different SKUs, different prices."""
        rows = [JOBS_ROW, ALL_PURPOSE_ROW]
        conn = DatabricksConnector(full_credentials)
        mock_conn = _mock_connection(rows)
        with _patch_sql_connect(conn, mock_conn):
            costs = conn.fetch_costs(days=7)
        by_sku = {c.metadata["sku"]: c for c in costs}
        assert by_sku["STANDARD_JOBS_COMPUTE"].metadata["list_price_per_unit"] == 0.15
        assert by_sku["PREMIUM_ALL_PURPOSE_COMPUTE"].metadata["list_price_per_unit"] == 0.55

    def test_azure_cloud_forwarded(self):
        creds = {
            "access_token": "t",
            "server_hostname": "h",
            "warehouse_http_path": "/w",
            "cloud": "AZURE",
        }
        conn = DatabricksConnector(creds)
        azure_row = make_row(cloud="AZURE")
        mock_conn = _mock_connection([azure_row])
        with _patch_sql_connect(conn, mock_conn):
            costs = conn.fetch_costs(days=7)
        assert costs[0].metadata["cloud"] == "AZURE"


# ─── Fallbacks & no-fantasy-math guarantees ────────────────────────────────


class TestFallbacks:
    def test_missing_warehouse_returns_empty_list(self, legacy_only_credentials):
        """Spec: No warehouse_http_path → honest empty return, not fake data."""
        conn = DatabricksConnector(legacy_only_credentials)
        costs = conn.fetch_costs(days=7)
        assert costs == []

    def test_missing_token_returns_empty_list(self):
        conn = DatabricksConnector(
            {"server_hostname": "h", "warehouse_http_path": "/w"}
        )
        assert conn.fetch_costs(days=7) == []

    def test_zero_days_returns_empty_list(self, full_credentials):
        conn = DatabricksConnector(full_credentials)
        # _sql_connect should never be called — assert it via patch
        with patch.object(conn, "_sql_connect") as mock_connect:
            costs = conn.fetch_costs(days=0)
            assert costs == []
            mock_connect.assert_not_called()

    def test_connect_failure_returns_empty_list(self, full_credentials):
        conn = DatabricksConnector(full_credentials)
        with patch.object(conn, "_sql_connect", side_effect=RuntimeError("boom")):
            assert conn.fetch_costs(days=7) == []

    def test_query_failure_returns_empty_list(self, full_credentials):
        conn = DatabricksConnector(full_credentials)
        mock_conn = _mock_connection([])
        mock_conn.cursor.return_value.execute.side_effect = RuntimeError("query error")
        with _patch_sql_connect(conn, mock_conn):
            assert conn.fetch_costs(days=7) == []

    def test_driver_not_installed_returns_empty_list(self, full_credentials):
        """When the databricks-sql-connector package isn't installed."""
        from app.services.connectors.databricks_connector import _ConnectorImportError

        conn = DatabricksConnector(full_credentials)
        with patch.object(
            conn, "_sql_connect",
            side_effect=_ConnectorImportError("not installed"),
        ):
            assert conn.fetch_costs(days=7) == []


# ─── SQL shape guarantees (regression) ─────────────────────────────────────


class TestSqlShape:
    def test_uses_system_tables_not_deprecated_endpoint(self, full_credentials):
        """Regression guard: fetch_costs must not touch the deprecated
        `/accounts/{id}/usage/download` REST endpoint."""
        conn = DatabricksConnector(full_credentials)
        mock_conn = _mock_connection([JOBS_ROW])
        with _patch_sql_connect(conn, mock_conn):
            conn.fetch_costs(days=14)
        executed = [call.args[0] for call in mock_conn.cursor.return_value.execute.call_args_list]
        assert executed, "Expected at least one SQL execution"
        joined = "\n".join(executed)
        assert "system.billing.usage" in joined
        assert "system.billing.list_prices" in joined
        assert "/usage/download" not in joined

    def test_days_parameter_is_interpolated(self, full_credentials):
        conn = DatabricksConnector(full_credentials)
        mock_conn = _mock_connection([JOBS_ROW])
        with _patch_sql_connect(conn, mock_conn):
            conn.fetch_costs(days=14)
        executed = "\n".join(
            call.args[0] for call in mock_conn.cursor.return_value.execute.call_args_list
        )
        assert "DATEADD(DAY, -14" in executed

    def test_source_does_not_use_utcnow(self):
        """datetime.utcnow() is deprecated in Python 3.12+ and the spec bans it."""
        from app.services.connectors import databricks_connector

        source = open(databricks_connector.__file__).read()
        assert "datetime.utcnow" not in source, (
            "datetime.utcnow() is banned — use datetime.now(timezone.utc) instead"
        )

    def test_source_does_not_use_deprecated_endpoint(self):
        """Hard regression: the deprecated `/usage/download` endpoint must be gone."""
        from app.services.connectors import databricks_connector

        source = open(databricks_connector.__file__).read()
        assert "/usage/download" not in source
        assert "accounts.cloud.databricks.com" not in source


# ─── Module-level helpers ──────────────────────────────────────────────────


class TestHelpers:
    def test_classify_known_products(self):
        assert _classify("JOBS") == CostCategory.compute
        assert _classify("DLT") == CostCategory.transformation
        assert _classify("MODEL_SERVING") == CostCategory.ml_serving
        assert _classify("VECTOR_SEARCH") == CostCategory.serving
        assert _classify("DEFAULT_STORAGE") == CostCategory.storage

    def test_classify_case_insensitive(self):
        assert _classify("jobs") == CostCategory.compute
        assert _classify("Sql") == CostCategory.compute

    def test_classify_unknown_defaults_to_compute(self):
        assert _classify("SOMETHING_NEW_2030") == CostCategory.compute

    def test_classify_none_defaults_to_compute(self):
        assert _classify(None) == CostCategory.compute
        assert _classify("") == CostCategory.compute

    def test_billing_product_map_covers_modern_products(self):
        """Smoke test: new 2025/2026 Databricks products are mapped."""
        for product in (
            "JOBS", "ALL_PURPOSE", "SQL", "DLT", "MODEL_SERVING",
            "VECTOR_SEARCH", "APPS", "AGENT_BRICKS", "AGENT_EVALUATION",
            "AI_GATEWAY", "AI_FUNCTIONS", "AI_RUNTIME", "DATABASE",
            "FOUNDATION_MODEL_TRAINING", "LAKEHOUSE_MONITORING",
            "LAKEFLOW_CONNECT", "CLEAN_ROOM", "NETWORKING",
        ):
            assert product in BILLING_PRODUCT_CATEGORY, f"Missing product: {product}"

    def test_apply_overrides_no_overrides(self):
        assert _apply_pricing_overrides("SKU", 0.55, {}) == 0.55

    def test_apply_overrides_per_sku(self):
        assert _apply_pricing_overrides("SKU", 0.55, {"SKU": 0.10}) == 0.10

    def test_apply_overrides_dbu_discount(self):
        assert _apply_pricing_overrides("SKU", 1.0, {"dbu_discount_pct": 25}) == 0.75

    def test_coerce_mapping_dict(self):
        assert _coerce_mapping({"a": 1}) == {"a": 1}

    def test_coerce_mapping_json_string(self):
        assert _coerce_mapping('{"a": 1}') == {"a": 1}

    def test_coerce_mapping_none(self):
        assert _coerce_mapping(None) == {}

    def test_coerce_mapping_bad_string(self):
        assert _coerce_mapping("not json") == {}

    def test_is_photon_true(self):
        assert _is_photon({"photon_enabled": True}) is True

    def test_is_photon_alt_key(self):
        assert _is_photon({"is_photon": True}) is True

    def test_is_photon_false(self):
        assert _is_photon({}) is False
        assert _is_photon({"photon_enabled": False}) is False

    def test_resolve_team_prefers_team_tag(self):
        assert _resolve_team({"team": "data"}, {}) == "data"

    def test_resolve_team_owner_fallback(self):
        assert _resolve_team({"owner": "ada"}, {}) == "ada"

    def test_resolve_team_from_identity(self):
        assert _resolve_team({}, {"run_as": "svc@x.com"}) == "svc@x.com"

    def test_resolve_team_none(self):
        assert _resolve_team({}, {}) is None

    def test_resolve_project_prefers_tag(self):
        assert _resolve_project({"project": "p"}, {}) == "p"

    def test_resolve_project_job_name_fallback(self):
        assert _resolve_project({}, {"job_name": "daily-etl"}) == "daily-etl"

    def test_resolve_resource_prefers_job_name(self):
        assert _resolve_resource({"job_name": "x"}, "ws", "SKU") == "x"

    def test_resolve_resource_falls_back_to_workspace(self):
        assert _resolve_resource({}, "ws-1", "SKU") == "workspace:ws-1"

    def test_resolve_resource_falls_back_to_sku(self):
        assert _resolve_resource({}, "", "MY_SKU") == "my_sku"


# ─── UnifiedCost contract ──────────────────────────────────────────────────


class TestUnifiedCostContract:
    def test_date_format(self, full_credentials):
        conn = DatabricksConnector(full_credentials)
        mock_conn = _mock_connection([JOBS_ROW])
        with _patch_sql_connect(conn, mock_conn):
            costs = conn.fetch_costs(days=7)
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", costs[0].date)

    def test_usage_unit_is_dbu(self, full_credentials):
        conn = DatabricksConnector(full_credentials)
        mock_conn = _mock_connection([JOBS_ROW])
        with _patch_sql_connect(conn, mock_conn):
            costs = conn.fetch_costs(days=7)
        assert costs[0].usage_unit == "DBU"

    def test_service_string_is_prefixed(self, full_credentials):
        conn = DatabricksConnector(full_credentials)
        mock_conn = _mock_connection([JOBS_ROW, DLT_ROW])
        with _patch_sql_connect(conn, mock_conn):
            costs = conn.fetch_costs(days=7)
        services = {c.service for c in costs}
        assert {"databricks_jobs", "databricks_dlt"} <= services

    def test_cost_rounded(self, full_credentials):
        conn = DatabricksConnector(full_credentials)
        row = make_row(usage_quantity=1.0, list_dbu_price=0.123456789, effective_list_price=0.123456789)
        mock_conn = _mock_connection([row])
        with _patch_sql_connect(conn, mock_conn):
            costs = conn.fetch_costs(days=7)
        # 6 decimals of precision is good enough and avoids float noise
        assert abs(costs[0].cost_usd - round(0.123456789, 6)) < 1e-9


# ─── Additional edge-case coverage ─────────────────────────────────────────


class TestEdgeCases:
    """Covers the defensive branches that real-world drivers exercise."""

    def test_row_with_asdict_method(self, full_credentials):
        """databricks-sql Rows expose `asDict()` — the connector must use it."""

        class RowLike:
            def __init__(self, data: dict) -> None:
                self._data = data

            def asDict(self) -> dict:
                return self._data

        conn = DatabricksConnector(full_credentials)
        mock_conn = _mock_connection([RowLike(JOBS_ROW)])
        with _patch_sql_connect(conn, mock_conn):
            costs = conn.fetch_costs(days=7)
        assert len(costs) == 1
        assert costs[0].metadata["sku"] == "STANDARD_JOBS_COMPUTE"

    def test_row_via_attribute_access(self, full_credentials):
        """Last-ditch path: Row-like object without asDict(), attribute-only."""

        class AttrRow:
            pass

        row = AttrRow()
        for k, v in JOBS_ROW.items():
            setattr(row, k, v)

        conn = DatabricksConnector(full_credentials)
        mock_conn = _mock_connection([row])
        with _patch_sql_connect(conn, mock_conn):
            costs = conn.fetch_costs(days=7)
        assert len(costs) == 1
        assert costs[0].metadata["sku"] == "STANDARD_JOBS_COMPUTE"

    def test_format_date_datetime_object(self):
        from datetime import datetime as _dt
        from app.services.connectors.databricks_connector import _format_date

        assert _format_date(_dt(2026, 4, 21, 12, 0, 0)) == "2026-04-21"

    def test_format_date_none_uses_today_utc(self):
        from datetime import datetime, timezone as _tz
        from app.services.connectors.databricks_connector import _format_date

        result = _format_date(None)
        expected = datetime.now(_tz.utc).strftime("%Y-%m-%d")
        assert result == expected

    def test_format_date_str_trims_to_ten(self):
        from app.services.connectors.databricks_connector import _format_date

        assert _format_date("2026-04-21T12:34:56Z") == "2026-04-21"

    def test_test_connection_driver_not_installed(self, full_credentials):
        from app.services.connectors.databricks_connector import _ConnectorImportError

        conn = DatabricksConnector(full_credentials)
        with patch.object(
            conn, "_sql_connect",
            side_effect=_ConnectorImportError("driver missing"),
        ):
            result = conn.test_connection()
        assert result["success"] is False
        assert result["error_code"] == CONNECTION_FAILED
        assert "driver missing" in result["message"]

    def test_coerce_mapping_bad_asdict_swallowed(self):
        """Row-like object whose asDict() raises — helper returns empty dict."""
        from app.services.connectors.databricks_connector import _coerce_mapping

        class BadRow:
            def asDict(self):
                raise RuntimeError("broken row")

        assert _coerce_mapping(BadRow()) == {}

    def test_dbu_pricing_deprecated_constant_still_exported(self):
        """Back-compat: the old DBU_PRICING dict is still importable for any UI."""
        from app.services.connectors.databricks_connector import DBU_PRICING

        assert "JOBS" in DBU_PRICING
        # 0.30 was the old wrong price; the corrected value is $0.15/DBU
        assert DBU_PRICING["JOBS"] == 0.15

    def test_effective_list_price_preferred_over_default(self, full_credentials):
        """Account-negotiated effective_list price wins over the public default."""
        conn = DatabricksConnector(full_credentials)
        row = make_row(
            usage_quantity=10.0,
            list_dbu_price=0.30,          # Public list
            effective_list_price=0.22,    # Account-specific
        )
        mock_conn = _mock_connection([row])
        with _patch_sql_connect(conn, mock_conn):
            costs = conn.fetch_costs(days=7)
        assert costs[0].cost_usd == pytest.approx(10.0 * 0.22, rel=1e-6)

    def test_null_list_prices_do_not_crash(self, full_credentials):
        """If list_prices JOIN returned NULL (SKU not yet in pricing), cost == 0."""
        conn = DatabricksConnector(full_credentials)
        row = make_row(list_dbu_price=None, effective_list_price=None)
        mock_conn = _mock_connection([row])
        with _patch_sql_connect(conn, mock_conn):
            costs = conn.fetch_costs(days=7)
        assert len(costs) == 1
        assert costs[0].cost_usd == 0.0

    def test_negative_usage_quantity_skipped(self, full_credentials):
        """Never emit a record with non-positive usage (credit/refund rows etc.)."""
        conn = DatabricksConnector(full_credentials)
        row = make_row(usage_quantity=-3.0)
        mock_conn = _mock_connection([row])
        with _patch_sql_connect(conn, mock_conn):
            costs = conn.fetch_costs(days=7)
        assert costs == []
