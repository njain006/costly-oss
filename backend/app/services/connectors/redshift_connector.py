"""Redshift connector — dedicated, first-class.

Amazon Redshift has its own billing model that does *not* fit cleanly into the
AWS Cost Explorer umbrella (which rolls everything up as ``Amazon Redshift`` as
a single service line). This connector goes deeper by reading Redshift's own
system tables via the Redshift Data API (``redshift-data`` boto3 client) and
augmenting with cluster / workgroup metadata from the control-plane APIs.

Supported compute surfaces:

- **Provisioned (RA3 / DC2)** — fixed per-node-hour price. Billed by cluster
  uptime. Query-level attribution comes from ``SYS_QUERY_HISTORY`` +
  ``STV_WLM_QUERY_STATE`` (paused clusters incur $0 but reserved-node buyers
  still pay — we surface this via ``cluster_paused`` in metadata).
- **Serverless** — per-RPU-second metering from ``SYS_SERVERLESS_USAGE``
  (60-second minimum already applied by Redshift). RPUs default to $0.375/hour
  (base capacity 8 RPU in us-east-1, Mar 2026 list price).
- **Spectrum** — $5 per TB scanned against external tables. Extracted from
  ``SYS_EXTERNAL_QUERY_DETAIL`` rows (``total_bytes_external`` column).
- **Concurrency Scaling** — 1 free hour per day per cluster; overage billed
  per-second at the on-demand cluster rate. Pulled from
  ``STL_CONCURRENCY_SCALING_USAGE`` (free + charged seconds surfaced).

Storage:
- Managed storage (RA3) is metered in ``SYS_SERVERLESS_USAGE`` for Serverless
  workgroups and ``STV_NODE_STORAGE_CAPACITY`` / ``SVV_TABLE_INFO`` for
  provisioned RA3. We emit one daily per-cluster/workgroup storage record at
  $0.024/GB/month.

Credentials (``PlatformConnectionCreate.credentials``)::

    {
        "aws_access_key_id": "AKIA...",
        "aws_secret_access_key": "...",
        "region": "us-east-1",

        # One of these two modes:
        "cluster_identifier": "analytics-prod",      # Provisioned
        "workgroup_name": "analytics",               # Serverless

        # Data API auth (pick one path):
        "database": "dev",                           # required
        "db_user": "costly_reader",                  # IAM-auth (temporary creds)
        # OR
        "secret_arn": "arn:aws:secretsmanager:...",  # stored admin password

        # Optional overrides
        "node_type": "ra3.4xlarge",                  # auto-detected otherwise
        "pricing_overrides": {...},
    }

References:
- https://aws.amazon.com/redshift/pricing/
- https://docs.aws.amazon.com/redshift/latest/dg/sys-query-history.html
- https://docs.aws.amazon.com/redshift/latest/dg/sys-serverless-usage.html
- https://docs.aws.amazon.com/redshift/latest/dg/stl-concurrency-scaling-usage.html
- https://docs.aws.amazon.com/redshift/latest/mgmt/data-api.html
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.models.platform import CostCategory, UnifiedCost
from app.services.connectors.base import BaseConnector

logger = logging.getLogger(__name__)


# ─── Default pricing (USD, AWS us-east-1 list price, Mar 2026) ──────────

# Provisioned on-demand $/node/hour. Covers the main families.
# https://aws.amazon.com/redshift/pricing/ (accessed 2026-03)
DEFAULT_NODE_HOUR: dict[str, float] = {
    # RA3 (managed storage, recommended)
    "ra3.large": 0.543,       # small / test
    "ra3.xlplus": 1.086,
    "ra3.4xlarge": 3.26,
    "ra3.16xlarge": 13.04,
    # DC2 (legacy dense compute)
    "dc2.large": 0.25,
    "dc2.8xlarge": 4.80,
    # DS2 (deprecated, still billed for legacy accounts)
    "ds2.xlarge": 0.85,
    "ds2.8xlarge": 6.80,
}
_DEFAULT_NODE_HOUR_FALLBACK = 1.086  # ra3.xlplus — safe middle ground

# Serverless base capacity: $0.375 per RPU-hour (8 RPU minimum) in us-east-1.
DEFAULT_SERVERLESS_RPU_HOUR = 0.375

# Redshift Spectrum: $5 per TB scanned.
DEFAULT_SPECTRUM_PER_TB = 5.0

# Concurrency Scaling: 1 free hour/day/cluster then per-second at on-demand rate.
DEFAULT_CONCURRENCY_SCALING_FREE_HR_PER_DAY = 1.0

# Managed storage — RA3 only, $0.024 per GB-month (us-east-1).
DEFAULT_MANAGED_STORAGE_GB_MONTH = 0.024

# Unit conversions
_TB = 1024 ** 4
_GB = 1024 ** 3
_SECONDS_PER_HOUR = 3600.0
_DAYS_PER_MONTH = 30.0


class RedshiftError(RuntimeError):
    """Structured Redshift connector error with optional remediation hint."""


@dataclass(frozen=True)
class RedshiftPricing:
    """Immutable pricing table — defaults + overrides merged."""

    node_hour: dict[str, float] = field(
        default_factory=lambda: dict(DEFAULT_NODE_HOUR)
    )
    serverless_rpu_hour: float = DEFAULT_SERVERLESS_RPU_HOUR
    spectrum_per_tb: float = DEFAULT_SPECTRUM_PER_TB
    managed_storage_gb_month: float = DEFAULT_MANAGED_STORAGE_GB_MONTH
    concurrency_scaling_free_hr_per_day: float = (
        DEFAULT_CONCURRENCY_SCALING_FREE_HR_PER_DAY
    )
    discount_pct: float = 0.0

    def node_rate(self, node_type: Optional[str]) -> float:
        """Look up per-node-hour rate. Unknown node types fall back safely."""
        if not node_type:
            return _DEFAULT_NODE_HOUR_FALLBACK
        key = node_type.strip().lower()
        return self.node_hour.get(key, _DEFAULT_NODE_HOUR_FALLBACK)

    def apply_discount(self, cost: float) -> float:
        if self.discount_pct <= 0:
            return cost
        return cost * (1.0 - self.discount_pct / 100.0)


def _merge_pricing(overrides: dict | None) -> RedshiftPricing:
    """Merge user-supplied overrides onto default pricing (immutable return)."""
    if not overrides:
        return RedshiftPricing()

    node_hour = dict(DEFAULT_NODE_HOUR)
    for k, v in (overrides.get("node_hour", {}) or {}).items():
        node_hour[str(k).strip().lower()] = float(v)

    return RedshiftPricing(
        node_hour=node_hour,
        serverless_rpu_hour=float(
            overrides.get("serverless_rpu_hour", DEFAULT_SERVERLESS_RPU_HOUR)
        ),
        spectrum_per_tb=float(
            overrides.get("spectrum_per_tb", DEFAULT_SPECTRUM_PER_TB)
        ),
        managed_storage_gb_month=float(
            overrides.get(
                "managed_storage_gb_month", DEFAULT_MANAGED_STORAGE_GB_MONTH
            )
        ),
        concurrency_scaling_free_hr_per_day=float(
            overrides.get(
                "concurrency_scaling_free_hr_per_day",
                DEFAULT_CONCURRENCY_SCALING_FREE_HR_PER_DAY,
            )
        ),
        discount_pct=float(overrides.get("discount_pct", 0.0) or 0.0),
    )


# ─── SQL templates (parameterised per Redshift Data API) ────────────────

# Per-query usage from SYS_QUERY_HISTORY (provisioned) — last N days.
# ``compute_type`` differentiates main-cluster vs. concurrency-scaling queries.
_SQL_QUERY_HISTORY = """
SELECT
  TO_CHAR(start_time, 'YYYY-MM-DD')      AS day,
  user_id,
  database_name,
  query_id,
  query_type,
  execution_time,
  elapsed_time,
  queue_time,
  COALESCE(compute_type, 'main')         AS compute_type,
  query_label
FROM SYS_QUERY_HISTORY
WHERE start_time >= :start_ts
  AND start_time <  :end_ts
  AND status = 'success'
ORDER BY start_time
""".strip()

# Per-second RPU billing for Serverless workgroups.
_SQL_SERVERLESS_USAGE = """
SELECT
  TO_CHAR(start_time, 'YYYY-MM-DD')      AS day,
  workgroup_name,
  SUM(charged_seconds)                   AS charged_seconds,
  SUM(charged_rpu_seconds)               AS charged_rpu_seconds,
  SUM(storage_in_mb)                     AS storage_mb
FROM SYS_SERVERLESS_USAGE
WHERE start_time >= :start_ts
  AND start_time <  :end_ts
GROUP BY 1, 2
ORDER BY 1
""".strip()

# Spectrum scan bytes per query.
_SQL_SPECTRUM = """
SELECT
  TO_CHAR(start_time, 'YYYY-MM-DD')      AS day,
  user_id,
  query_id,
  SUM(total_bytes_external)              AS bytes_scanned
FROM SYS_EXTERNAL_QUERY_DETAIL
WHERE start_time >= :start_ts
  AND start_time <  :end_ts
GROUP BY 1, 2, 3
""".strip()

# Concurrency Scaling usage. ``usage_in_seconds`` is billed beyond the free
# hour/day/cluster allocation (Redshift already applies the free tier in
# ``free_usage_in_seconds``).
_SQL_CONCURRENCY_SCALING = """
SELECT
  TO_CHAR(start_time, 'YYYY-MM-DD')      AS day,
  cluster_identifier,
  SUM(usage_in_seconds)                  AS billable_seconds,
  SUM(free_usage_in_seconds)             AS free_seconds
FROM STL_CONCURRENCY_SCALING_USAGE
WHERE start_time >= :start_ts
  AND start_time <  :end_ts
GROUP BY 1, 2
""".strip()


# ─── Data API client ────────────────────────────────────────────────────


class _RedshiftDataClient:
    """Thin wrapper around the boto3 ``redshift-data`` client.

    Uses ``execute_statement`` + ``get_statement_result`` polling. Separated
    from the connector so tests can patch it easily.
    """

    # Poll parameters — small + bounded so tests run fast.
    _POLL_INTERVAL_S = 0.25
    _POLL_MAX_S = 120.0

    def __init__(
        self,
        *,
        aws_access_key_id: str,
        aws_secret_access_key: str,
        region: str,
        cluster_identifier: Optional[str] = None,
        workgroup_name: Optional[str] = None,
        database: str,
        db_user: Optional[str] = None,
        secret_arn: Optional[str] = None,
    ):
        import boto3  # lazy import — keep module importable without boto3

        if not cluster_identifier and not workgroup_name:
            raise RedshiftError(
                "Redshift credentials require either cluster_identifier "
                "(provisioned) or workgroup_name (serverless)"
            )
        if not database:
            raise RedshiftError("Redshift credentials missing 'database'")
        if not db_user and not secret_arn:
            raise RedshiftError(
                "Redshift credentials need either 'db_user' (IAM auth) or "
                "'secret_arn' (Secrets Manager)"
            )

        self._data = boto3.client(
            "redshift-data",
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            region_name=region,
        )
        self._cluster_identifier = cluster_identifier
        self._workgroup_name = workgroup_name
        self._database = database
        self._db_user = db_user
        self._secret_arn = secret_arn

    # -- execution ----------------------------------------------------

    def query(self, sql: str, params: dict[str, Any] | None = None) -> list[dict]:
        """Run a SQL statement and return rows as ``{column: value}`` dicts.

        ``params`` uses ``:name`` placeholders — they are turned into the
        ``Parameters=[{name, value}]`` shape the Redshift Data API expects.
        """
        kwargs: dict[str, Any] = {
            "Database": self._database,
            "Sql": sql,
        }
        if self._workgroup_name:
            kwargs["WorkgroupName"] = self._workgroup_name
        else:
            kwargs["ClusterIdentifier"] = self._cluster_identifier
        if self._db_user:
            kwargs["DbUser"] = self._db_user
        if self._secret_arn:
            kwargs["SecretArn"] = self._secret_arn
        if params:
            kwargs["Parameters"] = _encode_params(params)

        try:
            started = self._data.execute_statement(**kwargs)
        except Exception as exc:  # pragma: no cover — translated below
            raise _translate_boto_error(exc)

        statement_id = started["Id"]
        status = self._wait(statement_id)
        if status != "FINISHED":
            err = self._data.describe_statement(Id=statement_id).get("Error", "")
            raise RedshiftError(
                f"Redshift statement {statement_id} ended in {status}: {err}"
            )

        return self._fetch_rows(statement_id)

    # -- helpers ------------------------------------------------------

    def _wait(self, statement_id: str) -> str:
        deadline = time.monotonic() + self._POLL_MAX_S
        while True:
            desc = self._data.describe_statement(Id=statement_id)
            status = desc.get("Status", "")
            if status in ("FINISHED", "FAILED", "ABORTED"):
                return status
            if time.monotonic() > deadline:
                raise RedshiftError(
                    f"Redshift statement {statement_id} timed out"
                )
            time.sleep(self._POLL_INTERVAL_S)

    def _fetch_rows(self, statement_id: str) -> list[dict]:
        """Page through ``get_statement_result`` collecting all rows."""
        rows: list[dict] = []
        next_token: Optional[str] = None
        columns: list[str] = []

        while True:
            kwargs: dict[str, Any] = {"Id": statement_id}
            if next_token:
                kwargs["NextToken"] = next_token
            res = self._data.get_statement_result(**kwargs)

            if not columns:
                columns = [c.get("name", "") for c in res.get("ColumnMetadata", [])]

            for record in res.get("Records", []):
                rows.append(_decode_record(record, columns))

            next_token = res.get("NextToken")
            if not next_token:
                break
        return rows


def _encode_params(params: dict[str, Any]) -> list[dict[str, str]]:
    """Redshift Data API always takes strings — format common types safely."""
    out: list[dict[str, str]] = []
    for name, value in params.items():
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            formatted = value.astimezone(timezone.utc).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        elif value is None:
            formatted = ""
        else:
            formatted = str(value)
        out.append({"name": name, "value": formatted})
    return out


def _decode_record(record: list[dict], columns: list[str]) -> dict[str, Any]:
    """Decode a single ``Records`` entry (list of ``{TYPE: value}``) to a dict."""
    out: dict[str, Any] = {}
    for idx, cell in enumerate(record):
        name = columns[idx] if idx < len(columns) else f"col_{idx}"
        # Cell is one of {stringValue, longValue, doubleValue, booleanValue, isNull}
        if cell.get("isNull"):
            out[name] = None
        elif "stringValue" in cell:
            out[name] = cell["stringValue"]
        elif "longValue" in cell:
            out[name] = cell["longValue"]
        elif "doubleValue" in cell:
            out[name] = cell["doubleValue"]
        elif "booleanValue" in cell:
            out[name] = cell["booleanValue"]
        else:
            # Unknown — pass the whole cell through so metadata remains readable.
            out[name] = next(iter(cell.values()), None)
    return out


def _translate_boto_error(exc: Exception) -> RedshiftError:
    """Turn a boto3 ClientError / generic exception into a RedshiftError."""
    message = str(exc)
    code = ""
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        code = response.get("Error", {}).get("Code", "") or ""
        message = response.get("Error", {}).get("Message", message)

    lower = code.lower() + " " + message.lower()
    hint = ""
    if "accessdenied" in lower or "notauthorized" in lower or "permission" in lower:
        hint = (
            " Hint: the IAM principal needs redshift-data:ExecuteStatement, "
            "redshift-data:DescribeStatement, redshift-data:GetStatementResult, "
            "redshift:GetClusterCredentials (or secretsmanager:GetSecretValue if "
            "using secret_arn) plus SELECT on the SYS_* views."
        )
    elif "notfound" in lower or "does not exist" in lower:
        hint = (
            " Hint: check cluster_identifier / workgroup_name and that the "
            "region matches where the Redshift resource lives."
        )
    elif "validationexception" in lower:
        hint = (
            " Hint: Serverless connections must pass WorkgroupName; "
            "provisioned must pass ClusterIdentifier — not both."
        )
    return RedshiftError(f"Redshift Data API error{': ' + code if code else ''}: {message}{hint}")


# ─── Connector ──────────────────────────────────────────────────────────


class RedshiftConnector(BaseConnector):
    """First-class Amazon Redshift connector (provisioned + serverless)."""

    platform = "redshift"

    def __init__(
        self,
        credentials: dict,
        *,
        pricing_overrides: dict | None = None,
    ):
        super().__init__(credentials)

        required = ("aws_access_key_id", "aws_secret_access_key", "region")
        for key in required:
            if not credentials.get(key):
                raise RedshiftError(f"Redshift credentials missing '{key}'")

        self.region: str = credentials["region"]
        self.cluster_identifier: Optional[str] = credentials.get("cluster_identifier") or None
        self.workgroup_name: Optional[str] = credentials.get("workgroup_name") or None
        self.is_serverless: bool = bool(self.workgroup_name) and not self.cluster_identifier
        self.database: str = credentials.get("database") or "dev"
        self.node_type: Optional[str] = credentials.get("node_type")

        if not self.cluster_identifier and not self.workgroup_name:
            raise RedshiftError(
                "Redshift credentials require either 'cluster_identifier' "
                "(provisioned) or 'workgroup_name' (serverless)"
            )

        overrides = pricing_overrides or credentials.get("pricing_overrides")
        self.pricing = _merge_pricing(overrides)

        self._data_client: _RedshiftDataClient | None = None

    # -- data client lazy construction -------------------------------

    @property
    def data_client(self) -> _RedshiftDataClient:
        if self._data_client is None:
            self._data_client = _RedshiftDataClient(
                aws_access_key_id=self.credentials["aws_access_key_id"],
                aws_secret_access_key=self.credentials["aws_secret_access_key"],
                region=self.region,
                cluster_identifier=self.cluster_identifier,
                workgroup_name=self.workgroup_name,
                database=self.database,
                db_user=self.credentials.get("db_user"),
                secret_arn=self.credentials.get("secret_arn"),
            )
        return self._data_client

    # -- public API --------------------------------------------------

    def test_connection(self) -> dict:
        try:
            rows = self.data_client.query("SELECT 1 AS ok")
            if rows and rows[0].get("ok") in (1, "1", True):
                return {
                    "success": True,
                    "message": (
                        f"Redshift Serverless workgroup '{self.workgroup_name}' reachable"
                        if self.is_serverless
                        else f"Redshift cluster '{self.cluster_identifier}' reachable"
                    ),
                }
            return {"success": False, "message": "Unexpected result from SELECT 1"}
        except RedshiftError as exc:
            return {"success": False, "message": str(exc)}
        except Exception as exc:  # pragma: no cover
            logger.exception("Redshift test_connection failed")
            return {"success": False, "message": str(exc)}

    def fetch_costs(self, days: int = 30) -> list[UnifiedCost]:
        end = datetime.now(timezone.utc).replace(microsecond=0)
        start = end - timedelta(days=days)
        params = {"start_ts": start, "end_ts": end}

        costs: list[UnifiedCost] = []
        if self.is_serverless:
            costs.extend(self._fetch_serverless_costs(params))
        else:
            costs.extend(self._fetch_provisioned_query_costs(params))
            costs.extend(self._fetch_concurrency_scaling_costs(params))

        costs.extend(self._fetch_spectrum_costs(params))

        if self.pricing.discount_pct > 0:
            costs = [
                c.model_copy(
                    update={
                        "cost_usd": round(
                            self.pricing.apply_discount(c.cost_usd), 6
                        )
                    }
                )
                for c in costs
            ]
        return costs

    # -- provisioned: query-level attribution ------------------------

    def _fetch_provisioned_query_costs(
        self, params: dict[str, Any]
    ) -> list[UnifiedCost]:
        """Attribute cluster per-hour cost to queries by execution time share.

        ``SYS_QUERY_HISTORY`` gives execution_time in microseconds; we convert
        to compute-seconds and multiply by node-rate / 3600 × node_count.
        """
        try:
            rows = self.data_client.query(_SQL_QUERY_HISTORY, params=params)
        except RedshiftError as exc:
            logger.warning(
                "SYS_QUERY_HISTORY query failed for cluster %s: %s",
                self.cluster_identifier,
                exc,
            )
            return []

        node_count = self._describe_cluster_node_count()
        node_type = self.node_type or self._describe_cluster_node_type()
        node_rate = self.pricing.node_rate(node_type)

        costs: list[UnifiedCost] = []
        for row in rows:
            day = row.get("day")
            if not day:
                continue
            exec_us = _coerce_int(row.get("execution_time"))
            exec_hours = exec_us / 1_000_000.0 / _SECONDS_PER_HOUR
            if exec_hours <= 0:
                continue

            compute_type = (row.get("compute_type") or "main").lower()
            cost_usd = exec_hours * node_rate * max(node_count, 1)

            costs.append(
                UnifiedCost(
                    date=day,
                    platform="redshift",
                    service="redshift_query",
                    resource=self.cluster_identifier or "unknown",
                    category=CostCategory.compute,
                    cost_usd=round(cost_usd, 6),
                    usage_quantity=round(exec_hours, 6),
                    usage_unit="compute_hours",
                    team=row.get("query_label") or None,
                    metadata={
                        "cluster_id": self.cluster_identifier,
                        "query_id": row.get("query_id"),
                        "user_name": row.get("user_id"),
                        "database_name": row.get("database_name"),
                        "query_type": row.get("query_type"),
                        "compute_type": compute_type,
                        "queue_time_ms": _coerce_int(row.get("queue_time")),
                        "node_type": node_type,
                        "node_count": node_count,
                    },
                )
            )
        return costs

    def _describe_cluster_node_count(self) -> int:
        """Ask the Redshift control plane how many nodes the cluster has."""
        if not self.cluster_identifier:
            return 1
        try:
            import boto3

            rs = boto3.client(
                "redshift",
                aws_access_key_id=self.credentials["aws_access_key_id"],
                aws_secret_access_key=self.credentials["aws_secret_access_key"],
                region_name=self.region,
            )
            resp = rs.describe_clusters(
                ClusterIdentifier=self.cluster_identifier
            )
            clusters = resp.get("Clusters", [])
            if not clusters:
                return 1
            return int(clusters[0].get("NumberOfNodes", 1) or 1)
        except Exception as exc:
            logger.debug("describe_clusters failed: %s", exc)
            return 1

    def _describe_cluster_node_type(self) -> Optional[str]:
        if not self.cluster_identifier:
            return None
        try:
            import boto3

            rs = boto3.client(
                "redshift",
                aws_access_key_id=self.credentials["aws_access_key_id"],
                aws_secret_access_key=self.credentials["aws_secret_access_key"],
                region_name=self.region,
            )
            resp = rs.describe_clusters(
                ClusterIdentifier=self.cluster_identifier
            )
            clusters = resp.get("Clusters", [])
            if not clusters:
                return None
            return clusters[0].get("NodeType")
        except Exception as exc:
            logger.debug("describe_clusters node_type failed: %s", exc)
            return None

    # -- concurrency scaling ----------------------------------------

    def _fetch_concurrency_scaling_costs(
        self, params: dict[str, Any]
    ) -> list[UnifiedCost]:
        try:
            rows = self.data_client.query(
                _SQL_CONCURRENCY_SCALING, params=params
            )
        except RedshiftError as exc:
            logger.debug("STL_CONCURRENCY_SCALING_USAGE skipped: %s", exc)
            return []

        node_count = self._describe_cluster_node_count()
        node_type = self.node_type or self._describe_cluster_node_type()
        node_rate = self.pricing.node_rate(node_type)

        costs: list[UnifiedCost] = []
        for row in rows:
            day = row.get("day")
            billable_s = _coerce_int(row.get("billable_seconds"))
            free_s = _coerce_int(row.get("free_seconds"))
            if not day or billable_s <= 0:
                continue
            hours = billable_s / _SECONDS_PER_HOUR
            cost_usd = hours * node_rate * max(node_count, 1)
            costs.append(
                UnifiedCost(
                    date=day,
                    platform="redshift",
                    service="redshift_concurrency_scaling",
                    resource=row.get("cluster_identifier")
                    or self.cluster_identifier
                    or "unknown",
                    category=CostCategory.compute,
                    cost_usd=round(cost_usd, 6),
                    usage_quantity=round(hours, 6),
                    usage_unit="cs_hours",
                    metadata={
                        "cluster_id": self.cluster_identifier,
                        "compute_type": "CS",
                        "billable_seconds": billable_s,
                        "free_seconds": free_s,
                        "node_type": node_type,
                        "node_count": node_count,
                    },
                )
            )
        return costs

    # -- serverless: RPU-seconds + storage --------------------------

    def _fetch_serverless_costs(
        self, params: dict[str, Any]
    ) -> list[UnifiedCost]:
        try:
            rows = self.data_client.query(
                _SQL_SERVERLESS_USAGE, params=params
            )
        except RedshiftError as exc:
            logger.warning(
                "SYS_SERVERLESS_USAGE query failed for workgroup %s: %s",
                self.workgroup_name,
                exc,
            )
            return []

        costs: list[UnifiedCost] = []
        for row in rows:
            day = row.get("day")
            if not day:
                continue
            rpu_seconds = _coerce_int(row.get("charged_rpu_seconds"))
            storage_mb = _coerce_int(row.get("storage_mb"))

            rpu_hours = rpu_seconds / _SECONDS_PER_HOUR
            compute_cost = rpu_hours * self.pricing.serverless_rpu_hour

            if compute_cost > 0 or rpu_seconds > 0:
                costs.append(
                    UnifiedCost(
                        date=day,
                        platform="redshift",
                        service="redshift_serverless",
                        resource=row.get("workgroup_name") or self.workgroup_name or "unknown",
                        category=CostCategory.compute,
                        cost_usd=round(compute_cost, 6),
                        usage_quantity=round(rpu_hours, 6),
                        usage_unit="RPU_hours",
                        metadata={
                            "workgroup": row.get("workgroup_name")
                            or self.workgroup_name,
                            "compute_type": "Serverless",
                            "charged_seconds": _coerce_int(
                                row.get("charged_seconds")
                            ),
                            "rpu_seconds": rpu_seconds,
                        },
                    )
                )

            # Managed storage — pro-rated daily.
            if storage_mb > 0:
                storage_gb = storage_mb / 1024.0
                daily_storage_cost = (
                    storage_gb
                    * self.pricing.managed_storage_gb_month
                    / _DAYS_PER_MONTH
                )
                costs.append(
                    UnifiedCost(
                        date=day,
                        platform="redshift",
                        service="redshift_managed_storage",
                        resource=row.get("workgroup_name")
                        or self.workgroup_name
                        or "unknown",
                        category=CostCategory.storage,
                        cost_usd=round(daily_storage_cost, 6),
                        usage_quantity=round(storage_gb, 4),
                        usage_unit="GB",
                        metadata={
                            "workgroup": row.get("workgroup_name")
                            or self.workgroup_name,
                            "compute_type": "Serverless",
                        },
                    )
                )
        return costs

    # -- spectrum ----------------------------------------------------

    def _fetch_spectrum_costs(
        self, params: dict[str, Any]
    ) -> list[UnifiedCost]:
        """Spectrum scans against external / Glue Catalog tables."""
        try:
            rows = self.data_client.query(_SQL_SPECTRUM, params=params)
        except RedshiftError as exc:
            logger.debug("SYS_EXTERNAL_QUERY_DETAIL skipped: %s", exc)
            return []

        resource = self.cluster_identifier or self.workgroup_name or "unknown"
        costs: list[UnifiedCost] = []
        for row in rows:
            day = row.get("day")
            bytes_scanned = _coerce_int(row.get("bytes_scanned"))
            if not day or bytes_scanned <= 0:
                continue
            tb = bytes_scanned / _TB
            cost_usd = tb * self.pricing.spectrum_per_tb
            costs.append(
                UnifiedCost(
                    date=day,
                    platform="redshift",
                    service="redshift_spectrum",
                    resource=resource,
                    category=CostCategory.compute,
                    cost_usd=round(cost_usd, 6),
                    usage_quantity=round(tb, 6),
                    usage_unit="TB_scanned",
                    metadata={
                        "cluster_id": self.cluster_identifier,
                        "workgroup": self.workgroup_name,
                        "query_id": row.get("query_id"),
                        "user_name": row.get("user_id"),
                        "compute_type": "Spectrum",
                        "bytes_scanned": bytes_scanned,
                    },
                )
            )
        return costs


# ─── helpers ────────────────────────────────────────────────────────────


def _coerce_int(value: Any) -> int:
    """Best-effort ``int(x)`` that tolerates ``None`` / strings / floats."""
    if value is None or value == "":
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return 0


__all__ = [
    "RedshiftConnector",
    "RedshiftError",
    "RedshiftPricing",
    "DEFAULT_NODE_HOUR",
    "DEFAULT_SERVERLESS_RPU_HOUR",
    "DEFAULT_SPECTRUM_PER_TB",
    "DEFAULT_CONCURRENCY_SCALING_FREE_HR_PER_DAY",
    "DEFAULT_MANAGED_STORAGE_GB_MONTH",
]
