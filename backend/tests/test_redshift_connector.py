"""Tests for RedshiftConnector.

The connector talks to two AWS surfaces: the ``redshift-data`` Data API
(``execute_statement`` / ``get_statement_result``) and the ``redshift``
control plane (``describe_clusters``). We patch the ``_RedshiftDataClient``
and the ``boto3`` import to keep tests fast, deterministic, and offline.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from app.models.platform import CostCategory, UnifiedCost
from app.services.connectors.redshift_connector import (
    DEFAULT_MANAGED_STORAGE_GB_MONTH,
    DEFAULT_NODE_HOUR,
    DEFAULT_SERVERLESS_RPU_HOUR,
    DEFAULT_SPECTRUM_PER_TB,
    RedshiftConnector,
    RedshiftError,
    RedshiftPricing,
    _coerce_int,
    _decode_record,
    _encode_params,
    _merge_pricing,
    _translate_boto_error,
)


_TB = 1024 ** 4
_GB = 1024 ** 3
_SECONDS_PER_HOUR = 3600.0


# ─── Helpers ───────────────────────────────────────────────────────────


def _provisioned_creds(**overrides) -> dict:
    base = {
        "aws_access_key_id": "AKIAIOSFODNN7EXAMPLE",
        "aws_secret_access_key": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        "region": "us-east-1",
        "cluster_identifier": "analytics-prod",
        "database": "analytics",
        "db_user": "costly_reader",
        "node_type": "ra3.4xlarge",
    }
    base.update(overrides)
    return base


def _serverless_creds(**overrides) -> dict:
    base = {
        "aws_access_key_id": "AKIAIOSFODNN7EXAMPLE",
        "aws_secret_access_key": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        "region": "us-east-1",
        "workgroup_name": "analytics-wg",
        "database": "dev",
        "db_user": "costly_reader",
    }
    base.update(overrides)
    return base


class _FakeDataClient:
    """Routes SQL → canned rows (first substring match wins)."""

    def __init__(self, routes: list[tuple[str, list[dict] | Exception]]):
        self.routes = routes
        self.calls: list[dict] = []

    def query(self, sql: str, params=None):
        self.calls.append({"sql": sql, "params": params})
        for pattern, result in self.routes:
            if pattern in sql:
                if isinstance(result, Exception):
                    raise result
                return result
        return []


def _make_connector(
    *,
    serverless: bool = False,
    routes: list[tuple[str, list[dict] | Exception]] | None = None,
    pricing_overrides: dict | None = None,
    node_count: int = 2,
) -> tuple[RedshiftConnector, _FakeDataClient]:
    creds = _serverless_creds() if serverless else _provisioned_creds()
    conn = RedshiftConnector(creds, pricing_overrides=pricing_overrides)
    fake = _FakeDataClient(routes or [])
    conn._data_client = fake  # type: ignore[assignment]
    if not serverless:
        conn._describe_cluster_node_count = lambda: node_count  # type: ignore[assignment]
        conn._describe_cluster_node_type = lambda: creds["node_type"]  # type: ignore[assignment]
    return conn, fake


# ─── Instantiation & validation ────────────────────────────────────────


class TestInstantiation:

    def test_provisioned_success(self):
        conn = RedshiftConnector(_provisioned_creds())
        assert conn.platform == "redshift"
        assert conn.cluster_identifier == "analytics-prod"
        assert conn.workgroup_name is None
        assert conn.is_serverless is False
        assert conn.region == "us-east-1"
        assert conn.database == "analytics"

    def test_serverless_success(self):
        conn = RedshiftConnector(_serverless_creds())
        assert conn.is_serverless is True
        assert conn.workgroup_name == "analytics-wg"
        assert conn.cluster_identifier is None

    def test_missing_access_key_raises(self):
        with pytest.raises(RedshiftError, match="aws_access_key_id"):
            RedshiftConnector(_provisioned_creds(aws_access_key_id=""))

    def test_missing_secret_raises(self):
        with pytest.raises(RedshiftError, match="aws_secret_access_key"):
            RedshiftConnector(_provisioned_creds(aws_secret_access_key=""))

    def test_missing_region_raises(self):
        with pytest.raises(RedshiftError, match="region"):
            RedshiftConnector(_provisioned_creds(region=""))

    def test_no_cluster_or_workgroup_raises(self):
        creds = _provisioned_creds()
        creds.pop("cluster_identifier")
        with pytest.raises(RedshiftError, match="cluster_identifier"):
            RedshiftConnector(creds)


# ─── Pricing ───────────────────────────────────────────────────────────


class TestPricing:

    def test_defaults_exposed(self):
        assert DEFAULT_NODE_HOUR["ra3.xlplus"] > 0
        assert DEFAULT_NODE_HOUR["ra3.4xlarge"] > DEFAULT_NODE_HOUR["ra3.xlplus"]
        assert DEFAULT_NODE_HOUR["ra3.16xlarge"] > DEFAULT_NODE_HOUR["ra3.4xlarge"]
        assert DEFAULT_SERVERLESS_RPU_HOUR == 0.375
        assert DEFAULT_SPECTRUM_PER_TB == 5.0
        assert DEFAULT_MANAGED_STORAGE_GB_MONTH == 0.024

    def test_node_rate_lookup_is_case_insensitive(self):
        pricing = RedshiftPricing()
        assert pricing.node_rate("RA3.4XLarge") == DEFAULT_NODE_HOUR["ra3.4xlarge"]

    def test_node_rate_unknown_falls_back(self):
        pricing = RedshiftPricing()
        # Unknown node type should return a non-zero fallback rate.
        assert pricing.node_rate("ra9.titan") > 0

    def test_merge_pricing_applies_node_hour_override(self):
        pricing = _merge_pricing(
            {"node_hour": {"ra3.4xlarge": 2.00}, "spectrum_per_tb": 4.0}
        )
        assert pricing.node_rate("ra3.4xlarge") == 2.00
        assert pricing.node_rate("ra3.xlplus") == DEFAULT_NODE_HOUR["ra3.xlplus"]
        assert pricing.spectrum_per_tb == 4.0

    def test_merge_pricing_discount(self):
        pricing = _merge_pricing({"discount_pct": 10})
        assert pricing.apply_discount(100.0) == pytest.approx(90.0)

    def test_merge_pricing_none(self):
        pricing = _merge_pricing(None)
        assert pricing.node_rate("ra3.xlplus") == DEFAULT_NODE_HOUR["ra3.xlplus"]
        assert pricing.discount_pct == 0.0


# ─── Provisioned query costs ───────────────────────────────────────────


class TestProvisionedQueryCosts:

    def test_attributes_cost_by_execution_time(self):
        conn, _ = _make_connector(
            routes=[
                (
                    "SYS_QUERY_HISTORY",
                    [
                        {
                            "day": "2026-04-20",
                            "user_id": "123",
                            "database_name": "analytics",
                            "query_id": 42,
                            "query_type": "SELECT",
                            # 3_600_000_000 µs = 1 hour of compute
                            "execution_time": 3_600_000_000,
                            "elapsed_time": 3_600_000_000,
                            "queue_time": 0,
                            "compute_type": "main",
                            "query_label": "analytics_team",
                        }
                    ],
                ),
                ("STL_CONCURRENCY_SCALING_USAGE", []),
                ("SYS_EXTERNAL_QUERY_DETAIL", []),
            ],
            node_count=2,
        )
        costs = conn.fetch_costs(days=7)
        assert len(costs) == 1
        c = costs[0]
        assert c.platform == "redshift"
        assert c.service == "redshift_query"
        assert c.category == CostCategory.compute
        assert c.resource == "analytics-prod"
        # 1 hour × $3.26 × 2 nodes = $6.52
        assert c.cost_usd == pytest.approx(6.52, rel=1e-3)
        assert c.metadata["compute_type"] == "main"
        assert c.metadata["cluster_id"] == "analytics-prod"
        assert c.metadata["node_type"] == "ra3.4xlarge"
        assert c.metadata["node_count"] == 2
        assert c.team == "analytics_team"

    def test_skips_zero_execution_time(self):
        conn, _ = _make_connector(
            routes=[
                (
                    "SYS_QUERY_HISTORY",
                    [
                        {
                            "day": "2026-04-20",
                            "user_id": "1",
                            "query_id": 1,
                            "execution_time": 0,
                            "compute_type": "main",
                        }
                    ],
                ),
            ],
        )
        costs = conn.fetch_costs(days=1)
        assert costs == []

    def test_permission_error_logged_not_raised(self):
        conn, _ = _make_connector(
            routes=[
                (
                    "SYS_QUERY_HISTORY",
                    RedshiftError("Access denied: SELECT on SYS_QUERY_HISTORY"),
                ),
                ("STL_CONCURRENCY_SCALING_USAGE", []),
                ("SYS_EXTERNAL_QUERY_DETAIL", []),
            ],
        )
        costs = conn.fetch_costs(days=1)
        # Permission error must degrade to empty, not raise.
        assert costs == []


# ─── Concurrency scaling ───────────────────────────────────────────────


class TestConcurrencyScaling:

    def test_cs_billable_seconds_costed(self):
        conn, _ = _make_connector(
            routes=[
                ("SYS_QUERY_HISTORY", []),
                (
                    "STL_CONCURRENCY_SCALING_USAGE",
                    [
                        {
                            "day": "2026-04-20",
                            "cluster_identifier": "analytics-prod",
                            # 3600 billable seconds = 1 hour
                            "billable_seconds": 3600,
                            "free_seconds": 3600,
                        }
                    ],
                ),
                ("SYS_EXTERNAL_QUERY_DETAIL", []),
            ],
            node_count=2,
        )
        costs = conn.fetch_costs(days=1)
        cs = [c for c in costs if c.service == "redshift_concurrency_scaling"]
        assert len(cs) == 1
        # 1 hour × $3.26 × 2 nodes
        assert cs[0].cost_usd == pytest.approx(6.52, rel=1e-3)
        assert cs[0].metadata["compute_type"] == "CS"
        assert cs[0].metadata["free_seconds"] == 3600

    def test_cs_zero_billable_skipped(self):
        conn, _ = _make_connector(
            routes=[
                ("SYS_QUERY_HISTORY", []),
                (
                    "STL_CONCURRENCY_SCALING_USAGE",
                    [
                        {
                            "day": "2026-04-20",
                            "cluster_identifier": "analytics-prod",
                            "billable_seconds": 0,
                            "free_seconds": 3600,
                        }
                    ],
                ),
                ("SYS_EXTERNAL_QUERY_DETAIL", []),
            ],
        )
        costs = conn.fetch_costs(days=1)
        assert costs == []


# ─── Serverless ────────────────────────────────────────────────────────


class TestServerless:

    def test_rpu_seconds_costed(self):
        conn, _ = _make_connector(
            serverless=True,
            routes=[
                (
                    "SYS_SERVERLESS_USAGE",
                    [
                        {
                            "day": "2026-04-20",
                            "workgroup_name": "analytics-wg",
                            "charged_seconds": 3600,
                            # 1 hour × 8 RPU = 28800 RPU-seconds
                            "charged_rpu_seconds": 28_800,
                            "storage_mb": 10_240,  # 10 GB
                        }
                    ],
                ),
                ("SYS_EXTERNAL_QUERY_DETAIL", []),
            ],
        )
        costs = conn.fetch_costs(days=1)

        compute = [c for c in costs if c.service == "redshift_serverless"]
        assert len(compute) == 1
        # 8 RPU-hours × $0.375 = $3.00
        assert compute[0].cost_usd == pytest.approx(3.0, rel=1e-3)
        assert compute[0].category == CostCategory.compute
        assert compute[0].usage_unit == "RPU_hours"
        assert compute[0].metadata["compute_type"] == "Serverless"
        assert compute[0].metadata["workgroup"] == "analytics-wg"

        storage = [c for c in costs if c.service == "redshift_managed_storage"]
        assert len(storage) == 1
        # 10 GB × $0.024 / 30 days = $0.008
        assert storage[0].cost_usd == pytest.approx(0.008, rel=1e-3)
        assert storage[0].category == CostCategory.storage

    def test_serverless_skips_storage_when_zero(self):
        conn, _ = _make_connector(
            serverless=True,
            routes=[
                (
                    "SYS_SERVERLESS_USAGE",
                    [
                        {
                            "day": "2026-04-20",
                            "workgroup_name": "analytics-wg",
                            "charged_seconds": 60,
                            "charged_rpu_seconds": 480,
                            "storage_mb": 0,
                        }
                    ],
                ),
                ("SYS_EXTERNAL_QUERY_DETAIL", []),
            ],
        )
        costs = conn.fetch_costs(days=1)
        # Only compute, no storage line.
        assert all(c.service != "redshift_managed_storage" for c in costs)
        assert any(c.service == "redshift_serverless" for c in costs)

    def test_serverless_does_not_query_provisioned_tables(self):
        conn, fake = _make_connector(
            serverless=True,
            routes=[
                ("SYS_SERVERLESS_USAGE", []),
                ("SYS_EXTERNAL_QUERY_DETAIL", []),
            ],
        )
        conn.fetch_costs(days=1)
        sqls = [call["sql"] for call in fake.calls]
        assert not any("SYS_QUERY_HISTORY" in s for s in sqls)
        assert not any("STL_CONCURRENCY_SCALING_USAGE" in s for s in sqls)


# ─── Spectrum ──────────────────────────────────────────────────────────


class TestSpectrum:

    def test_spectrum_bytes_costed(self):
        conn, _ = _make_connector(
            routes=[
                ("SYS_QUERY_HISTORY", []),
                ("STL_CONCURRENCY_SCALING_USAGE", []),
                (
                    "SYS_EXTERNAL_QUERY_DETAIL",
                    [
                        {
                            "day": "2026-04-20",
                            "user_id": "42",
                            "query_id": 101,
                            # 1 TB
                            "bytes_scanned": _TB,
                        }
                    ],
                ),
            ],
        )
        costs = conn.fetch_costs(days=1)
        spec = [c for c in costs if c.service == "redshift_spectrum"]
        assert len(spec) == 1
        # 1 TB × $5 = $5
        assert spec[0].cost_usd == pytest.approx(5.0, rel=1e-6)
        assert spec[0].usage_unit == "TB_scanned"
        assert spec[0].metadata["compute_type"] == "Spectrum"

    def test_spectrum_zero_bytes_skipped(self):
        conn, _ = _make_connector(
            routes=[
                ("SYS_QUERY_HISTORY", []),
                ("STL_CONCURRENCY_SCALING_USAGE", []),
                (
                    "SYS_EXTERNAL_QUERY_DETAIL",
                    [
                        {
                            "day": "2026-04-20",
                            "user_id": "42",
                            "query_id": 1,
                            "bytes_scanned": 0,
                        }
                    ],
                ),
            ],
        )
        costs = conn.fetch_costs(days=1)
        assert all(c.service != "redshift_spectrum" for c in costs)


# ─── Pricing overrides end-to-end ──────────────────────────────────────


class TestPricingOverridesEndToEnd:

    def test_node_hour_override_changes_query_cost(self):
        conn, _ = _make_connector(
            pricing_overrides={"node_hour": {"ra3.4xlarge": 1.00}},
            routes=[
                (
                    "SYS_QUERY_HISTORY",
                    [
                        {
                            "day": "2026-04-20",
                            "user_id": "1",
                            "query_id": 1,
                            "execution_time": 3_600_000_000,
                            "compute_type": "main",
                        }
                    ],
                ),
                ("STL_CONCURRENCY_SCALING_USAGE", []),
                ("SYS_EXTERNAL_QUERY_DETAIL", []),
            ],
            node_count=2,
        )
        costs = conn.fetch_costs(days=1)
        # 1 hour × $1.00 × 2 nodes = $2.00
        assert costs[0].cost_usd == pytest.approx(2.0, rel=1e-3)

    def test_discount_pct_applied_globally(self):
        conn, _ = _make_connector(
            pricing_overrides={"discount_pct": 50},
            routes=[
                (
                    "SYS_QUERY_HISTORY",
                    [
                        {
                            "day": "2026-04-20",
                            "user_id": "1",
                            "query_id": 1,
                            # 1 hour
                            "execution_time": 3_600_000_000,
                            "compute_type": "main",
                        }
                    ],
                ),
                ("STL_CONCURRENCY_SCALING_USAGE", []),
                ("SYS_EXTERNAL_QUERY_DETAIL", []),
            ],
            node_count=2,
        )
        costs = conn.fetch_costs(days=1)
        # $6.52 × 0.5 = $3.26
        assert costs[0].cost_usd == pytest.approx(3.26, rel=1e-3)

    def test_spectrum_per_tb_override(self):
        conn, _ = _make_connector(
            pricing_overrides={"spectrum_per_tb": 3.0},
            routes=[
                ("SYS_QUERY_HISTORY", []),
                ("STL_CONCURRENCY_SCALING_USAGE", []),
                (
                    "SYS_EXTERNAL_QUERY_DETAIL",
                    [
                        {
                            "day": "2026-04-20",
                            "query_id": 1,
                            "user_id": "1",
                            "bytes_scanned": _TB,
                        }
                    ],
                ),
            ],
        )
        costs = conn.fetch_costs(days=1)
        spec = [c for c in costs if c.service == "redshift_spectrum"]
        assert spec[0].cost_usd == pytest.approx(3.0, rel=1e-6)


# ─── Unified-cost envelope ─────────────────────────────────────────────


class TestUnifiedCostEnvelope:

    def test_records_validate_as_unified_costs(self):
        conn, _ = _make_connector(
            routes=[
                (
                    "SYS_QUERY_HISTORY",
                    [
                        {
                            "day": "2026-04-20",
                            "user_id": "1",
                            "query_id": 1,
                            "execution_time": 3_600_000_000,
                            "compute_type": "main",
                        }
                    ],
                ),
                ("STL_CONCURRENCY_SCALING_USAGE", []),
                ("SYS_EXTERNAL_QUERY_DETAIL", []),
            ],
        )
        costs = conn.fetch_costs(days=1)
        for c in costs:
            assert isinstance(c, UnifiedCost)
            # Round trip through pydantic to ensure full validation.
            UnifiedCost(**c.model_dump())


# ─── Helpers ───────────────────────────────────────────────────────────


class TestCoerceInt:

    @pytest.mark.parametrize(
        "value,expected",
        [
            (None, 0),
            ("", 0),
            ("42", 42),
            (42, 42),
            (42.9, 42),
            ("42.7", 42),
            ("nan-like", 0),
            (True, 1),
        ],
    )
    def test_coerce(self, value, expected):
        assert _coerce_int(value) == expected


class TestEncodeParams:

    def test_datetime_formatted_utc(self):
        from datetime import datetime, timezone

        encoded = _encode_params(
            {"start_ts": datetime(2026, 4, 20, 12, 0, 0, tzinfo=timezone.utc)}
        )
        assert encoded == [{"name": "start_ts", "value": "2026-04-20 12:00:00"}]

    def test_naive_datetime_assumed_utc(self):
        from datetime import datetime

        encoded = _encode_params({"ts": datetime(2026, 4, 20, 0, 0, 0)})
        assert encoded[0]["value"].startswith("2026-04-20")

    def test_none_becomes_empty_string(self):
        encoded = _encode_params({"x": None})
        assert encoded == [{"name": "x", "value": ""}]

    def test_int_and_string(self):
        encoded = _encode_params({"n": 42, "s": "hi"})
        values = {p["name"]: p["value"] for p in encoded}
        assert values == {"n": "42", "s": "hi"}


class TestDecodeRecord:

    def test_decodes_all_cell_types(self):
        record = [
            {"stringValue": "hello"},
            {"longValue": 42},
            {"doubleValue": 3.14},
            {"booleanValue": True},
            {"isNull": True},
        ]
        columns = ["a", "b", "c", "d", "e"]
        out = _decode_record(record, columns)
        assert out == {"a": "hello", "b": 42, "c": 3.14, "d": True, "e": None}


class TestTranslateBotoError:

    def test_access_denied_hint(self):
        class _CE(Exception):
            response = {"Error": {"Code": "AccessDeniedException", "Message": "no perms"}}

        err = _translate_boto_error(_CE("no perms"))
        assert isinstance(err, RedshiftError)
        assert "redshift-data:ExecuteStatement" in str(err)

    def test_not_found_hint(self):
        class _CE(Exception):
            response = {"Error": {"Code": "ResourceNotFoundException", "Message": "cluster does not exist"}}

        err = _translate_boto_error(_CE("cluster does not exist"))
        assert "cluster_identifier" in str(err)

    def test_validation_hint_mentions_workgroup(self):
        class _CE(Exception):
            response = {"Error": {"Code": "ValidationException", "Message": "Either specify cluster or workgroup"}}

        err = _translate_boto_error(_CE("validation"))
        assert "WorkgroupName" in str(err) or "ClusterIdentifier" in str(err)


# ─── test_connection ───────────────────────────────────────────────────


class TestTestConnection:

    def test_success_provisioned(self):
        conn, _ = _make_connector(routes=[("SELECT 1", [{"ok": 1}])])
        result = conn.test_connection()
        assert result["success"] is True
        assert "analytics-prod" in result["message"]

    def test_success_serverless(self):
        conn, _ = _make_connector(
            serverless=True, routes=[("SELECT 1", [{"ok": 1}])]
        )
        result = conn.test_connection()
        assert result["success"] is True
        assert "analytics-wg" in result["message"]

    def test_permission_denied(self):
        conn, _ = _make_connector(
            routes=[("SELECT 1", RedshiftError("Access denied"))]
        )
        result = conn.test_connection()
        assert result["success"] is False
        assert "Access denied" in result["message"]


# ─── Module-level integration with BaseConnector ───────────────────────


class TestBaseConnector:

    def test_is_subclass(self):
        from app.services.connectors.base import BaseConnector
        assert issubclass(RedshiftConnector, BaseConnector)

    def test_platform_attribute(self):
        assert RedshiftConnector.platform == "redshift"
