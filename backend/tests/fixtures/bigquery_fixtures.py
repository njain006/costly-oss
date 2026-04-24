"""Reusable BigQuery REST-API response fixtures.

Each helper returns a minimal, realistic HTTP response body matching the shape
produced by ``https://bigquery.googleapis.com/bigquery/v2/projects/.../queries``.
"""
from __future__ import annotations

from typing import Any


def bq_rows_response(fields: list[tuple[str, str]], rows: list[list[Any]]) -> dict:
    """Build a BigQuery REST ``queries`` response body.

    Args:
        fields: ``[(name, type), ...]`` — type is informational only for tests.
        rows: list of row values aligned with ``fields``.
    """
    schema_fields = [{"name": n, "type": t} for n, t in fields]
    row_payload = [
        {"f": [{"v": None if v is None else str(v)} for v in row]}
        for row in rows
    ]
    return {
        "kind": "bigquery#queryResponse",
        "schema": {"fields": schema_fields},
        "rows": row_payload,
        "totalRows": str(len(rows)),
        "jobComplete": True,
    }


def empty_response() -> dict:
    return {
        "kind": "bigquery#queryResponse",
        "schema": {"fields": []},
        "rows": [],
        "totalRows": "0",
        "jobComplete": True,
    }


# ── canned fixtures for common queries ───────────────────────────────

SCHEMATA_ROWS_US_ONLY = bq_rows_response(
    [("location", "STRING")],
    [["US"]],
)

SCHEMATA_ROWS_MULTI = bq_rows_response(
    [("location", "STRING")],
    [["US"], ["EU"], ["asia-northeast1"]],
)

SCHEMATA_OPTIONS_MIXED = bq_rows_response(
    [("dataset", "STRING"), ("billing_model", "STRING")],
    [
        ["analytics", "LOGICAL"],
        ["archive", "PHYSICAL"],
    ],
)


def jobs_rows(
    *,
    date: str = "2026-04-01",
    user: str = "alice@example.com",
    project: str = "test-project",
    reservation_id: str | None = None,
    edition: str | None = None,
    statement_type: str = "SELECT",
    bytes_billed: int = 0,
    slot_ms: int = 0,
    job_count: int = 1,
) -> dict:
    return bq_rows_response(
        [
            ("job_date", "DATE"),
            ("user_email", "STRING"),
            ("project_id", "STRING"),
            ("reservation_id", "STRING"),
            ("edition", "STRING"),
            ("statement_type", "STRING"),
            ("total_bytes_billed", "INT64"),
            ("total_slot_ms", "INT64"),
            ("job_count", "INT64"),
        ],
        [[
            date,
            user,
            project,
            reservation_id,
            edition,
            statement_type,
            bytes_billed,
            slot_ms,
            job_count,
        ]],
    )


def table_storage_rows(rows: list[dict]) -> dict:
    """Build a TABLE_STORAGE response.

    Each row dict needs ``dataset`` plus any of:
    ``active_logical_bytes``, ``long_term_logical_bytes``,
    ``active_physical_bytes``, ``long_term_physical_bytes`` (default 0).
    """
    fields = [
        ("dataset", "STRING"),
        ("active_logical_bytes", "INT64"),
        ("long_term_logical_bytes", "INT64"),
        ("active_physical_bytes", "INT64"),
        ("long_term_physical_bytes", "INT64"),
    ]
    values = [
        [
            r["dataset"],
            r.get("active_logical_bytes", 0),
            r.get("long_term_logical_bytes", 0),
            r.get("active_physical_bytes", 0),
            r.get("long_term_physical_bytes", 0),
        ]
        for r in rows
    ]
    return bq_rows_response(fields, values)


def streaming_rows(rows: list[dict]) -> dict:
    fields = [("day", "DATE"), ("bytes", "INT64"), ("requests", "INT64")]
    values = [[r["day"], r.get("bytes", 0), r.get("requests", 0)] for r in rows]
    return bq_rows_response(fields, values)


def bi_capacities_rows(rows: list[dict]) -> dict:
    fields = [("day", "DATE"), ("gb_hours", "FLOAT64")]
    values = [[r["day"], r.get("gb_hours", 0)] for r in rows]
    return bq_rows_response(fields, values)


SERVICE_ACCOUNT_JSON = (
    '{"type":"service_account",'
    '"project_id":"test-project",'
    '"private_key_id":"abc",'
    '"private_key":"-----BEGIN PRIVATE KEY-----\\nfake\\n-----END PRIVATE KEY-----\\n",'
    '"client_email":"bq-test@test-project.iam.gserviceaccount.com",'
    '"client_id":"1",'
    '"token_uri":"https://oauth2.googleapis.com/token"}'
)
