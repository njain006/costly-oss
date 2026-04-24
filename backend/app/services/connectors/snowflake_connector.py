"""Snowflake connector for the unified cost platform.

Upgrades over the original minimal implementation:

1.  Serverless credit lines (Serverless Tasks, Snowpipe, Auto-Clustering,
    Materialized View refresh, Search Optimization, Cortex AI Services,
    Replication, Query Acceleration, Snowpipe Streaming) — together they are
    typically 15-30 %+ of modern Snowflake bills.
2.  `pricing_overrides` support (credit prices, per-warehouse-size overrides,
    storage price per TB, and on-demand vs capacity flag).
3.  Per-user / role / query-tag attribution via
    `SNOWFLAKE.ACCOUNT_USAGE.QUERY_ATTRIBUTION_HISTORY`.
4.  Preferred path through `SNOWFLAKE.ORGANIZATION_USAGE.USAGE_IN_CURRENCY_DAILY`
    (returns already-billed USD including on-demand/capacity and the 10%
    Cloud Services discount). Falls back to ACCOUNT_USAGE when the role
    lacks ORGUSAGE access.
5.  Storage is split into active + time-travel + failsafe lines with
    per-database trend via `DATABASE_STORAGE_USAGE_HISTORY`. Active and
    archive storage can be priced separately.
6.  Cloud Services free-allowance (10% of compute) honoured through
    `METERING_DAILY_HISTORY.CREDITS_ADJUSTMENT_CLOUD_SERVICES`.
7.  Structured permission errors explain which grants are missing instead
    of silently swallowing them.
8.  Timezone-aware `datetime.now(timezone.utc)` throughout.

Design notes
------------

The connector is self-contained. `build_sf_connection()` is reused from
`app.services.snowflake` (which in turn wraps `snowflake.connector.connect`).
All SQL lives here so it is unambiguous what the connector queries. Each
fetch helper catches Snowflake permission errors and converts them into a
`SnowflakeConnectorWarning` entry on the connector so callers can surface
the precise GRANT needed to unblock them.

References
----------

* Snowflake docs — `ACCOUNT_USAGE` views:
  https://docs.snowflake.com/en/sql-reference/account-usage
* Snowflake docs — `ORGANIZATION_USAGE.USAGE_IN_CURRENCY_DAILY`:
  https://docs.snowflake.com/en/sql-reference/organization-usage/usage_in_currency_daily
* Snowflake docs — `QUERY_ATTRIBUTION_HISTORY`:
  https://docs.snowflake.com/en/sql-reference/account-usage/query_attribution_history
* Select.dev cost intelligence patterns:
  https://select.dev/docs/snowflake-cost-management
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from app.models.platform import CostCategory, UnifiedCost
from app.services.connectors.base import BaseConnector

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pricing constants
# ---------------------------------------------------------------------------
# Edition defaults for the Snowflake compute credit price (USD/credit) when
# customer has not supplied pricing_overrides. See
# https://www.snowflake.com/pricing/ for current on-demand pricing.
DEFAULT_CREDIT_PRICE_USD: float = 3.00  # Enterprise edition on-demand
DEFAULT_EDITION_PRICES: dict[str, float] = {
    "standard": 2.00,
    "enterprise": 3.00,
    "business_critical": 4.00,
    "vps": 4.00,
}

# Default storage prices (USD per TB per month).
# Snowflake list prices — on-demand $23/TB, capacity $20/TB (and lower).
# Active vs time-travel/failsafe are billed at the same rate, but we keep
# them separate so overrides can split them (e.g. capacity contracts that
# offer an archive tier).
DEFAULT_ACTIVE_STORAGE_PRICE_PER_TB: float = 23.00
DEFAULT_FAILSAFE_STORAGE_PRICE_PER_TB: float = 23.00
DEFAULT_TIMETRAVEL_STORAGE_PRICE_PER_TB: float = 23.00

# Service-type -> CostCategory mapping for USAGE_IN_CURRENCY_DAILY and the
# various serverless views.
SERVICE_TYPE_CATEGORY: dict[str, CostCategory] = {
    "COMPUTE": CostCategory.compute,
    "WAREHOUSE_METERING": CostCategory.compute,
    "CLOUD_SERVICES": CostCategory.compute,
    "SERVERLESS_TASK": CostCategory.compute,
    "PIPE": CostCategory.ingestion,
    "SNOWPIPE": CostCategory.ingestion,
    "SNOWPIPE_STREAMING": CostCategory.ingestion,
    "AUTO_CLUSTERING": CostCategory.compute,
    "MATERIALIZED_VIEW": CostCategory.compute,
    "SEARCH_OPTIMIZATION": CostCategory.compute,
    "REPLICATION": CostCategory.storage,
    "QUERY_ACCELERATION": CostCategory.compute,
    "AI_SERVICES": CostCategory.ai_inference,
    "CORTEX": CostCategory.ai_inference,
    "STORAGE": CostCategory.storage,
    "DATA_TRANSFER": CostCategory.networking,
    "LOGGING": CostCategory.orchestration,
    "HYBRID_TABLE_STORAGE": CostCategory.storage,
    "HYBRID_TABLE_REQUESTS": CostCategory.compute,
    "ICEBERG_TABLE_REQUESTS": CostCategory.storage,
    "SNOWPARK_CONTAINER_SERVICES": CostCategory.compute,
}

# SERVICE_TYPE -> service slug we expose (prefixed with snowflake_ so the
# frontend can easily tell them apart).
SERVICE_TYPE_SLUG: dict[str, str] = {
    "COMPUTE": "snowflake_compute",
    "WAREHOUSE_METERING": "snowflake_compute",
    "CLOUD_SERVICES": "snowflake_cloud_services",
    "SERVERLESS_TASK": "snowflake_serverless_tasks",
    "PIPE": "snowflake_snowpipe",
    "SNOWPIPE": "snowflake_snowpipe",
    "SNOWPIPE_STREAMING": "snowflake_snowpipe_streaming",
    "AUTO_CLUSTERING": "snowflake_auto_clustering",
    "MATERIALIZED_VIEW": "snowflake_materialized_views",
    "SEARCH_OPTIMIZATION": "snowflake_search_optimization",
    "REPLICATION": "snowflake_replication",
    "QUERY_ACCELERATION": "snowflake_query_acceleration",
    "AI_SERVICES": "snowflake_cortex",
    "CORTEX": "snowflake_cortex",
    "STORAGE": "snowflake_storage",
    "DATA_TRANSFER": "snowflake_data_transfer",
    "LOGGING": "snowflake_event_tables",
    "HYBRID_TABLE_STORAGE": "snowflake_hybrid_storage",
    "HYBRID_TABLE_REQUESTS": "snowflake_hybrid_tables",
    "ICEBERG_TABLE_REQUESTS": "snowflake_iceberg",
    "SNOWPARK_CONTAINER_SERVICES": "snowflake_snowpark_container_services",
}

BYTES_PER_TB: float = 1024.0 ** 4
BYTES_PER_GB: float = 1024.0 ** 3


# ---------------------------------------------------------------------------
# Pricing resolution
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PricingConfig:
    """Resolved pricing for this connection.

    Built from `pricing_overrides` on the credentials dict, with defaults for
    anything not set. All values are immutable once built.
    """

    credit_price_usd: float = DEFAULT_CREDIT_PRICE_USD
    active_storage_price_per_tb: float = DEFAULT_ACTIVE_STORAGE_PRICE_PER_TB
    timetravel_storage_price_per_tb: float = DEFAULT_TIMETRAVEL_STORAGE_PRICE_PER_TB
    failsafe_storage_price_per_tb: float = DEFAULT_FAILSAFE_STORAGE_PRICE_PER_TB
    # Per-warehouse-size overrides, e.g. {"LARGE": 4.5}. Keys are normalized
    # (upper, hyphens stripped).
    warehouse_size_prices: dict[str, float] = field(default_factory=dict)
    # Per-SERVICE_TYPE overrides, e.g. {"AI_SERVICES": 5.0}. Snowflake prices
    # Cortex and serverless services in credits but some enterprise deals
    # apply a different effective rate.
    service_type_prices: dict[str, float] = field(default_factory=dict)
    # When True, prefer ORGANIZATION_USAGE.USAGE_IN_CURRENCY_DAILY (which
    # already reflects effective billed USD including discounts). Defaults
    # to True so we try it first.
    prefer_org_usage: bool = True

    @classmethod
    def from_credentials(cls, credentials: dict) -> "PricingConfig":
        overrides = (credentials or {}).get("pricing_overrides") or {}

        def _positive(value: Any, default: float) -> float:
            try:
                f = float(value)
                return f if f > 0 else default
            except (TypeError, ValueError):
                return default

        edition = str(overrides.get("edition", "")).strip().lower()
        default_credit = DEFAULT_EDITION_PRICES.get(edition, DEFAULT_CREDIT_PRICE_USD)

        credit_price = _positive(
            overrides.get("credit_price_usd", overrides.get("credit_price")),
            default_credit,
        )

        active_price = _positive(
            overrides.get("storage_price_per_tb", overrides.get("storage_price")),
            DEFAULT_ACTIVE_STORAGE_PRICE_PER_TB,
        )
        timetravel_price = _positive(
            overrides.get("timetravel_storage_price_per_tb"),
            active_price,
        )
        failsafe_price = _positive(
            overrides.get("failsafe_storage_price_per_tb"),
            active_price,
        )

        warehouse_sizes_raw = overrides.get("warehouse_size_prices") or {}
        warehouse_sizes: dict[str, float] = {}
        if isinstance(warehouse_sizes_raw, dict):
            for size, price in warehouse_sizes_raw.items():
                if size is None:
                    continue
                normalized = str(size).upper().replace("-", "").strip()
                try:
                    f = float(price)
                except (TypeError, ValueError):
                    continue
                if f > 0:
                    warehouse_sizes[normalized] = f

        service_type_prices_raw = overrides.get("service_type_prices") or {}
        service_type_prices: dict[str, float] = {}
        if isinstance(service_type_prices_raw, dict):
            for svc, price in service_type_prices_raw.items():
                if svc is None:
                    continue
                try:
                    f = float(price)
                except (TypeError, ValueError):
                    continue
                if f > 0:
                    service_type_prices[str(svc).upper()] = f

        prefer_org_usage = bool(overrides.get("prefer_org_usage", True))

        return cls(
            credit_price_usd=credit_price,
            active_storage_price_per_tb=active_price,
            timetravel_storage_price_per_tb=timetravel_price,
            failsafe_storage_price_per_tb=failsafe_price,
            warehouse_size_prices=warehouse_sizes,
            service_type_prices=service_type_prices,
            prefer_org_usage=prefer_org_usage,
        )

    def credit_price_for_warehouse(self, warehouse_size: Optional[str]) -> float:
        if not warehouse_size:
            return self.credit_price_usd
        key = str(warehouse_size).upper().replace("-", "").strip()
        return self.warehouse_size_prices.get(key, self.credit_price_usd)

    def credit_price_for_service_type(self, service_type: Optional[str]) -> float:
        if not service_type:
            return self.credit_price_usd
        return self.service_type_prices.get(
            str(service_type).upper(), self.credit_price_usd
        )


# ---------------------------------------------------------------------------
# Exceptions & warnings
# ---------------------------------------------------------------------------
class SnowflakePermissionError(RuntimeError):
    """Raised when the role lacks the required ACCOUNT_USAGE grant.

    Carries a human-readable remediation string explaining the exact grant.
    """

    def __init__(self, view: str, role: str, original: Optional[BaseException] = None):
        self.view = view
        self.role = role
        self.original = original
        database = "SNOWFLAKE"
        if "ORGANIZATION_USAGE" in view.upper():
            message = (
                f"Role {role!r} cannot read {view}. "
                "Grant: GRANT APPLY TAG ON ACCOUNT TO ROLE "
                f"{role}; plus GRANT DATABASE ROLE SNOWFLAKE.ORGANIZATION_USAGE_VIEWER "
                f"TO ROLE {role};"
            )
        else:
            message = (
                f"Role {role!r} cannot read {view}. "
                f"Grant: GRANT IMPORTED PRIVILEGES ON DATABASE {database} TO ROLE {role};"
            )
        super().__init__(message)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _to_conn_doc(credentials: dict) -> dict:
    """Convert platform_connections credentials to the conn_doc dict that
    `build_sf_connection()` expects.
    """
    # Imported here so the module stays import-safe even when the encryption
    # stack cannot initialise (e.g. missing ENCRYPTION_KEY in certain test
    # harnesses). `encrypt_value` is still required for real connections.
    from app.services.encryption import encrypt_value

    account_raw = str(credentials.get("account", "")).strip().lower()
    account = account_raw.replace(".snowflakecomputing.com", "")

    doc: dict[str, Any] = {
        "account": account,
        "username": credentials.get("user", credentials.get("username", "")),
        "auth_type": credentials.get("auth_type", "keypair"),
        "warehouse": credentials.get("warehouse", "COMPUTE_WH"),
        "database": credentials.get("database", "SNOWFLAKE"),
        "schema_name": credentials.get("schema_name", "ACCOUNT_USAGE"),
        "role": credentials.get("role", "ACCOUNTADMIN"),
    }
    if doc["auth_type"] == "password":
        password = credentials.get("password", "")
        doc["password_encrypted"] = encrypt_value(password) if password else ""
    else:
        private_key = credentials.get("private_key", "")
        doc["private_key_encrypted"] = encrypt_value(private_key) if private_key else ""
        passphrase = credentials.get("private_key_passphrase")
        if passphrase:
            doc["private_key_passphrase_encrypted"] = encrypt_value(passphrase)
    return doc


def _today_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _classify_error(err: BaseException) -> bool:
    """Return True when the error looks like a permission / access problem."""
    msg = str(err).lower()
    needles = (
        "does not exist or not authorized",
        "insufficient privileges",
        "not authorized",
        "does not have privilege",
        "access denied",
        "privilege 'usage'",
        "privilege 'imported privileges'",
        "access control",
    )
    return any(n in msg for n in needles)


def _normalize_date(value: Any) -> str:
    """Coerce a Snowflake row value to YYYY-MM-DD."""
    if value is None:
        return _today_iso()
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).strftime("%Y-%m-%d") if value.tzinfo else value.strftime("%Y-%m-%d")
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    s = str(value)
    # Already YYYY-MM-DD?
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    return s


def _fetchall(cur) -> list[tuple]:
    rows = cur.fetchall()
    return list(rows) if rows is not None else []


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------
class SnowflakeConnector(BaseConnector):
    """Snowflake cost connector.

    Queries a combination of ACCOUNT_USAGE and ORGANIZATION_USAGE views and
    normalises the results into `UnifiedCost` records. Safe to use with
    read-only roles (ACCOUNTADMIN is not required — any role with
    IMPORTED PRIVILEGES on the SNOWFLAKE database works).
    """

    platform = "snowflake"

    def __init__(self, credentials: dict):
        super().__init__(credentials)
        self.conn_doc = _to_conn_doc(credentials)
        self.pricing = PricingConfig.from_credentials(credentials)
        # Each fetch_costs() run collects warnings (permission failures,
        # missing views, etc.) so the UI can surface them to the user.
        self.warnings: list[str] = []

    # ----- connection helpers -------------------------------------------------
    def _connect(self):  # pragma: no cover — thin wrapper
        from app.services.snowflake import build_sf_connection

        return build_sf_connection(self.conn_doc)

    def test_connection(self) -> dict:
        try:
            sf = self._connect()
            try:
                cur = sf.cursor()
                cur.execute("SELECT CURRENT_USER(), CURRENT_ROLE(), CURRENT_WAREHOUSE()")
                row = cur.fetchone() or ("", "", "")
                cur.close()
                return {
                    "success": True,
                    "message": f"Connected as {row[0]}, role {row[1]}, warehouse {row[2]}",
                }
            finally:
                try:
                    sf.close()
                except Exception:
                    logger.debug("snowflake close failed", exc_info=True)
        except Exception as e:  # noqa: BLE001 — we want to capture and present everything
            return {"success": False, "message": str(e)}

    # ----- main entry --------------------------------------------------------
    def fetch_costs(self, days: int = 30) -> list[UnifiedCost]:
        """Fetch a normalized UnifiedCost list for the last `days` days.

        Strategy:

        * Try ORGANIZATION_USAGE.USAGE_IN_CURRENCY_DAILY first (already-billed
          USD). If the role can see it we use it verbatim and only top up with
          attribution + storage breakdowns.
        * Otherwise fall back to the ACCOUNT_USAGE stack:
          METERING_DAILY_HISTORY (warehouse compute + Cloud Services net of
          the 10% free allowance) + serverless views + storage views.

        All failures are caught and recorded in `self.warnings`.
        """
        self.warnings = []
        costs: list[UnifiedCost] = []

        try:
            sf = self._connect()
        except Exception as e:  # noqa: BLE001
            logger.warning("snowflake connect failed: %s", e)
            self.warnings.append(f"Snowflake connection failed: {e}")
            return costs

        try:
            cur = sf.cursor()
            try:
                used_org_usage = False
                if self.pricing.prefer_org_usage:
                    try:
                        org_rows = self._fetch_org_usage(cur, days)
                        if org_rows:
                            costs.extend(org_rows)
                            used_org_usage = True
                    except SnowflakePermissionError as e:
                        self.warnings.append(str(e))
                    except Exception as e:  # noqa: BLE001
                        self.warnings.append(
                            f"ORGANIZATION_USAGE.USAGE_IN_CURRENCY_DAILY query failed: {e}"
                        )

                if not used_org_usage:
                    # Fall back to ACCOUNT_USAGE metering + serverless views.
                    costs.extend(self._fetch_metering_daily(cur, days))
                    costs.extend(self._fetch_serverless(cur, days))

                # Attribution, storage breakdown and Cortex always run on top
                # regardless of which primary source we used — they provide
                # dimensions that USAGE_IN_CURRENCY_DAILY does not.
                costs.extend(self._fetch_attribution(cur, days))
                costs.extend(self._fetch_storage(cur, days))
            finally:
                try:
                    cur.close()
                except Exception:
                    logger.debug("cursor close failed", exc_info=True)
        finally:
            try:
                sf.close()
            except Exception:
                logger.debug("snowflake close failed", exc_info=True)

        return costs

    # ----- ORGANIZATION_USAGE.USAGE_IN_CURRENCY_DAILY ------------------------
    def _fetch_org_usage(self, cur, days: int) -> list[UnifiedCost]:
        """Preferred path: pull already-billed USD per service type.

        `USAGE_IN_CURRENCY_DAILY` already reflects the 10% Cloud Services
        free allowance, on-demand vs capacity pricing, and any currency
        conversion. See
        https://docs.snowflake.com/en/sql-reference/organization-usage/usage_in_currency_daily
        """
        sql = f"""
            SELECT
                USAGE_DATE,
                ACCOUNT_NAME,
                SERVICE_TYPE,
                USAGE_TYPE,
                SUM(USAGE) AS USAGE,
                ANY_VALUE(USAGE_UNITS) AS USAGE_UNITS,
                SUM(USAGE_IN_CURRENCY) AS USAGE_IN_CURRENCY,
                ANY_VALUE(CURRENCY) AS CURRENCY
            FROM SNOWFLAKE.ORGANIZATION_USAGE.USAGE_IN_CURRENCY_DAILY
            WHERE USAGE_DATE >= DATEADD(day, -{int(days)}, CURRENT_DATE())
            GROUP BY 1, 2, 3, 4
            ORDER BY 1
        """
        try:
            cur.execute(sql)
        except Exception as e:  # noqa: BLE001
            if _classify_error(e):
                raise SnowflakePermissionError(
                    "SNOWFLAKE.ORGANIZATION_USAGE.USAGE_IN_CURRENCY_DAILY",
                    self.conn_doc.get("role", ""),
                    e,
                )
            raise

        rows: list[UnifiedCost] = []
        for row in _fetchall(cur):
            usage_date, account_name, service_type, usage_type, usage, usage_units, usd, currency = row
            cost_usd = float(usd or 0)
            if cost_usd <= 0:
                continue
            stype = str(service_type or "").upper()
            category = SERVICE_TYPE_CATEGORY.get(stype, CostCategory.compute)
            slug = SERVICE_TYPE_SLUG.get(stype, "snowflake_" + stype.lower())
            resource = usage_type or service_type or "Snowflake"
            rows.append(
                UnifiedCost(
                    date=_normalize_date(usage_date),
                    platform="snowflake",
                    service=slug,
                    resource=str(resource),
                    category=category,
                    cost_usd=round(cost_usd, 4),
                    usage_quantity=round(float(usage or 0), 4),
                    usage_unit=str(usage_units or "").lower(),
                    metadata={
                        "source": "ORGANIZATION_USAGE.USAGE_IN_CURRENCY_DAILY",
                        "service_type": stype,
                        "account_name": account_name,
                        "currency": currency or "USD",
                    },
                )
            )
        return rows

    # ----- METERING_DAILY_HISTORY --------------------------------------------
    def _fetch_metering_daily(self, cur, days: int) -> list[UnifiedCost]:
        """Fallback path: ACCOUNT_USAGE.METERING_DAILY_HISTORY.

        This is the best source for compute + Cloud Services credits because
        it already exposes the Cloud Services discount through
        `CREDITS_ADJUSTMENT_CLOUD_SERVICES`. Net billed Cloud Services
        credits = CREDITS_USED_CLOUD_SERVICES + CREDITS_ADJUSTMENT_CLOUD_SERVICES
        (the adjustment is already negative when the 10% free allowance
        applies).
        """
        sql = f"""
            SELECT
                USAGE_DATE,
                SERVICE_TYPE,
                SUM(CREDITS_USED_COMPUTE) AS CREDITS_COMPUTE,
                SUM(CREDITS_USED_CLOUD_SERVICES) AS CREDITS_CLOUD,
                SUM(CREDITS_ADJUSTMENT_CLOUD_SERVICES) AS CREDITS_CLOUD_ADJ,
                SUM(CREDITS_BILLED) AS CREDITS_BILLED
            FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_DAILY_HISTORY
            WHERE USAGE_DATE >= DATEADD(day, -{int(days)}, CURRENT_DATE())
            GROUP BY 1, 2
            ORDER BY 1
        """
        try:
            cur.execute(sql)
        except Exception as e:  # noqa: BLE001
            if _classify_error(e):
                self.warnings.append(
                    str(SnowflakePermissionError(
                        "SNOWFLAKE.ACCOUNT_USAGE.METERING_DAILY_HISTORY",
                        self.conn_doc.get("role", ""),
                        e,
                    ))
                )
                # Fall through to the legacy WAREHOUSE_METERING_HISTORY path.
                return self._fetch_warehouse_metering(cur, days)
            self.warnings.append(f"METERING_DAILY_HISTORY query failed: {e}")
            return self._fetch_warehouse_metering(cur, days)

        rows: list[UnifiedCost] = []
        for row in _fetchall(cur):
            usage_date, service_type, credits_compute, credits_cloud, credits_cloud_adj, _billed = row
            stype = str(service_type or "COMPUTE").upper()
            credit_price = self.pricing.credit_price_for_service_type(stype)
            compute_credits = float(credits_compute or 0)
            cloud_credits = float(credits_cloud or 0)
            cloud_adj = float(credits_cloud_adj or 0)
            net_cloud_credits = max(cloud_credits + cloud_adj, 0.0)

            if compute_credits > 0:
                rows.append(
                    UnifiedCost(
                        date=_normalize_date(usage_date),
                        platform="snowflake",
                        service=SERVICE_TYPE_SLUG.get(stype, "snowflake_compute"),
                        resource=f"{stype.title().replace('_', ' ')} (compute)",
                        category=SERVICE_TYPE_CATEGORY.get(stype, CostCategory.compute),
                        cost_usd=round(compute_credits * credit_price, 4),
                        usage_quantity=round(compute_credits, 4),
                        usage_unit="credits",
                        metadata={
                            "source": "ACCOUNT_USAGE.METERING_DAILY_HISTORY",
                            "service_type": stype,
                            "credit_price_usd": credit_price,
                        },
                    )
                )
            if net_cloud_credits > 0:
                rows.append(
                    UnifiedCost(
                        date=_normalize_date(usage_date),
                        platform="snowflake",
                        service="snowflake_cloud_services",
                        resource=f"{stype.title().replace('_', ' ')} (cloud services)",
                        category=CostCategory.compute,
                        cost_usd=round(net_cloud_credits * credit_price, 4),
                        usage_quantity=round(net_cloud_credits, 4),
                        usage_unit="credits",
                        metadata={
                            "source": "ACCOUNT_USAGE.METERING_DAILY_HISTORY",
                            "service_type": stype,
                            "gross_cloud_credits": cloud_credits,
                            "cloud_adjustment": cloud_adj,
                            "credit_price_usd": credit_price,
                        },
                    )
                )
        return rows

    def _fetch_warehouse_metering(self, cur, days: int) -> list[UnifiedCost]:
        """Last-resort compute path: WAREHOUSE_METERING_HISTORY.

        Used when METERING_DAILY_HISTORY cannot be read (newer account_usage
        view that some shared-tenant accounts have limited visibility into).
        """
        sql = f"""
            SELECT
                TO_CHAR(START_TIME, 'YYYY-MM-DD') AS D,
                WAREHOUSE_NAME,
                WAREHOUSE_SIZE,
                SUM(CREDITS_USED_COMPUTE) AS CREDITS_COMPUTE,
                SUM(CREDITS_USED_CLOUD_SERVICES) AS CREDITS_CLOUD
            FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
            WHERE START_TIME >= DATEADD(day, -{int(days)}, CURRENT_TIMESTAMP())
            GROUP BY 1, 2, 3
            ORDER BY 1
        """
        try:
            cur.execute(sql)
        except Exception as e:  # noqa: BLE001
            if _classify_error(e):
                self.warnings.append(
                    str(SnowflakePermissionError(
                        "SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY",
                        self.conn_doc.get("role", ""),
                        e,
                    ))
                )
                return []
            self.warnings.append(f"WAREHOUSE_METERING_HISTORY query failed: {e}")
            return []

        rows: list[UnifiedCost] = []
        for row in _fetchall(cur):
            d, warehouse, wh_size, credits_compute, credits_cloud = row
            compute = float(credits_compute or 0)
            cloud = float(credits_cloud or 0)
            credit_price = self.pricing.credit_price_for_warehouse(wh_size)
            if compute > 0:
                rows.append(
                    UnifiedCost(
                        date=_normalize_date(d),
                        platform="snowflake",
                        service="snowflake_compute",
                        resource=str(warehouse),
                        category=CostCategory.compute,
                        cost_usd=round(compute * credit_price, 4),
                        usage_quantity=round(compute, 4),
                        usage_unit="credits",
                        metadata={
                            "source": "ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY",
                            "warehouse_size": wh_size,
                            "credit_price_usd": credit_price,
                        },
                    )
                )
            if cloud > 0:
                rows.append(
                    UnifiedCost(
                        date=_normalize_date(d),
                        platform="snowflake",
                        service="snowflake_cloud_services",
                        resource=str(warehouse),
                        category=CostCategory.compute,
                        cost_usd=round(cloud * credit_price, 4),
                        usage_quantity=round(cloud, 4),
                        usage_unit="credits",
                        metadata={
                            "source": "ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY",
                            "warehouse_size": wh_size,
                            "credit_price_usd": credit_price,
                            "note": "cloud services gross (10% allowance not deducted)",
                        },
                    )
                )
        return rows

    # ----- Serverless credit lines ------------------------------------------
    _SERVERLESS_QUERIES: tuple[tuple[str, str, str, str, str], ...] = (
        # (view, date_col, resource_col, service_type, credits_col)
        (
            "SNOWFLAKE.ACCOUNT_USAGE.SERVERLESS_TASK_HISTORY",
            "START_TIME",
            "TASK_NAME",
            "SERVERLESS_TASK",
            "CREDITS_USED",
        ),
        (
            "SNOWFLAKE.ACCOUNT_USAGE.PIPE_USAGE_HISTORY",
            "START_TIME",
            "PIPE_NAME",
            "SNOWPIPE",
            "CREDITS_USED",
        ),
        (
            "SNOWFLAKE.ACCOUNT_USAGE.AUTOMATIC_CLUSTERING_HISTORY",
            "START_TIME",
            "TABLE_NAME",
            "AUTO_CLUSTERING",
            "CREDITS_USED",
        ),
        (
            "SNOWFLAKE.ACCOUNT_USAGE.MATERIALIZED_VIEW_REFRESH_HISTORY",
            "START_TIME",
            "TABLE_NAME",
            "MATERIALIZED_VIEW",
            "CREDITS_USED",
        ),
        (
            "SNOWFLAKE.ACCOUNT_USAGE.SEARCH_OPTIMIZATION_HISTORY",
            "START_TIME",
            "TABLE_NAME",
            "SEARCH_OPTIMIZATION",
            "CREDITS_USED",
        ),
        (
            "SNOWFLAKE.ACCOUNT_USAGE.REPLICATION_USAGE_HISTORY",
            "START_TIME",
            "DATABASE_NAME",
            "REPLICATION",
            "CREDITS_USED",
        ),
        (
            "SNOWFLAKE.ACCOUNT_USAGE.QUERY_ACCELERATION_HISTORY",
            "START_TIME",
            "WAREHOUSE_NAME",
            "QUERY_ACCELERATION",
            "CREDITS_USED",
        ),
        (
            "SNOWFLAKE.ACCOUNT_USAGE.SNOWPIPE_STREAMING_CLIENT_HISTORY",
            "START_TIME",
            "CLIENT_NAME",
            "SNOWPIPE_STREAMING",
            "CREDITS_USED",
        ),
        # Snowpark Container Services (SPCS). The view name is
        # SNOWPARK_CONTAINER_SERVICES_HISTORY on newer accounts.
        (
            "SNOWFLAKE.ACCOUNT_USAGE.SNOWPARK_CONTAINER_SERVICES_HISTORY",
            "START_TIME",
            "SERVICE_NAME",
            "SNOWPARK_CONTAINER_SERVICES",
            "CREDITS_USED",
        ),
        # Hybrid table requests (Unistore). Billed as serverless compute.
        (
            "SNOWFLAKE.ACCOUNT_USAGE.HYBRID_TABLE_USAGE_HISTORY",
            "START_TIME",
            "TABLE_NAME",
            "HYBRID_TABLE_REQUESTS",
            "CREDITS_USED",
        ),
    )

    def _fetch_serverless(self, cur, days: int) -> list[UnifiedCost]:
        """Query each serverless credit view.

        These are typically 15-30% of modern Snowflake bills and were entirely
        missing from the original connector.
        """
        rows: list[UnifiedCost] = []
        for view, date_col, resource_col, service_type, credits_col in self._SERVERLESS_QUERIES:
            rows.extend(
                self._fetch_serverless_view(
                    cur, days, view, date_col, resource_col, service_type, credits_col
                )
            )
        # Cortex AI services get their own helper because the schema differs.
        rows.extend(self._fetch_cortex(cur, days))
        return rows

    def _fetch_serverless_view(
        self,
        cur,
        days: int,
        view: str,
        date_col: str,
        resource_col: str,
        service_type: str,
        credits_col: str,
    ) -> list[UnifiedCost]:
        sql = f"""
            SELECT
                TO_CHAR({date_col}, 'YYYY-MM-DD') AS D,
                {resource_col} AS RES,
                SUM({credits_col}) AS C
            FROM {view}
            WHERE {date_col} >= DATEADD(day, -{int(days)}, CURRENT_TIMESTAMP())
            GROUP BY 1, 2
            ORDER BY 1
        """
        try:
            cur.execute(sql)
        except Exception as e:  # noqa: BLE001
            if _classify_error(e):
                self.warnings.append(
                    str(SnowflakePermissionError(view, self.conn_doc.get("role", ""), e))
                )
            else:
                self.warnings.append(f"{view} query failed: {e}")
            return []

        credit_price = self.pricing.credit_price_for_service_type(service_type)
        service_slug = SERVICE_TYPE_SLUG.get(service_type, "snowflake_" + service_type.lower())
        category = SERVICE_TYPE_CATEGORY.get(service_type, CostCategory.compute)

        rows: list[UnifiedCost] = []
        for row in _fetchall(cur):
            d, resource, credits = row
            c = float(credits or 0)
            if c <= 0:
                continue
            rows.append(
                UnifiedCost(
                    date=_normalize_date(d),
                    platform="snowflake",
                    service=service_slug,
                    resource=str(resource or service_type),
                    category=category,
                    cost_usd=round(c * credit_price, 4),
                    usage_quantity=round(c, 4),
                    usage_unit="credits",
                    metadata={
                        "source": view,
                        "service_type": service_type,
                        "credit_price_usd": credit_price,
                    },
                )
            )
        return rows

    def _fetch_cortex(self, cur, days: int) -> list[UnifiedCost]:
        """Cortex AI functions (COMPLETE, EMBED_TEXT, TRANSLATE, ...).

        Snowflake exposes both `CORTEX_FUNCTIONS_USAGE_HISTORY` (per-function
        token credits) and the newer `CORTEX_ANALYST_USAGE_HISTORY` (per-
        message credits). We try the modern name first, then fall back.
        """
        candidates = (
            (
                "SNOWFLAKE.ACCOUNT_USAGE.CORTEX_FUNCTIONS_USAGE_HISTORY",
                """
                    SELECT
                        TO_CHAR(START_TIME, 'YYYY-MM-DD') AS D,
                        FUNCTION_NAME AS RES,
                        SUM(TOKEN_CREDITS) AS C
                    FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_FUNCTIONS_USAGE_HISTORY
                    WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
                    GROUP BY 1, 2
                """,
            ),
            (
                "SNOWFLAKE.ACCOUNT_USAGE.CORTEX_ANALYST_USAGE_HISTORY",
                """
                    SELECT
                        TO_CHAR(START_TIME, 'YYYY-MM-DD') AS D,
                        'cortex_analyst' AS RES,
                        SUM(CREDITS_USED) AS C
                    FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_ANALYST_USAGE_HISTORY
                    WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
                    GROUP BY 1, 2
                """,
            ),
        )
        credit_price = self.pricing.credit_price_for_service_type("CORTEX")
        rows: list[UnifiedCost] = []
        found_any = False
        for view, sql_template in candidates:
            try:
                cur.execute(sql_template.format(days=int(days)))
            except Exception as e:  # noqa: BLE001
                if _classify_error(e):
                    self.warnings.append(
                        str(SnowflakePermissionError(view, self.conn_doc.get("role", ""), e))
                    )
                else:
                    self.warnings.append(f"{view} query failed: {e}")
                continue
            found_any = True
            for row in _fetchall(cur):
                d, resource, credits = row
                c = float(credits or 0)
                if c <= 0:
                    continue
                rows.append(
                    UnifiedCost(
                        date=_normalize_date(d),
                        platform="snowflake",
                        service="snowflake_cortex",
                        resource=str(resource or "cortex"),
                        category=CostCategory.ai_inference,
                        cost_usd=round(c * credit_price, 4),
                        usage_quantity=round(c, 4),
                        usage_unit="credits",
                        metadata={
                            "source": view,
                            "service_type": "CORTEX",
                            "credit_price_usd": credit_price,
                        },
                    )
                )
        if not found_any and not self.warnings:
            # No warnings recorded yet means the role may simply not have
            # Cortex enabled — that is not an error.
            logger.debug("no Cortex usage visible")
        return rows

    # ----- Attribution -------------------------------------------------------
    def _fetch_attribution(self, cur, days: int) -> list[UnifiedCost]:
        """Per-user / role / query-tag attribution.

        Powered by `QUERY_ATTRIBUTION_HISTORY`. Warehouse-level grouping
        alone hides 80% of the cost story — attribution tells us which
        human/service is driving spend.
        """
        sql = f"""
            SELECT
                TO_CHAR(START_TIME, 'YYYY-MM-DD') AS D,
                USER_NAME,
                ROLE_NAME,
                WAREHOUSE_NAME,
                NULLIF(QUERY_TAG, '') AS QUERY_TAG,
                SUM(CREDITS_ATTRIBUTED_COMPUTE) AS CREDITS
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_ATTRIBUTION_HISTORY
            WHERE START_TIME >= DATEADD(day, -{int(days)}, CURRENT_TIMESTAMP())
            GROUP BY 1, 2, 3, 4, 5
            HAVING CREDITS > 0
            ORDER BY 1
        """
        try:
            cur.execute(sql)
        except Exception as e:  # noqa: BLE001
            if _classify_error(e):
                self.warnings.append(
                    str(SnowflakePermissionError(
                        "SNOWFLAKE.ACCOUNT_USAGE.QUERY_ATTRIBUTION_HISTORY",
                        self.conn_doc.get("role", ""),
                        e,
                    ))
                )
            else:
                self.warnings.append(f"QUERY_ATTRIBUTION_HISTORY query failed: {e}")
            return []

        rows: list[UnifiedCost] = []
        for row in _fetchall(cur):
            d, user_name, role_name, warehouse, query_tag, credits = row
            c = float(credits or 0)
            if c <= 0:
                continue
            credit_price = self.pricing.credit_price_for_warehouse(None)
            rows.append(
                UnifiedCost(
                    date=_normalize_date(d),
                    platform="snowflake",
                    service="snowflake_attribution",
                    resource=str(warehouse or "unknown"),
                    category=CostCategory.compute,
                    cost_usd=round(c * credit_price, 4),
                    usage_quantity=round(c, 4),
                    usage_unit="credits",
                    team=role_name or None,
                    project=query_tag or None,
                    metadata={
                        "source": "ACCOUNT_USAGE.QUERY_ATTRIBUTION_HISTORY",
                        "user_name": user_name,
                        "role_name": role_name,
                        "query_tag": query_tag,
                        "credit_price_usd": credit_price,
                    },
                )
            )
        return rows

    # ----- Storage -----------------------------------------------------------
    def _fetch_storage(self, cur, days: int) -> list[UnifiedCost]:
        """Daily per-database storage with active vs time-travel vs failsafe
        split.

        Uses `DATABASE_STORAGE_USAGE_HISTORY` which has one row per database
        per day. Each row is expanded into up to three `UnifiedCost` records
        (active / time-travel / failsafe) so the dashboard can show the
        breakdown. Price per TB is read from the override config so capacity
        contracts can be honoured.
        """
        sql = f"""
            SELECT
                USAGE_DATE,
                DATABASE_NAME,
                AVG(AVERAGE_DATABASE_BYTES) AS ACTIVE_BYTES,
                AVG(AVERAGE_FAILSAFE_BYTES) AS FAILSAFE_BYTES
            FROM SNOWFLAKE.ACCOUNT_USAGE.DATABASE_STORAGE_USAGE_HISTORY
            WHERE USAGE_DATE >= DATEADD(day, -{int(days)}, CURRENT_DATE())
            GROUP BY 1, 2
            ORDER BY 1
        """
        try:
            cur.execute(sql)
        except Exception as e:  # noqa: BLE001
            if _classify_error(e):
                self.warnings.append(
                    str(SnowflakePermissionError(
                        "SNOWFLAKE.ACCOUNT_USAGE.DATABASE_STORAGE_USAGE_HISTORY",
                        self.conn_doc.get("role", ""),
                        e,
                    ))
                )
                # Try the legacy averaged STORAGE_USAGE view as a fallback
                # so we emit *something* for storage.
                return self._fetch_storage_legacy(cur, days)
            self.warnings.append(f"DATABASE_STORAGE_USAGE_HISTORY query failed: {e}")
            return self._fetch_storage_legacy(cur, days)

        rows: list[UnifiedCost] = []
        for row in _fetchall(cur):
            usage_date, database, active_bytes, failsafe_bytes = row
            active = float(active_bytes or 0)
            failsafe = float(failsafe_bytes or 0)
            d = _normalize_date(usage_date)
            active_tb = active / BYTES_PER_TB
            failsafe_tb = failsafe / BYTES_PER_TB
            # One day's share of the monthly rate.
            active_daily_price = self.pricing.active_storage_price_per_tb / 30.0
            failsafe_daily_price = self.pricing.failsafe_storage_price_per_tb / 30.0
            if active_tb > 0:
                rows.append(
                    UnifiedCost(
                        date=d,
                        platform="snowflake",
                        service="snowflake_storage",
                        resource=f"{database} (active)",
                        category=CostCategory.storage,
                        cost_usd=round(active_tb * active_daily_price, 4),
                        usage_quantity=round(active_tb * 1024, 4),  # GB
                        usage_unit="GB",
                        metadata={
                            "source": "ACCOUNT_USAGE.DATABASE_STORAGE_USAGE_HISTORY",
                            "database": database,
                            "tier": "active",
                            "price_per_tb_month": self.pricing.active_storage_price_per_tb,
                        },
                    )
                )
            if failsafe_tb > 0:
                rows.append(
                    UnifiedCost(
                        date=d,
                        platform="snowflake",
                        service="snowflake_storage",
                        resource=f"{database} (failsafe)",
                        category=CostCategory.storage,
                        cost_usd=round(failsafe_tb * failsafe_daily_price, 4),
                        usage_quantity=round(failsafe_tb * 1024, 4),
                        usage_unit="GB",
                        metadata={
                            "source": "ACCOUNT_USAGE.DATABASE_STORAGE_USAGE_HISTORY",
                            "database": database,
                            "tier": "failsafe",
                            "price_per_tb_month": self.pricing.failsafe_storage_price_per_tb,
                        },
                    )
                )
        # Also pull time-travel via TABLE_STORAGE_METRICS (it does not appear
        # in DATABASE_STORAGE_USAGE_HISTORY — only active + failsafe do).
        rows.extend(self._fetch_time_travel_storage(cur, days))
        return rows

    def _fetch_time_travel_storage(self, cur, days: int) -> list[UnifiedCost]:
        """Time-travel bytes come from TABLE_STORAGE_METRICS (not in
        DATABASE_STORAGE_USAGE_HISTORY). This runs as a one-shot snapshot
        reflecting current time-travel retention.
        """
        sql = """
            SELECT
                TABLE_CATALOG,
                SUM(TIME_TRAVEL_BYTES) AS TT_BYTES
            FROM SNOWFLAKE.ACCOUNT_USAGE.TABLE_STORAGE_METRICS
            WHERE NOT DELETED
            GROUP BY 1
            HAVING TT_BYTES > 0
        """
        try:
            cur.execute(sql)
        except Exception as e:  # noqa: BLE001
            if _classify_error(e):
                self.warnings.append(
                    str(SnowflakePermissionError(
                        "SNOWFLAKE.ACCOUNT_USAGE.TABLE_STORAGE_METRICS",
                        self.conn_doc.get("role", ""),
                        e,
                    ))
                )
            else:
                self.warnings.append(f"TABLE_STORAGE_METRICS query failed: {e}")
            return []

        # Time-travel is a snapshot, not daily. Book it to today and
        # apportion by 1/30 so it lines up with active / failsafe's
        # per-day treatment.
        today = _today_iso()
        rows: list[UnifiedCost] = []
        daily_price = self.pricing.timetravel_storage_price_per_tb / 30.0
        for row in _fetchall(cur):
            database, bytes_ = row
            tb = float(bytes_ or 0) / BYTES_PER_TB
            if tb <= 0:
                continue
            rows.append(
                UnifiedCost(
                    date=today,
                    platform="snowflake",
                    service="snowflake_storage",
                    resource=f"{database} (time-travel)",
                    category=CostCategory.storage,
                    cost_usd=round(tb * daily_price, 4),
                    usage_quantity=round(tb * 1024, 4),
                    usage_unit="GB",
                    metadata={
                        "source": "ACCOUNT_USAGE.TABLE_STORAGE_METRICS",
                        "database": database,
                        "tier": "time_travel",
                        "price_per_tb_month": self.pricing.timetravel_storage_price_per_tb,
                        "note": "snapshot (current retention, not daily history)",
                    },
                )
            )
        return rows

    def _fetch_storage_legacy(self, cur, days: int) -> list[UnifiedCost]:
        """Last-resort storage path when DATABASE_STORAGE_USAGE_HISTORY is
        not readable. Pulls the account-wide STORAGE_USAGE average for the
        most recent day and books it as active storage for today. Emits a
        warning so operators know daily trend is unavailable.
        """
        try:
            cur.execute(
                """
                SELECT
                    AVERAGE_DATABASE_BYTES,
                    AVERAGE_FAILSAFE_BYTES,
                    USAGE_DATE
                FROM SNOWFLAKE.ACCOUNT_USAGE.STORAGE_USAGE
                ORDER BY USAGE_DATE DESC
                LIMIT 1
                """
            )
        except Exception as e:  # noqa: BLE001
            if _classify_error(e):
                self.warnings.append(
                    str(SnowflakePermissionError(
                        "SNOWFLAKE.ACCOUNT_USAGE.STORAGE_USAGE",
                        self.conn_doc.get("role", ""),
                        e,
                    ))
                )
            else:
                self.warnings.append(f"STORAGE_USAGE query failed: {e}")
            return []

        row = cur.fetchone()
        if not row:
            return []
        active_bytes, failsafe_bytes, usage_date = row
        rows: list[UnifiedCost] = []
        today = _normalize_date(usage_date) if usage_date else _today_iso()
        active_tb = float(active_bytes or 0) / BYTES_PER_TB
        failsafe_tb = float(failsafe_bytes or 0) / BYTES_PER_TB
        active_daily_price = self.pricing.active_storage_price_per_tb / 30.0
        failsafe_daily_price = self.pricing.failsafe_storage_price_per_tb / 30.0
        if active_tb > 0:
            rows.append(
                UnifiedCost(
                    date=today,
                    platform="snowflake",
                    service="snowflake_storage",
                    resource="Account Storage (active)",
                    category=CostCategory.storage,
                    cost_usd=round(active_tb * active_daily_price, 4),
                    usage_quantity=round(active_tb * 1024, 4),
                    usage_unit="GB",
                    metadata={
                        "source": "ACCOUNT_USAGE.STORAGE_USAGE",
                        "tier": "active",
                        "note": "daily trend unavailable — averaged snapshot",
                    },
                )
            )
        if failsafe_tb > 0:
            rows.append(
                UnifiedCost(
                    date=today,
                    platform="snowflake",
                    service="snowflake_storage",
                    resource="Account Storage (failsafe)",
                    category=CostCategory.storage,
                    cost_usd=round(failsafe_tb * failsafe_daily_price, 4),
                    usage_quantity=round(failsafe_tb * 1024, 4),
                    usage_unit="GB",
                    metadata={
                        "source": "ACCOUNT_USAGE.STORAGE_USAGE",
                        "tier": "failsafe",
                        "note": "daily trend unavailable — averaged snapshot",
                    },
                )
            )
        return rows


__all__ = [
    "SnowflakeConnector",
    "SnowflakePermissionError",
    "PricingConfig",
    "DEFAULT_CREDIT_PRICE_USD",
    "DEFAULT_ACTIVE_STORAGE_PRICE_PER_TB",
    "SERVICE_TYPE_CATEGORY",
    "SERVICE_TYPE_SLUG",
]
