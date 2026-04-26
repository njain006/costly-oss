"""Contract tests for the Snowflake connector.

Snowflake connectors don't speak HTTP (they use the snowflake-connector-python
DBAPI cursor), so respx isn't applicable. Instead we mock the cursor directly
and feed it rows pulled from JSON fixtures that mirror the
``ORGANIZATION_USAGE.USAGE_IN_CURRENCY_DAILY`` and
``ACCOUNT_USAGE.METERING_DAILY_HISTORY`` view shapes.

Re-record fixtures
------------------
To re-capture rows from a real account, run a query like:

    SELECT USAGE_DATE, ACCOUNT_NAME, SERVICE_TYPE, USAGE_TYPE,
           SUM(USAGE), ANY_VALUE(USAGE_UNITS),
           SUM(USAGE_IN_CURRENCY), ANY_VALUE(CURRENCY)
    FROM SNOWFLAKE.ORGANIZATION_USAGE.USAGE_IN_CURRENCY_DAILY
    WHERE USAGE_DATE >= DATEADD(day, -7, CURRENT_DATE())
    GROUP BY 1, 2, 3, 4
    ORDER BY 1;

Save the result as a JSON list of arrays in
``backend/tests/fixtures/snowflake/usage_in_currency_daily.json``. Strip any
PII (account name, role) before committing.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.models.platform import CostCategory
from app.services.connectors.snowflake_connector import SnowflakeConnector

from tests.contract.conftest import load_fixture


SF_CREDS: dict[str, Any] = {
    "account": "xy12345.us-east-1",
    "user": "costly_user",
    "password": "secret",
    "warehouse": "ANALYTICS_WH",
    "database": "SNOWFLAKE",
    "schema_name": "ACCOUNT_USAGE",
    "role": "COSTLY_READ_ROLE",
}


class _ScriptedCursor:
    """Minimal cursor — yields scripted rows in FIFO order keyed by SQL needle."""

    def __init__(self, programs: list[tuple[str, list[tuple]]]):
        # Append wildcard fallback so the freshness probe + drilldown queries
        # don't blow up when the test only programs the primary path.
        self.programs = list(programs) + [("*", [])]
        self._pending: list[tuple] = []
        self.executed: list[str] = []

    def execute(self, sql: str) -> None:
        self.executed.append(sql)
        for i, (needle, rows) in enumerate(self.programs):
            if needle == "*" or needle in sql:
                if needle != "*":
                    self.programs.pop(i)
                self._pending = list(rows)
                return
        raise AssertionError(f"Unprogrammed SQL: {sql[:120]!r}")

    def fetchall(self) -> list[tuple]:
        rows = self._pending
        self._pending = []
        return rows

    def fetchone(self) -> tuple | None:
        return self._pending[0] if self._pending else None

    def close(self) -> None:
        pass


class _ScriptedConnection:
    def __init__(self, cursor: _ScriptedCursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def close(self):
        pass


def _build(cursor: _ScriptedCursor) -> SnowflakeConnector:
    conn = SnowflakeConnector(SF_CREDS)
    conn._connect = lambda: _ScriptedConnection(cursor)  # type: ignore[method-assign]
    return conn


def _row_to_tuple(row: list) -> tuple:
    """Convert JSON-friendly date strings back into ``date`` objects.

    The Snowflake driver returns the first column as a ``datetime.date`` —
    matching that here keeps ``_normalize_date`` happy.
    """
    out = list(row)
    if isinstance(out[0], str) and len(out[0]) == 10:
        out[0] = date.fromisoformat(out[0])
    return tuple(out)


def test_org_usage_path_emits_one_record_per_service_type():
    fixture = load_fixture("snowflake", "usage_in_currency_daily")
    rows = [_row_to_tuple(r) for r in fixture["rows"]]
    cursor = _ScriptedCursor([
        ("USAGE_IN_CURRENCY_DAILY", rows),
        ("QUERY_ATTRIBUTION_HISTORY", []),
        ("DATABASE_STORAGE_USAGE_HISTORY", []),
        ("TABLE_STORAGE_METRICS", []),
    ])
    conn = _build(cursor)
    costs = conn.fetch_costs(days=7)

    org_costs = [
        c for c in costs
        if c.metadata.get("source") == "ORGANIZATION_USAGE.USAGE_IN_CURRENCY_DAILY"
    ]
    assert len(org_costs) == 4

    by_service = {c.service: c for c in org_costs}
    assert by_service["snowflake_compute"].cost_usd == 37.5
    assert by_service["snowflake_compute"].category == CostCategory.compute
    assert by_service["snowflake_storage"].category == CostCategory.storage
    assert by_service["snowflake_cortex"].category == CostCategory.ai_inference
    assert by_service["snowflake_snowpipe"].category == CostCategory.ingestion
    assert conn.warnings == []


def test_metering_fallback_when_org_usage_denied():
    """Negative path: ORG_USAGE permission error → fall back to ACCOUNT_USAGE."""
    metering = load_fixture("snowflake", "metering_daily_history")
    rows = [_row_to_tuple(r) for r in metering["rows"]]

    # Synthesize a Snowflake permission error matching what _classify_error
    # treats as "missing privilege".
    class _SnowflakeProgrammingError(Exception):
        pass

    err = _SnowflakeProgrammingError(
        "002003 (42S02): SQL compilation error: Object "
        "'SNOWFLAKE.ORGANIZATION_USAGE.USAGE_IN_CURRENCY_DAILY' does not exist or not authorized."
    )

    cursor = _ScriptedCursor([
        ("USAGE_IN_CURRENCY_DAILY", []),  # placeholder; we patch execute below
        ("METERING_DAILY_HISTORY", rows),
        ("QUERY_ATTRIBUTION_HISTORY", []),
        ("DATABASE_STORAGE_USAGE_HISTORY", []),
        ("TABLE_STORAGE_METRICS", []),
    ])
    # Override execute to raise on the first ORG_USAGE call.
    original_execute = cursor.execute
    state = {"first": True}

    def _raise_first_org_usage(sql: str) -> None:
        if state["first"] and "USAGE_IN_CURRENCY_DAILY" in sql:
            state["first"] = False
            raise err
        original_execute(sql)

    cursor.execute = _raise_first_org_usage  # type: ignore[assignment]

    conn = _build(cursor)
    costs = conn.fetch_costs(days=7)

    # ORG_USAGE failed → metering path produced records
    metering_costs = [
        c for c in costs
        if c.metadata.get("source") == "ACCOUNT_USAGE.METERING_DAILY_HISTORY"
    ]
    assert len(metering_costs) >= 1
    # Connector recorded the permission warning so the UI can surface it.
    assert any("USAGE_IN_CURRENCY_DAILY" in w for w in conn.warnings)


def test_test_connection_success():
    cursor = _ScriptedCursor([
        ("CURRENT_USER()", [("costly_user", "COSTLY_READ_ROLE", "ANALYTICS_WH")]),
    ])
    conn = _build(cursor)
    result = conn.test_connection()
    assert result["success"] is True
    assert "costly_user" in result["message"]
