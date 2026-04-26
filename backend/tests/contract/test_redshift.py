"""Contract tests for the Redshift connector.

Pins the connector to the boto3 ``redshift-data`` client surface:
  - ``execute_statement`` returns ``{Id: str, Status: ...}``
  - ``describe_statement`` polled until ``Status in {FINISHED, FAILED, ABORTED}``
  - ``get_statement_result`` returns ``{ColumnMetadata, Records, NextToken?}``

Re-record fixtures
------------------
The shapes pinned here are stable boto3 contracts. To capture a fresh
``get_statement_result`` for a real query, run::

    aws redshift-data execute-statement \\
        --cluster-identifier analytics-prod --database analytics \\
        --sql "SELECT 1" --db-user costly_reader
    # then poll describe-statement until FINISHED, then:
    aws redshift-data get-statement-result --id <Id> > fixture.json

Strip account-id / cluster-id PII before committing.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from app.services.connectors.redshift_connector import (
    _RedshiftDataClient,
    _decode_record,
    _translate_boto_error,
)

from tests.contract.conftest import load_fixture


def _build_client_with_fake_boto(boto_data: MagicMock) -> _RedshiftDataClient:
    """Construct ``_RedshiftDataClient`` with the boto3 client pre-mocked.

    We bypass ``__init__`` so we don't need boto3 installed.
    """
    client = _RedshiftDataClient.__new__(_RedshiftDataClient)
    client._data = boto_data
    client._cluster_identifier = "analytics-prod"
    client._workgroup_name = None
    client._database = "analytics"
    client._db_user = "costly_reader"
    client._secret_arn = None
    return client


def test_data_client_decodes_get_statement_result_into_dicts():
    execute_resp = load_fixture("redshift", "execute_statement")
    describe_resp = load_fixture("redshift", "describe_statement_finished")
    result_resp = load_fixture("redshift", "get_statement_result")

    boto = MagicMock()
    boto.execute_statement.return_value = execute_resp
    boto.describe_statement.return_value = describe_resp
    boto.get_statement_result.return_value = result_resp

    client = _build_client_with_fake_boto(boto)
    rows = client.query("SELECT usage_date, service_class, compute_seconds, queries FROM sys_serverless_usage")

    assert len(rows) == 2
    # _decode_record turns {longValue: 7200} into 7200, etc.
    assert rows[0] == {
        "usage_date": "2026-04-22",
        "service_class": "etl",
        "compute_seconds": 7200,
        "queries": 412,
    }
    assert rows[1]["compute_seconds"] == 5400


def test_decode_record_handles_all_cell_types():
    """Negative path: schema drift safety — every cell variant is decoded."""
    columns = ["s", "l", "d", "b", "n"]
    record = [
        {"stringValue": "hello"},
        {"longValue": 42},
        {"doubleValue": 3.14},
        {"booleanValue": True},
        {"isNull": True},
    ]
    out = _decode_record(record, columns)
    assert out == {"s": "hello", "l": 42, "d": 3.14, "b": True, "n": None}


def test_translate_access_denied_error_includes_iam_hint():
    """Negative path: AccessDeniedException → RedshiftError with actionable IAM hint."""
    err = load_fixture("redshift", "access_denied_error")
    boto_exc = type("ClientError", (Exception,), {})("Access denied")
    boto_exc.response = err  # type: ignore[attr-defined]

    translated = _translate_boto_error(boto_exc)
    msg = str(translated)
    assert "redshift-data:ExecuteStatement" in msg
    assert "Hint" in msg


def test_data_client_raises_when_statement_fails():
    """Negative path: describe_statement returns FAILED → query() raises RedshiftError."""
    from app.services.connectors.redshift_connector import RedshiftError

    boto = MagicMock()
    boto.execute_statement.return_value = {"Id": "stmt-fail"}
    boto.describe_statement.return_value = {
        "Id": "stmt-fail",
        "Status": "FAILED",
        "Error": "syntax error at or near \"SELEKT\"",
    }

    client = _build_client_with_fake_boto(boto)
    try:
        client.query("SELEKT 1")
    except RedshiftError as e:
        assert "FAILED" in str(e)
        assert "SELEKT" in str(e)
    else:
        raise AssertionError("expected RedshiftError")
