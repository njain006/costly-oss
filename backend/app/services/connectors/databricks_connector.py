"""Databricks connector — System Tables edition.

Queries `system.billing.usage` and `system.billing.list_prices` via a customer-
provided SQL warehouse using the `databricks-sql-connector` driver.

System Tables have been GA since October 2024 and are the canonical billing
source per the Databricks admin docs:
  https://docs.databricks.com/aws/en/admin/system-tables/billing
  https://docs.databricks.com/aws/en/admin/system-tables/pricing

Credentials (dict):
    server_hostname:      workspace hostname, e.g. "dbc-abc-123.cloud.databricks.com"
    warehouse_http_path:  SQL warehouse HTTP path, e.g. "/sql/1.0/warehouses/abc123"
    access_token:         PAT with permission to query `system.billing.*`
    cloud (optional):     "AWS" | "AZURE" | "GCP" — used to resolve list prices
    pricing_overrides (optional):
        - per-SKU unit price:       {"STANDARD_JOBS_COMPUTE": 0.15}
        - global DBU discount:      {"dbu_discount_pct": 30}
        - generic discount:         {"discount_pct": 20}

Legacy fields (accepted, unused for querying — retained for test_connection
metadata and backward-compat when previously stored):
    account_id, workspace_url

Notes
-----
* `usage_quantity` is native to each SKU (usually DBUs). Cost = qty * list price.
* Photon consumption is already doubled in `usage_quantity` by Databricks, so we
  just surface `photon_enabled` in metadata for UI breakdown — no extra math.
* DBU-only: infrastructure (EC2 / Azure VM / GCE) is billed separately by the
  cloud provider. For full TCO pair this connector with AWS / GCP / Azure.
  (v2: optionally auto-query AWS Cost Explorer when `cloud == "AWS"`.)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from app.models.platform import CostCategory, UnifiedCost
from app.services.connectors.base import BaseConnector


# ─── Structured error codes returned from test_connection() ────────────────
SCOPE_MISSING = "SCOPE_MISSING"                  # warehouse_http_path or credentials missing
WAREHOUSE_NOT_FOUND = "WAREHOUSE_NOT_FOUND"      # warehouse does not exist / wrong path
PERMISSION_DENIED = "PERMISSION_DENIED"          # token lacks access
TABLE_ACCESS_DENIED = "TABLE_ACCESS_DENIED"      # system.billing.* not shared to user
CONNECTION_FAILED = "CONNECTION_FAILED"          # transport / auth / unknown


# ─── Billing-origin-product → CostCategory (single source of truth) ──────────
# Every billing_origin_product that Databricks can return, mapped once. A new
# product defaults to CostCategory.compute so the connector never silently
# drops a record even when Databricks ships a new product mid-year.
BILLING_PRODUCT_CATEGORY: dict[str, CostCategory] = {
    # Classic compute
    "ALL_PURPOSE": CostCategory.compute,
    "JOBS": CostCategory.compute,
    "INTERACTIVE": CostCategory.compute,
    "SQL": CostCategory.compute,
    # Pipelines / transformation
    "DLT": CostCategory.transformation,
    "LAKEFLOW_CONNECT": CostCategory.ingestion,
    "DATA_SHARING": CostCategory.transformation,
    # Serving / inference
    "MODEL_SERVING": CostCategory.ml_serving,
    "AI_GATEWAY": CostCategory.ai_inference,
    "AI_FUNCTIONS": CostCategory.ai_inference,
    "AGENT_BRICKS": CostCategory.ai_inference,
    "AGENT_EVALUATION": CostCategory.ai_inference,
    "FOUNDATION_MODEL_TRAINING": CostCategory.ml_training,
    "AI_RUNTIME": CostCategory.ml_training,
    # Data quality
    "LAKEHOUSE_MONITORING": CostCategory.data_quality,
    "DATA_QUALITY_MONITORING": CostCategory.data_quality,
    "DATA_CLASSIFICATION": CostCategory.data_quality,
    # Storage + optimization
    "DEFAULT_STORAGE": CostCategory.storage,
    "ONLINE_TABLES": CostCategory.storage,
    "DATABASE": CostCategory.storage,
    "PREDICTIVE_OPTIMIZATION": CostCategory.compute,
    # Search
    "VECTOR_SEARCH": CostCategory.serving,
    # Misc / platform
    "APPS": CostCategory.serving,
    "CLEAN_ROOM": CostCategory.compute,
    "NETWORKING": CostCategory.networking,
    "FINE_GRAINED_ACCESS_CONTROL": CostCategory.compute,
    "BASE_ENVIRONMENTS": CostCategory.compute,
}


CLOUD_INFRA_NOTE = (
    "DBU-only; EC2/VM infrastructure costs billed separately by your cloud provider"
)


# Cost-per-record query. Joins usage to list_prices for the price in effect at
# `usage_start_time`; DATEADD/CURRENT_DATE() are Databricks SQL built-ins.
_USAGE_SQL = """
SELECT
  u.usage_date,
  u.workspace_id,
  u.sku_name,
  u.cloud,
  u.billing_origin_product,
  u.usage_quantity,
  u.usage_unit,
  u.usage_metadata,
  u.custom_tags,
  u.identity_metadata,
  p.pricing.default AS list_dbu_price,
  p.pricing.effective_list.default AS effective_list_price,
  p.currency_code
FROM system.billing.usage AS u
LEFT JOIN system.billing.list_prices AS p
  ON u.sku_name = p.sku_name
  AND u.cloud = p.cloud
  AND u.usage_start_time >= p.price_start_time
  AND (p.price_end_time IS NULL OR u.usage_start_time < p.price_end_time)
WHERE u.usage_date >= DATEADD(DAY, -{days}, CURRENT_DATE())
ORDER BY u.usage_date
""".strip()


# ─── Helpers ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _CredentialCheck:
    """Result of credential validation. Not surfaced externally."""

    ok: bool
    error_code: str = ""
    message: str = ""


def _validate_credentials(credentials: dict) -> _CredentialCheck:
    if not credentials.get("access_token"):
        return _CredentialCheck(False, SCOPE_MISSING, "access_token is required")
    if not credentials.get("server_hostname"):
        return _CredentialCheck(False, SCOPE_MISSING, "server_hostname is required")
    if not credentials.get("warehouse_http_path"):
        return _CredentialCheck(
            False,
            SCOPE_MISSING,
            "warehouse_http_path is required to query system.billing.* tables",
        )
    return _CredentialCheck(True)


def _classify(billing_origin_product: Optional[str]) -> CostCategory:
    """Map billing_origin_product → CostCategory (single-lookup, no overwrites)."""
    if not billing_origin_product:
        return CostCategory.compute
    return BILLING_PRODUCT_CATEGORY.get(
        billing_origin_product.upper(), CostCategory.compute
    )


def _row_to_dict(row: Any) -> dict:
    """Normalize a databricks-sql-connector Row into a plain dict.

    The driver's Row supports attribute access and `asDict()`. This helper
    tolerates whichever is provided by mocks in tests.
    """
    as_dict = getattr(row, "asDict", None)
    if callable(as_dict):
        try:
            return dict(as_dict())
        except Exception:
            pass
    if isinstance(row, dict):
        return dict(row)
    keys = (
        "usage_date", "workspace_id", "sku_name", "cloud", "billing_origin_product",
        "usage_quantity", "usage_unit", "usage_metadata", "custom_tags",
        "identity_metadata", "list_dbu_price", "effective_list_price",
        "currency_code",
    )
    return {k: getattr(row, k, None) for k in keys}


def _coerce_mapping(value: Any) -> dict:
    """System-tables map/struct columns arrive as dict; tolerate str/None."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            import json

            out = json.loads(value)
            return out if isinstance(out, dict) else {}
        except Exception:
            return {}
    as_dict = getattr(value, "asDict", None)
    if callable(as_dict):
        try:
            return dict(as_dict())
        except Exception:
            return {}
    return {}


def _is_photon(usage_metadata: dict) -> bool:
    """Photon flag — Databricks surfaces this in usage_metadata on Spark SKUs."""
    value = usage_metadata.get("photon_enabled")
    if value is None:
        value = usage_metadata.get("is_photon")
    return bool(value) if value is not None else False


def _resolve_team(custom_tags: dict, identity_metadata: dict) -> Optional[str]:
    """Extract team/owner attribution from custom_tags or identity."""
    for key in ("team", "Team", "owner", "Owner", "cost_center", "CostCenter"):
        value = custom_tags.get(key)
        if value:
            return str(value)
    owner = identity_metadata.get("run_as") or identity_metadata.get("owned_by")
    return str(owner) if owner else None


def _resolve_project(custom_tags: dict, usage_metadata: dict) -> Optional[str]:
    """Extract project attribution from custom_tags or job metadata."""
    for key in ("project", "Project", "application", "app"):
        value = custom_tags.get(key)
        if value:
            return str(value)
    name = usage_metadata.get("job_name")
    return str(name) if name else None


def _resolve_resource(usage_metadata: dict, workspace_id: Any, sku: str) -> str:
    """Prefer the most specific identifier; fall back to workspace or sku."""
    for key in ("job_name", "run_name", "endpoint_name", "app_name", "notebook_path"):
        value = usage_metadata.get(key)
        if value:
            return str(value)
    for key in (
        "job_id", "warehouse_id", "endpoint_id", "cluster_id",
        "dlt_pipeline_id", "app_id", "database_instance_id",
    ):
        value = usage_metadata.get(key)
        if value:
            return str(value)
    if workspace_id:
        return f"workspace:{workspace_id}"
    return sku.lower()


def _apply_pricing_overrides(
    sku: str,
    base_price: float,
    pricing_overrides: dict,
) -> float:
    """Return the per-unit price after applying overrides.

    Precedence:
      1. per-SKU override (exact match, case-insensitive)
      2. dbu_discount_pct (applied to the DBU list price)
      3. discount_pct     (generic flat discount)
    """
    if not pricing_overrides:
        return base_price

    sku_upper = sku.upper()
    for key, value in pricing_overrides.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        if key.upper() == sku_upper:
            return float(value)

    discount = pricing_overrides.get("dbu_discount_pct")
    if discount is None:
        discount = pricing_overrides.get("discount_pct")
    if discount is not None:
        try:
            pct = float(discount)
            return base_price * (1 - pct / 100.0)
        except (TypeError, ValueError):
            return base_price
    return base_price


def _format_date(value: Any) -> str:
    """Return YYYY-MM-DD from date/datetime/str/None."""
    if value is None:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if isinstance(value, str):
        return value[:10]
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()[:10]
        except Exception:
            return str(value)[:10]
    return str(value)[:10]


# ─── Driver import guard ────────────────────────────────────────────────────


class _ConnectorImportError(ImportError):
    """Raised when the databricks-sql-connector driver is not installed."""


# ─── Connector ──────────────────────────────────────────────────────────────


class DatabricksConnector(BaseConnector):
    """Pulls Databricks DBU spend from `system.billing.usage` + list prices."""

    platform = "databricks"

    def __init__(self, credentials: dict):
        super().__init__(credentials)
        self.access_token: str = credentials.get("access_token", "")
        self.server_hostname: str = (credentials.get("server_hostname") or "").strip()
        self.warehouse_http_path: str = (
            credentials.get("warehouse_http_path") or ""
        ).strip()
        self.cloud: Optional[str] = (credentials.get("cloud") or "").upper() or None

        # Legacy — kept for display only, not used for querying.
        self.account_id: str = credentials.get("account_id", "")
        self.workspace_url: str = credentials.get("workspace_url", "")

        overrides = credentials.get("pricing_overrides")
        self.pricing_overrides: dict = overrides if isinstance(overrides, dict) else {}

    # ── public API ──────────────────────────────────────────────────────────

    def test_connection(self) -> dict:
        """Probe the SQL warehouse and a trivial `system.billing.usage` query."""
        check = _validate_credentials(self.credentials)
        if not check.ok:
            return {
                "success": False,
                "error_code": check.error_code,
                "message": check.message,
            }

        try:
            conn = self._sql_connect()
        except _ConnectorImportError as e:
            return {
                "success": False,
                "error_code": CONNECTION_FAILED,
                "message": str(e),
            }
        except Exception as e:  # auth / transport
            return self._classify_exception(e)

        try:
            with conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT 1")
                    cursor.fetchall()
                    cursor.execute("SELECT 1 FROM system.billing.usage LIMIT 1")
                    cursor.fetchall()
            return {
                "success": True,
                "message": (
                    f"Connected to Databricks SQL warehouse "
                    f"{self.warehouse_http_path} on {self.server_hostname}"
                ),
            }
        except Exception as e:
            return self._classify_exception(e)

    def fetch_costs(self, days: int = 30) -> list[UnifiedCost]:
        """Query system.billing.usage joined to list_prices and normalize."""
        if days <= 0:
            return []

        if not _validate_credentials(self.credentials).ok:
            # Honest fallback: no fantasy math, just return [].
            return []

        try:
            conn = self._sql_connect()
        except _ConnectorImportError:
            return []
        except Exception:
            return []

        rows: list[dict] = []
        try:
            with conn:
                with conn.cursor() as cursor:
                    cursor.execute(_USAGE_SQL.format(days=int(days)))
                    for raw in cursor.fetchall():
                        rows.append(_row_to_dict(raw))
        except Exception:
            return []

        results: list[UnifiedCost] = []
        for row in rows:
            cost = self._row_to_unified(row)
            if cost is not None:
                results.append(cost)
        return results

    # ── internals ───────────────────────────────────────────────────────────

    def _sql_connect(self):
        """Open a databricks-sql-connector connection (lazy import for tests)."""
        try:
            from databricks import sql as databricks_sql  # type: ignore
        except ImportError as exc:  # pragma: no cover - exercised via mock
            raise _ConnectorImportError(
                "databricks-sql-connector not installed. "
                "Install with `pip install databricks-sql-connector`."
            ) from exc

        return databricks_sql.connect(
            server_hostname=self.server_hostname,
            http_path=self.warehouse_http_path,
            access_token=self.access_token,
        )

    def _row_to_unified(self, row: dict) -> Optional[UnifiedCost]:
        usage_quantity = float(row.get("usage_quantity") or 0)
        if usage_quantity <= 0:
            return None

        sku = str(row.get("sku_name") or "UNKNOWN")
        billing_product = row.get("billing_origin_product") or ""
        date_str = _format_date(row.get("usage_date"))
        workspace_id = row.get("workspace_id") or ""
        cloud = (row.get("cloud") or self.cloud or "").upper() or None

        usage_metadata = _coerce_mapping(row.get("usage_metadata"))
        custom_tags = _coerce_mapping(row.get("custom_tags"))
        identity_metadata = _coerce_mapping(row.get("identity_metadata"))

        # Effective list price precedence: account effective_list > default list.
        base_price = row.get("effective_list_price")
        if base_price in (None, 0):
            base_price = row.get("list_dbu_price")
        base_price = float(base_price or 0)

        unit_price = _apply_pricing_overrides(sku, base_price, self.pricing_overrides)
        cost_usd = round(usage_quantity * unit_price, 6)

        metadata: dict = {
            "sku": sku,
            "cloud": cloud,
            "billing_origin_product": billing_product,
            "usage_unit": row.get("usage_unit") or "DBU",
            "list_price_per_unit": round(base_price, 6),
            "effective_price_per_unit": round(unit_price, 6),
            "currency_code": row.get("currency_code") or "USD",
            "photon_enabled": _is_photon(usage_metadata),
            "note": CLOUD_INFRA_NOTE,
        }
        if workspace_id:
            metadata["workspace_id"] = str(workspace_id)

        # Bubble up per-job / per-notebook / per-warehouse / per-app attribution
        for key in (
            "job_id", "job_name", "job_run_id", "run_name",
            "notebook_id", "notebook_path",
            "cluster_id", "instance_pool_id", "node_type",
            "warehouse_id",
            "endpoint_id", "endpoint_name",
            "dlt_pipeline_id", "dlt_update_id",
            "app_id", "app_name",
            "metastore_id", "budget_policy_id",
        ):
            value = usage_metadata.get(key)
            if value:
                metadata[key] = str(value)
        if custom_tags:
            metadata["custom_tags"] = {str(k): str(v) for k, v in custom_tags.items()}
        run_as = identity_metadata.get("run_as")
        if run_as:
            metadata["run_as"] = str(run_as)

        return UnifiedCost(
            date=date_str,
            platform="databricks",
            service=f"databricks_{(billing_product or 'compute').lower()}",
            resource=_resolve_resource(usage_metadata, workspace_id, sku),
            category=_classify(billing_product),
            cost_usd=cost_usd,
            usage_quantity=round(usage_quantity, 6),
            usage_unit=str(row.get("usage_unit") or "DBU"),
            team=_resolve_team(custom_tags, identity_metadata),
            project=_resolve_project(custom_tags, usage_metadata),
            metadata=metadata,
        )

    def _classify_exception(self, exc: Exception) -> dict:
        """Turn a raw driver exception into a structured connector error."""
        message = str(exc)
        low = message.lower()

        if "system.billing" in low and ("denied" in low or "not found" in low):
            code = TABLE_ACCESS_DENIED
        elif "warehouse" in low and ("not found" in low or "does not exist" in low):
            code = WAREHOUSE_NOT_FOUND
        elif "http_path" in low or "invalid endpoint" in low:
            code = WAREHOUSE_NOT_FOUND
        elif (
            "permission denied" in low
            or "access denied" in low
            or "forbidden" in low
            or "not authorized" in low
            or "unauthorized" in low
            or "401" in low
            or "403" in low
        ):
            code = PERMISSION_DENIED
        else:
            code = CONNECTION_FAILED

        return {
            "success": False,
            "error_code": code,
            "message": message,
        }


# ─── Backward compatibility ─────────────────────────────────────────────────
#
# Keep `DBU_PRICING` exported for any UI/docs code that imports it, but mark it
# deprecated. The connector itself no longer uses it — list prices come from
# `system.billing.list_prices` at query time.

DBU_PRICING: dict[str, float] = {
    "ALL_PURPOSE": 0.55,       # Premium tier, illustrative only
    "JOBS": 0.15,              # Jobs Compute (updated from 0.30 — Databricks 2024 pricing)
    "SQL": 0.22,               # Classic SQL
    "DLT": 0.36,               # Delta Live Tables Advanced
    "MODEL_SERVING": 0.07,     # Mosaic AI Serving
    "INTERACTIVE": 0.55,
    "SERVERLESS_SQL": 0.70,
    "SERVERLESS_COMPUTE": 0.70,
    "FOUNDATION_MODEL": 0.07,
}
