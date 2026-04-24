"""BigQuery connector — compute + storage + streaming + BI Engine costs.

Queries ``INFORMATION_SCHEMA.JOBS_BY_PROJECT`` (all users' jobs, requires
``bigquery.resourceViewer``), ``INFORMATION_SCHEMA.TABLE_STORAGE`` (active /
long-term × logical / physical bytes), ``INFORMATION_SCHEMA.SCHEMATA_OPTIONS``
(``storage_billing_model``), ``INFORMATION_SCHEMA.SCHEMATA`` (per-dataset
location) and ``INFORMATION_SCHEMA.RESERVATIONS_TIMELINE`` + BI Engine
reservations where available.

Supports:
- Multi-region discovery (no hardcoded ``region-us``)
- On-demand vs. Editions (Standard / Enterprise / Enterprise Plus) detection
  via ``reservation_id`` — slot-ms billing for reservations, per-TB otherwise
- Active vs. long-term storage (split at 90 days) across logical and physical
  billing modes per-dataset
- Parameterised SQL (``@param``) via the BigQuery REST jobs.query API
- ``pricing_overrides`` for on-demand TB rate, slot-hour rates, storage rates,
  and flat discount

Credentials (``PlatformConnectionCreate.credentials``)::

    {
        "project_id": "my-project",
        "service_account_json": "{...}",   # JSON string or dict
        # optional:
        "locations": ["US", "EU", "asia-northeast1"],    # restrict regions
        "pricing_overrides": {...},                      # also accepted here
    }

References:
- https://cloud.google.com/bigquery/pricing
- https://cloud.google.com/bigquery/docs/information-schema-jobs
- https://cloud.google.com/bigquery/docs/information-schema-table-storage
- https://cloud.google.com/bigquery/docs/reference/rest/v2/jobs/query
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

import httpx

from app.models.platform import CostCategory, UnifiedCost
from app.services.connectors.base import BaseConnector

logger = logging.getLogger(__name__)


# ─── Default pricing (USD, public list price as of 2026) ───────────────

# On-demand analysis
DEFAULT_ON_DEMAND_TB = 6.25  # $6.25 / TB scanned (first 1 TiB/month free not modelled)

# BigQuery Editions slot-hour rates (flat-rate / reservations)
DEFAULT_EDITION_SLOT_HR = {
    "standard": 0.04,
    "enterprise": 0.06,
    "enterprise-plus": 0.10,
    "enterprise_plus": 0.10,
}
DEFAULT_SLOT_HR_FALLBACK = 0.04  # assume Standard when edition unknown

# Storage $/GB/month (billing model × age)
#   https://cloud.google.com/bigquery/pricing#storage
DEFAULT_STORAGE_GB_MONTH = {
    ("logical", "active"): 0.02,
    ("logical", "long_term"): 0.01,
    ("physical", "active"): 0.04,
    ("physical", "long_term"): 0.02,
}

# Streaming inserts: $0.01 per 200 MB ⇒ $0.05/GB
DEFAULT_STREAMING_GB = 0.05

# BI Engine reservation: ~$0.0416/GB/hour published list price
DEFAULT_BI_ENGINE_GB_HR = 0.0416

# BigQuery Storage Read API: $1.10/TB
DEFAULT_STORAGE_READ_TB = 1.10

# Quota used everywhere
_TB = 1024 ** 4
_GB = 1024 ** 3
_MB = 1024 ** 2

# SECONDS_PER_MONTH used for active-storage proration ("/day" cost shown)
_DAYS_PER_MONTH = 30.0
_MS_PER_HOUR = 3_600_000.0

_BQ_ROOT = "https://bigquery.googleapis.com/bigquery/v2"

# Default multi-regions to probe when SCHEMATA discovery fails / is denied
_FALLBACK_REGIONS = ("region-us", "region-eu", "region-asia-northeast1")

_OAUTH_SCOPES = (
    "https://www.googleapis.com/auth/bigquery.readonly",
    "https://www.googleapis.com/auth/cloud-platform",
)


class BigQueryError(RuntimeError):
    """Structured BigQuery connector error (includes remediation hints)."""


@dataclass(frozen=True)
class BQPricing:
    """Immutable pricing table — default + pricing_overrides merged."""

    on_demand_tb: float = DEFAULT_ON_DEMAND_TB
    edition_slot_hr: dict[str, float] = field(
        default_factory=lambda: dict(DEFAULT_EDITION_SLOT_HR)
    )
    storage_gb_month: dict[tuple[str, str], float] = field(
        default_factory=lambda: dict(DEFAULT_STORAGE_GB_MONTH)
    )
    streaming_gb: float = DEFAULT_STREAMING_GB
    bi_engine_gb_hr: float = DEFAULT_BI_ENGINE_GB_HR
    storage_read_tb: float = DEFAULT_STORAGE_READ_TB
    discount_pct: float = 0.0

    def slot_hr_for(self, edition: str | None) -> float:
        """Look up slot-hour rate. Unknown editions fall back to Standard."""
        if not edition:
            return DEFAULT_SLOT_HR_FALLBACK
        key = edition.strip().lower().replace(" ", "-")
        return self.edition_slot_hr.get(key, DEFAULT_SLOT_HR_FALLBACK)

    def apply_discount(self, cost: float) -> float:
        if self.discount_pct <= 0:
            return cost
        return cost * (1.0 - self.discount_pct / 100.0)


def _merge_pricing(overrides: dict | None) -> BQPricing:
    """Merge user-supplied overrides onto default pricing (immutable return)."""
    if not overrides:
        return BQPricing()

    on_demand = float(overrides.get("on_demand_tb", DEFAULT_ON_DEMAND_TB))

    slot_hr = dict(DEFAULT_EDITION_SLOT_HR)
    for k, v in (overrides.get("slot_hr", {}) or {}).items():
        slot_hr[str(k).strip().lower().replace(" ", "-")] = float(v)

    storage = dict(DEFAULT_STORAGE_GB_MONTH)
    storage_overrides = overrides.get("storage_gb_month", {}) or {}
    for k, v in storage_overrides.items():
        # Accept {"logical_active": 0.018} or nested {"logical": {"active": 0.018}}
        if isinstance(v, dict):
            for sub, rate in v.items():
                storage[(str(k).lower(), str(sub).lower())] = float(rate)
        else:
            parts = str(k).lower().replace("-", "_").split("_", 1)
            if len(parts) == 2:
                storage[(parts[0], parts[1])] = float(v)

    return BQPricing(
        on_demand_tb=on_demand,
        edition_slot_hr=slot_hr,
        storage_gb_month=storage,
        streaming_gb=float(overrides.get("streaming_gb", DEFAULT_STREAMING_GB)),
        bi_engine_gb_hr=float(overrides.get("bi_engine_gb_hr", DEFAULT_BI_ENGINE_GB_HR)),
        storage_read_tb=float(overrides.get("storage_read_tb", DEFAULT_STORAGE_READ_TB)),
        discount_pct=float(overrides.get("discount_pct", 0.0) or 0.0),
    )


# ─── BigQuery REST client (minimal, httpx-based) ───────────────────────


class _BigQueryRestClient:
    """Thin wrapper around the BigQuery REST API.

    We avoid ``google-cloud-bigquery`` to keep the dependency footprint small;
    only ``google-auth`` (already required by the project) is needed for
    service-account OAuth.
    """

    def __init__(self, project_id: str, service_account: str | dict):
        self.project_id = project_id
        self._service_account = service_account
        self._token: str | None = None
        self._token_expiry: float = 0.0

    # -- auth ----------------------------------------------------------

    def _service_account_info(self) -> dict:
        if isinstance(self._service_account, dict):
            return self._service_account
        try:
            return json.loads(self._service_account)
        except (TypeError, ValueError) as exc:
            raise BigQueryError(
                "Invalid service_account_json: expected JSON string or dict"
            ) from exc

    def get_access_token(self) -> str:
        if self._token and time.time() < self._token_expiry - 60:
            return self._token

        sa_info = self._service_account_info()
        try:
            from google.auth.transport.requests import Request
            from google.oauth2 import service_account as sa_module

            creds = sa_module.Credentials.from_service_account_info(
                sa_info, scopes=list(_OAUTH_SCOPES)
            )
            creds.refresh(Request())
            self._token = creds.token
            # google-auth exposes expiry as datetime (naive UTC)
            if creds.expiry:
                self._token_expiry = creds.expiry.replace(
                    tzinfo=timezone.utc
                ).timestamp()
            else:
                self._token_expiry = time.time() + 3500
            return self._token
        except BigQueryError:
            raise
        except ImportError as exc:
            raise BigQueryError(
                "google-auth is required to mint BigQuery OAuth tokens"
            ) from exc
        except Exception as exc:
            raise BigQueryError(
                f"Failed to obtain OAuth token for service account "
                f"{sa_info.get('client_email', '<unknown>')}: {exc}"
            ) from exc

    # -- queries -------------------------------------------------------

    def query(
        self,
        sql: str,
        *,
        location: str | None = None,
        params: dict[str, Any] | None = None,
        timeout_ms: int = 60_000,
    ) -> list[dict[str, Any]]:
        """Run a parameterised SQL query and return rows as dicts.

        ``params`` uses ``@name`` placeholders in the SQL. Supported Python
        types: str → STRING, int → INT64, float → FLOAT64, bool → BOOL,
        datetime → TIMESTAMP.
        """
        token = self.get_access_token()
        body: dict[str, Any] = {
            "query": sql,
            "useLegacySql": False,
            "timeoutMs": timeout_ms,
        }
        if location:
            body["location"] = _canonicalise_location(location)
        if params:
            body["parameterMode"] = "NAMED"
            body["queryParameters"] = _encode_params(params)

        try:
            resp = httpx.post(
                f"{_BQ_ROOT}/projects/{self.project_id}/queries",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=body,
                timeout=max(30, (timeout_ms // 1000) + 10),
            )
        except httpx.HTTPError as exc:
            raise BigQueryError(f"BigQuery REST request failed: {exc}") from exc

        if resp.status_code != 200:
            raise _translate_http_error(resp)

        payload = resp.json()
        if payload.get("errors"):
            raise BigQueryError(
                f"BigQuery query errors: {payload['errors']}"
            )

        schema_fields = payload.get("schema", {}).get("fields", [])
        rows = payload.get("rows", [])
        return [_decode_row(r, schema_fields) for r in rows]


def _canonicalise_location(location: str) -> str:
    """Normalise location values from SCHEMATA / user input.

    INFORMATION_SCHEMA views require the ``region-<name>`` form (lowercase) for
    multi-regions. SCHEMATA.location returns values like ``US`` or
    ``asia-northeast1``. We canonicalise to the prefixed form.
    """
    loc = location.strip()
    if not loc:
        return loc
    if loc.lower().startswith("region-"):
        return loc.lower()
    if loc.upper() in {"US", "EU"}:
        return f"region-{loc.lower()}"
    return f"region-{loc.lower()}"


def _encode_params(params: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert a ``{name: value}`` mapping into BigQuery queryParameters."""
    encoded: list[dict[str, Any]] = []
    for name, value in params.items():
        if isinstance(value, bool):
            type_name, str_value = "BOOL", "true" if value else "false"
        elif isinstance(value, int):
            type_name, str_value = "INT64", str(value)
        elif isinstance(value, float):
            type_name, str_value = "FLOAT64", repr(value)
        elif isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            type_name = "TIMESTAMP"
            str_value = value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f UTC")
        elif value is None:
            type_name, str_value = "STRING", None  # type: ignore[assignment]
        else:
            type_name, str_value = "STRING", str(value)

        entry: dict[str, Any] = {
            "name": name,
            "parameterType": {"type": type_name},
        }
        if str_value is None:
            entry["parameterValue"] = {}
        else:
            entry["parameterValue"] = {"value": str_value}
        encoded.append(entry)
    return encoded


def _decode_row(row: dict[str, Any], fields: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    cells = row.get("f", [])
    for field_def, cell in zip(fields, cells):
        out[field_def.get("name", "")] = cell.get("v")
    return out


def _translate_http_error(resp: httpx.Response) -> BigQueryError:
    """Turn a BQ REST error into an actionable BigQueryError."""
    try:
        payload = resp.json()
        err = payload.get("error", {})
        reason = (err.get("errors") or [{}])[0].get("reason", "")
        message = err.get("message", resp.text[:400])
    except Exception:
        reason = ""
        message = resp.text[:400]

    hint = ""
    if resp.status_code in (401, 403):
        hint = (
            " Hint: the service account needs roles/bigquery.jobUser and "
            "roles/bigquery.resourceViewer (for JOBS_BY_PROJECT) plus "
            "roles/bigquery.metadataViewer (for TABLE_STORAGE / SCHEMATA)."
        )
    elif resp.status_code == 404:
        hint = " Hint: check project_id and that the region has BigQuery data."
    return BigQueryError(
        f"BigQuery API {resp.status_code} {reason or ''}: {message}{hint}".strip()
    )


# ─── Connector ─────────────────────────────────────────────────────────


class BigQueryConnector(BaseConnector):
    platform = "gcp"

    def __init__(
        self,
        credentials: dict,
        *,
        pricing_overrides: dict | None = None,
    ):
        super().__init__(credentials)
        if "project_id" not in credentials or not credentials["project_id"]:
            raise BigQueryError("BigQuery credentials missing 'project_id'")
        self.project_id: str = credentials["project_id"]
        self.service_account: str | dict = (
            credentials.get("service_account_json")
            or credentials.get("service_account")
            or {}
        )
        if not self.service_account:
            raise BigQueryError(
                "BigQuery credentials missing 'service_account_json'"
            )

        configured_locations = credentials.get("locations") or []
        self._configured_locations: tuple[str, ...] = tuple(
            _canonicalise_location(loc) for loc in configured_locations if loc
        )

        overrides = pricing_overrides or credentials.get("pricing_overrides")
        self.pricing = _merge_pricing(overrides)
        self._client = _BigQueryRestClient(self.project_id, self.service_account)

    # -- for tests / subclasses ---------------------------------------

    @property
    def client(self) -> _BigQueryRestClient:
        return self._client

    # -- public API ---------------------------------------------------

    def test_connection(self) -> dict:
        try:
            token = self._client.get_access_token()
            resp = httpx.get(
                f"{_BQ_ROOT}/projects/{self.project_id}/datasets",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            )
            if resp.status_code == 200:
                return {
                    "success": True,
                    "message": "BigQuery connection successful",
                }
            err = _translate_http_error(resp)
            return {"success": False, "message": str(err)}
        except BigQueryError as exc:
            return {"success": False, "message": str(exc)}
        except Exception as exc:  # pragma: no cover — surface anything odd
            logger.exception("BigQuery test_connection failed")
            return {"success": False, "message": str(exc)}

    def fetch_costs(self, days: int = 30) -> list[UnifiedCost]:
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days)

        try:
            locations = self._discover_locations()
        except BigQueryError as exc:
            logger.warning(
                "BigQuery location discovery failed (%s); falling back to defaults",
                exc,
            )
            locations = list(self._configured_locations or _FALLBACK_REGIONS)

        if not locations:
            locations = list(_FALLBACK_REGIONS)

        costs: list[UnifiedCost] = []
        for location in locations:
            costs.extend(self._fetch_job_costs(location, start, end))
            costs.extend(self._fetch_storage_costs(location, end))
            costs.extend(self._fetch_streaming_costs(location, start, end))
            costs.extend(self._fetch_bi_engine_costs(location, start, end))

        # Apply discount (if any) in a single immutable pass
        if self.pricing.discount_pct > 0:
            costs = [
                c.model_copy(
                    update={
                        "cost_usd": round(self.pricing.apply_discount(c.cost_usd), 6)
                    }
                )
                for c in costs
            ]
        return costs

    # -- region discovery ---------------------------------------------

    def _discover_locations(self) -> list[str]:
        """Return BigQuery locations (``region-<x>``) that hold datasets.

        Discovery order:
        1. ``credentials.locations`` when explicitly supplied
        2. ``INFORMATION_SCHEMA.SCHEMATA`` ``location`` column (any region)
        3. ``_FALLBACK_REGIONS`` — probed lazily when the above fails
        """
        if self._configured_locations:
            return list(self._configured_locations)

        # Try SCHEMATA in each fallback region until one succeeds.
        for region in _FALLBACK_REGIONS:
            try:
                rows = self._client.query(
                    "SELECT DISTINCT location "
                    f"FROM `{region}`.INFORMATION_SCHEMA.SCHEMATA",
                    location=region,
                )
            except BigQueryError as exc:
                logger.debug("SCHEMATA probe failed for %s: %s", region, exc)
                continue
            discovered = {
                _canonicalise_location(r["location"])
                for r in rows
                if r.get("location")
            }
            if discovered:
                return sorted(discovered)

        return list(_FALLBACK_REGIONS)

    # -- jobs (compute) -----------------------------------------------

    def _fetch_job_costs(
        self, location: str, start: datetime, end: datetime
    ) -> list[UnifiedCost]:
        """Query JOBS_BY_PROJECT grouped by date / user / reservation."""
        sql = f"""
        SELECT
          DATE(creation_time) AS job_date,
          COALESCE(user_email, 'unknown') AS user_email,
          project_id,
          reservation_id,
          edition,
          statement_type,
          SUM(COALESCE(total_bytes_billed, 0))   AS total_bytes_billed,
          SUM(COALESCE(total_slot_ms, 0))        AS total_slot_ms,
          COUNT(*)                               AS job_count
        FROM `{location}`.INFORMATION_SCHEMA.JOBS_BY_PROJECT
        WHERE creation_time >= @start_ts
          AND creation_time <  @end_ts
          AND state = 'DONE'
        GROUP BY job_date, user_email, project_id, reservation_id, edition, statement_type
        ORDER BY job_date
        """
        params = {"start_ts": start, "end_ts": end}

        try:
            rows = self._client.query(sql, location=location, params=params)
        except BigQueryError as exc:
            # Some projects lack the ``edition`` column (older regions).
            if "edition" in str(exc).lower():
                rows = self._client.query(
                    sql.replace("edition,\n          ", "")
                       .replace(", edition", "")
                       .replace("          edition,\n", ""),
                    location=location,
                    params=params,
                )
            else:
                logger.warning(
                    "JOBS_BY_PROJECT query failed in %s: %s", location, exc
                )
                return []

        costs: list[UnifiedCost] = []
        for row in rows:
            cost = self._job_row_to_unified_cost(row, location)
            if cost is not None:
                costs.append(cost)
        return costs

    def _job_row_to_unified_cost(
        self, row: dict[str, Any], location: str
    ) -> UnifiedCost | None:
        job_date = row.get("job_date")
        if not job_date:
            return None

        bytes_billed = int(row.get("total_bytes_billed") or 0)
        slot_ms = int(row.get("total_slot_ms") or 0)
        job_count = int(row.get("job_count") or 0)
        user = row.get("user_email") or "unknown"
        project = row.get("project_id") or self.project_id
        reservation = row.get("reservation_id")
        edition = row.get("edition")
        statement_type = row.get("statement_type") or "UNKNOWN"

        if reservation:
            slot_hr = self.pricing.slot_hr_for(edition)
            slot_hours = slot_ms / _MS_PER_HOUR
            cost_usd = slot_hours * slot_hr
            usage_quantity = round(slot_hours, 6)
            usage_unit = "slot_hours"
            pricing_model = "editions"
        else:
            tb_scanned = bytes_billed / _TB
            cost_usd = tb_scanned * self.pricing.on_demand_tb
            usage_quantity = round(tb_scanned, 6)
            usage_unit = "TB_scanned"
            pricing_model = "on_demand"

        if cost_usd <= 0 and bytes_billed == 0 and slot_ms == 0:
            return None

        return UnifiedCost(
            date=_date_string(job_date),
            platform="gcp",
            service="bigquery",
            resource=f"{project}/{user}",
            category=CostCategory.compute,
            cost_usd=round(cost_usd, 6),
            usage_quantity=usage_quantity,
            usage_unit=usage_unit,
            project=project,
            metadata={
                "bytes_billed": bytes_billed,
                "slot_ms": slot_ms,
                "job_count": job_count,
                "user": user,
                "reservation_id": reservation,
                "edition": edition,
                "statement_type": statement_type,
                "pricing_model": pricing_model,
                "location": location,
            },
        )

    # -- storage ------------------------------------------------------

    def _fetch_storage_costs(
        self, location: str, as_of: datetime
    ) -> list[UnifiedCost]:
        """Per-dataset storage cost split by active / long-term × logical /
        physical billing mode. Emits a single daily record per dataset.
        """
        billing_modes = self._fetch_storage_billing_modes(location)

        sql = f"""
        SELECT
          table_schema AS dataset,
          SUM(COALESCE(active_logical_bytes, 0))      AS active_logical_bytes,
          SUM(COALESCE(long_term_logical_bytes, 0))   AS long_term_logical_bytes,
          SUM(COALESCE(active_physical_bytes, 0))     AS active_physical_bytes,
          SUM(COALESCE(long_term_physical_bytes, 0))  AS long_term_physical_bytes
        FROM `{location}`.INFORMATION_SCHEMA.TABLE_STORAGE
        WHERE deleted = FALSE
        GROUP BY dataset
        """
        try:
            rows = self._client.query(sql, location=location)
        except BigQueryError as exc:
            logger.warning(
                "TABLE_STORAGE query failed in %s: %s", location, exc
            )
            return []

        date_str = as_of.strftime("%Y-%m-%d")
        costs: list[UnifiedCost] = []
        for row in rows:
            dataset = row.get("dataset") or "unknown"
            billing_mode = billing_modes.get(dataset, "logical")

            if billing_mode == "physical":
                active_gb = int(row.get("active_physical_bytes") or 0) / _GB
                lt_gb = int(row.get("long_term_physical_bytes") or 0) / _GB
                active_rate = self.pricing.storage_gb_month[("physical", "active")]
                lt_rate = self.pricing.storage_gb_month[("physical", "long_term")]
            else:
                active_gb = int(row.get("active_logical_bytes") or 0) / _GB
                lt_gb = int(row.get("long_term_logical_bytes") or 0) / _GB
                active_rate = self.pricing.storage_gb_month[("logical", "active")]
                lt_rate = self.pricing.storage_gb_month[("logical", "long_term")]

            # Per-day cost (monthly rate / 30)
            daily_cost = (
                (active_gb * active_rate + lt_gb * lt_rate) / _DAYS_PER_MONTH
            )
            total_gb = active_gb + lt_gb

            if daily_cost <= 0 and total_gb <= 0:
                continue

            costs.append(
                UnifiedCost(
                    date=date_str,
                    platform="gcp",
                    service="bigquery_storage",
                    resource=f"{self.project_id}/{dataset}",
                    category=CostCategory.storage,
                    cost_usd=round(daily_cost, 6),
                    usage_quantity=round(total_gb, 4),
                    usage_unit="GB",
                    project=self.project_id,
                    metadata={
                        "dataset": dataset,
                        "billing_model": billing_mode,
                        "active_gb": round(active_gb, 4),
                        "long_term_gb": round(lt_gb, 4),
                        "location": location,
                    },
                )
            )
        return costs

    def _fetch_storage_billing_modes(self, location: str) -> dict[str, str]:
        """Map dataset name → ``logical`` or ``physical`` billing model."""
        sql = f"""
        SELECT schema_name AS dataset, option_value AS billing_model
        FROM `{location}`.INFORMATION_SCHEMA.SCHEMATA_OPTIONS
        WHERE option_name = 'storage_billing_model'
        """
        try:
            rows = self._client.query(sql, location=location)
        except BigQueryError as exc:
            logger.debug(
                "SCHEMATA_OPTIONS query failed in %s: %s", location, exc
            )
            return {}

        modes: dict[str, str] = {}
        for row in rows:
            dataset = row.get("dataset")
            raw = (row.get("billing_model") or "").strip().strip('"').lower()
            if not dataset or not raw:
                continue
            modes[dataset] = "physical" if "physical" in raw else "logical"
        return modes

    # -- streaming inserts -------------------------------------------

    def _fetch_streaming_costs(
        self, location: str, start: datetime, end: datetime
    ) -> list[UnifiedCost]:
        """Approximate streaming-insert costs.

        The ``INFORMATION_SCHEMA.STREAMING_TIMELINE_BY_PROJECT`` view (if
        present in the region) exposes ``total_input_bytes`` per minute; if it
        is unavailable we skip silently.
        """
        sql = f"""
        SELECT
          DATE(start_timestamp) AS day,
          SUM(COALESCE(total_input_bytes, 0)) AS bytes,
          SUM(COALESCE(total_requests, 0))    AS requests
        FROM `{location}`.INFORMATION_SCHEMA.STREAMING_TIMELINE_BY_PROJECT
        WHERE start_timestamp >= @start_ts
          AND start_timestamp <  @end_ts
        GROUP BY day
        ORDER BY day
        """
        params = {"start_ts": start, "end_ts": end}
        try:
            rows = self._client.query(sql, location=location, params=params)
        except BigQueryError as exc:
            logger.debug(
                "STREAMING_TIMELINE query skipped in %s: %s", location, exc
            )
            return []

        costs: list[UnifiedCost] = []
        for row in rows:
            day = row.get("day")
            if not day:
                continue
            bytes_ingested = int(row.get("bytes") or 0)
            if bytes_ingested <= 0:
                continue
            gb = bytes_ingested / _GB
            cost_usd = gb * self.pricing.streaming_gb
            costs.append(
                UnifiedCost(
                    date=_date_string(day),
                    platform="gcp",
                    service="bigquery_streaming",
                    resource=f"{self.project_id}/streaming",
                    category=CostCategory.ingestion,
                    cost_usd=round(cost_usd, 6),
                    usage_quantity=round(gb, 4),
                    usage_unit="GB",
                    project=self.project_id,
                    metadata={
                        "location": location,
                        "requests": int(row.get("requests") or 0),
                    },
                )
            )
        return costs

    # -- BI Engine ----------------------------------------------------

    def _fetch_bi_engine_costs(
        self, location: str, start: datetime, end: datetime
    ) -> list[UnifiedCost]:
        """Surface BI Engine reservation cost.

        Uses ``INFORMATION_SCHEMA.BI_CAPACITIES`` (preview) or the
        ``RESERVATIONS_TIMELINE`` view. If neither exists we skip.
        """
        sql = f"""
        SELECT
          DATE(period_start) AS day,
          SUM(COALESCE(capacity_gb, 0)) AS gb_hours
        FROM `{location}`.INFORMATION_SCHEMA.BI_CAPACITIES
        WHERE period_start >= @start_ts
          AND period_start <  @end_ts
        GROUP BY day
        """
        params = {"start_ts": start, "end_ts": end}
        try:
            rows = self._client.query(sql, location=location, params=params)
        except BigQueryError as exc:
            logger.debug("BI_CAPACITIES query skipped in %s: %s", location, exc)
            return []

        costs: list[UnifiedCost] = []
        for row in rows:
            day = row.get("day")
            gb_hours = float(row.get("gb_hours") or 0)
            if not day or gb_hours <= 0:
                continue
            cost_usd = gb_hours * self.pricing.bi_engine_gb_hr
            costs.append(
                UnifiedCost(
                    date=_date_string(day),
                    platform="gcp",
                    service="bigquery_bi_engine",
                    resource=f"{self.project_id}/bi_engine",
                    category=CostCategory.serving,
                    cost_usd=round(cost_usd, 6),
                    usage_quantity=round(gb_hours, 4),
                    usage_unit="GB_hours",
                    project=self.project_id,
                    metadata={"location": location},
                )
            )
        return costs


# ─── helpers ───────────────────────────────────────────────────────────


def _date_string(value: Any) -> str:
    """Normalise a date-ish value returned by BigQuery into YYYY-MM-DD."""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, str):
        return value[:10]
    return str(value)[:10]


__all__ = [
    "BigQueryConnector",
    "BigQueryError",
    "BQPricing",
    "DEFAULT_ON_DEMAND_TB",
    "DEFAULT_EDITION_SLOT_HR",
    "DEFAULT_STORAGE_GB_MONTH",
    "DEFAULT_STREAMING_GB",
    "DEFAULT_BI_ENGINE_GB_HR",
]


# Ensure Iterable import used (keeps type-checkers happy without runtime cost)
_ = Iterable  # noqa: F841
