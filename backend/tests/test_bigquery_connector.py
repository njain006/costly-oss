"""Tests for BigQueryConnector.

The connector talks to two HTTP surfaces: OAuth (google-auth) and the BQ REST
``/queries`` endpoint (httpx). We short-circuit both by patching
``_BigQueryRestClient.get_access_token`` (returns a canned token) and
``_BigQueryRestClient.query`` (returns dict rows — same shape the real
``query()`` produces after REST decoding).

This keeps the tests fast, deterministic, and free of network + google-auth
dependencies.
"""
from __future__ import annotations

import httpx
import pytest
from unittest.mock import MagicMock, patch

from app.models.platform import CostCategory, UnifiedCost
from app.services.connectors.bigquery_connector import (
    BQPricing,
    BigQueryConnector,
    BigQueryError,
    DEFAULT_EDITION_SLOT_HR,
    DEFAULT_ON_DEMAND_TB,
    DEFAULT_STORAGE_GB_MONTH,
    _BigQueryRestClient,
    _canonicalise_location,
    _date_string,
    _encode_params,
    _merge_pricing,
    _translate_http_error,
)

from tests.fixtures.bigquery_fixtures import SERVICE_ACCOUNT_JSON


_TB = 1024 ** 4
_GB = 1024 ** 3
_MS_PER_HOUR = 3_600_000.0


# ─── Helpers ───────────────────────────────────────────────────────────


def _make_connector(pricing_overrides=None, locations=None) -> BigQueryConnector:
    creds = {
        "project_id": "test-project",
        "service_account_json": SERVICE_ACCOUNT_JSON,
    }
    if locations is not None:
        creds["locations"] = locations
    conn = BigQueryConnector(creds, pricing_overrides=pricing_overrides)
    # Always bypass OAuth in unit tests.
    conn.client.get_access_token = MagicMock(return_value="fake-token")
    return conn


class _FakeQuery:
    """Routing fake for ``_BigQueryRestClient.query``.

    Matches SQL to a list of canned responses (first substring that hits wins);
    records all calls so tests can assert parameters / locations.
    """

    def __init__(self, routes: list[tuple[str, list[dict]]]):
        self.routes = routes
        self.calls: list[dict] = []

    def __call__(self, sql, *, location=None, params=None, timeout_ms=60_000):
        self.calls.append(
            {"sql": sql, "location": location, "params": params, "timeout_ms": timeout_ms}
        )
        for pattern, result in self.routes:
            if pattern in sql:
                if isinstance(result, Exception):
                    raise result
                return result
        return []


# ─── _merge_pricing / BQPricing ───────────────────────────────────────


class TestPricingMerge:
    def test_defaults(self):
        p = _merge_pricing(None)
        assert p.on_demand_tb == DEFAULT_ON_DEMAND_TB
        assert p.edition_slot_hr["standard"] == DEFAULT_EDITION_SLOT_HR["standard"]
        assert p.storage_gb_month[("logical", "active")] == 0.02
        assert p.discount_pct == 0.0

    def test_override_on_demand_tb(self):
        p = _merge_pricing({"on_demand_tb": 4.90})
        assert p.on_demand_tb == 4.90

    def test_override_slot_hr(self):
        p = _merge_pricing({"slot_hr": {"enterprise": 0.048}})
        assert p.edition_slot_hr["enterprise"] == 0.048
        # Others untouched
        assert p.edition_slot_hr["standard"] == 0.04

    def test_override_storage_nested(self):
        p = _merge_pricing(
            {"storage_gb_month": {"logical": {"active": 0.018, "long_term": 0.009}}}
        )
        assert p.storage_gb_month[("logical", "active")] == 0.018
        assert p.storage_gb_month[("logical", "long_term")] == 0.009
        # Physical untouched
        assert p.storage_gb_month[("physical", "active")] == 0.04

    def test_override_storage_flat(self):
        p = _merge_pricing({"storage_gb_month": {"physical_active": 0.035}})
        assert p.storage_gb_month[("physical", "active")] == 0.035

    def test_override_discount_pct(self):
        p = _merge_pricing({"discount_pct": 15})
        assert p.apply_discount(100.0) == pytest.approx(85.0)

    def test_slot_hr_unknown_edition_defaults_to_standard(self):
        p = BQPricing()
        assert p.slot_hr_for(None) == 0.04
        assert p.slot_hr_for("Enterprise Plus") == 0.10
        assert p.slot_hr_for("nonsense") == 0.04


# ─── _canonicalise_location ───────────────────────────────────────────


class TestCanonicaliseLocation:
    @pytest.mark.parametrize(
        "inp,expected",
        [
            ("US", "region-us"),
            ("EU", "region-eu"),
            ("us", "region-us"),
            ("asia-northeast1", "region-asia-northeast1"),
            ("Region-US", "region-us"),
            ("region-eu", "region-eu"),
        ],
    )
    def test_canonical_form(self, inp, expected):
        assert _canonicalise_location(inp) == expected


# ─── _encode_params ───────────────────────────────────────────────────


class TestEncodeParams:
    def test_int_param(self):
        out = _encode_params({"n": 42})
        assert out == [
            {
                "name": "n",
                "parameterType": {"type": "INT64"},
                "parameterValue": {"value": "42"},
            }
        ]

    def test_string_param(self):
        out = _encode_params({"s": "hello"})
        assert out[0]["parameterType"]["type"] == "STRING"
        assert out[0]["parameterValue"]["value"] == "hello"

    def test_datetime_param_is_timestamp_utc(self):
        from datetime import datetime, timezone

        dt = datetime(2026, 4, 1, 12, 30, tzinfo=timezone.utc)
        out = _encode_params({"t": dt})
        assert out[0]["parameterType"]["type"] == "TIMESTAMP"
        assert "2026-04-01 12:30:00" in out[0]["parameterValue"]["value"]
        assert out[0]["parameterValue"]["value"].endswith("UTC")

    def test_bool_param(self):
        out = _encode_params({"b": True})
        assert out[0]["parameterType"]["type"] == "BOOL"
        assert out[0]["parameterValue"]["value"] == "true"


# ─── _translate_http_error ────────────────────────────────────────────


class TestHttpError:
    def _resp(self, status: int, payload: dict) -> httpx.Response:
        return httpx.Response(status_code=status, json=payload)

    def test_403_includes_role_hint(self):
        resp = self._resp(
            403,
            {
                "error": {
                    "errors": [{"reason": "accessDenied"}],
                    "message": "Permission bigquery.jobs.list denied",
                }
            },
        )
        err = _translate_http_error(resp)
        assert "403" in str(err)
        assert "bigquery.resourceViewer" in str(err)
        assert "bigquery.jobUser" in str(err)

    def test_404_includes_project_hint(self):
        resp = self._resp(
            404,
            {"error": {"errors": [{"reason": "notFound"}], "message": "Not found"}},
        )
        err = _translate_http_error(resp)
        assert "404" in str(err)
        assert "project_id" in str(err)


# ─── _date_string ──────────────────────────────────────────────────────


class TestDateString:
    def test_iso_string_truncated(self):
        assert _date_string("2026-04-01T12:34:56") == "2026-04-01"

    def test_none_becomes_empty_prefix(self):
        assert _date_string(None) == "None"[:10]


# ─── Instantiation ────────────────────────────────────────────────────


class TestConstruction:
    def test_missing_project_raises(self):
        with pytest.raises(BigQueryError, match="project_id"):
            BigQueryConnector({"service_account_json": SERVICE_ACCOUNT_JSON})

    def test_missing_service_account_raises(self):
        with pytest.raises(BigQueryError, match="service_account_json"):
            BigQueryConnector({"project_id": "p"})

    def test_pricing_overrides_via_credentials(self):
        conn = BigQueryConnector(
            {
                "project_id": "p",
                "service_account_json": SERVICE_ACCOUNT_JSON,
                "pricing_overrides": {"on_demand_tb": 4.9},
            }
        )
        assert conn.pricing.on_demand_tb == 4.9

    def test_pricing_overrides_via_kwarg_wins(self):
        conn = BigQueryConnector(
            {"project_id": "p", "service_account_json": SERVICE_ACCOUNT_JSON},
            pricing_overrides={"on_demand_tb": 3.5},
        )
        assert conn.pricing.on_demand_tb == 3.5

    def test_configured_locations_canonicalised(self):
        conn = BigQueryConnector(
            {
                "project_id": "p",
                "service_account_json": SERVICE_ACCOUNT_JSON,
                "locations": ["US", "EU"],
            }
        )
        assert conn._configured_locations == ("region-us", "region-eu")


# ─── test_connection ─────────────────────────────────────────────────


class TestTestConnection:
    def test_success(self):
        conn = _make_connector()
        with patch(
            "app.services.connectors.bigquery_connector.httpx.get",
            return_value=httpx.Response(200, json={"datasets": []}),
        ):
            result = conn.test_connection()
        assert result["success"] is True

    def test_403_returns_structured_message(self):
        conn = _make_connector()
        with patch(
            "app.services.connectors.bigquery_connector.httpx.get",
            return_value=httpx.Response(
                403,
                json={
                    "error": {
                        "errors": [{"reason": "accessDenied"}],
                        "message": "denied",
                    }
                },
            ),
        ):
            result = conn.test_connection()
        assert result["success"] is False
        assert "bigquery.jobUser" in result["message"]

    def test_oauth_failure_bubbles(self):
        conn = _make_connector()
        conn.client.get_access_token = MagicMock(
            side_effect=BigQueryError("bad key")
        )
        result = conn.test_connection()
        assert result["success"] is False
        assert "bad key" in result["message"]


# ─── Location discovery ──────────────────────────────────────────────


class TestLocationDiscovery:
    def test_uses_configured_locations_without_probing(self):
        conn = _make_connector(locations=["US", "asia-northeast1"])
        fake = _FakeQuery([])
        conn.client.query = fake
        assert conn._discover_locations() == ["region-us", "region-asia-northeast1"]
        assert fake.calls == []

    def test_discovers_via_schemata(self):
        conn = _make_connector()
        from tests.fixtures.bigquery_fixtures import SCHEMATA_ROWS_MULTI

        # _BigQueryRestClient.query returns decoded rows. Build that shape:
        rows = [
            {"location": "US"},
            {"location": "EU"},
            {"location": "asia-northeast1"},
        ]
        fake = _FakeQuery([("INFORMATION_SCHEMA.SCHEMATA", rows)])
        conn.client.query = fake
        locations = conn._discover_locations()
        assert "region-us" in locations
        assert "region-eu" in locations
        assert "region-asia-northeast1" in locations

    def test_falls_back_to_defaults_on_failure(self):
        conn = _make_connector()
        fake = _FakeQuery([("SCHEMATA", BigQueryError("nope"))])
        conn.client.query = fake
        # Every probe fails → fallback list
        locations = conn._discover_locations()
        assert locations == ["region-us", "region-eu", "region-asia-northeast1"]


# ─── Jobs / Editions pricing ─────────────────────────────────────────


class TestJobCosts:
    def test_on_demand_pricing(self):
        conn = _make_connector(locations=["US"])
        rows = [
            {
                "job_date": "2026-04-01",
                "user_email": "alice@example.com",
                "project_id": "test-project",
                "reservation_id": None,
                "edition": None,
                "statement_type": "SELECT",
                "total_bytes_billed": _TB,  # exactly 1 TB
                "total_slot_ms": 120_000,
                "job_count": 1,
            }
        ]
        fake = _FakeQuery(
            [
                ("JOBS_BY_PROJECT", rows),
                ("TABLE_STORAGE", []),
                ("STREAMING_TIMELINE", []),
                ("BI_CAPACITIES", []),
                ("SCHEMATA_OPTIONS", []),
            ]
        )
        conn.client.query = fake

        costs = conn.fetch_costs(days=7)
        assert len(costs) == 1
        cost = costs[0]
        assert cost.platform == "gcp"
        assert cost.service == "bigquery"
        assert cost.cost_usd == pytest.approx(DEFAULT_ON_DEMAND_TB)
        assert cost.usage_unit == "TB_scanned"
        assert cost.metadata["pricing_model"] == "on_demand"

    @pytest.mark.parametrize(
        "edition,expected_rate",
        [
            ("STANDARD", 0.04),
            ("ENTERPRISE", 0.06),
            ("ENTERPRISE_PLUS", 0.10),
            ("ENTERPRISE PLUS", 0.10),
        ],
    )
    def test_editions_pricing(self, edition, expected_rate):
        conn = _make_connector(locations=["US"])
        # 1 hour of slot time = 3,600,000 ms
        rows = [
            {
                "job_date": "2026-04-01",
                "user_email": "alice@example.com",
                "project_id": "test-project",
                "reservation_id": "my-reservation",
                "edition": edition,
                "statement_type": "SELECT",
                "total_bytes_billed": 5 * _TB,  # should be IGNORED for reservations
                "total_slot_ms": int(_MS_PER_HOUR),
                "job_count": 1,
            }
        ]
        fake = _FakeQuery(
            [
                ("JOBS_BY_PROJECT", rows),
                ("TABLE_STORAGE", []),
                ("STREAMING_TIMELINE", []),
                ("BI_CAPACITIES", []),
                ("SCHEMATA_OPTIONS", []),
            ]
        )
        conn.client.query = fake

        costs = conn.fetch_costs(days=7)
        assert len(costs) == 1
        cost = costs[0]
        assert cost.cost_usd == pytest.approx(expected_rate)
        assert cost.usage_unit == "slot_hours"
        assert cost.usage_quantity == pytest.approx(1.0)
        assert cost.metadata["pricing_model"] == "editions"
        assert cost.metadata["reservation_id"] == "my-reservation"

    def test_load_copy_export_not_filtered(self):
        conn = _make_connector(locations=["US"])
        rows = [
            {
                "job_date": "2026-04-01",
                "user_email": "svc@example.com",
                "project_id": "test-project",
                "reservation_id": None,
                "edition": None,
                "statement_type": stmt,
                "total_bytes_billed": 100 * _GB,
                "total_slot_ms": 1000,
                "job_count": 1,
            }
            for stmt in ("LOAD", "COPY", "EXPORT")
        ]
        fake = _FakeQuery(
            [
                ("JOBS_BY_PROJECT", rows),
                ("TABLE_STORAGE", []),
                ("STREAMING_TIMELINE", []),
                ("BI_CAPACITIES", []),
                ("SCHEMATA_OPTIONS", []),
            ]
        )
        conn.client.query = fake

        costs = conn.fetch_costs(days=7)
        types = {c.metadata["statement_type"] for c in costs}
        assert types == {"LOAD", "COPY", "EXPORT"}

    def test_captures_procedure_ml_and_external_table_statements(self):
        """Analytics Hub reads, Spark/BigLake procedures, and ML.GENERATE_TEXT
        all surface as JOBS_BY_PROJECT rows — assert they're captured and
        their statement_type is preserved in metadata for reporting.
        """
        conn = _make_connector(locations=["US"])
        rows = [
            {
                "job_date": "2026-04-01",
                "user_email": "ml@example.com",
                "project_id": "test-project",
                "reservation_id": None,
                "edition": None,
                "statement_type": stmt,
                "total_bytes_billed": 100 * _GB,
                "total_slot_ms": 1_000,
                "job_count": 1,
            }
            for stmt in ("PROCEDURE", "CREATE_MODEL", "CALL", "QUERY")
        ]
        fake = _FakeQuery(
            [
                ("JOBS_BY_PROJECT", rows),
                ("TABLE_STORAGE", []),
                ("STREAMING_TIMELINE", []),
                ("BI_CAPACITIES", []),
                ("SCHEMATA_OPTIONS", []),
            ]
        )
        conn.client.query = fake
        costs = conn.fetch_costs(days=7)
        types = {c.metadata["statement_type"] for c in costs}
        assert types == {"PROCEDURE", "CREATE_MODEL", "CALL", "QUERY"}

    def test_zero_cost_zero_bytes_rows_skipped(self):
        conn = _make_connector(locations=["US"])
        rows = [
            {
                "job_date": "2026-04-01",
                "user_email": "x",
                "project_id": "test-project",
                "reservation_id": None,
                "edition": None,
                "statement_type": "SELECT",
                "total_bytes_billed": 0,
                "total_slot_ms": 0,
                "job_count": 3,
            }
        ]
        fake = _FakeQuery(
            [
                ("JOBS_BY_PROJECT", rows),
                ("TABLE_STORAGE", []),
                ("STREAMING_TIMELINE", []),
                ("BI_CAPACITIES", []),
                ("SCHEMATA_OPTIONS", []),
            ]
        )
        conn.client.query = fake
        assert conn.fetch_costs(days=7) == []

    def test_query_uses_bind_params_not_interpolation(self):
        conn = _make_connector(locations=["US"])
        rows = [
            {
                "job_date": "2026-04-01",
                "user_email": "u",
                "project_id": "test-project",
                "reservation_id": None,
                "edition": None,
                "statement_type": "SELECT",
                "total_bytes_billed": _TB,
                "total_slot_ms": 100,
                "job_count": 1,
            }
        ]
        fake = _FakeQuery(
            [
                ("JOBS_BY_PROJECT", rows),
                ("TABLE_STORAGE", []),
                ("STREAMING_TIMELINE", []),
                ("BI_CAPACITIES", []),
                ("SCHEMATA_OPTIONS", []),
            ]
        )
        conn.client.query = fake
        conn.fetch_costs(days=7)

        # Assert jobs call used @start_ts / @end_ts params (no interpolation)
        jobs_calls = [c for c in fake.calls if "JOBS_BY_PROJECT" in c["sql"]]
        assert jobs_calls
        call = jobs_calls[0]
        assert "@start_ts" in call["sql"]
        assert "@end_ts" in call["sql"]
        assert call["params"] is not None
        assert "start_ts" in call["params"]
        assert "end_ts" in call["params"]


# ─── Storage costs ───────────────────────────────────────────────────


class TestStorageCosts:
    def test_logical_billing_active_and_long_term_split(self):
        conn = _make_connector(locations=["US"])
        storage_rows = [
            {
                "dataset": "analytics",
                "active_logical_bytes": 100 * _GB,
                "long_term_logical_bytes": 900 * _GB,
                "active_physical_bytes": 10 * _GB,
                "long_term_physical_bytes": 90 * _GB,
            }
        ]
        fake = _FakeQuery(
            [
                ("JOBS_BY_PROJECT", []),
                ("TABLE_STORAGE", storage_rows),
                ("SCHEMATA_OPTIONS", [{"dataset": "analytics", "billing_model": "LOGICAL"}]),
                ("STREAMING_TIMELINE", []),
                ("BI_CAPACITIES", []),
            ]
        )
        conn.client.query = fake

        costs = conn.fetch_costs(days=7)
        storage = [c for c in costs if c.service == "bigquery_storage"]
        assert len(storage) == 1
        # Monthly cost = 100 * 0.02 + 900 * 0.01 = 2 + 9 = $11.
        # Daily = 11 / 30 ≈ 0.3667
        assert storage[0].cost_usd == pytest.approx(11.0 / 30.0, rel=1e-4)
        assert storage[0].metadata["billing_model"] == "logical"
        assert storage[0].metadata["active_gb"] == pytest.approx(100.0)
        assert storage[0].metadata["long_term_gb"] == pytest.approx(900.0)

    def test_physical_billing_uses_physical_bytes_and_rates(self):
        conn = _make_connector(locations=["US"])
        storage_rows = [
            {
                "dataset": "archive",
                "active_logical_bytes": 1000 * _GB,  # ignored (physical billing)
                "long_term_logical_bytes": 5000 * _GB,
                "active_physical_bytes": 200 * _GB,
                "long_term_physical_bytes": 800 * _GB,
            }
        ]
        fake = _FakeQuery(
            [
                ("JOBS_BY_PROJECT", []),
                ("TABLE_STORAGE", storage_rows),
                ("SCHEMATA_OPTIONS", [{"dataset": "archive", "billing_model": "PHYSICAL"}]),
                ("STREAMING_TIMELINE", []),
                ("BI_CAPACITIES", []),
            ]
        )
        conn.client.query = fake

        costs = conn.fetch_costs(days=7)
        storage = [c for c in costs if c.service == "bigquery_storage"]
        assert len(storage) == 1
        # 200*0.04 + 800*0.02 = 8 + 16 = $24/mo → $0.8/day
        assert storage[0].cost_usd == pytest.approx(24.0 / 30.0, rel=1e-4)
        assert storage[0].metadata["billing_model"] == "physical"

    def test_defaults_to_logical_when_no_option_row(self):
        conn = _make_connector(locations=["US"])
        storage_rows = [
            {
                "dataset": "ds",
                "active_logical_bytes": 100 * _GB,
                "long_term_logical_bytes": 0,
                "active_physical_bytes": 0,
                "long_term_physical_bytes": 0,
            }
        ]
        fake = _FakeQuery(
            [
                ("JOBS_BY_PROJECT", []),
                ("TABLE_STORAGE", storage_rows),
                ("SCHEMATA_OPTIONS", []),  # no billing mode info
                ("STREAMING_TIMELINE", []),
                ("BI_CAPACITIES", []),
            ]
        )
        conn.client.query = fake

        costs = conn.fetch_costs(days=7)
        storage = [c for c in costs if c.service == "bigquery_storage"]
        assert storage[0].metadata["billing_model"] == "logical"
        # 100 * 0.02 = $2/mo → ~$0.0667/day
        assert storage[0].cost_usd == pytest.approx(2.0 / 30.0, rel=1e-4)

    def test_zero_bytes_skipped(self):
        conn = _make_connector(locations=["US"])
        storage_rows = [{"dataset": "empty"}]
        fake = _FakeQuery(
            [
                ("JOBS_BY_PROJECT", []),
                ("TABLE_STORAGE", storage_rows),
                ("SCHEMATA_OPTIONS", []),
                ("STREAMING_TIMELINE", []),
                ("BI_CAPACITIES", []),
            ]
        )
        conn.client.query = fake
        costs = conn.fetch_costs(days=7)
        assert all(c.service != "bigquery_storage" for c in costs)


# ─── Streaming ───────────────────────────────────────────────────────


class TestStreamingCosts:
    def test_streaming_priced_per_gb(self):
        conn = _make_connector(locations=["US"])
        streaming = [{"day": "2026-04-01", "bytes": _GB, "requests": 1000}]
        fake = _FakeQuery(
            [
                ("JOBS_BY_PROJECT", []),
                ("TABLE_STORAGE", []),
                ("STREAMING_TIMELINE", streaming),
                ("BI_CAPACITIES", []),
                ("SCHEMATA_OPTIONS", []),
            ]
        )
        conn.client.query = fake

        costs = conn.fetch_costs(days=7)
        stream = [c for c in costs if c.service == "bigquery_streaming"]
        assert len(stream) == 1
        # 1 GB * $0.05/GB = $0.05
        assert stream[0].cost_usd == pytest.approx(0.05)
        assert stream[0].category == CostCategory.ingestion

    def test_streaming_skipped_when_view_missing(self):
        conn = _make_connector(locations=["US"])
        fake = _FakeQuery(
            [
                ("JOBS_BY_PROJECT", []),
                ("TABLE_STORAGE", []),
                ("STREAMING_TIMELINE", BigQueryError("not found")),
                ("BI_CAPACITIES", []),
                ("SCHEMATA_OPTIONS", []),
            ]
        )
        conn.client.query = fake
        costs = conn.fetch_costs(days=7)
        assert all(c.service != "bigquery_streaming" for c in costs)


# ─── BI Engine ───────────────────────────────────────────────────────


class TestBIEngineCosts:
    def test_bi_engine_priced_per_gb_hr(self):
        conn = _make_connector(locations=["US"])
        rows = [{"day": "2026-04-01", "gb_hours": 10.0}]
        fake = _FakeQuery(
            [
                ("JOBS_BY_PROJECT", []),
                ("TABLE_STORAGE", []),
                ("STREAMING_TIMELINE", []),
                ("BI_CAPACITIES", rows),
                ("SCHEMATA_OPTIONS", []),
            ]
        )
        conn.client.query = fake

        costs = conn.fetch_costs(days=7)
        bi = [c for c in costs if c.service == "bigquery_bi_engine"]
        assert len(bi) == 1
        # 10 GB-hours * 0.0416 = $0.416
        assert bi[0].cost_usd == pytest.approx(0.416, rel=1e-4)
        assert bi[0].usage_unit == "GB_hours"


# ─── Pricing overrides ───────────────────────────────────────────────


class TestPricingOverrides:
    def test_on_demand_tb_override(self):
        conn = _make_connector(
            locations=["US"], pricing_overrides={"on_demand_tb": 5.00}
        )
        rows = [
            {
                "job_date": "2026-04-01",
                "user_email": "u",
                "project_id": "test-project",
                "reservation_id": None,
                "edition": None,
                "statement_type": "SELECT",
                "total_bytes_billed": _TB,
                "total_slot_ms": 100,
                "job_count": 1,
            }
        ]
        fake = _FakeQuery(
            [
                ("JOBS_BY_PROJECT", rows),
                ("TABLE_STORAGE", []),
                ("STREAMING_TIMELINE", []),
                ("BI_CAPACITIES", []),
                ("SCHEMATA_OPTIONS", []),
            ]
        )
        conn.client.query = fake
        costs = conn.fetch_costs(days=7)
        assert costs[0].cost_usd == pytest.approx(5.00)

    def test_slot_hr_override(self):
        conn = _make_connector(
            locations=["US"],
            pricing_overrides={"slot_hr": {"enterprise": 0.048}},
        )
        rows = [
            {
                "job_date": "2026-04-01",
                "user_email": "u",
                "project_id": "test-project",
                "reservation_id": "r",
                "edition": "ENTERPRISE",
                "statement_type": "SELECT",
                "total_bytes_billed": 0,
                "total_slot_ms": int(_MS_PER_HOUR),
                "job_count": 1,
            }
        ]
        fake = _FakeQuery(
            [
                ("JOBS_BY_PROJECT", rows),
                ("TABLE_STORAGE", []),
                ("STREAMING_TIMELINE", []),
                ("BI_CAPACITIES", []),
                ("SCHEMATA_OPTIONS", []),
            ]
        )
        conn.client.query = fake
        costs = conn.fetch_costs(days=7)
        assert costs[0].cost_usd == pytest.approx(0.048)

    def test_storage_rate_override(self):
        conn = _make_connector(
            locations=["US"],
            pricing_overrides={"storage_gb_month": {"logical_active": 0.018}},
        )
        storage_rows = [
            {
                "dataset": "d",
                "active_logical_bytes": 100 * _GB,
                "long_term_logical_bytes": 0,
                "active_physical_bytes": 0,
                "long_term_physical_bytes": 0,
            }
        ]
        fake = _FakeQuery(
            [
                ("JOBS_BY_PROJECT", []),
                ("TABLE_STORAGE", storage_rows),
                ("SCHEMATA_OPTIONS", []),
                ("STREAMING_TIMELINE", []),
                ("BI_CAPACITIES", []),
            ]
        )
        conn.client.query = fake
        costs = conn.fetch_costs(days=7)
        storage = [c for c in costs if c.service == "bigquery_storage"]
        # 100 GB * 0.018 = $1.80/mo → ~$0.06/day
        assert storage[0].cost_usd == pytest.approx(1.80 / 30.0, rel=1e-4)

    def test_discount_pct_applied_last(self):
        conn = _make_connector(
            locations=["US"], pricing_overrides={"discount_pct": 10}
        )
        rows = [
            {
                "job_date": "2026-04-01",
                "user_email": "u",
                "project_id": "test-project",
                "reservation_id": None,
                "edition": None,
                "statement_type": "SELECT",
                "total_bytes_billed": _TB,
                "total_slot_ms": 100,
                "job_count": 1,
            }
        ]
        fake = _FakeQuery(
            [
                ("JOBS_BY_PROJECT", rows),
                ("TABLE_STORAGE", []),
                ("STREAMING_TIMELINE", []),
                ("BI_CAPACITIES", []),
                ("SCHEMATA_OPTIONS", []),
            ]
        )
        conn.client.query = fake
        costs = conn.fetch_costs(days=7)
        # 1 TB * $6.25 * 0.9 = $5.625
        assert costs[0].cost_usd == pytest.approx(DEFAULT_ON_DEMAND_TB * 0.9)


# ─── Multi-region iteration ──────────────────────────────────────────


class TestMultiRegion:
    def test_queries_run_per_region(self):
        conn = _make_connector(locations=["US", "EU"])
        fake = _FakeQuery([])  # all empty
        conn.client.query = fake
        conn.fetch_costs(days=7)

        # Count distinct locations across jobs calls
        job_locs = {
            c["location"] for c in fake.calls if "JOBS_BY_PROJECT" in c["sql"]
        }
        assert job_locs == {"region-us", "region-eu"}

    def test_uses_parameterised_location_template(self):
        conn = _make_connector(locations=["asia-northeast1"])
        fake = _FakeQuery([])
        conn.client.query = fake
        conn.fetch_costs(days=7)

        job_calls = [c for c in fake.calls if "JOBS_BY_PROJECT" in c["sql"]]
        assert any("`region-asia-northeast1`" in c["sql"] for c in job_calls)


# ─── datetime.now(timezone.utc) — no deprecated utcnow ──────────────


class TestNoDeprecatedUtcNow:
    def test_source_does_not_reference_utcnow(self):
        import app.services.connectors.bigquery_connector as mod
        import inspect

        src = inspect.getsource(mod)
        assert "utcnow" not in src, (
            "Replace datetime.utcnow() with datetime.now(timezone.utc)"
        )


# ─── End-to-end smoke ────────────────────────────────────────────────


class TestEndToEnd:
    def test_fetch_costs_days_30_integrates_all_sources(self):
        conn = _make_connector(locations=["US"])
        job_rows = [
            {
                "job_date": "2026-04-01",
                "user_email": "alice@example.com",
                "project_id": "test-project",
                "reservation_id": None,
                "edition": None,
                "statement_type": "SELECT",
                "total_bytes_billed": _TB,
                "total_slot_ms": 100,
                "job_count": 10,
            },
            {
                "job_date": "2026-04-01",
                "user_email": "svc@example.com",
                "project_id": "test-project",
                "reservation_id": "proj-res",
                "edition": "ENTERPRISE",
                "statement_type": "LOAD",
                "total_bytes_billed": 0,
                "total_slot_ms": int(_MS_PER_HOUR * 2),  # 2 slot-hours
                "job_count": 5,
            },
        ]
        storage_rows = [
            {
                "dataset": "analytics",
                "active_logical_bytes": 100 * _GB,
                "long_term_logical_bytes": 900 * _GB,
                "active_physical_bytes": 0,
                "long_term_physical_bytes": 0,
            }
        ]
        streaming_rows = [{"day": "2026-04-01", "bytes": 2 * _GB, "requests": 500}]
        bi_rows = [{"day": "2026-04-01", "gb_hours": 5.0}]

        fake = _FakeQuery(
            [
                ("JOBS_BY_PROJECT", job_rows),
                ("TABLE_STORAGE", storage_rows),
                ("SCHEMATA_OPTIONS", [{"dataset": "analytics", "billing_model": "LOGICAL"}]),
                ("STREAMING_TIMELINE", streaming_rows),
                ("BI_CAPACITIES", bi_rows),
            ]
        )
        conn.client.query = fake

        costs = conn.fetch_costs(days=30)

        services = {c.service for c in costs}
        assert "bigquery" in services
        assert "bigquery_storage" in services
        assert "bigquery_streaming" in services
        assert "bigquery_bi_engine" in services

        # All are UnifiedCost instances with non-negative cost
        for c in costs:
            assert isinstance(c, UnifiedCost)
            assert c.cost_usd >= 0
            assert c.platform == "gcp"
