"""Contract tests for the Gemini / Vertex AI connector.

Pins the connector to the BigQuery jobs.query response shape used by the
billing-export query. The actual billing tables are produced by Google Cloud
Billing's "BigQuery export" feature; the connector pulls aggregate rows via
``POST https://bigquery.googleapis.com/bigquery/v2/projects/{p}/queries``.

Re-record fixture
-----------------
Run the connector's billing query against a real BigQuery export table::

    bq query --use_legacy_sql=false --format=prettyjson \\
        "SELECT ... FROM \\`<project>.billing_export.gcp_billing_export_v1_<ACCT>\\` WHERE ..."

Save the JSON response under
``backend/tests/fixtures/gemini/billing_export_query.json``.
"""
from __future__ import annotations

from unittest.mock import patch

import httpx
import respx
from app.models.platform import CostCategory
from app.services.connectors.gemini_connector import GeminiConnector

from tests.contract.conftest import load_fixture

CREDS = {
    "service_account_json": '{"type":"service_account"}',
    "project_id": "test-project",
    "billing_project": "test-project",
    "billing_dataset": "billing_export",
    "billing_account_id": "012345-6789AB-CDEF01",
    "region": "us-central1",
}


@respx.mock
def test_fetch_costs_parses_billing_export_rows():
    fixture = load_fixture("gemini", "billing_export_query")
    respx.post(
        "https://bigquery.googleapis.com/bigquery/v2/projects/test-project/queries"
    ).mock(return_value=httpx.Response(200, json=fixture))

    with patch.object(GeminiConnector, "_get_access_token", return_value="tok"):
        costs = GeminiConnector(CREDS).fetch_costs(days=7)

    assert len(costs) == 2
    for c in costs:
        assert c.platform == "gemini"
        assert c.category == CostCategory.ai_inference
        assert c.cost_usd > 0
        assert c.usage_unit == "tokens"

    # Sanity: total = 1.875 + 3.0 = 4.875
    total = sum(c.cost_usd for c in costs)
    assert abs(total - 4.875) < 1e-6


@respx.mock
def test_fetch_costs_empty_on_403():
    """Negative path: BigQuery returns 403 → connector returns []."""
    err = load_fixture("gemini", "billing_export_403")
    respx.post(
        "https://bigquery.googleapis.com/bigquery/v2/projects/test-project/queries"
    ).mock(return_value=httpx.Response(403, json=err))

    with patch.object(GeminiConnector, "_get_access_token", return_value="tok"):
        assert GeminiConnector(CREDS).fetch_costs(days=7) == []


def test_ai_studio_only_credentials_return_empty():
    """AI Studio (api_key only) has no usage API → fetch_costs short-circuits."""
    conn = GeminiConnector({"api_key": "AIzaTest"})
    assert conn.use_vertex is False
    assert conn.fetch_costs(days=7) == []
