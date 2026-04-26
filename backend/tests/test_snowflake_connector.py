"""Tests for the SnowflakeConnector.

These tests exercise the connector with a fully mocked Snowflake SDK. The
real `snowflake.connector` package is stubbed out in `conftest.py` so the
test environment doesn't need it.

We cover:

* Pricing-override resolution (credit_price_usd, per-warehouse-size,
  per-service-type, storage tiers, edition).
* Preferred ORGANIZATION_USAGE path when the role has access.
* Fallback to ACCOUNT_USAGE.METERING_DAILY_HISTORY when it doesn't.
* Serverless credit views (Serverless Tasks, Snowpipe, Auto-Clustering,
  MV refresh, Search Optimization, Replication, Query Acceleration,
  Snowpipe Streaming, Cortex AI).
* Per-user / role / query-tag attribution via QUERY_ATTRIBUTION_HISTORY.
* Storage breakdown (active / time-travel / failsafe) and time-travel
  snapshot via TABLE_STORAGE_METRICS.
* Cloud Services free-allowance deduction through METERING_DAILY_HISTORY.
* Structured permission errors (instead of silent swallowing).
* UnifiedCost schema compliance for every record produced.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.models.platform import CostCategory, UnifiedCost
from app.services.connectors.base import BaseConnector
from app.services.connectors.snowflake_connector import (
    AI_SERVICE_FAMILY_TO_TYPE,
    DEFAULT_ACTIVE_STORAGE_PRICE_PER_TB,
    DEFAULT_CREDIT_PRICE_USD,
    FRESHNESS_STALE_HOURS,
    FRESHNESS_WARN_HOURS,
    PricingConfig,
    SERVICE_TYPE_CATEGORY,
    SERVICE_TYPE_SLUG,
    SnowflakeConnector,
    SnowflakePermissionError,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def sf_credentials() -> dict:
    """Base credentials with minimum fields populated."""
    return {
        "account": "xy12345.us-east-1",
        "user": "costly_user",
        "private_key": "-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----",
        "warehouse": "ANALYTICS_WH",
        "database": "SNOWFLAKE",
        "schema_name": "ACCOUNT_USAGE",
        "role": "COSTLY_READ_ROLE",
    }


class FakeCursor:
    """Scriptable cursor stand-in.

    `programs` is a list of (sql_substring, result) where result is either:

    * an iterable of rows (returned via fetchall())
    * a single row (returned via fetchone())
    * an Exception instance (raised during execute())

    Each entry is consumed in FIFO order. A program whose needle is `"*"`
    acts as a persistent wildcard fallback (not consumed) for SQL calls
    that don't match a specific needle — useful for the freshness probe
    which ran after all the scripted calls in existing tests. Unmatched
    executes with no wildcard raise `AssertionError` to flag missing
    programming in the test.
    """

    def __init__(self, programs: list[tuple[str, Any]]):
        # Auto-append a permissive default for the freshness probe so the
        # many existing tests don't need to re-program themselves. Tests
        # that explicitly want to assert the freshness query ran can still
        # override by supplying their own "MAX(" program earlier.
        extended = list(programs) + [
            ("AI_SERVICES_USAGE_HISTORY", []),
            ("*", None),
        ]
        self.programs = extended
        self._pending_rows: list[tuple] = []
        self._pending_single: tuple | None = None
        self.executed: list[str] = []

    def execute(self, sql: str) -> None:
        self.executed.append(sql)
        for i, (needle, result) in enumerate(self.programs):
            matched = needle == "*" or needle in sql
            if matched:
                if needle != "*":
                    self.programs.pop(i)
                if isinstance(result, BaseException):
                    raise result
                if isinstance(result, list):
                    self._pending_rows = list(result)
                    self._pending_single = result[0] if result else None
                elif isinstance(result, tuple):
                    self._pending_rows = [result]
                    self._pending_single = result
                elif result is None:
                    self._pending_rows = []
                    self._pending_single = None
                else:
                    raise AssertionError(f"Unexpected program result type: {type(result)!r}")
                return
        raise AssertionError(
            f"Unprogrammed SQL executed: {sql[:120]!r}. "
            f"Remaining programs: {[p[0] for p in self.programs]!r}"
        )

    def fetchall(self) -> list[tuple]:
        rows = self._pending_rows
        self._pending_rows = []
        self._pending_single = None
        return rows

    def fetchone(self) -> tuple | None:
        row = self._pending_single
        self._pending_rows = []
        self._pending_single = None
        return row

    def close(self) -> None:
        pass


class FakeConnection:
    def __init__(self, cursor: FakeCursor):
        self._cursor = cursor

    def cursor(self) -> FakeCursor:
        return self._cursor

    def close(self) -> None:
        pass


def _build_connector_with_cursor(credentials: dict, cursor: FakeCursor) -> SnowflakeConnector:
    conn = SnowflakeConnector(credentials)

    def _connect():
        return FakeConnection(cursor)

    conn._connect = _connect  # type: ignore[method-assign]
    return conn


# ---------------------------------------------------------------------------
# Module-level / class-level tests
# ---------------------------------------------------------------------------
class TestConnectorContract:

    def test_is_base_connector(self):
        assert issubclass(SnowflakeConnector, BaseConnector)

    def test_platform_attribute(self):
        assert SnowflakeConnector.platform == "snowflake"

    def test_service_type_mapping_complete(self):
        """Every mapped service_type must have a slug and a category."""
        for svc in SERVICE_TYPE_CATEGORY:
            assert svc in SERVICE_TYPE_SLUG, f"Missing slug for {svc}"
            assert isinstance(SERVICE_TYPE_CATEGORY[svc], CostCategory)

    def test_instantiation(self, sf_credentials):
        conn = SnowflakeConnector(sf_credentials)
        assert conn.platform == "snowflake"
        assert conn.conn_doc["account"] == "xy12345.us-east-1"
        assert conn.conn_doc["role"] == "COSTLY_READ_ROLE"
        assert conn.conn_doc["schema_name"] == "ACCOUNT_USAGE"

    def test_account_suffix_stripped(self, sf_credentials):
        sf_credentials["account"] = "XY12345.us-east-1.snowflakecomputing.com"
        conn = SnowflakeConnector(sf_credentials)
        assert conn.conn_doc["account"] == "xy12345.us-east-1"

    def test_warnings_initially_empty(self, sf_credentials):
        conn = SnowflakeConnector(sf_credentials)
        assert conn.warnings == []


# ---------------------------------------------------------------------------
# PricingConfig
# ---------------------------------------------------------------------------
class TestPricingConfig:

    def test_defaults(self):
        cfg = PricingConfig.from_credentials({})
        assert cfg.credit_price_usd == DEFAULT_CREDIT_PRICE_USD
        assert cfg.active_storage_price_per_tb == DEFAULT_ACTIVE_STORAGE_PRICE_PER_TB
        assert cfg.timetravel_storage_price_per_tb == DEFAULT_ACTIVE_STORAGE_PRICE_PER_TB
        assert cfg.failsafe_storage_price_per_tb == DEFAULT_ACTIVE_STORAGE_PRICE_PER_TB
        assert cfg.warehouse_size_prices == {}
        assert cfg.service_type_prices == {}
        assert cfg.prefer_org_usage is True

    def test_credit_price_override(self):
        creds = {"pricing_overrides": {"credit_price_usd": 2.5}}
        cfg = PricingConfig.from_credentials(creds)
        assert cfg.credit_price_usd == 2.5

    def test_legacy_credit_price_key(self):
        # Some existing customers supply "credit_price" (no _usd suffix).
        creds = {"pricing_overrides": {"credit_price": 1.80}}
        cfg = PricingConfig.from_credentials(creds)
        assert cfg.credit_price_usd == 1.80

    def test_edition_defaults(self):
        assert PricingConfig.from_credentials(
            {"pricing_overrides": {"edition": "standard"}}
        ).credit_price_usd == 2.00
        assert PricingConfig.from_credentials(
            {"pricing_overrides": {"edition": "business_critical"}}
        ).credit_price_usd == 4.00

    def test_explicit_override_beats_edition(self):
        cfg = PricingConfig.from_credentials(
            {"pricing_overrides": {"edition": "business_critical", "credit_price_usd": 2.0}}
        )
        assert cfg.credit_price_usd == 2.0

    def test_storage_override(self):
        cfg = PricingConfig.from_credentials(
            {"pricing_overrides": {"storage_price_per_tb": 20.0}}
        )
        assert cfg.active_storage_price_per_tb == 20.0
        # Time-travel / failsafe inherit active unless separately set.
        assert cfg.timetravel_storage_price_per_tb == 20.0
        assert cfg.failsafe_storage_price_per_tb == 20.0

    def test_storage_tier_overrides(self):
        cfg = PricingConfig.from_credentials({
            "pricing_overrides": {
                "storage_price_per_tb": 20.0,
                "failsafe_storage_price_per_tb": 15.0,
                "timetravel_storage_price_per_tb": 18.0,
            }
        })
        assert cfg.active_storage_price_per_tb == 20.0
        assert cfg.failsafe_storage_price_per_tb == 15.0
        assert cfg.timetravel_storage_price_per_tb == 18.0

    def test_warehouse_size_override(self):
        cfg = PricingConfig.from_credentials(
            {"pricing_overrides": {"warehouse_size_prices": {"LARGE": 4.5, "X-Small": 2.0}}}
        )
        assert cfg.credit_price_for_warehouse("LARGE") == 4.5
        assert cfg.credit_price_for_warehouse("Large") == 4.5
        assert cfg.credit_price_for_warehouse("X-SMALL") == 2.0
        assert cfg.credit_price_for_warehouse("XSMALL") == 2.0
        # Unknown size falls back to base credit price.
        assert cfg.credit_price_for_warehouse("MEDIUM") == DEFAULT_CREDIT_PRICE_USD

    def test_service_type_override(self):
        cfg = PricingConfig.from_credentials(
            {"pricing_overrides": {"service_type_prices": {"CORTEX": 5.0, "SERVERLESS_TASK": 2.0}}}
        )
        assert cfg.credit_price_for_service_type("CORTEX") == 5.0
        assert cfg.credit_price_for_service_type("cortex") == 5.0
        assert cfg.credit_price_for_service_type("SERVERLESS_TASK") == 2.0
        assert cfg.credit_price_for_service_type("COMPUTE") == DEFAULT_CREDIT_PRICE_USD

    def test_invalid_values_are_ignored(self):
        cfg = PricingConfig.from_credentials({
            "pricing_overrides": {
                "credit_price_usd": "not-a-number",
                "storage_price_per_tb": -5,
                "warehouse_size_prices": {"LARGE": "abc", "MEDIUM": 4},
            }
        })
        assert cfg.credit_price_usd == DEFAULT_CREDIT_PRICE_USD
        assert cfg.active_storage_price_per_tb == DEFAULT_ACTIVE_STORAGE_PRICE_PER_TB
        assert "LARGE" not in cfg.warehouse_size_prices
        assert cfg.warehouse_size_prices["MEDIUM"] == 4

    def test_prefer_org_usage_flag(self):
        cfg = PricingConfig.from_credentials(
            {"pricing_overrides": {"prefer_org_usage": False}}
        )
        assert cfg.prefer_org_usage is False

    def test_frozen(self):
        cfg = PricingConfig.from_credentials({})
        with pytest.raises(Exception):
            cfg.credit_price_usd = 999.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# test_connection()
# ---------------------------------------------------------------------------
class TestTestConnection:

    def test_success(self, sf_credentials):
        cursor = FakeCursor([
            ("CURRENT_USER()", ("costly_user", "COSTLY_READ_ROLE", "ANALYTICS_WH")),
        ])
        conn = _build_connector_with_cursor(sf_credentials, cursor)
        result = conn.test_connection()
        assert result["success"] is True
        assert "costly_user" in result["message"]
        assert "COSTLY_READ_ROLE" in result["message"]

    def test_connection_failure(self, sf_credentials):
        conn = SnowflakeConnector(sf_credentials)

        def _raise():
            raise RuntimeError("DNS lookup failed")

        conn._connect = _raise  # type: ignore[method-assign]
        result = conn.test_connection()
        assert result["success"] is False
        assert "DNS lookup failed" in result["message"]


# ---------------------------------------------------------------------------
# ORGANIZATION_USAGE preferred path
# ---------------------------------------------------------------------------
class TestOrgUsagePreferredPath:

    def _org_rows(self) -> list[tuple]:
        return [
            # date, account, service_type, usage_type, usage, units, usd, currency
            (date(2026, 3, 1), "MY_ACCOUNT", "COMPUTE", "warehouse credits", 10.0, "credits", 30.0, "USD"),
            (date(2026, 3, 1), "MY_ACCOUNT", "CLOUD_SERVICES", "cloud services credits", 1.0, "credits", 1.5, "USD"),
            (date(2026, 3, 1), "MY_ACCOUNT", "STORAGE", "active storage", 1024.0, "terabytes", 23.0, "USD"),
            (date(2026, 3, 1), "MY_ACCOUNT", "SERVERLESS_TASK", "serverless task", 2.0, "credits", 6.0, "USD"),
            (date(2026, 3, 1), "MY_ACCOUNT", "AI_SERVICES", "cortex complete", 0.5, "credits", 3.0, "USD"),
            (date(2026, 3, 1), "MY_ACCOUNT", "PIPE", "snowpipe", 0.3, "credits", 0.9, "USD"),
        ]

    def test_iceberg_and_hybrid_tables_via_org_usage(self, sf_credentials):
        """Iceberg table and hybrid table lines come through
        USAGE_IN_CURRENCY_DAILY as their own SERVICE_TYPE."""
        rows = [
            (date(2026, 3, 1), "ACCT", "ICEBERG_TABLE_REQUESTS", "iceberg", 100.0, "requests", 0.5, "USD"),
            (date(2026, 3, 1), "ACCT", "HYBRID_TABLE_REQUESTS", "hybrid", 500.0, "requests", 0.25, "USD"),
            (date(2026, 3, 1), "ACCT", "SNOWPARK_CONTAINER_SERVICES", "spcs", 2.0, "credits", 6.0, "USD"),
        ]
        cursor = FakeCursor([
            ("USAGE_IN_CURRENCY_DAILY", rows),
            ("QUERY_ATTRIBUTION_HISTORY", []),
            ("DATABASE_STORAGE_USAGE_HISTORY", []),
            ("TABLE_STORAGE_METRICS", []),
        ])
        conn = _build_connector_with_cursor(sf_credentials, cursor)
        costs = conn.fetch_costs(days=7)
        by_svc = {c.service: c for c in costs}
        assert by_svc["snowflake_iceberg"].category == CostCategory.storage
        assert by_svc["snowflake_hybrid_tables"].category == CostCategory.compute
        assert by_svc["snowflake_snowpark_container_services"].category == CostCategory.compute
        assert by_svc["snowflake_snowpark_container_services"].cost_usd == 6.0

    def test_org_usage_preferred(self, sf_credentials):
        cursor = FakeCursor([
            ("USAGE_IN_CURRENCY_DAILY", self._org_rows()),
            ("QUERY_ATTRIBUTION_HISTORY", []),
            ("DATABASE_STORAGE_USAGE_HISTORY", []),
            ("TABLE_STORAGE_METRICS", []),
        ])
        conn = _build_connector_with_cursor(sf_credentials, cursor)
        costs = conn.fetch_costs(days=7)

        # 6 cost records from org usage (storage got 1 row — it is legal for
        # USAGE_IN_CURRENCY_DAILY to have one storage row per day)
        org_costs = [c for c in costs if c.metadata.get("source") == "ORGANIZATION_USAGE.USAGE_IN_CURRENCY_DAILY"]
        assert len(org_costs) == 6

        by_svc = {c.service: c for c in org_costs}
        # Compute
        assert by_svc["snowflake_compute"].cost_usd == 30.0
        assert by_svc["snowflake_compute"].category == CostCategory.compute
        # Cloud services (no need to deduct 10% again — already billed USD)
        assert by_svc["snowflake_cloud_services"].cost_usd == 1.5
        # Storage
        assert by_svc["snowflake_storage"].category == CostCategory.storage
        # Serverless tasks
        assert by_svc["snowflake_serverless_tasks"].cost_usd == 6.0
        # Cortex AI = ai_inference category
        assert by_svc["snowflake_cortex"].category == CostCategory.ai_inference
        # Snowpipe ingestion
        assert by_svc["snowflake_snowpipe"].category == CostCategory.ingestion

        assert conn.warnings == []

    def test_org_usage_permission_denied_falls_back(self, sf_credentials):
        # USAGE_IN_CURRENCY_DAILY is denied -> fall back to METERING_DAILY_HISTORY.
        metering_rows = [
            (date(2026, 3, 1), "COMPUTE", 10.0, 1.5, -1.0, 10.5),  # net cloud = 0.5
        ]
        cursor = FakeCursor([
            ("USAGE_IN_CURRENCY_DAILY", Exception("SQL access control error: insufficient privileges")),
            ("METERING_DAILY_HISTORY", metering_rows),
            ("SERVERLESS_TASK_HISTORY", []),
            ("PIPE_USAGE_HISTORY", []),
            ("AUTOMATIC_CLUSTERING_HISTORY", []),
            ("MATERIALIZED_VIEW_REFRESH_HISTORY", []),
            ("SEARCH_OPTIMIZATION_HISTORY", []),
            ("REPLICATION_USAGE_HISTORY", []),
            ("QUERY_ACCELERATION_HISTORY", []),
            ("SNOWPIPE_STREAMING_CLIENT_HISTORY", []),
            ("SNOWPARK_CONTAINER_SERVICES_HISTORY", []),
            ("HYBRID_TABLE_USAGE_HISTORY", []),
            ("CORTEX_FUNCTIONS_USAGE_HISTORY", []),
            ("CORTEX_ANALYST_USAGE_HISTORY", []),
            ("QUERY_ATTRIBUTION_HISTORY", []),
            ("DATABASE_STORAGE_USAGE_HISTORY", []),
            ("TABLE_STORAGE_METRICS", []),
        ])
        conn = _build_connector_with_cursor(sf_credentials, cursor)
        costs = conn.fetch_costs(days=30)

        # Compute + Cloud Services rows both emitted with net Cloud Services.
        by_svc = {c.service: c for c in costs if c.metadata.get("source", "").endswith("METERING_DAILY_HISTORY")}
        assert by_svc["snowflake_compute"].cost_usd == 30.0  # 10 * 3.0 default
        # Net cloud services = 1.5 - 1.0 = 0.5 credits @ $3 = $1.50
        assert by_svc["snowflake_cloud_services"].cost_usd == 1.5
        assert by_svc["snowflake_cloud_services"].metadata["gross_cloud_credits"] == 1.5
        assert by_svc["snowflake_cloud_services"].metadata["cloud_adjustment"] == -1.0

        # Permission warning should be surfaced.
        assert any("ORGANIZATION_USAGE.USAGE_IN_CURRENCY_DAILY" in w for w in conn.warnings)

    def test_org_usage_disabled_via_override(self, sf_credentials):
        # Explicit opt-out must skip the org usage query entirely.
        sf_credentials["pricing_overrides"] = {"prefer_org_usage": False}
        cursor = FakeCursor([
            ("METERING_DAILY_HISTORY", []),
            ("SERVERLESS_TASK_HISTORY", []),
            ("PIPE_USAGE_HISTORY", []),
            ("AUTOMATIC_CLUSTERING_HISTORY", []),
            ("MATERIALIZED_VIEW_REFRESH_HISTORY", []),
            ("SEARCH_OPTIMIZATION_HISTORY", []),
            ("REPLICATION_USAGE_HISTORY", []),
            ("QUERY_ACCELERATION_HISTORY", []),
            ("SNOWPIPE_STREAMING_CLIENT_HISTORY", []),
            ("SNOWPARK_CONTAINER_SERVICES_HISTORY", []),
            ("HYBRID_TABLE_USAGE_HISTORY", []),
            ("CORTEX_FUNCTIONS_USAGE_HISTORY", []),
            ("CORTEX_ANALYST_USAGE_HISTORY", []),
            ("QUERY_ATTRIBUTION_HISTORY", []),
            ("DATABASE_STORAGE_USAGE_HISTORY", []),
            ("TABLE_STORAGE_METRICS", []),
        ])
        conn = _build_connector_with_cursor(sf_credentials, cursor)
        _ = conn.fetch_costs(days=7)
        # USAGE_IN_CURRENCY_DAILY must not appear in the executed SQL.
        assert not any("USAGE_IN_CURRENCY_DAILY" in s for s in cursor.executed)


# ---------------------------------------------------------------------------
# METERING_DAILY_HISTORY
# ---------------------------------------------------------------------------
class TestMeteringDailyHistory:

    def test_net_cloud_services(self, sf_credentials):
        """Cloud Services credits net the 10% free allowance via
        CREDITS_ADJUSTMENT_CLOUD_SERVICES (which is zero or negative)."""
        sf_credentials["pricing_overrides"] = {"prefer_org_usage": False, "credit_price_usd": 3.0}
        metering = [
            (date(2026, 3, 1), "COMPUTE", 100.0, 12.0, -10.0, 102.0),  # net cloud = 2
            (date(2026, 3, 1), "PIPE", 0.0, 0.5, 0.0, 0.5),  # only cloud services
        ]
        cursor = FakeCursor([
            ("METERING_DAILY_HISTORY", metering),
            ("SERVERLESS_TASK_HISTORY", []),
            ("PIPE_USAGE_HISTORY", []),
            ("AUTOMATIC_CLUSTERING_HISTORY", []),
            ("MATERIALIZED_VIEW_REFRESH_HISTORY", []),
            ("SEARCH_OPTIMIZATION_HISTORY", []),
            ("REPLICATION_USAGE_HISTORY", []),
            ("QUERY_ACCELERATION_HISTORY", []),
            ("SNOWPIPE_STREAMING_CLIENT_HISTORY", []),
            ("SNOWPARK_CONTAINER_SERVICES_HISTORY", []),
            ("HYBRID_TABLE_USAGE_HISTORY", []),
            ("CORTEX_FUNCTIONS_USAGE_HISTORY", []),
            ("CORTEX_ANALYST_USAGE_HISTORY", []),
            ("QUERY_ATTRIBUTION_HISTORY", []),
            ("DATABASE_STORAGE_USAGE_HISTORY", []),
            ("TABLE_STORAGE_METRICS", []),
        ])
        conn = _build_connector_with_cursor(sf_credentials, cursor)
        costs = conn.fetch_costs(days=7)

        # Expect one compute record (100 credits * $3 = $300) + one net CS record.
        metering_costs = [c for c in costs if c.metadata.get("source", "").endswith("METERING_DAILY_HISTORY")]
        compute = [c for c in metering_costs if c.service == "snowflake_compute"]
        cloud = [c for c in metering_costs if c.service == "snowflake_cloud_services"]

        assert len(compute) == 1 and compute[0].cost_usd == 300.0
        # Net cloud credits for COMPUTE row = 12 - 10 = 2 credits * $3 = $6
        # Plus PIPE cloud services = 0.5 credits * $3 = $1.5
        assert sum(c.cost_usd for c in cloud) == pytest.approx(7.5)

    def test_price_per_service_type_override(self, sf_credentials):
        # Credit price differs per SERVICE_TYPE.
        sf_credentials["pricing_overrides"] = {
            "prefer_org_usage": False,
            "credit_price_usd": 3.0,
            "service_type_prices": {"SERVERLESS_TASK": 2.0},
        }
        metering = [
            (date(2026, 3, 1), "SERVERLESS_TASK", 10.0, 0.0, 0.0, 10.0),
        ]
        cursor = FakeCursor([
            ("METERING_DAILY_HISTORY", metering),
            ("SERVERLESS_TASK_HISTORY", []),
            ("PIPE_USAGE_HISTORY", []),
            ("AUTOMATIC_CLUSTERING_HISTORY", []),
            ("MATERIALIZED_VIEW_REFRESH_HISTORY", []),
            ("SEARCH_OPTIMIZATION_HISTORY", []),
            ("REPLICATION_USAGE_HISTORY", []),
            ("QUERY_ACCELERATION_HISTORY", []),
            ("SNOWPIPE_STREAMING_CLIENT_HISTORY", []),
            ("SNOWPARK_CONTAINER_SERVICES_HISTORY", []),
            ("HYBRID_TABLE_USAGE_HISTORY", []),
            ("CORTEX_FUNCTIONS_USAGE_HISTORY", []),
            ("CORTEX_ANALYST_USAGE_HISTORY", []),
            ("QUERY_ATTRIBUTION_HISTORY", []),
            ("DATABASE_STORAGE_USAGE_HISTORY", []),
            ("TABLE_STORAGE_METRICS", []),
        ])
        conn = _build_connector_with_cursor(sf_credentials, cursor)
        costs = conn.fetch_costs(days=7)
        serverless = [c for c in costs if c.service == "snowflake_serverless_tasks"
                      and c.metadata.get("source", "").endswith("METERING_DAILY_HISTORY")]
        assert len(serverless) == 1
        assert serverless[0].cost_usd == 20.0  # 10 credits * $2

    def test_metering_permission_falls_back_to_warehouse_metering(self, sf_credentials):
        """When METERING_DAILY_HISTORY is denied, try WAREHOUSE_METERING_HISTORY."""
        sf_credentials["pricing_overrides"] = {"prefer_org_usage": False}
        warehouse_rows = [
            ("2026-03-01", "ANALYTICS_WH", "LARGE", 20.0, 1.0),
        ]
        cursor = FakeCursor([
            ("METERING_DAILY_HISTORY", Exception("SQL access control error: insufficient privileges")),
            ("WAREHOUSE_METERING_HISTORY", warehouse_rows),
            ("SERVERLESS_TASK_HISTORY", []),
            ("PIPE_USAGE_HISTORY", []),
            ("AUTOMATIC_CLUSTERING_HISTORY", []),
            ("MATERIALIZED_VIEW_REFRESH_HISTORY", []),
            ("SEARCH_OPTIMIZATION_HISTORY", []),
            ("REPLICATION_USAGE_HISTORY", []),
            ("QUERY_ACCELERATION_HISTORY", []),
            ("SNOWPIPE_STREAMING_CLIENT_HISTORY", []),
            ("SNOWPARK_CONTAINER_SERVICES_HISTORY", []),
            ("HYBRID_TABLE_USAGE_HISTORY", []),
            ("CORTEX_FUNCTIONS_USAGE_HISTORY", []),
            ("CORTEX_ANALYST_USAGE_HISTORY", []),
            ("QUERY_ATTRIBUTION_HISTORY", []),
            ("DATABASE_STORAGE_USAGE_HISTORY", []),
            ("TABLE_STORAGE_METRICS", []),
        ])
        conn = _build_connector_with_cursor(sf_credentials, cursor)
        costs = conn.fetch_costs(days=7)

        warehouse_costs = [c for c in costs if c.metadata.get("source", "").endswith("WAREHOUSE_METERING_HISTORY")]
        assert warehouse_costs, "Expected warehouse metering fallback"
        by_svc = {c.service: c for c in warehouse_costs}
        assert by_svc["snowflake_compute"].cost_usd == 60.0  # 20 * $3
        assert by_svc["snowflake_compute"].resource == "ANALYTICS_WH"

        # Permission warning must be surfaced.
        assert any("METERING_DAILY_HISTORY" in w for w in conn.warnings)
        assert any("GRANT IMPORTED PRIVILEGES" in w for w in conn.warnings)


# ---------------------------------------------------------------------------
# Warehouse-size pricing overrides
# ---------------------------------------------------------------------------
class TestWarehouseSizePricing:

    def test_size_override_applied(self, sf_credentials):
        sf_credentials["pricing_overrides"] = {
            "prefer_org_usage": False,
            "credit_price_usd": 3.0,
            "warehouse_size_prices": {"LARGE": 4.5},
        }
        cursor = FakeCursor([
            ("METERING_DAILY_HISTORY", Exception("SQL access control error: insufficient privileges")),
            (
                "WAREHOUSE_METERING_HISTORY",
                [("2026-03-01", "BIG_WH", "LARGE", 10.0, 0.0),
                 ("2026-03-01", "TINY_WH", "X-SMALL", 2.0, 0.0)],
            ),
            ("SERVERLESS_TASK_HISTORY", []),
            ("PIPE_USAGE_HISTORY", []),
            ("AUTOMATIC_CLUSTERING_HISTORY", []),
            ("MATERIALIZED_VIEW_REFRESH_HISTORY", []),
            ("SEARCH_OPTIMIZATION_HISTORY", []),
            ("REPLICATION_USAGE_HISTORY", []),
            ("QUERY_ACCELERATION_HISTORY", []),
            ("SNOWPIPE_STREAMING_CLIENT_HISTORY", []),
            ("SNOWPARK_CONTAINER_SERVICES_HISTORY", []),
            ("HYBRID_TABLE_USAGE_HISTORY", []),
            ("CORTEX_FUNCTIONS_USAGE_HISTORY", []),
            ("CORTEX_ANALYST_USAGE_HISTORY", []),
            ("QUERY_ATTRIBUTION_HISTORY", []),
            ("DATABASE_STORAGE_USAGE_HISTORY", []),
            ("TABLE_STORAGE_METRICS", []),
        ])
        conn = _build_connector_with_cursor(sf_credentials, cursor)
        costs = conn.fetch_costs(days=7)
        by_resource = {c.resource: c for c in costs
                       if c.metadata.get("source", "").endswith("WAREHOUSE_METERING_HISTORY")}
        # LARGE uses the override, X-SMALL uses the base price.
        assert by_resource["BIG_WH"].cost_usd == 45.0  # 10 * $4.50
        assert by_resource["TINY_WH"].cost_usd == 6.0  # 2 * $3.00


# ---------------------------------------------------------------------------
# Serverless views
# ---------------------------------------------------------------------------
class TestServerlessViews:

    @pytest.fixture
    def empty_primaries(self) -> list[tuple[str, Any]]:
        # Metering empty so we exercise the serverless helpers directly.
        return [
            ("USAGE_IN_CURRENCY_DAILY", Exception("SQL access control error: insufficient privileges")),
            ("METERING_DAILY_HISTORY", []),
        ]

    @pytest.fixture
    def trailing_empty(self) -> list[tuple[str, Any]]:
        return [
            ("QUERY_ATTRIBUTION_HISTORY", []),
            ("DATABASE_STORAGE_USAGE_HISTORY", []),
            ("TABLE_STORAGE_METRICS", []),
        ]

    def test_serverless_tasks_emitted(self, sf_credentials, empty_primaries, trailing_empty):
        cursor = FakeCursor(empty_primaries + [
            ("SERVERLESS_TASK_HISTORY", [("2026-03-01", "my_task", 3.0)]),
            ("PIPE_USAGE_HISTORY", []),
            ("AUTOMATIC_CLUSTERING_HISTORY", []),
            ("MATERIALIZED_VIEW_REFRESH_HISTORY", []),
            ("SEARCH_OPTIMIZATION_HISTORY", []),
            ("REPLICATION_USAGE_HISTORY", []),
            ("QUERY_ACCELERATION_HISTORY", []),
            ("SNOWPIPE_STREAMING_CLIENT_HISTORY", []),
            ("SNOWPARK_CONTAINER_SERVICES_HISTORY", []),
            ("HYBRID_TABLE_USAGE_HISTORY", []),
            ("CORTEX_FUNCTIONS_USAGE_HISTORY", []),
            ("CORTEX_ANALYST_USAGE_HISTORY", []),
        ] + trailing_empty)
        conn = _build_connector_with_cursor(sf_credentials, cursor)
        costs = conn.fetch_costs(days=7)
        task_costs = [c for c in costs if c.service == "snowflake_serverless_tasks"]
        assert len(task_costs) == 1
        assert task_costs[0].category == CostCategory.compute
        assert task_costs[0].cost_usd == 9.0  # 3 credits @ $3
        assert task_costs[0].resource == "my_task"

    @pytest.mark.parametrize("view_substring,expected_service,expected_category", [
        ("SERVERLESS_TASK_HISTORY", "snowflake_serverless_tasks", CostCategory.compute),
        ("PIPE_USAGE_HISTORY", "snowflake_snowpipe", CostCategory.ingestion),
        ("AUTOMATIC_CLUSTERING_HISTORY", "snowflake_auto_clustering", CostCategory.compute),
        ("MATERIALIZED_VIEW_REFRESH_HISTORY", "snowflake_materialized_views", CostCategory.compute),
        ("SEARCH_OPTIMIZATION_HISTORY", "snowflake_search_optimization", CostCategory.compute),
        ("REPLICATION_USAGE_HISTORY", "snowflake_replication", CostCategory.storage),
        ("QUERY_ACCELERATION_HISTORY", "snowflake_query_acceleration", CostCategory.compute),
        ("SNOWPIPE_STREAMING_CLIENT_HISTORY", "snowflake_snowpipe_streaming", CostCategory.ingestion),
        ("SNOWPARK_CONTAINER_SERVICES_HISTORY", "snowflake_snowpark_container_services", CostCategory.compute),
        ("HYBRID_TABLE_USAGE_HISTORY", "snowflake_hybrid_tables", CostCategory.compute),
    ])
    def test_each_serverless_view(
        self, sf_credentials, empty_primaries, trailing_empty,
        view_substring, expected_service, expected_category,
    ):
        programs = list(empty_primaries)
        for needle in (
            "SERVERLESS_TASK_HISTORY",
            "PIPE_USAGE_HISTORY",
            "AUTOMATIC_CLUSTERING_HISTORY",
            "MATERIALIZED_VIEW_REFRESH_HISTORY",
            "SEARCH_OPTIMIZATION_HISTORY",
            "REPLICATION_USAGE_HISTORY",
            "QUERY_ACCELERATION_HISTORY",
            "SNOWPIPE_STREAMING_CLIENT_HISTORY",
            "SNOWPARK_CONTAINER_SERVICES_HISTORY",
            "HYBRID_TABLE_USAGE_HISTORY",
        ):
            if needle == view_substring:
                programs.append((needle, [("2026-03-02", "thing", 2.0)]))
            else:
                programs.append((needle, []))
        programs.extend([
            ("CORTEX_FUNCTIONS_USAGE_HISTORY", []),
            ("CORTEX_ANALYST_USAGE_HISTORY", []),
        ])
        programs.extend(trailing_empty)
        cursor = FakeCursor(programs)
        conn = _build_connector_with_cursor(sf_credentials, cursor)
        costs = conn.fetch_costs(days=7)
        emitted = [c for c in costs if c.service == expected_service]
        assert len(emitted) == 1, f"Expected 1 record from {view_substring}, got {len(emitted)}"
        assert emitted[0].category == expected_category
        assert emitted[0].cost_usd == 6.0  # 2 credits @ $3
        assert emitted[0].resource == "thing"

    def test_cortex_functions_emitted(self, sf_credentials, empty_primaries, trailing_empty):
        """Cortex functions emit ai_inference records."""
        programs = list(empty_primaries) + [
            ("SERVERLESS_TASK_HISTORY", []),
            ("PIPE_USAGE_HISTORY", []),
            ("AUTOMATIC_CLUSTERING_HISTORY", []),
            ("MATERIALIZED_VIEW_REFRESH_HISTORY", []),
            ("SEARCH_OPTIMIZATION_HISTORY", []),
            ("REPLICATION_USAGE_HISTORY", []),
            ("QUERY_ACCELERATION_HISTORY", []),
            ("SNOWPIPE_STREAMING_CLIENT_HISTORY", []),
            ("CORTEX_FUNCTIONS_USAGE_HISTORY",
             [("2026-03-01", "COMPLETE", 1.5),
              ("2026-03-01", "EMBED_TEXT", 0.2)]),
            ("CORTEX_ANALYST_USAGE_HISTORY",
             [("2026-03-01", "cortex_analyst", 0.3)]),
        ] + trailing_empty
        cursor = FakeCursor(programs)
        conn = _build_connector_with_cursor(sf_credentials, cursor)
        costs = conn.fetch_costs(days=7)
        cortex = [c for c in costs if c.service == "snowflake_cortex"]
        assert len(cortex) == 3
        for c in cortex:
            assert c.category == CostCategory.ai_inference
            assert c.usage_unit == "credits"
        total = sum(c.cost_usd for c in cortex)
        # (1.5 + 0.2 + 0.3) * $3 = $6.00
        assert total == pytest.approx(6.0)

    def test_serverless_view_permission_error_adds_warning(
        self, sf_credentials, empty_primaries, trailing_empty
    ):
        programs = list(empty_primaries) + [
            ("SERVERLESS_TASK_HISTORY", Exception("SQL access control error: insufficient privileges for operation")),
            ("PIPE_USAGE_HISTORY", []),
            ("AUTOMATIC_CLUSTERING_HISTORY", []),
            ("MATERIALIZED_VIEW_REFRESH_HISTORY", []),
            ("SEARCH_OPTIMIZATION_HISTORY", []),
            ("REPLICATION_USAGE_HISTORY", []),
            ("QUERY_ACCELERATION_HISTORY", []),
            ("SNOWPIPE_STREAMING_CLIENT_HISTORY", []),
            ("SNOWPARK_CONTAINER_SERVICES_HISTORY", []),
            ("HYBRID_TABLE_USAGE_HISTORY", []),
            ("CORTEX_FUNCTIONS_USAGE_HISTORY", []),
            ("CORTEX_ANALYST_USAGE_HISTORY", []),
        ] + trailing_empty
        cursor = FakeCursor(programs)
        conn = _build_connector_with_cursor(sf_credentials, cursor)
        conn.fetch_costs(days=7)
        assert any("SERVERLESS_TASK_HISTORY" in w for w in conn.warnings)
        assert any("GRANT IMPORTED PRIVILEGES" in w for w in conn.warnings)


# ---------------------------------------------------------------------------
# Attribution
# ---------------------------------------------------------------------------
class TestQueryAttribution:

    def test_attribution_recorded(self, sf_credentials):
        # Org usage empty => fallback path runs, then attribution on top.
        cursor = FakeCursor([
            ("USAGE_IN_CURRENCY_DAILY", []),
            ("METERING_DAILY_HISTORY", []),
            ("SERVERLESS_TASK_HISTORY", []),
            ("PIPE_USAGE_HISTORY", []),
            ("AUTOMATIC_CLUSTERING_HISTORY", []),
            ("MATERIALIZED_VIEW_REFRESH_HISTORY", []),
            ("SEARCH_OPTIMIZATION_HISTORY", []),
            ("REPLICATION_USAGE_HISTORY", []),
            ("QUERY_ACCELERATION_HISTORY", []),
            ("SNOWPIPE_STREAMING_CLIENT_HISTORY", []),
            ("SNOWPARK_CONTAINER_SERVICES_HISTORY", []),
            ("HYBRID_TABLE_USAGE_HISTORY", []),
            ("CORTEX_FUNCTIONS_USAGE_HISTORY", []),
            ("CORTEX_ANALYST_USAGE_HISTORY", []),
            (
                "QUERY_ATTRIBUTION_HISTORY",
                [
                    ("2026-03-01", "alice", "ANALYST_ROLE", "ANALYTICS_WH", "etl_daily", 5.0),
                    ("2026-03-01", "bob", "FINANCE_ROLE", "FIN_WH", None, 2.0),
                ],
            ),
            ("DATABASE_STORAGE_USAGE_HISTORY", []),
            ("TABLE_STORAGE_METRICS", []),
        ])
        conn = _build_connector_with_cursor(sf_credentials, cursor)
        costs = conn.fetch_costs(days=7)
        attribution = [c for c in costs if c.service == "snowflake_attribution"]
        assert len(attribution) == 2
        alice = next(c for c in attribution if c.metadata["user_name"] == "alice")
        assert alice.team == "ANALYST_ROLE"
        assert alice.project == "etl_daily"
        assert alice.cost_usd == 15.0  # 5 credits @ $3

        bob = next(c for c in attribution if c.metadata["user_name"] == "bob")
        assert bob.team == "FINANCE_ROLE"
        assert bob.project is None

    def test_attribution_permission_denied_warns(self, sf_credentials):
        cursor = FakeCursor([
            ("USAGE_IN_CURRENCY_DAILY", []),
            ("METERING_DAILY_HISTORY", []),
            ("SERVERLESS_TASK_HISTORY", []),
            ("PIPE_USAGE_HISTORY", []),
            ("AUTOMATIC_CLUSTERING_HISTORY", []),
            ("MATERIALIZED_VIEW_REFRESH_HISTORY", []),
            ("SEARCH_OPTIMIZATION_HISTORY", []),
            ("REPLICATION_USAGE_HISTORY", []),
            ("QUERY_ACCELERATION_HISTORY", []),
            ("SNOWPIPE_STREAMING_CLIENT_HISTORY", []),
            ("SNOWPARK_CONTAINER_SERVICES_HISTORY", []),
            ("HYBRID_TABLE_USAGE_HISTORY", []),
            ("CORTEX_FUNCTIONS_USAGE_HISTORY", []),
            ("CORTEX_ANALYST_USAGE_HISTORY", []),
            ("QUERY_ATTRIBUTION_HISTORY", Exception("access denied: insufficient privileges")),
            ("DATABASE_STORAGE_USAGE_HISTORY", []),
            ("TABLE_STORAGE_METRICS", []),
        ])
        conn = _build_connector_with_cursor(sf_credentials, cursor)
        conn.fetch_costs(days=7)
        assert any("QUERY_ATTRIBUTION_HISTORY" in w for w in conn.warnings)
        assert any("GRANT IMPORTED PRIVILEGES" in w for w in conn.warnings)


# ---------------------------------------------------------------------------
# Storage breakdown
# ---------------------------------------------------------------------------
class TestStorageBreakdown:

    def test_active_and_failsafe_split(self, sf_credentials):
        """DATABASE_STORAGE_USAGE_HISTORY produces per-database daily rows
        split into active + failsafe records."""
        one_tb = 1024 ** 4
        sf_credentials["pricing_overrides"] = {
            "prefer_org_usage": False,
            "storage_price_per_tb": 20.0,
            "failsafe_storage_price_per_tb": 15.0,
        }
        db_rows = [
            (date(2026, 3, 1), "PROD_DB", one_tb, 0.5 * one_tb),
            (date(2026, 3, 2), "PROD_DB", one_tb, 0.5 * one_tb),
        ]
        cursor = FakeCursor([
            ("METERING_DAILY_HISTORY", []),
            ("SERVERLESS_TASK_HISTORY", []),
            ("PIPE_USAGE_HISTORY", []),
            ("AUTOMATIC_CLUSTERING_HISTORY", []),
            ("MATERIALIZED_VIEW_REFRESH_HISTORY", []),
            ("SEARCH_OPTIMIZATION_HISTORY", []),
            ("REPLICATION_USAGE_HISTORY", []),
            ("QUERY_ACCELERATION_HISTORY", []),
            ("SNOWPIPE_STREAMING_CLIENT_HISTORY", []),
            ("SNOWPARK_CONTAINER_SERVICES_HISTORY", []),
            ("HYBRID_TABLE_USAGE_HISTORY", []),
            ("CORTEX_FUNCTIONS_USAGE_HISTORY", []),
            ("CORTEX_ANALYST_USAGE_HISTORY", []),
            ("QUERY_ATTRIBUTION_HISTORY", []),
            ("DATABASE_STORAGE_USAGE_HISTORY", db_rows),
            ("TABLE_STORAGE_METRICS", []),
        ])
        conn = _build_connector_with_cursor(sf_credentials, cursor)
        costs = conn.fetch_costs(days=7)

        storage = [c for c in costs if c.category == CostCategory.storage]
        # 2 days * (active, failsafe) = 4 records.
        assert len(storage) == 4

        active = [c for c in storage if c.metadata.get("tier") == "active"]
        failsafe = [c for c in storage if c.metadata.get("tier") == "failsafe"]

        assert len(active) == 2
        assert len(failsafe) == 2

        # Active: 1 TB * $20/30 = $0.6667 per day.
        assert active[0].cost_usd == pytest.approx(20.0 / 30.0, abs=1e-3)
        # Failsafe: 0.5 TB * $15/30 = $0.25 per day.
        assert failsafe[0].cost_usd == pytest.approx(0.5 * 15.0 / 30.0, abs=1e-3)

        # Every storage record must tag the database.
        for c in storage:
            assert c.metadata["database"] == "PROD_DB"

    def test_time_travel_from_table_storage_metrics(self, sf_credentials):
        one_tb = 1024 ** 4
        cursor = FakeCursor([
            ("USAGE_IN_CURRENCY_DAILY", []),
            ("METERING_DAILY_HISTORY", []),
            ("SERVERLESS_TASK_HISTORY", []),
            ("PIPE_USAGE_HISTORY", []),
            ("AUTOMATIC_CLUSTERING_HISTORY", []),
            ("MATERIALIZED_VIEW_REFRESH_HISTORY", []),
            ("SEARCH_OPTIMIZATION_HISTORY", []),
            ("REPLICATION_USAGE_HISTORY", []),
            ("QUERY_ACCELERATION_HISTORY", []),
            ("SNOWPIPE_STREAMING_CLIENT_HISTORY", []),
            ("SNOWPARK_CONTAINER_SERVICES_HISTORY", []),
            ("HYBRID_TABLE_USAGE_HISTORY", []),
            ("CORTEX_FUNCTIONS_USAGE_HISTORY", []),
            ("CORTEX_ANALYST_USAGE_HISTORY", []),
            ("QUERY_ATTRIBUTION_HISTORY", []),
            ("DATABASE_STORAGE_USAGE_HISTORY", []),
            ("TABLE_STORAGE_METRICS", [("STAGING_DB", 2 * one_tb)]),
        ])
        conn = _build_connector_with_cursor(sf_credentials, cursor)
        costs = conn.fetch_costs(days=7)
        tt = [c for c in costs if c.metadata.get("tier") == "time_travel"]
        assert len(tt) == 1
        assert tt[0].resource == "STAGING_DB (time-travel)"
        # 2 TB @ $23/TB/mo / 30 days/mo = 2 * 23 / 30 ≈ $1.533
        assert tt[0].cost_usd == pytest.approx(2 * 23.0 / 30.0, abs=1e-3)

    def test_storage_fallback_to_storage_usage(self, sf_credentials):
        """Legacy STORAGE_USAGE fallback is only used if
        DATABASE_STORAGE_USAGE_HISTORY raises a permission error."""
        one_tb = 1024 ** 4
        cursor = FakeCursor([
            ("USAGE_IN_CURRENCY_DAILY", []),
            ("METERING_DAILY_HISTORY", []),
            ("SERVERLESS_TASK_HISTORY", []),
            ("PIPE_USAGE_HISTORY", []),
            ("AUTOMATIC_CLUSTERING_HISTORY", []),
            ("MATERIALIZED_VIEW_REFRESH_HISTORY", []),
            ("SEARCH_OPTIMIZATION_HISTORY", []),
            ("REPLICATION_USAGE_HISTORY", []),
            ("QUERY_ACCELERATION_HISTORY", []),
            ("SNOWPIPE_STREAMING_CLIENT_HISTORY", []),
            ("SNOWPARK_CONTAINER_SERVICES_HISTORY", []),
            ("HYBRID_TABLE_USAGE_HISTORY", []),
            ("CORTEX_FUNCTIONS_USAGE_HISTORY", []),
            ("CORTEX_ANALYST_USAGE_HISTORY", []),
            ("QUERY_ATTRIBUTION_HISTORY", []),
            ("DATABASE_STORAGE_USAGE_HISTORY", Exception("access denied for DATABASE_STORAGE_USAGE_HISTORY")),
            ("STORAGE_USAGE", (one_tb, 0.25 * one_tb, date(2026, 3, 1))),
        ])
        conn = _build_connector_with_cursor(sf_credentials, cursor)
        costs = conn.fetch_costs(days=7)
        storage = [c for c in costs if c.metadata.get("source", "").endswith("STORAGE_USAGE")]
        assert len(storage) == 2
        tiers = {c.metadata["tier"] for c in storage}
        assert tiers == {"active", "failsafe"}


# ---------------------------------------------------------------------------
# Structured permission error messages
# ---------------------------------------------------------------------------
class TestStructuredErrors:

    def test_permission_error_message_includes_grant(self):
        err = SnowflakePermissionError(
            view="SNOWFLAKE.ACCOUNT_USAGE.METERING_DAILY_HISTORY",
            role="COSTLY_READ",
        )
        msg = str(err)
        assert "METERING_DAILY_HISTORY" in msg
        assert "COSTLY_READ" in msg
        assert "GRANT IMPORTED PRIVILEGES" in msg
        assert "SNOWFLAKE" in msg

    def test_org_usage_error_message_mentions_org_role(self):
        err = SnowflakePermissionError(
            view="SNOWFLAKE.ORGANIZATION_USAGE.USAGE_IN_CURRENCY_DAILY",
            role="COSTLY_READ",
        )
        msg = str(err)
        assert "ORGANIZATION_USAGE_VIEWER" in msg or "ORGANIZATION_USAGE" in msg

    def test_no_silent_failure_on_connection(self, sf_credentials):
        conn = SnowflakeConnector(sf_credentials)

        def _connect_fails():
            raise RuntimeError("TCP connection timed out")

        conn._connect = _connect_fails  # type: ignore[method-assign]
        costs = conn.fetch_costs(days=7)
        assert costs == []
        # Error is surfaced via warnings.
        assert any("timed out" in w for w in conn.warnings)


# ---------------------------------------------------------------------------
# UnifiedCost schema compliance
# ---------------------------------------------------------------------------
class TestUnifiedCostCompliance:

    def test_all_records_valid(self, sf_credentials):
        cursor = FakeCursor([
            (
                "USAGE_IN_CURRENCY_DAILY",
                [(date(2026, 3, 1), "A", "COMPUTE", "t", 1.0, "credits", 3.0, "USD")],
            ),
            ("QUERY_ATTRIBUTION_HISTORY", [("2026-03-01", "u", "r", "w", "q", 1.0)]),
            ("DATABASE_STORAGE_USAGE_HISTORY", [(date(2026, 3, 1), "DB", 1024**4, 0.0)]),
            ("TABLE_STORAGE_METRICS", []),
        ])
        conn = _build_connector_with_cursor(sf_credentials, cursor)
        costs = conn.fetch_costs(days=7)
        assert len(costs) >= 3
        for c in costs:
            assert isinstance(c, UnifiedCost)
            assert c.platform == "snowflake"
            assert isinstance(c.category, CostCategory)
            assert c.cost_usd >= 0
            assert len(c.date) == 10  # YYYY-MM-DD
            assert c.service.startswith("snowflake_")

    def test_timezone_aware_dates(self, sf_credentials):
        """fetch_costs should never use naive datetime.utcnow() —
        resource dates coming from Snowflake rows should always be 10 chars."""
        cursor = FakeCursor([
            ("USAGE_IN_CURRENCY_DAILY", []),
            ("METERING_DAILY_HISTORY", []),
            ("SERVERLESS_TASK_HISTORY", []),
            ("PIPE_USAGE_HISTORY", []),
            ("AUTOMATIC_CLUSTERING_HISTORY", []),
            ("MATERIALIZED_VIEW_REFRESH_HISTORY", []),
            ("SEARCH_OPTIMIZATION_HISTORY", []),
            ("REPLICATION_USAGE_HISTORY", []),
            ("QUERY_ACCELERATION_HISTORY", []),
            ("SNOWPIPE_STREAMING_CLIENT_HISTORY", []),
            ("SNOWPARK_CONTAINER_SERVICES_HISTORY", []),
            ("HYBRID_TABLE_USAGE_HISTORY", []),
            ("CORTEX_FUNCTIONS_USAGE_HISTORY", []),
            ("CORTEX_ANALYST_USAGE_HISTORY", []),
            ("QUERY_ATTRIBUTION_HISTORY", []),
            ("DATABASE_STORAGE_USAGE_HISTORY", []),
            ("TABLE_STORAGE_METRICS", [("DB1", 1024**4)]),
        ])
        conn = _build_connector_with_cursor(sf_credentials, cursor)
        costs = conn.fetch_costs(days=7)
        for c in costs:
            assert len(c.date) == 10


# ---------------------------------------------------------------------------
# Zero-credit rows are filtered out
# ---------------------------------------------------------------------------
class TestZeroCreditFiltering:

    def test_zero_usd_org_usage_skipped(self, sf_credentials):
        cursor = FakeCursor([
            (
                "USAGE_IN_CURRENCY_DAILY",
                [
                    (date(2026, 3, 1), "A", "COMPUTE", "t", 0.0, "credits", 0.0, "USD"),
                    (date(2026, 3, 1), "A", "COMPUTE", "t", 1.0, "credits", 3.0, "USD"),
                ],
            ),
            ("QUERY_ATTRIBUTION_HISTORY", []),
            ("DATABASE_STORAGE_USAGE_HISTORY", []),
            ("TABLE_STORAGE_METRICS", []),
        ])
        conn = _build_connector_with_cursor(sf_credentials, cursor)
        costs = conn.fetch_costs(days=7)
        org = [c for c in costs if c.metadata.get("source", "").endswith("USAGE_IN_CURRENCY_DAILY")]
        assert len(org) == 1
        assert org[0].cost_usd == 3.0

    def test_zero_credit_serverless_skipped(self, sf_credentials):
        cursor = FakeCursor([
            ("USAGE_IN_CURRENCY_DAILY", Exception("SQL access control error: insufficient privileges")),
            ("METERING_DAILY_HISTORY", []),
            ("SERVERLESS_TASK_HISTORY", [("2026-03-01", "task_a", 0.0), ("2026-03-01", "task_b", 1.0)]),
            ("PIPE_USAGE_HISTORY", []),
            ("AUTOMATIC_CLUSTERING_HISTORY", []),
            ("MATERIALIZED_VIEW_REFRESH_HISTORY", []),
            ("SEARCH_OPTIMIZATION_HISTORY", []),
            ("REPLICATION_USAGE_HISTORY", []),
            ("QUERY_ACCELERATION_HISTORY", []),
            ("SNOWPIPE_STREAMING_CLIENT_HISTORY", []),
            ("SNOWPARK_CONTAINER_SERVICES_HISTORY", []),
            ("HYBRID_TABLE_USAGE_HISTORY", []),
            ("CORTEX_FUNCTIONS_USAGE_HISTORY", []),
            ("CORTEX_ANALYST_USAGE_HISTORY", []),
            ("QUERY_ATTRIBUTION_HISTORY", []),
            ("DATABASE_STORAGE_USAGE_HISTORY", []),
            ("TABLE_STORAGE_METRICS", []),
        ])
        conn = _build_connector_with_cursor(sf_credentials, cursor)
        costs = conn.fetch_costs(days=7)
        tasks = [c for c in costs if c.service == "snowflake_serverless_tasks"]
        assert len(tasks) == 1
        assert tasks[0].resource == "task_b"


# ---------------------------------------------------------------------------
# Real-world combined scenario
# ---------------------------------------------------------------------------
class TestCombinedScenario:

    def test_end_to_end_with_everything(self, sf_credentials):
        """Simulate a realistic account: org usage returns compute + cloud
        services + cortex, plus attribution and storage breakdown."""
        one_tb = 1024 ** 4
        sf_credentials["pricing_overrides"] = {
            "credit_price_usd": 2.5,
            "storage_price_per_tb": 20.0,
        }
        cursor = FakeCursor([
            (
                "USAGE_IN_CURRENCY_DAILY",
                [
                    (date(2026, 3, 1), "ACCT", "COMPUTE", "warehouse", 40.0, "credits", 100.0, "USD"),
                    (date(2026, 3, 1), "ACCT", "CLOUD_SERVICES", "cs", 4.0, "credits", 10.0, "USD"),
                    (date(2026, 3, 1), "ACCT", "AI_SERVICES", "cortex", 2.0, "credits", 5.0, "USD"),
                    (date(2026, 3, 1), "ACCT", "SERVERLESS_TASK", "tasks", 0.5, "credits", 1.25, "USD"),
                ],
            ),
            (
                "QUERY_ATTRIBUTION_HISTORY",
                [
                    ("2026-03-01", "alice", "ANALYST", "ETL_WH", "nightly", 20.0),
                    ("2026-03-01", "svc_bot", "SERVICE", "ETL_WH", None, 15.0),
                ],
            ),
            (
                "DATABASE_STORAGE_USAGE_HISTORY",
                [(date(2026, 3, 1), "PROD_DB", 3 * one_tb, 0.5 * one_tb)],
            ),
            ("TABLE_STORAGE_METRICS", [("PROD_DB", 1 * one_tb)]),
        ])
        conn = _build_connector_with_cursor(sf_credentials, cursor)
        costs = conn.fetch_costs(days=7)

        # Org usage should produce 4 rows.
        org = [c for c in costs if c.metadata.get("source") == "ORGANIZATION_USAGE.USAGE_IN_CURRENCY_DAILY"]
        assert len(org) == 4

        # Attribution produces 2 rows.
        attribution = [c for c in costs if c.service == "snowflake_attribution"]
        assert len(attribution) == 2

        # Storage: 1 daily row (active + failsafe) + 1 time-travel snapshot.
        storage = [c for c in costs if c.category == CostCategory.storage]
        tiers = [c.metadata.get("tier") for c in storage]
        assert tiers.count("active") == 1
        assert tiers.count("failsafe") == 1
        assert tiers.count("time_travel") == 1

        # No warnings in the happy path.
        assert conn.warnings == []

        # Total cost is finite and positive.
        total = sum(c.cost_usd for c in costs)
        assert total > 0

    def test_mixed_warnings_still_returns_what_it_can(self, sf_credentials):
        """If some views are denied, we still return partial results and
        surface warnings — never silently empty."""
        cursor = FakeCursor([
            ("USAGE_IN_CURRENCY_DAILY", Exception("SQL access control error: insufficient privileges")),
            (
                "METERING_DAILY_HISTORY",
                [(date(2026, 3, 1), "COMPUTE", 5.0, 0.0, 0.0, 5.0)],
            ),
            ("SERVERLESS_TASK_HISTORY", Exception("SQL access control error: insufficient privileges")),
            ("PIPE_USAGE_HISTORY", []),
            ("AUTOMATIC_CLUSTERING_HISTORY", []),
            ("MATERIALIZED_VIEW_REFRESH_HISTORY", []),
            ("SEARCH_OPTIMIZATION_HISTORY", []),
            ("REPLICATION_USAGE_HISTORY", []),
            ("QUERY_ACCELERATION_HISTORY", []),
            ("SNOWPIPE_STREAMING_CLIENT_HISTORY", []),
            ("SNOWPARK_CONTAINER_SERVICES_HISTORY", []),
            ("HYBRID_TABLE_USAGE_HISTORY", []),
            ("CORTEX_FUNCTIONS_USAGE_HISTORY", []),
            ("CORTEX_ANALYST_USAGE_HISTORY", []),
            ("QUERY_ATTRIBUTION_HISTORY", Exception("access denied: insufficient privileges")),
            ("DATABASE_STORAGE_USAGE_HISTORY", []),
            ("TABLE_STORAGE_METRICS", []),
        ])
        conn = _build_connector_with_cursor(sf_credentials, cursor)
        costs = conn.fetch_costs(days=7)
        # Compute metering still worked.
        compute = [c for c in costs if c.service == "snowflake_compute"]
        assert len(compute) == 1
        # Warnings for each permission failure.
        assert len(conn.warnings) >= 3
        permission_warnings = [w for w in conn.warnings if "GRANT" in w]
        assert len(permission_warnings) >= 2


# ---------------------------------------------------------------------------
# AI_SERVICES_USAGE_HISTORY — April 2026 GA
# ---------------------------------------------------------------------------
class TestAIServicesUsageHistory:
    """Tests for the per-model / per-family AI spend drill-down."""

    @pytest.fixture
    def ai_services_row_types(self) -> list[tuple]:
        """One row per documented AI family in the April 2026 release."""
        return [
            # (date, service_type, function_name, model_name, tokens, credits)
            ("2026-04-15", "CORTEX_FUNCTIONS", "COMPLETE", "llama3-70b", 1_000_000, 2.5),
            ("2026-04-15", "CORTEX_FUNCTIONS", "COMPLETE", "claude-3-5-sonnet", 500_000, 5.0),
            ("2026-04-15", "CORTEX_FUNCTIONS", "EMBED_TEXT_768", "arctic", 2_000_000, 0.4),
            ("2026-04-15", "CORTEX_FUNCTIONS", "TRANSLATE", "llama3-8b", 300_000, 0.3),
            ("2026-04-15", "CORTEX_FUNCTIONS", "SENTIMENT", "mistral-large", 200_000, 0.6),
            ("2026-04-15", "CORTEX_FUNCTIONS", "SUMMARIZE", "llama3-70b", 400_000, 1.0),
            ("2026-04-15", "CORTEX_FUNCTIONS", "EXTRACT_ANSWER", "llama3-8b", 150_000, 0.15),
            ("2026-04-15", "CORTEX_FUNCTIONS", "CLASSIFY_TEXT", "mistral-7b", 100_000, 0.08),
            ("2026-04-15", "CORTEX_ANALYST", "ANALYST_MESSAGE", None, 0, 3.2),
            ("2026-04-15", "CORTEX_SEARCH", "SEARCH_QUERY", None, 0, 0.9),
            ("2026-04-15", "DOCUMENT_AI", "EXTRACT", None, 0, 1.8),
            ("2026-04-15", "UNIVERSAL_SEARCH", "SEARCH", None, 0, 0.4),
        ]

    def _programs_with_ai_services(self, rows: list[tuple]) -> list[tuple]:
        """Shared setup: empty org usage + empty primaries + AI services rows."""
        return [
            ("USAGE_IN_CURRENCY_DAILY", []),
            ("QUERY_ATTRIBUTION_HISTORY", []),
            ("DATABASE_STORAGE_USAGE_HISTORY", []),
            ("TABLE_STORAGE_METRICS", []),
            ("AI_SERVICES_USAGE_HISTORY", rows),
        ]

    @pytest.mark.parametrize(
        "service_type,expected_slug,expected_category",
        [
            ("CORTEX_FUNCTIONS", "snowflake_cortex", CostCategory.ai_inference),
            ("CORTEX_ANALYST", "snowflake_cortex_analyst", CostCategory.ai_inference),
            ("CORTEX_SEARCH", "snowflake_cortex_search", CostCategory.ai_inference),
            ("DOCUMENT_AI", "snowflake_document_ai", CostCategory.ai_inference),
            ("UNIVERSAL_SEARCH", "snowflake_universal_search", CostCategory.ai_inference),
        ],
    )
    def test_each_ai_family_slug_and_category(
        self, sf_credentials, service_type, expected_slug, expected_category
    ):
        rows = [("2026-04-15", service_type, "FN", "some-model", 1000, 2.0)]
        cursor = FakeCursor(self._programs_with_ai_services(rows))
        conn = _build_connector_with_cursor(sf_credentials, cursor)
        costs = conn.fetch_costs(days=7)
        ai = [c for c in costs if c.metadata.get("source") == "ACCOUNT_USAGE.AI_SERVICES_USAGE_HISTORY"]
        assert len(ai) == 1
        assert ai[0].service == expected_slug
        assert ai[0].category == expected_category
        assert ai[0].metadata["drilldown"] is True

    def test_service_type_alias_cortex_maps_to_functions(self, sf_credentials):
        """Older accounts may emit the short alias CORTEX; we should treat
        it as CORTEX_FUNCTIONS."""
        rows = [("2026-04-15", "CORTEX", "COMPLETE", "llama3-70b", 1000, 1.0)]
        cursor = FakeCursor(self._programs_with_ai_services(rows))
        conn = _build_connector_with_cursor(sf_credentials, cursor)
        costs = conn.fetch_costs(days=7)
        ai = [c for c in costs if c.service == "snowflake_cortex"]
        assert len(ai) == 1
        assert ai[0].metadata["service_type"] == "CORTEX"

    def test_per_model_pricing_override(self, sf_credentials):
        """Per-model override must beat the global credit price."""
        sf_credentials["pricing_overrides"] = {
            "credit_price_usd": 3.0,
            "cortex_model_prices": {
                "llama3-70b": 1.2,            # cheap Llama-3
                "claude-3-5-sonnet": 5.0,     # premium Claude
            },
        }
        rows = [
            ("2026-04-15", "CORTEX_FUNCTIONS", "COMPLETE", "llama3-70b", 1_000_000, 10.0),
            ("2026-04-15", "CORTEX_FUNCTIONS", "COMPLETE", "claude-3-5-sonnet", 500_000, 4.0),
            ("2026-04-15", "CORTEX_FUNCTIONS", "COMPLETE", "unknown-xyz", 100_000, 1.0),
        ]
        cursor = FakeCursor(self._programs_with_ai_services(rows))
        conn = _build_connector_with_cursor(sf_credentials, cursor)
        costs = conn.fetch_costs(days=7)
        ai = {c.resource: c for c in costs if c.metadata.get("source") == "ACCOUNT_USAGE.AI_SERVICES_USAGE_HISTORY"}
        # Llama-3-70b: 10 credits * $1.2 = $12
        assert ai["llama3-70b"].cost_usd == 12.0
        assert ai["llama3-70b"].metadata["credit_price_usd"] == 1.2
        # Claude: 4 credits * $5.0 = $20
        assert ai["claude-3-5-sonnet"].cost_usd == 20.0
        assert ai["claude-3-5-sonnet"].metadata["credit_price_usd"] == 5.0
        # Unknown model -> falls back to service_type price (CORTEX) -> base
        assert ai["unknown-xyz"].cost_usd == 3.0  # 1 credit * $3
        assert ai["unknown-xyz"].metadata["credit_price_usd"] == 3.0

    def test_case_insensitive_model_match(self, sf_credentials):
        """Snowflake sometimes returns MixedCase model names; our
        override-lookup must be case-insensitive."""
        sf_credentials["pricing_overrides"] = {
            "cortex_model_prices": {"Llama3-70B": 1.25},
        }
        rows = [
            ("2026-04-15", "CORTEX_FUNCTIONS", "COMPLETE", "LLAMA3-70B", 100, 2.0),
        ]
        cursor = FakeCursor(self._programs_with_ai_services(rows))
        conn = _build_connector_with_cursor(sf_credentials, cursor)
        costs = conn.fetch_costs(days=7)
        row = next(c for c in costs if c.metadata.get("source") == "ACCOUNT_USAGE.AI_SERVICES_USAGE_HISTORY")
        assert row.metadata["credit_price_usd"] == 1.25
        assert row.metadata["model_name"] == "llama3-70b"  # normalized

    def test_tokens_populate_usage_quantity(self, sf_credentials):
        """Token-bearing rows use tokens as the usage_quantity/unit."""
        rows = [
            ("2026-04-15", "CORTEX_FUNCTIONS", "COMPLETE", "llama3-70b", 1_000_000, 2.0),
            ("2026-04-15", "CORTEX_ANALYST", "ANALYST_MESSAGE", None, 0, 1.0),
        ]
        cursor = FakeCursor(self._programs_with_ai_services(rows))
        conn = _build_connector_with_cursor(sf_credentials, cursor)
        costs = conn.fetch_costs(days=7)
        ai = {c.service: c for c in costs if c.metadata.get("source") == "ACCOUNT_USAGE.AI_SERVICES_USAGE_HISTORY"}
        cortex = ai["snowflake_cortex"]
        assert cortex.usage_unit == "tokens"
        assert cortex.usage_quantity == 1_000_000
        # Analyst has no tokens column -> fall back to credits
        analyst = ai["snowflake_cortex_analyst"]
        assert analyst.usage_unit == "credits"

    def test_zero_credit_rows_filtered(self, sf_credentials):
        rows = [
            ("2026-04-15", "CORTEX_FUNCTIONS", "COMPLETE", "llama3-70b", 1000, 0.0),
            ("2026-04-15", "CORTEX_FUNCTIONS", "COMPLETE", "llama3-70b", 1000, 2.0),
        ]
        cursor = FakeCursor(self._programs_with_ai_services(rows))
        conn = _build_connector_with_cursor(sf_credentials, cursor)
        costs = conn.fetch_costs(days=7)
        ai = [c for c in costs if c.metadata.get("source") == "ACCOUNT_USAGE.AI_SERVICES_USAGE_HISTORY"]
        assert len(ai) == 1

    def test_permission_error_adds_warning(self, sf_credentials):
        """Permission failure on the April-2026 view must not crash the
        fetch; emit a clear warning with the required GRANT."""
        programs = [
            ("USAGE_IN_CURRENCY_DAILY", []),
            ("QUERY_ATTRIBUTION_HISTORY", []),
            ("DATABASE_STORAGE_USAGE_HISTORY", []),
            ("TABLE_STORAGE_METRICS", []),
            ("AI_SERVICES_USAGE_HISTORY", Exception("access denied: insufficient privileges for AI_SERVICES_USAGE_HISTORY")),
        ]
        cursor = FakeCursor(programs)
        conn = _build_connector_with_cursor(sf_credentials, cursor)
        conn.fetch_costs(days=7)
        assert any("AI_SERVICES_USAGE_HISTORY" in w for w in conn.warnings)
        assert any("GRANT IMPORTED PRIVILEGES" in w for w in conn.warnings)

    def test_missing_view_on_old_accounts_warns_softly(self, sf_credentials):
        """Pre-April-2026 accounts raise a table-not-found. Connector must
        fall through silently-ish (warning but not error)."""
        programs = [
            ("USAGE_IN_CURRENCY_DAILY", []),
            ("QUERY_ATTRIBUTION_HISTORY", []),
            ("DATABASE_STORAGE_USAGE_HISTORY", []),
            ("TABLE_STORAGE_METRICS", []),
            (
                "AI_SERVICES_USAGE_HISTORY",
                Exception("SQL compilation error: Object 'SNOWFLAKE.ACCOUNT_USAGE.AI_SERVICES_USAGE_HISTORY' does not exist."),
            ),
        ]
        cursor = FakeCursor(programs)
        conn = _build_connector_with_cursor(sf_credentials, cursor)
        conn.fetch_costs(days=7)
        # "does not exist" matches the permission-error classifier, so the
        # warning is emitted with the canonical GRANT remediation — that's
        # fine; the point is that fetch_costs() did not raise.
        assert any("AI_SERVICES_USAGE_HISTORY" in w for w in conn.warnings)

    def test_drilldown_opt_out(self, sf_credentials):
        """Setting enable_ai_services_drilldown=False must skip the query."""
        sf_credentials["pricing_overrides"] = {"enable_ai_services_drilldown": False}
        programs = [
            ("USAGE_IN_CURRENCY_DAILY", []),
            ("QUERY_ATTRIBUTION_HISTORY", []),
            ("DATABASE_STORAGE_USAGE_HISTORY", []),
            ("TABLE_STORAGE_METRICS", []),
        ]
        cursor = FakeCursor(programs)
        conn = _build_connector_with_cursor(sf_credentials, cursor)
        conn.fetch_costs(days=7)
        assert not any("AI_SERVICES_USAGE_HISTORY" in s for s in cursor.executed)

    def test_full_april_release_breakdown(self, sf_credentials, ai_services_row_types):
        """Ingest one row per AI family + function and verify:
        - each is classified into ai_inference
        - per-model pricing is honoured
        - drilldown=True on every row
        - cost math round-trips from credits * credit_price
        """
        sf_credentials["pricing_overrides"] = {
            "credit_price_usd": 3.0,
            "cortex_model_prices": {"llama3-70b": 1.2, "claude-3-5-sonnet": 5.0},
        }
        cursor = FakeCursor(self._programs_with_ai_services(ai_services_row_types))
        conn = _build_connector_with_cursor(sf_credentials, cursor)
        costs = conn.fetch_costs(days=7)
        ai = [c for c in costs if c.metadata.get("source") == "ACCOUNT_USAGE.AI_SERVICES_USAGE_HISTORY"]
        assert len(ai) == len(ai_services_row_types)
        for c in ai:
            assert c.category == CostCategory.ai_inference
            assert c.metadata["drilldown"] is True
            # Round-trip: credits * credit_price_usd == cost_usd
            credits = c.metadata["credits"]
            price = c.metadata["credit_price_usd"]
            assert c.cost_usd == pytest.approx(round(credits * price, 4), abs=1e-3)

    def test_pricing_config_credit_price_for_cortex_model(self):
        cfg = PricingConfig.from_credentials({
            "pricing_overrides": {
                "credit_price_usd": 3.0,
                "service_type_prices": {"CORTEX_ANALYST": 4.0},
                "cortex_model_prices": {"llama3-70b": 1.2},
            }
        })
        assert cfg.credit_price_for_cortex_model("llama3-70b") == 1.2
        # Case-insensitive.
        assert cfg.credit_price_for_cortex_model("LLAMA3-70B") == 1.2
        # Unknown model -> service-type override wins.
        assert cfg.credit_price_for_cortex_model(None, service_type="CORTEX_ANALYST") == 4.0
        # Unknown model + unknown service -> base.
        assert cfg.credit_price_for_cortex_model(None, service_type="CORTEX") == 3.0

    def test_service_family_alias_mapping(self):
        """AI_SERVICE_FAMILY_TO_TYPE must include every April-2026
        SERVICE_TYPE value emitted by the view."""
        for alias in (
            "CORTEX_FUNCTIONS", "CORTEX_FUNCTION", "AI_FUNCTIONS", "CORTEX",
            "CORTEX_ANALYST", "ANALYST", "CORTEX_SEARCH",
            "CORTEX_SEARCH_SERVING", "DOCUMENT_AI", "DOCUMENT_INTELLIGENCE",
            "UNIVERSAL_SEARCH", "AI_SERVICES",
        ):
            assert alias in AI_SERVICE_FAMILY_TO_TYPE


# ---------------------------------------------------------------------------
# ACCOUNT_USAGE latency / freshness probe
# ---------------------------------------------------------------------------
class TestFreshnessProbe:
    """Surfaces how stale the ACCOUNT_USAGE / ORGANIZATION_USAGE view data
    is so the UI can render a "last updated" badge and warn on lag."""

    def _probe_programs(self, latest: Any) -> list[tuple]:
        return [
            ("USAGE_IN_CURRENCY_DAILY", []),
            ("QUERY_ATTRIBUTION_HISTORY", []),
            ("DATABASE_STORAGE_USAGE_HISTORY", []),
            ("TABLE_STORAGE_METRICS", []),
            # Freshness probe uses USAGE_IN_CURRENCY_DAILY first. It runs
            # AFTER the initial org-usage fetch has consumed its program,
            # so we register a SECOND USAGE_IN_CURRENCY_DAILY program
            # whose tuple becomes the MAX() result.
            ("USAGE_IN_CURRENCY_DAILY", (latest,)),
        ]

    def test_freshness_recent_no_warning(self, sf_credentials):
        from datetime import datetime, timedelta, timezone

        recent = datetime.now(timezone.utc) - timedelta(hours=25)  # 1h beyond daily lag
        cursor = FakeCursor(self._probe_programs(recent))
        conn = _build_connector_with_cursor(sf_credentials, cursor)
        conn.fetch_costs(days=7)
        # 1h beyond 24h daily lag is below the 3h warn threshold -> no warning.
        latency_warnings = [w for w in conn.warnings if "freshness" in w]
        assert latency_warnings == []
        assert conn.freshness is not None
        assert conn.freshness["view"].endswith("USAGE_IN_CURRENCY_DAILY")
        assert conn.freshness["age_hours"] >= 24.0

    def test_freshness_lag_warning(self, sf_credentials):
        from datetime import datetime, timedelta, timezone

        laggy = datetime.now(timezone.utc) - timedelta(hours=24 + FRESHNESS_WARN_HOURS + 1)
        cursor = FakeCursor(self._probe_programs(laggy))
        conn = _build_connector_with_cursor(sf_credentials, cursor)
        conn.fetch_costs(days=7)
        latency_warnings = [w for w in conn.warnings if "freshness" in w]
        assert latency_warnings, "Expected a freshness warning when lag exceeds 3h"
        assert conn.freshness["adjusted_hours"] >= FRESHNESS_WARN_HOURS

    def test_freshness_stale_critical(self, sf_credentials):
        from datetime import datetime, timedelta, timezone

        stale = datetime.now(timezone.utc) - timedelta(hours=24 + FRESHNESS_STALE_HOURS + 2)
        cursor = FakeCursor(self._probe_programs(stale))
        conn = _build_connector_with_cursor(sf_credentials, cursor)
        conn.fetch_costs(days=7)
        stale_warnings = [w for w in conn.warnings if "STALE" in w]
        assert stale_warnings, "Expected a STALE-tagged warning at critical lag"

    def test_freshness_none_when_all_views_denied(self, sf_credentials):
        """If every freshness view is denied, self.freshness stays None and
        no warning is added."""
        programs = [
            ("USAGE_IN_CURRENCY_DAILY", Exception("SQL access control error: insufficient privileges")),
            ("METERING_DAILY_HISTORY", []),
            ("SERVERLESS_TASK_HISTORY", []),
            ("PIPE_USAGE_HISTORY", []),
            ("AUTOMATIC_CLUSTERING_HISTORY", []),
            ("MATERIALIZED_VIEW_REFRESH_HISTORY", []),
            ("SEARCH_OPTIMIZATION_HISTORY", []),
            ("REPLICATION_USAGE_HISTORY", []),
            ("QUERY_ACCELERATION_HISTORY", []),
            ("SNOWPIPE_STREAMING_CLIENT_HISTORY", []),
            ("SNOWPARK_CONTAINER_SERVICES_HISTORY", []),
            ("HYBRID_TABLE_USAGE_HISTORY", []),
            ("CORTEX_FUNCTIONS_USAGE_HISTORY", []),
            ("CORTEX_ANALYST_USAGE_HISTORY", []),
            ("QUERY_ATTRIBUTION_HISTORY", []),
            ("DATABASE_STORAGE_USAGE_HISTORY", []),
            ("TABLE_STORAGE_METRICS", []),
            ("AI_SERVICES_USAGE_HISTORY", []),
            # Freshness probe: every view raises.
            ("USAGE_IN_CURRENCY_DAILY", Exception("access denied")),
            ("METERING_DAILY_HISTORY", Exception("access denied")),
            ("WAREHOUSE_METERING_HISTORY", Exception("access denied")),
        ]
        cursor = FakeCursor(programs)
        conn = _build_connector_with_cursor(sf_credentials, cursor)
        conn.fetch_costs(days=7)
        assert conn.freshness is None

    def test_freshness_probe_skipped_when_prefer_org_usage_false(self, sf_credentials):
        """When the customer has opted out of ORGANIZATION_USAGE, the
        freshness probe must NOT touch it — use METERING_DAILY_HISTORY
        instead."""
        from datetime import date as _date

        sf_credentials["pricing_overrides"] = {"prefer_org_usage": False}
        programs = [
            ("METERING_DAILY_HISTORY", []),
            ("SERVERLESS_TASK_HISTORY", []),
            ("PIPE_USAGE_HISTORY", []),
            ("AUTOMATIC_CLUSTERING_HISTORY", []),
            ("MATERIALIZED_VIEW_REFRESH_HISTORY", []),
            ("SEARCH_OPTIMIZATION_HISTORY", []),
            ("REPLICATION_USAGE_HISTORY", []),
            ("QUERY_ACCELERATION_HISTORY", []),
            ("SNOWPIPE_STREAMING_CLIENT_HISTORY", []),
            ("SNOWPARK_CONTAINER_SERVICES_HISTORY", []),
            ("HYBRID_TABLE_USAGE_HISTORY", []),
            ("CORTEX_FUNCTIONS_USAGE_HISTORY", []),
            ("CORTEX_ANALYST_USAGE_HISTORY", []),
            ("QUERY_ATTRIBUTION_HISTORY", []),
            ("DATABASE_STORAGE_USAGE_HISTORY", []),
            ("TABLE_STORAGE_METRICS", []),
            ("AI_SERVICES_USAGE_HISTORY", []),
            # Freshness probe will go to METERING_DAILY_HISTORY.
            ("METERING_DAILY_HISTORY", (_date(2026, 4, 22),)),
        ]
        cursor = FakeCursor(programs)
        conn = _build_connector_with_cursor(sf_credentials, cursor)
        conn.fetch_costs(days=7)
        # No SELECT MAX(USAGE_DATE) FROM ORGANIZATION_USAGE
        freshness_org = [s for s in cursor.executed
                         if s.strip().upper().startswith("SELECT MAX")
                         and "ORGANIZATION_USAGE" in s]
        assert freshness_org == []
        # But some freshness call landed on METERING.
        assert conn.freshness is not None
        assert "METERING_DAILY_HISTORY" in conn.freshness["view"]


# ---------------------------------------------------------------------------
# PricingConfig extensions for per-model Cortex prices
# ---------------------------------------------------------------------------
class TestPricingConfigCortexModels:

    def test_defaults_empty(self):
        cfg = PricingConfig.from_credentials({})
        assert cfg.cortex_model_prices == {}
        assert cfg.enable_ai_services_drilldown is True

    def test_model_prices_lowercased(self):
        cfg = PricingConfig.from_credentials({
            "pricing_overrides": {
                "cortex_model_prices": {"Llama3-70B": 1.2, "Claude-3-5-Sonnet": 5.0}
            }
        })
        assert cfg.cortex_model_prices == {"llama3-70b": 1.2, "claude-3-5-sonnet": 5.0}

    def test_invalid_model_price_ignored(self):
        cfg = PricingConfig.from_credentials({
            "pricing_overrides": {
                "cortex_model_prices": {"llama3-70b": "not-a-number", "claude": -1, "arctic": 0.5}
            }
        })
        assert "llama3-70b" not in cfg.cortex_model_prices
        assert "claude" not in cfg.cortex_model_prices  # -1 is not positive
        assert cfg.cortex_model_prices["arctic"] == 0.5

    def test_disable_drilldown(self):
        cfg = PricingConfig.from_credentials({
            "pricing_overrides": {"enable_ai_services_drilldown": False}
        })
        assert cfg.enable_ai_services_drilldown is False
