"""Realistic fixture rows mirroring `system.billing.usage` + list_prices.

Each record is a dict that matches the SELECT column aliases in
`databricks_connector._USAGE_SQL`, so the mocked cursor can yield them
directly via `fetchall()`.

Prices here are illustrative of Databricks' 2025 list prices (per-DBU):
    Jobs Compute (classic, AWS):      0.15
    All-Purpose Compute (Premium):    0.55
    SQL (classic):                    0.22
    DLT (Advanced):                   0.36
    Model Serving:                    0.07
    Serverless SQL:                   0.70
"""

from __future__ import annotations

from datetime import date
from typing import Any


def make_row(**overrides: Any) -> dict:
    """Return a fully-populated default row, overridden by kwargs."""
    base = {
        "usage_date": date(2026, 4, 21),
        "workspace_id": "1234567890",
        "sku_name": "STANDARD_JOBS_COMPUTE",
        "cloud": "AWS",
        "billing_origin_product": "JOBS",
        "usage_quantity": 10.0,
        "usage_unit": "DBU",
        "usage_metadata": {},
        "custom_tags": {},
        "identity_metadata": {},
        "list_dbu_price": 0.15,
        "effective_list_price": 0.15,
        "currency_code": "USD",
    }
    base.update(overrides)
    return base


# Canonical per-SKU rows used by parameterized tests
JOBS_ROW = make_row(
    sku_name="STANDARD_JOBS_COMPUTE",
    billing_origin_product="JOBS",
    usage_quantity=10.0,
    list_dbu_price=0.15,
    effective_list_price=0.15,
    usage_metadata={
        "job_id": "987",
        "job_name": "daily-etl",
        "job_run_id": "run-42",
        "run_name": "daily-etl (manual)",
        "cluster_id": "0423-abc",
    },
    custom_tags={"team": "data-platform", "env": "prod"},
    identity_metadata={"run_as": "etl@example.com"},
)

ALL_PURPOSE_ROW = make_row(
    sku_name="PREMIUM_ALL_PURPOSE_COMPUTE",
    billing_origin_product="ALL_PURPOSE",
    usage_quantity=4.0,
    list_dbu_price=0.55,
    effective_list_price=0.55,
    usage_metadata={
        "notebook_id": "n-1",
        "notebook_path": "/Users/ada/analysis",
        "cluster_id": "0423-def",
        "photon_enabled": True,
    },
    custom_tags={"owner": "ada@example.com"},
)

SQL_ROW = make_row(
    sku_name="STANDARD_SQL_COMPUTE",
    billing_origin_product="SQL",
    usage_quantity=20.0,
    list_dbu_price=0.22,
    effective_list_price=0.22,
    usage_metadata={"warehouse_id": "wh-xyz"},
)

DLT_ROW = make_row(
    sku_name="PREMIUM_DLT_ADVANCED_COMPUTE",
    billing_origin_product="DLT",
    usage_quantity=5.0,
    list_dbu_price=0.36,
    effective_list_price=0.36,
    usage_metadata={
        "dlt_pipeline_id": "pipe-1",
        "dlt_update_id": "update-7",
    },
)

MODEL_SERVING_ROW = make_row(
    sku_name="PREMIUM_SERVERLESS_MODEL_SERVING",
    billing_origin_product="MODEL_SERVING",
    usage_quantity=100.0,
    list_dbu_price=0.07,
    effective_list_price=0.07,
    usage_metadata={"endpoint_id": "ep-1", "endpoint_name": "llama3-prod"},
    custom_tags={"project": "chatbot"},
)

FOUNDATION_ROW = make_row(
    sku_name="PREMIUM_FOUNDATION_MODEL_TRAINING",
    billing_origin_product="FOUNDATION_MODEL_TRAINING",
    usage_quantity=2.0,
    list_dbu_price=1.60,
    effective_list_price=1.60,
)

AGENT_BRICKS_ROW = make_row(
    sku_name="PREMIUM_AGENT_BRICKS",
    billing_origin_product="AGENT_BRICKS",
    usage_quantity=3.0,
    list_dbu_price=0.30,
    effective_list_price=0.30,
    usage_metadata={"agent_bricks_id": "ab-9"},
)

APPS_ROW = make_row(
    sku_name="PREMIUM_DATABRICKS_APPS",
    billing_origin_product="APPS",
    usage_quantity=6.5,
    list_dbu_price=0.10,
    effective_list_price=0.10,
    usage_metadata={"app_id": "app-42", "app_name": "internal-dashboard"},
)

VECTOR_SEARCH_ROW = make_row(
    sku_name="PREMIUM_VECTOR_SEARCH",
    billing_origin_product="VECTOR_SEARCH",
    usage_quantity=1.5,
    list_dbu_price=0.55,
    effective_list_price=0.55,
)

DATABASE_ROW = make_row(
    sku_name="PREMIUM_LAKEBASE_DATABASE",
    billing_origin_product="DATABASE",
    usage_quantity=12.0,
    list_dbu_price=0.10,
    effective_list_price=0.10,
    usage_metadata={"database_instance_id": "db-1"},
)

# Zero-quantity — should be filtered out
ZERO_ROW = make_row(
    sku_name="STANDARD_JOBS_COMPUTE",
    usage_quantity=0.0,
)

# Unknown product — should fall back to compute, not blow up
UNKNOWN_PRODUCT_ROW = make_row(
    sku_name="SOMETHING_NEW",
    billing_origin_product="BRAND_NEW_2027_PRODUCT",
    usage_quantity=1.0,
    list_dbu_price=0.10,
    effective_list_price=0.10,
)

# Photon + discount edge case
PHOTON_ROW = make_row(
    sku_name="PREMIUM_ALL_PURPOSE_COMPUTE_PHOTON",
    billing_origin_product="ALL_PURPOSE",
    usage_quantity=8.0,  # Databricks already pre-doubled this
    list_dbu_price=0.55,
    effective_list_price=0.55,
    usage_metadata={"photon_enabled": True, "cluster_id": "pc-1"},
)

ALL_ROWS = [
    JOBS_ROW,
    ALL_PURPOSE_ROW,
    SQL_ROW,
    DLT_ROW,
    MODEL_SERVING_ROW,
    FOUNDATION_ROW,
    AGENT_BRICKS_ROW,
    APPS_ROW,
    VECTOR_SEARCH_ROW,
    DATABASE_ROW,
]
