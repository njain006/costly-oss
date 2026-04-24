"""Google Gemini / Vertex AI connector.

Pulls Gemini / Vertex AI token-usage costs with two layered sources:

1. **BigQuery billing export** (primary, authoritative).
   Queries ``{billing_project}.{billing_dataset}.gcp_billing_export_v1_{BILLING_ACCOUNT}``
   filtered to ``service.description = 'Vertex AI'`` or
   ``service.description LIKE 'Generative Language API%'``.
   See: https://cloud.google.com/billing/docs/how-to/export-data-bigquery-tables/standard-usage

2. **Cloud Billing catalog API** (secondary, optional).
   ``cloudbilling.googleapis.com/v1/services/{serviceId}/skus`` gives current list
   prices; used to refresh the built-in pricing table when the SA has access.

3. **AI Studio** (``generativelanguage.googleapis.com``) has no first-party
   usage/cost API as of early 2026. Surfaced honestly: ``test_connection``
   reports that Vertex AI billing export is required for cost tracking.

Credentials (all fields optional unless otherwise noted):

    api_key                 — AI Studio API key (test/dev only)
    service_account_json    — GCP SA JSON (str or dict). Required for Vertex.
    project_id              — GCP project that owns the Vertex AI workloads.
    region                  — Vertex region (default ``us-central1``).
    billing_project         — Project hosting the BigQuery billing dataset.
                              Defaults to ``project_id``.
    billing_dataset         — Dataset name (e.g. ``billing_export``).
    billing_account_id      — The billing account id with dashes replaced by
                              underscores (e.g. ``01ABCD_234567_89EFGH``).
    billing_table           — Override the full table name (advanced; rarely
                              needed — we derive it from the three fields above).
    pricing_overrides       — Per-model pricing overrides (same shape as
                              ``MODEL_PRICING``) applied at cost-estimate time.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx

from app.models.platform import CostCategory, UnifiedCost
from app.services.connectors.base import BaseConnector

# ---------------------------------------------------------------------------
# Pricing table — list prices per million tokens (USD), sourced from
# https://ai.google.dev/gemini-api/docs/pricing and the Vertex AI pricing page
# (https://cloud.google.com/vertex-ai/generative-ai/pricing), current as of
# early 2026. Values are updated via the Cloud Billing SKU catalog when the
# service account has ``cloudbilling.services.list`` permission.
#
# Derived tiers:
#   cache_read  = 0.25 × input  (Gemini cached-content discount: ~75% off)
#   cache_write = 1.00 × input  (cache storage billed separately per hour,
#                                not captured here)
#   thoughts    = 1.00 × output (2.5 thinking tokens billed as output)
# ---------------------------------------------------------------------------

MODEL_PRICING: dict[str, dict[str, float]] = {
    # Gemini 2.5 family (pro has a context-length tier break at 200k tokens)
    "gemini-2.5-pro": {
        "input": 1.25,
        "output": 10.0,
        "input_over_200k": 2.50,
        "output_over_200k": 15.0,
        "context_tier_tokens": 200_000,
    },
    "gemini-2.5-flash": {"input": 0.30, "output": 2.50},
    "gemini-2.5-flash-lite": {"input": 0.10, "output": 0.40},
    # Gemini 2.0 family
    "gemini-2.0-pro": {"input": 1.25, "output": 10.0},
    "gemini-2.0-flash-lite": {"input": 0.075, "output": 0.30},
    "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
    # Gemini 1.5 family (legacy)
    "gemini-1.5-pro": {"input": 1.25, "output": 5.0},
    "gemini-1.5-flash-8b": {"input": 0.0375, "output": 0.15},
    "gemini-1.5-flash": {"input": 0.075, "output": 0.30},
    # Gemini 1.0
    "gemini-1.0-pro": {"input": 0.50, "output": 1.50},
    # Experimental / preview (billed at Pro rate)
    "gemini-exp": {"input": 1.25, "output": 10.0},
    # Image generation (Gemini 2.0 Flash image gen) — per 1M image output tokens
    "gemini-2.0-flash-image": {"input": 0.10, "output": 30.0},
    # Embeddings — output is free, input per million
    "text-embedding-004": {"input": 0.025, "output": 0.0},
    "text-embedding": {"input": 0.025, "output": 0.0},
    "embedding-001": {"input": 0.025, "output": 0.0},
}

# Pricing multipliers for cached / thinking tokens (applied relative to the
# resolved input/output price).
CACHE_READ_MULTIPLIER = 0.25       # Gemini cached-content reads: ~75% off input
CACHE_WRITE_MULTIPLIER = 1.00      # Storage billed per hour — ignored here
THINKING_TOKEN_MULTIPLIER = 1.00   # 2.5 thinking tokens billed as output
TOOL_PROMPT_MULTIPLIER = 1.00      # tool-use prompt tokens billed as input

# Fallback pricing when no prefix matches the model name (Flash tier — the
# cheapest safe default; never over-estimates costs).
FALLBACK_PRICING: dict[str, float] = {"input": 0.10, "output": 0.40}

DEFAULT_REGION = "us-central1"
_VALID_REGIONS: tuple[str, ...] = (
    "us-central1",
    "us-east1",
    "us-east4",
    "us-east5",
    "us-west1",
    "us-west4",
    "europe-west1",
    "europe-west2",
    "europe-west3",
    "europe-west4",
    "europe-west9",
    "asia-east1",
    "asia-northeast1",
    "asia-northeast3",
    "asia-south1",
    "asia-southeast1",
)


# ---------------------------------------------------------------------------
# TokenUsage — captures every field Gemini reports in ``usage_metadata``.
# Mirrors the shape of ``claude_code_connector.TokenUsage``.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TokenUsage:
    """Token counts for a single Gemini turn.

    Fields map directly onto ``usage_metadata`` keys returned by both AI
    Studio and Vertex AI SDKs.
    """

    prompt_tokens: int = 0
    candidates_tokens: int = 0
    cached_content_tokens: int = 0
    thoughts_tokens: int = 0
    tool_use_prompt_tokens: int = 0

    @property
    def total(self) -> int:
        return (
            self.prompt_tokens
            + self.candidates_tokens
            + self.cached_content_tokens
            + self.thoughts_tokens
            + self.tool_use_prompt_tokens
        )

    @property
    def billable_input_tokens(self) -> int:
        """Input tokens charged at the standard input price.

        Excludes cached content (charged at a discount) but includes
        tool-use prompt tokens (charged as standard input).
        """
        return self.prompt_tokens + self.tool_use_prompt_tokens

    @property
    def billable_output_tokens(self) -> int:
        """Output tokens charged at the standard output price (thoughts included)."""
        return self.candidates_tokens + self.thoughts_tokens

    def __add__(self, other: "TokenUsage") -> "TokenUsage":
        if not isinstance(other, TokenUsage):
            return NotImplemented
        return TokenUsage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            candidates_tokens=self.candidates_tokens + other.candidates_tokens,
            cached_content_tokens=self.cached_content_tokens + other.cached_content_tokens,
            thoughts_tokens=self.thoughts_tokens + other.thoughts_tokens,
            tool_use_prompt_tokens=self.tool_use_prompt_tokens + other.tool_use_prompt_tokens,
        )


def parse_usage_metadata(raw: dict) -> TokenUsage:
    """Build a ``TokenUsage`` from a Gemini ``usage_metadata`` dict.

    Accepts both camelCase (Vertex) and snake_case (google-generativeai SDK)
    keys, falling back to zero for missing fields.
    """
    def _pick(*keys: str) -> int:
        for key in keys:
            if key in raw and raw[key] is not None:
                try:
                    return int(raw[key])
                except (TypeError, ValueError):
                    continue
        return 0

    return TokenUsage(
        prompt_tokens=_pick("prompt_token_count", "promptTokenCount"),
        candidates_tokens=_pick("candidates_token_count", "candidatesTokenCount"),
        cached_content_tokens=_pick(
            "cached_content_token_count", "cachedContentTokenCount"
        ),
        thoughts_tokens=_pick("thoughts_token_count", "thoughtsTokenCount"),
        tool_use_prompt_tokens=_pick(
            "tool_use_prompt_token_count", "toolUsePromptTokenCount"
        ),
    )


# ---------------------------------------------------------------------------
# Pricing resolution — longest prefix wins (deterministic, unlike dict order).
# ---------------------------------------------------------------------------


def _resolve_pricing(
    model: str,
    pricing_overrides: Optional[dict[str, dict[str, float]]] = None,
    table: Optional[dict[str, dict[str, float]]] = None,
) -> dict[str, float]:
    """Resolve list-price dict for a model name, longest-prefix match first.

    Overrides take precedence; fall back to ``FALLBACK_PRICING`` if nothing
    matches. Matching is case-insensitive and strips a leading ``models/``
    prefix returned by some Gemini endpoints.
    """
    if not model:
        return dict(FALLBACK_PRICING)

    name = model.lower().strip()
    if name.startswith("models/"):
        name = name[len("models/"):]

    candidates: dict[str, dict[str, float]] = {}
    if table is not None:
        candidates.update(table)
    else:
        candidates.update(MODEL_PRICING)
    if pricing_overrides:
        candidates.update(pricing_overrides)

    for key in sorted(candidates.keys(), key=len, reverse=True):
        if key.lower() in name:
            return candidates[key]
    return dict(FALLBACK_PRICING)


def _pricing_for_context(
    price: dict[str, float], prompt_tokens: int
) -> tuple[float, float]:
    """Return the (input, output) per-million rates accounting for context tier.

    Gemini 2.5 Pro charges 2× for prompts over 200k tokens. Models without
    a ``context_tier_tokens`` entry use the flat input/output prices.
    """
    tier_threshold = price.get("context_tier_tokens")
    if tier_threshold and prompt_tokens > tier_threshold:
        return (
            price.get("input_over_200k", price["input"]),
            price.get("output_over_200k", price["output"]),
        )
    return price["input"], price["output"]


def estimate_cost(
    model: str,
    usage: TokenUsage | None = None,
    *,
    pricing_overrides: Optional[dict[str, dict[str, float]]] = None,
) -> float:
    """Compute USD cost for a single turn.

    Cached content is charged at ``CACHE_READ_MULTIPLIER`` × input-rate
    (typically 25% of standard input). Thoughts tokens are charged at the
    output rate. Tool-use prompt tokens are charged at standard input.
    """
    if usage is None:
        return 0.0

    price = _resolve_pricing(model, pricing_overrides=pricing_overrides)
    input_rate, output_rate = _pricing_for_context(price, usage.prompt_tokens)

    per_million = 1_000_000.0
    cost = (
        usage.billable_input_tokens * input_rate / per_million
        + usage.billable_output_tokens * output_rate / per_million
        + usage.cached_content_tokens
        * input_rate
        * CACHE_READ_MULTIPLIER
        / per_million
    )
    return round(max(cost, 0.0), 6)


def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Back-compat helper — ``estimate_cost`` with flat input/output counts.

    Kept for existing callers (test suite + external code) that pass raw
    token counts instead of a full ``TokenUsage``.
    """
    usage = TokenUsage(prompt_tokens=int(input_tokens or 0),
                       candidates_tokens=int(output_tokens or 0))
    return estimate_cost(model, usage)


# ---------------------------------------------------------------------------
# Access-token helper — uses google-auth when available, manual JWT otherwise.
# ---------------------------------------------------------------------------


def _get_access_token_from_sa(
    service_account: dict | str,
    scopes: tuple[str, ...] = (
        "https://www.googleapis.com/auth/cloud-platform",
        "https://www.googleapis.com/auth/bigquery.readonly",
    ),
) -> str:
    """OAuth2 access token from a GCP service account.

    Tries ``google-auth`` first (preferred, handles key rotation, retries),
    falls back to manually signing a JWT bearer assertion against the
    token endpoint if the library is unavailable.
    """
    sa = json.loads(service_account) if isinstance(service_account, str) else service_account

    try:
        from google.auth.transport.requests import Request
        from google.oauth2 import service_account as sa_module

        creds = sa_module.Credentials.from_service_account_info(sa, scopes=list(scopes))
        creds.refresh(Request())
        return creds.token
    except ImportError:
        pass

    import jwt as pyjwt  # PyJWT

    now = int(time.time())
    payload = {
        "iss": sa["client_email"],
        "scope": " ".join(scopes),
        "aud": "https://oauth2.googleapis.com/token",
        "iat": now,
        "exp": now + 3600,
    }
    signed = pyjwt.encode(payload, sa["private_key"], algorithm="RS256")

    resp = httpx.post(
        "https://oauth2.googleapis.com/token",
        data={
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": signed,
        },
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


# ---------------------------------------------------------------------------
# HTTP error classification for test_connection + fetch_costs error paths.
# ---------------------------------------------------------------------------


def _classify_http_error(status: int, body: str) -> str:
    """Map HTTP status + GCP error body to a friendly message.

    Recognises:
    - 401 → invalid credentials
    - 403 with "permission" or "has not been used" → missing permission / API disabled
    - 404 → project or billing account not found
    """
    snippet = (body or "").strip()[:500]

    if status == 401:
        return "Invalid service account credentials (HTTP 401)"

    if status == 403:
        # Try parsing the JSON body for a permission hint.
        permission = _extract_permission(snippet)
        if permission:
            return f"Missing permission: {permission}"
        if "has not been used" in snippet or "is disabled" in snippet:
            return "API disabled — enable BigQuery/Cloud Billing API on the project"
        return f"Permission denied (HTTP 403): {snippet[:200]}"

    if status == 404:
        return "Project, dataset, or billing account not found (HTTP 404)"

    return f"HTTP {status}: {snippet[:200]}"


def _extract_permission(body: str) -> Optional[str]:
    """Pull a permission identifier from a GCP 403 body if present.

    GCP errors look like: ``{"error":{"message":"Permission 'bigquery.jobs.create'
    denied on resource ..."}}``
    """
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return None

    err = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(err, dict):
        return None
    msg = err.get("message") or ""
    # Look for: Permission 'x.y.z' or required permission: x.y.z
    import re
    match = re.search(r"[Pp]ermission[:\s'\"]+([a-zA-Z]+(?:\.[a-zA-Z]+)+)", msg)
    if match:
        return match.group(1)
    # Detail-style permission lists: "Required 'bigquery.jobs.create' permission"
    match = re.search(r"'([a-zA-Z]+(?:\.[a-zA-Z]+)+)'", msg)
    if match:
        return match.group(1)
    return None


# ---------------------------------------------------------------------------
# BigQuery billing export query builder.
# ---------------------------------------------------------------------------


def _normalize_billing_account(billing_account_id: str) -> str:
    """Convert ``01ABCD-234567-89EFGH`` → ``01ABCD_234567_89EFGH``."""
    return (billing_account_id or "").replace("-", "_").replace(".", "_")


def _billing_table_fqn(
    billing_project: str, billing_dataset: str, billing_account_id: str
) -> str:
    """Fully-qualified BigQuery table name for the standard-usage billing export."""
    account = _normalize_billing_account(billing_account_id)
    return f"`{billing_project}.{billing_dataset}.gcp_billing_export_v1_{account}`"


def _build_billing_query(
    table_fqn: str,
    start: datetime,
    end: datetime,
    project_id: Optional[str] = None,
) -> str:
    """Return the SQL that rolls up Gemini/Vertex AI costs from the billing export."""
    start_date = start.strftime("%Y-%m-%d")
    end_date = end.strftime("%Y-%m-%d")
    project_filter = (
        f"AND project.id = '{project_id}'" if project_id else ""
    )
    return (
        "SELECT\n"
        "  DATE(usage_start_time) AS usage_date,\n"
        "  sku.description AS sku_description,\n"
        "  sku.id AS sku_id,\n"
        "  service.description AS service_description,\n"
        "  project.id AS project_id,\n"
        "  location.region AS region,\n"
        "  SUM(COALESCE(usage.amount, 0)) AS usage_amount,\n"
        "  ANY_VALUE(usage.unit) AS usage_unit,\n"
        "  SUM(COALESCE(cost, 0)) AS cost,\n"
        "  ANY_VALUE(currency) AS currency,\n"
        "  SUM(IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c), 0)) AS credits_amount\n"
        f"FROM {table_fqn}\n"
        f"WHERE DATE(usage_start_time) >= DATE('{start_date}')\n"
        f"  AND DATE(usage_start_time) < DATE('{end_date}')\n"
        "  AND (\n"
        "       service.description = 'Vertex AI'\n"
        "    OR service.description = 'Generative Language API'\n"
        "    OR service.description LIKE 'Generative Language API%'\n"
        "    OR service.description = 'AI Platform'\n"
        "  )\n"
        f"  {project_filter}\n"
        "GROUP BY usage_date, sku_description, sku_id, service_description, project_id, region\n"
        "ORDER BY usage_date\n"
    )


# ---------------------------------------------------------------------------
# SKU-name → (category, model) classifier. Keeps connector UnifiedCost records
# legible even when the billing export doesn't include a model label.
# ---------------------------------------------------------------------------


def _classify_sku(sku_description: str) -> tuple[CostCategory, str]:
    """Best-effort category + model guess from a Vertex/GenAI SKU description."""
    desc = (sku_description or "").lower()

    if "embedding" in desc:
        return CostCategory.ai_inference, _guess_model(desc, default="text-embedding-004")
    if "image" in desc:
        return CostCategory.ai_inference, _guess_model(desc, default="gemini-2.0-flash-image")
    if "training" in desc or "fine-tuning" in desc or "fine tuning" in desc:
        return CostCategory.ml_training, _guess_model(desc, default="vertex-ai-training")
    if "prediction" in desc or "inference" in desc or "generate" in desc or "gemini" in desc:
        return CostCategory.ai_inference, _guess_model(desc, default="gemini")
    return CostCategory.ai_inference, _guess_model(desc, default="vertex-ai")


def _guess_model(desc: str, default: str = "vertex-ai") -> str:
    """Pick the longest matching known model name in the SKU description.

    SKU descriptions from the Cloud Billing catalog use spaces rather than
    hyphens (e.g. ``Gemini 2.5 Pro``), so we normalise both sides before
    prefix-matching against the hyphenated keys in ``MODEL_PRICING``.
    """
    normalised = desc.lower().replace("-", " ")
    for key in sorted(MODEL_PRICING.keys(), key=len, reverse=True):
        if key.replace("-", " ") in normalised:
            return key
    return default


# ---------------------------------------------------------------------------
# The connector.
# ---------------------------------------------------------------------------


class GeminiConnector(BaseConnector):
    """Gemini / Vertex AI cost connector — BigQuery-billing-export primary."""

    platform = "gemini"

    def __init__(self, credentials: dict):
        super().__init__(credentials)
        creds = credentials or {}

        self.api_key: Optional[str] = creds.get("api_key")
        self.service_account = creds.get("service_account_json")
        self.project_id: Optional[str] = creds.get("project_id")
        self.region: str = (creds.get("region") or DEFAULT_REGION).strip() or DEFAULT_REGION

        self.billing_project: Optional[str] = creds.get("billing_project") or self.project_id
        self.billing_dataset: Optional[str] = creds.get("billing_dataset")
        self.billing_account_id: Optional[str] = creds.get("billing_account_id")
        self.billing_table: Optional[str] = creds.get("billing_table")

        raw_overrides = creds.get("pricing_overrides") or {}
        self.pricing_overrides: dict[str, dict[str, float]] = (
            raw_overrides if isinstance(raw_overrides, dict) else {}
        )

        self.use_vertex: bool = bool(self.service_account and self.project_id)
        self.has_billing_export: bool = bool(
            self.service_account
            and self.billing_project
            and self.billing_dataset
            and self.billing_account_id
        )

    # ------------------------------------------------------------------ auth

    def _get_access_token(self) -> str:
        if not self.service_account:
            raise RuntimeError("No service_account_json configured for Vertex AI access")
        return _get_access_token_from_sa(self.service_account)

    # ---------------------------------------------------------- connection test

    def test_connection(self) -> dict:
        """Test credentials.

        Returns ``{"success": bool, "message": str}``. Differentiates between
        401 (bad credentials), 403 (missing IAM role), 404 (project/account
        not found), and "API disabled" states. AI-Studio-only credentials are
        flagged as insufficient for cost tracking.
        """
        if not self.use_vertex:
            if self.api_key:
                return self._test_ai_studio()
            return {
                "success": False,
                "message": (
                    "No credentials provided. Supply a Vertex AI service account "
                    "JSON with BigQuery billing export access to enable cost tracking."
                ),
            }

        if not self.has_billing_export:
            # SA present but no billing export — degrade gracefully.
            vertex_check = self._test_vertex_models_endpoint()
            if vertex_check["success"]:
                vertex_check["message"] = (
                    "Vertex AI credentials valid, but BigQuery billing export is not "
                    "configured. Set billing_project, billing_dataset, and "
                    "billing_account_id to enable cost tracking."
                )
                # Keep success=True but warn: data will be empty.
            return vertex_check

        return self._test_billing_export()

    def _test_ai_studio(self) -> dict:
        """AI Studio has no usage API — report honestly."""
        try:
            resp = httpx.get(
                "https://generativelanguage.googleapis.com/v1/models",
                params={"key": self.api_key},
                timeout=10,
            )
        except httpx.HTTPError as exc:
            return {"success": False, "message": f"Network error contacting AI Studio: {exc}"}

        if resp.status_code != 200:
            return {
                "success": False,
                "message": _classify_http_error(resp.status_code, resp.text),
            }
        return {
            "success": False,
            "message": (
                "Google AI Studio API key accepted, but AI Studio does not expose a "
                "usage/cost API. Use Vertex AI with BigQuery billing export for "
                "production cost tracking."
            ),
        }

    def _test_vertex_models_endpoint(self) -> dict:
        """Hit the regional publishers/google/models endpoint to validate the SA."""
        try:
            token = self._get_access_token()
        except Exception as exc:  # noqa: BLE001 — surface raw auth errors
            return {"success": False, "message": f"Service account auth failed: {exc}"}

        url = (
            f"https://{self.region}-aiplatform.googleapis.com/v1/projects/"
            f"{self.project_id}/locations/{self.region}/publishers/google/models"
        )
        try:
            resp = httpx.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=10)
        except httpx.HTTPError as exc:
            return {"success": False, "message": f"Network error: {exc}"}

        if resp.status_code == 200:
            return {"success": True, "message": f"Vertex AI credentials valid (region={self.region})"}
        return {
            "success": False,
            "message": _classify_http_error(resp.status_code, resp.text),
        }

    def _test_billing_export(self) -> dict:
        """Run a trivial dry-run query against the billing export table."""
        try:
            token = self._get_access_token()
        except Exception as exc:  # noqa: BLE001
            return {"success": False, "message": f"Service account auth failed: {exc}"}

        table_fqn = self._table_fqn()
        query = f"SELECT 1 AS ok FROM {table_fqn} LIMIT 1"

        try:
            resp = httpx.post(
                f"https://bigquery.googleapis.com/bigquery/v2/projects/"
                f"{self.billing_project}/queries",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json={"query": query, "useLegacySql": False, "dryRun": True, "timeoutMs": 15000},
                timeout=20,
            )
        except httpx.HTTPError as exc:
            return {"success": False, "message": f"Network error: {exc}"}

        if resp.status_code == 200:
            return {
                "success": True,
                "message": (
                    f"BigQuery billing export reachable "
                    f"({self.billing_project}.{self.billing_dataset})"
                ),
            }
        return {
            "success": False,
            "message": _classify_http_error(resp.status_code, resp.text),
        }

    # ------------------------------------------------------------------ costs

    def _table_fqn(self) -> str:
        if self.billing_table:
            # Allow callers to override the full FQN. Wrap in backticks if needed.
            raw = self.billing_table.strip()
            return raw if raw.startswith("`") else f"`{raw}`"
        return _billing_table_fqn(
            self.billing_project or "",
            self.billing_dataset or "",
            self.billing_account_id or "",
        )

    def fetch_costs(self, days: int = 30) -> list[UnifiedCost]:
        """Fetch Gemini / Vertex AI costs for the last ``days`` days.

        Order of preference:
        1. BigQuery billing export (authoritative, any region).
        2. Empty list + warning if only Vertex SA is available (no usage API).
        3. Empty list for AI Studio-only credentials.
        """
        if not self.use_vertex:
            return []
        if not self.has_billing_export:
            return []

        end = datetime.now(timezone.utc)
        start = end - timedelta(days=max(days, 1))

        try:
            token = self._get_access_token()
        except Exception:
            return []

        return self._fetch_from_billing_export(token, start, end)

    def _fetch_from_billing_export(
        self, token: str, start: datetime, end: datetime
    ) -> list[UnifiedCost]:
        """Execute the billing-export query and normalise rows → UnifiedCost."""
        table_fqn = self._table_fqn()
        query = _build_billing_query(table_fqn, start, end, self.project_id)

        try:
            resp = httpx.post(
                f"https://bigquery.googleapis.com/bigquery/v2/projects/"
                f"{self.billing_project}/queries",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json={"query": query, "useLegacySql": False, "timeoutMs": 60000},
                timeout=120,
            )
        except httpx.HTTPError:
            return []

        if resp.status_code != 200:
            return []

        try:
            data = resp.json()
        except ValueError:
            return []

        return list(self._iter_billing_rows(data))

    def _iter_billing_rows(self, data: dict) -> list[UnifiedCost]:
        rows = data.get("rows", []) or []
        results: list[UnifiedCost] = []
        for row in rows:
            values = [cell.get("v") for cell in row.get("f", [])]
            if len(values) < 10:
                continue

            (
                usage_date,
                sku_description,
                sku_id,
                service_description,
                project_id,
                region,
                usage_amount,
                usage_unit,
                cost,
                currency,
                *rest,
            ) = values + [None] * (11 - len(values))

            credits_amount = rest[0] if rest else 0.0

            try:
                cost_usd = float(cost or 0.0)
            except (TypeError, ValueError):
                cost_usd = 0.0
            try:
                credits = float(credits_amount or 0.0)
            except (TypeError, ValueError):
                credits = 0.0

            net_cost = round(max(cost_usd + credits, 0.0), 6)
            try:
                qty = float(usage_amount or 0.0)
            except (TypeError, ValueError):
                qty = 0.0

            if net_cost <= 0 and qty <= 0:
                continue

            category, model = _classify_sku(sku_description or "")
            date_str = str(usage_date or "")[:10]

            results.append(
                UnifiedCost(
                    date=date_str,
                    platform="gemini",
                    service=self._service_slug(service_description),
                    resource=sku_description or model,
                    category=category,
                    cost_usd=net_cost,
                    usage_quantity=round(qty, 6),
                    usage_unit=str(usage_unit or ""),
                    project=str(project_id) if project_id else None,
                    metadata={
                        "model": model,
                        "sku_id": sku_id,
                        "sku_description": sku_description,
                        "service_description": service_description,
                        "region": region or self.region,
                        "currency": currency or "USD",
                        "credits_amount": credits,
                        "gross_cost": round(cost_usd, 6),
                        "source": "bigquery_billing_export",
                    },
                )
            )
        return results

    @staticmethod
    def _service_slug(service_description: str | None) -> str:
        if not service_description:
            return "vertex_ai"
        mapping = {
            "vertex ai": "vertex_ai",
            "generative language api": "gemini_api",
            "ai platform": "vertex_ai",
        }
        return mapping.get(service_description.strip().lower(), "vertex_ai")

    # -------------------------------------------------- SKU catalog (optional)

    def refresh_pricing_from_catalog(self) -> dict[str, dict[str, float]]:
        """Best-effort: refresh pricing from the Cloud Billing SKU catalog.

        Returns the merged pricing table on success, or the static
        ``MODEL_PRICING`` on any failure. Does NOT raise — callers may still
        operate with built-in prices.
        """
        if not self.service_account:
            return dict(MODEL_PRICING)

        try:
            token = self._get_access_token()
        except Exception:
            return dict(MODEL_PRICING)

        # Vertex AI service id (stable across projects).
        vertex_service_id = "services/F7F8-86C4-2D0E"  # Vertex AI
        genai_service_id = "services/CCD8-9BF1-090E"   # Generative Language API (best-effort)

        merged = dict(MODEL_PRICING)
        for service_id in (vertex_service_id, genai_service_id):
            try:
                resp = httpx.get(
                    f"https://cloudbilling.googleapis.com/v1/{service_id}/skus",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=30,
                )
            except httpx.HTTPError:
                continue
            if resp.status_code != 200:
                continue
            try:
                catalog = resp.json()
            except ValueError:
                continue
            for sku in catalog.get("skus", []) or []:
                _merge_sku_into_pricing(sku, merged)

        return merged


def _merge_sku_into_pricing(sku: dict[str, Any], table: dict[str, dict[str, float]]) -> None:
    """Fold a single SKU's tiered rate into the pricing table if it matches a known model.

    The Cloud Billing SKU shape is documented at
    https://cloud.google.com/billing/docs/reference/rest/v1/services.skus.
    We only pull the first tier's unit price for simplicity; context-tiered
    pricing stays hardcoded.
    """
    description = (sku.get("description") or "").lower()
    normalised_desc = description.replace("-", " ")
    model_key = None
    for key in sorted(table.keys(), key=len, reverse=True):
        key_space = key.replace("-", " ")
        if key in description or key_space in normalised_desc:
            model_key = key
            break
    if not model_key:
        return

    for pricing_info in sku.get("pricingInfo", []) or []:
        expression = pricing_info.get("pricingExpression") or {}
        tiered = expression.get("tieredRates") or []
        if not tiered:
            continue
        unit = (expression.get("usageUnit") or "").lower()
        rate = tiered[0].get("unitPrice") or {}
        units = float(rate.get("units") or 0)
        nanos = float(rate.get("nanos") or 0) / 1e9
        price_per_unit = units + nanos
        if price_per_unit <= 0:
            continue

        per_million = price_per_unit * 1000.0 if "1k" in unit or "1 k" in unit else price_per_unit * 1_000_000.0
        # Guess input vs output from the description.
        if "output" in description or "completion" in description:
            table.setdefault(model_key, {"input": 0.0, "output": 0.0})["output"] = round(per_million, 6)
        elif "input" in description or "prompt" in description:
            table.setdefault(model_key, {"input": 0.0, "output": 0.0})["input"] = round(per_million, 6)
        # else: ambiguous SKU — leave static price in place.
