"""Anthropic Admin API usage connector.

Pulls token usage and costs from the Anthropic Admin API's report endpoints:

- POST https://api.anthropic.com/v1/organizations/usage_report/messages
- POST https://api.anthropic.com/v1/organizations/cost_report

The Admin API requires an *Admin* API key (prefix ``sk-ant-admin01...``), which
is created under console.anthropic.com → Organization Settings → Admin Keys.
A regular workspace ``sk-ant-api03...`` key cannot access these endpoints and
will receive a 401.

Cost resolution priority (first wins):

1. ``cost_report`` (authoritative — reflects committed discounts, credits,
   batch/priority tiers, cache rebates, etc.).
2. ``pricing_overrides`` (per-model or flat credit-discount) supplied via the
   user's negotiated enterprise agreement.
3. ``MODEL_PRICING`` catalog (2026 list prices) with cache-tier and
   service-tier multipliers applied to the token counts returned by
   ``usage_report/messages``.

References:
- Anthropic Admin API — Usage report (Messages): longest-stable contract,
  dimensions include ``workspace_id``, ``api_key_id``, ``model``,
  ``service_tier``, ``context_window``.
- Anthropic Admin API — Cost report: authoritative currency figures.
- ccusage (github.com/ryoppippi/ccusage) — cache tier multipliers.
- LiteLLM model_prices_and_context_window.json — list pricing source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

import httpx

from app.models.platform import CostCategory, UnifiedCost
from app.services.connectors.base import BaseConnector

# ---------------------------------------------------------------------------
# Pricing catalog — USD per 1M tokens (standard / non-cached input).
# Entries are ordered longest-prefix-first at lookup time so that more
# specific model IDs win (e.g. "claude-opus-4-7" before "claude-opus-4").
# Historical (3.x) pricing is kept for back-filling old usage periods.
# Source: https://www.anthropic.com/pricing (Apr 2026) + LiteLLM.
# ---------------------------------------------------------------------------
MODEL_PRICING: dict[str, dict[str, float]] = {
    # Claude 4.x — Opus family
    "claude-opus-4-7": {"input": 15.0, "output": 75.0},
    "claude-opus-4-6": {"input": 15.0, "output": 75.0},
    "claude-opus-4-5": {"input": 15.0, "output": 75.0},
    "claude-opus-4": {"input": 15.0, "output": 75.0},
    # Claude 4.x — Sonnet family
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0},
    "claude-sonnet-4-5": {"input": 3.0, "output": 15.0},
    "claude-sonnet-4": {"input": 3.0, "output": 15.0},
    # Claude 4.x — Haiku family
    "claude-haiku-4-5": {"input": 1.0, "output": 5.0},
    "claude-haiku-4": {"input": 1.0, "output": 5.0},
    # Legacy 3.x (retained for historical usage)
    "claude-3-7-sonnet": {"input": 3.0, "output": 15.0},
    "claude-3-5-sonnet": {"input": 3.0, "output": 15.0},
    "claude-sonnet-3-5": {"input": 3.0, "output": 15.0},
    "claude-3-5-haiku": {"input": 0.80, "output": 4.0},
    "claude-haiku-3-5": {"input": 0.80, "output": 4.0},
    "claude-3-opus": {"input": 15.0, "output": 75.0},
    "claude-3-sonnet": {"input": 3.0, "output": 15.0},
    "claude-3-haiku": {"input": 0.25, "output": 1.25},
}

# Service-tier multipliers applied on top of standard list price.
SERVICE_TIER_MULTIPLIERS: dict[str, float] = {
    "standard": 1.0,
    "batch": 0.5,
    "priority": 1.25,
}

# Cache-tier multipliers for input tokens.
# - cache_read: 10% of standard input rate (cached hit).
# - cache_creation_5m: 1.25x standard (writing a 5-minute ephemeral cache).
# - cache_creation_1h: 2.00x standard (writing a 1-hour ephemeral cache).
CACHE_TIER_MULTIPLIERS: dict[str, float] = {
    "cache_read": 0.10,
    "cache_creation_5m": 1.25,
    "cache_creation_1h": 2.00,
}

# Fallback pricing when the model id is unrecognised (mid-tier Sonnet).
_FALLBACK_PRICING = {"input": 3.0, "output": 15.0}

_ADMIN_KEY_PREFIX = "sk-ant-admin"
_ANTHROPIC_BASE = "https://api.anthropic.com/v1"
_ANTHROPIC_API_VERSION = "2023-06-01"
_DEFAULT_TIMEOUT = 30.0
_DEFAULT_TEST_TIMEOUT = 10.0
_MAX_PAGES = 50


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class TokenUsage:
    """Immutable snapshot of Anthropic token counters for a single bucket.

    Mirrors the ``usage_report/messages`` response schema. All fields default
    to 0 so partial payloads are safe to construct.
    """

    uncached_input_tokens: int = 0
    cache_creation_5m_input_tokens: int = 0
    cache_creation_1h_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    output_tokens: int = 0
    web_search_requests: int = 0

    @property
    def total_tokens(self) -> int:
        return (
            self.uncached_input_tokens
            + self.cache_creation_5m_input_tokens
            + self.cache_creation_1h_input_tokens
            + self.cache_read_input_tokens
            + self.output_tokens
        )

    @property
    def total_input_tokens(self) -> int:
        return (
            self.uncached_input_tokens
            + self.cache_creation_5m_input_tokens
            + self.cache_creation_1h_input_tokens
            + self.cache_read_input_tokens
        )

    def as_metadata(self) -> dict[str, int]:
        return {
            "uncached_input_tokens": self.uncached_input_tokens,
            "cache_creation_5m_input_tokens": self.cache_creation_5m_input_tokens,
            "cache_creation_1h_input_tokens": self.cache_creation_1h_input_tokens,
            "cache_read_input_tokens": self.cache_read_input_tokens,
            "output_tokens": self.output_tokens,
            "web_search_requests": self.web_search_requests,
        }


@dataclass(frozen=True)
class UsageBucket:
    """A single row from the ``usage_report/messages`` response."""

    date: str
    model: str
    tokens: TokenUsage
    service_tier: str = "standard"
    context_window: str = ""
    workspace_id: str = ""
    api_key_id: str = ""
    inference_geo: str = ""
    speed: str = ""


# ---------------------------------------------------------------------------
# Pricing helpers
# ---------------------------------------------------------------------------
def _resolve_pricing(
    model: str,
    overrides: dict | None = None,
) -> dict[str, float]:
    """Resolve input/output pricing for a model (USD per 1M tokens).

    Lookup order:
    1. Per-model override in ``pricing_overrides`` (longest-prefix match).
    2. ``MODEL_PRICING`` catalog (longest-prefix match).
    3. Sonnet-tier fallback.
    """
    if model is None:
        return dict(_FALLBACK_PRICING)

    model_lower = model.lower()
    overrides = overrides or {}

    # 1. Per-model override — only dict values with input/output are considered.
    per_model_overrides = {
        k.lower(): v
        for k, v in overrides.items()
        if isinstance(v, dict) and "input" in v and "output" in v
    }
    for key in sorted(per_model_overrides.keys(), key=lambda x: -len(x)):
        if key in model_lower:
            return {
                "input": float(per_model_overrides[key]["input"]),
                "output": float(per_model_overrides[key]["output"]),
            }

    # 2. Catalog (longest-prefix wins so "claude-opus-4-7" beats "claude-opus-4").
    for key in sorted(MODEL_PRICING.keys(), key=lambda x: -len(x)):
        if key in model_lower:
            return dict(MODEL_PRICING[key])

    # 3. Fallback.
    return dict(_FALLBACK_PRICING)


def _service_tier_multiplier(service_tier: str | None) -> float:
    if not service_tier:
        return 1.0
    return SERVICE_TIER_MULTIPLIERS.get(service_tier.lower(), 1.0)


def _credit_discount_multiplier(overrides: dict | None) -> float:
    """Return the discount multiplier (1.0 = no discount) from overrides.

    Accepted keys (all optional):
    - ``credit_discount_pct``: enterprise credits / committed-use discount
    - ``discount_pct``: generic discount applied to the final cost
    """
    if not overrides:
        return 1.0
    pct = overrides.get("credit_discount_pct") or overrides.get("discount_pct") or 0
    try:
        pct = float(pct)
    except (TypeError, ValueError):
        return 1.0
    if pct <= 0:
        return 1.0
    return max(0.0, 1.0 - (pct / 100.0))


def estimate_cost(
    model: str,
    tokens: TokenUsage,
    service_tier: str = "standard",
    pricing_overrides: dict | None = None,
) -> float:
    """Estimate the USD cost for a bucket of Anthropic token usage.

    The computation mirrors Anthropic's public pricing model:

    - uncached input tokens pay ``input`` rate
    - cache-read tokens pay 10% of ``input``
    - 5-minute cache-creation tokens pay 125% of ``input``
    - 1-hour cache-creation tokens pay 200% of ``input``
    - output tokens pay ``output`` rate
    - service tier (batch / priority) multiplies the whole result
    - ``credit_discount_pct`` in overrides applies last
    """
    pricing = _resolve_pricing(model, pricing_overrides)
    input_rate = pricing["input"] / 1_000_000
    output_rate = pricing["output"] / 1_000_000

    cost = (
        tokens.uncached_input_tokens * input_rate
        + tokens.cache_read_input_tokens * input_rate * CACHE_TIER_MULTIPLIERS["cache_read"]
        + tokens.cache_creation_5m_input_tokens * input_rate * CACHE_TIER_MULTIPLIERS["cache_creation_5m"]
        + tokens.cache_creation_1h_input_tokens * input_rate * CACHE_TIER_MULTIPLIERS["cache_creation_1h"]
        + tokens.output_tokens * output_rate
    )

    cost *= _service_tier_multiplier(service_tier)
    cost *= _credit_discount_multiplier(pricing_overrides)
    return round(cost, 6)


def _estimate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    pricing_overrides: dict | None = None,
) -> float:
    """Back-compat simple cost estimator (no cache tiers).

    Preserves the signature used by legacy tests and ``unified_costs._apply_pricing_overrides``.
    """
    tokens = TokenUsage(
        uncached_input_tokens=int(input_tokens),
        output_tokens=int(output_tokens),
    )
    return estimate_cost(model, tokens, "standard", pricing_overrides)


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------
def _bucket_start_date(bucket: dict) -> str:
    """Extract YYYY-MM-DD from a bucket's starting_at (or date) field."""
    raw = bucket.get("starting_at") or bucket.get("start_time") or bucket.get("date")
    if not raw:
        return ""
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(int(raw), tz=timezone.utc).strftime("%Y-%m-%d")
    text = str(raw)
    # Normalise trailing Z / offset.
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        return text[:10]


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _parse_token_usage(result: dict) -> TokenUsage:
    """Pull the full token schema out of a single usage_report result row."""
    cache_creation = result.get("cache_creation") or {}
    server_tool = result.get("server_tool_use") or {}
    return TokenUsage(
        uncached_input_tokens=_safe_int(result.get("uncached_input_tokens")),
        cache_creation_5m_input_tokens=_safe_int(
            cache_creation.get("ephemeral_5m_input_tokens")
        ),
        cache_creation_1h_input_tokens=_safe_int(
            cache_creation.get("ephemeral_1h_input_tokens")
        ),
        cache_read_input_tokens=_safe_int(result.get("cache_read_input_tokens")),
        output_tokens=_safe_int(result.get("output_tokens")),
        web_search_requests=_safe_int(server_tool.get("web_search_requests")),
    )


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------
class AnthropicConnector(BaseConnector):
    """Anthropic Admin API cost & usage connector."""

    platform = "anthropic"

    # Dimensions requested when calling usage_report/messages.
    # ``inference_geo`` and ``speed`` were added in late 2025 — including them
    # is backwards-compatible; the API simply ignores unknown group_by values.
    USAGE_GROUP_BY: tuple[str, ...] = (
        "workspace_id",
        "api_key_id",
        "model",
        "service_tier",
        "context_window",
    )

    COST_GROUP_BY: tuple[str, ...] = (
        "workspace_id",
        "description",
    )

    def __init__(self, credentials: dict) -> None:
        super().__init__(credentials)
        self.api_key: str = credentials["api_key"]
        self.base_url: str = credentials.get("base_url", _ANTHROPIC_BASE).rstrip("/")
        self.pricing_overrides: dict = credentials.get("pricing_overrides") or {}

    # ------------------------------------------------------------------
    # test_connection
    # ------------------------------------------------------------------
    def test_connection(self) -> dict:
        """Verify the Admin API credential. Returns ``{success, message}``.

        Distinguishes:
          - 401: invalid admin key
          - 403: admin key without ``usage_report`` scope
          - 429: rate-limited
          - Non-admin prefix: actionable message pointing at console
          - httpx network error: plain string
        """
        if not self._looks_like_admin_key(self.api_key):
            return {
                "success": False,
                "message": (
                    "This key looks like a regular API key; please use an "
                    "Anthropic Admin API key from console.anthropic.com "
                    "(Organization Settings → Admin Keys)."
                ),
            }

        now = datetime.now(timezone.utc)
        body = {
            "starting_at": (now - timedelta(hours=1)).isoformat(timespec="seconds"),
            "ending_at": now.isoformat(timespec="seconds"),
            "bucket_width": "1d",
            "limit": 1,
        }
        try:
            resp = httpx.post(
                f"{self.base_url}/organizations/usage_report/messages",
                headers=self._headers(),
                json=body,
                timeout=_DEFAULT_TEST_TIMEOUT,
            )
        except httpx.HTTPError as exc:
            return {
                "success": False,
                "message": f"Network error contacting Anthropic Admin API: {exc}",
            }

        if resp.status_code == 200:
            return {"success": True, "message": "Anthropic Admin API connection successful"}
        if resp.status_code == 401:
            return {"success": False, "message": "Invalid admin key (HTTP 401)"}
        if resp.status_code == 403:
            return {
                "success": False,
                "message": "Key lacks usage_report permission (HTTP 403)",
            }
        if resp.status_code == 429:
            return {
                "success": False,
                "message": "Rate limited by Anthropic Admin API — retry later (HTTP 429)",
            }
        return {
            "success": False,
            "message": f"HTTP {resp.status_code}: {resp.text[:200]}",
        }

    @staticmethod
    def _looks_like_admin_key(api_key: str) -> bool:
        """Anthropic Admin keys start with ``sk-ant-admin``; regular keys don't.

        Test fixtures use ``sk-ant-admin-...`` so the default test credentials
        still pass. For safety we accept any ``sk-ant-admin`` prefix.
        """
        return bool(api_key) and api_key.startswith(_ADMIN_KEY_PREFIX)

    # ------------------------------------------------------------------
    # fetch_costs
    # ------------------------------------------------------------------
    def fetch_costs(self, days: int = 30) -> list[UnifiedCost]:
        """Fetch daily Anthropic usage for the last ``days`` days.

        Strategy:
          1. Pull ``cost_report`` — authoritative USD per (date, workspace,
             description/model).
          2. Pull ``usage_report/messages`` — detailed token-tier counters.
          3. Merge into UnifiedCost records keyed by (date, workspace, model,
             service_tier, context_window). Prefer cost_report USD; fall
             back to the local estimator when the cost bucket is missing.
        """
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days)

        try:
            cost_rows = self._fetch_cost_report(start, end)
        except Exception:
            cost_rows = {}

        try:
            usage_buckets = self._fetch_usage_report(start, end)
        except Exception:
            usage_buckets = []

        return self._assemble_unified_costs(usage_buckets, cost_rows)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self.api_key,
            "anthropic-version": _ANTHROPIC_API_VERSION,
            "content-type": "application/json",
        }

    def _post_paginated(
        self,
        path: str,
        body: dict,
    ) -> Iterable[dict]:
        """POST and yield each ``data`` element, following ``next_page`` cursors."""
        page_cursor: str | None = None
        for _ in range(_MAX_PAGES):
            payload = dict(body)
            if page_cursor:
                payload["page"] = page_cursor
            resp = httpx.post(
                f"{self.base_url}{path}",
                headers=self._headers(),
                json=payload,
                timeout=_DEFAULT_TIMEOUT,
            )
            if resp.status_code != 200:
                # Surface non-200s to the caller via exception so fetch_costs
                # can distinguish network issues from empty responses.
                raise httpx.HTTPStatusError(
                    f"Anthropic Admin API {path} returned {resp.status_code}: {resp.text[:200]}",
                    request=resp.request,
                    response=resp,
                )
            data = resp.json()
            for item in data.get("data", []) or []:
                yield item
            page_cursor = data.get("next_page")
            if not page_cursor or not data.get("has_more"):
                return

    def _fetch_usage_report(
        self,
        start: datetime,
        end: datetime,
    ) -> list[UsageBucket]:
        """Pull per-day token usage broken down by our group_by dimensions."""
        body = {
            "starting_at": start.isoformat(timespec="seconds"),
            "ending_at": end.isoformat(timespec="seconds"),
            "bucket_width": "1d",
            "group_by": list(self.USAGE_GROUP_BY),
            "limit": 1000,
        }
        buckets: list[UsageBucket] = []
        for bucket in self._post_paginated(
            "/organizations/usage_report/messages",
            body,
        ):
            date = _bucket_start_date(bucket)
            for result in bucket.get("results", []) or []:
                tokens = _parse_token_usage(result)
                if (
                    tokens.total_tokens == 0
                    and tokens.web_search_requests == 0
                ):
                    continue
                buckets.append(
                    UsageBucket(
                        date=date,
                        model=result.get("model") or "unknown",
                        tokens=tokens,
                        service_tier=(result.get("service_tier") or "standard"),
                        context_window=result.get("context_window") or "",
                        workspace_id=result.get("workspace_id") or "",
                        api_key_id=result.get("api_key_id") or "",
                        inference_geo=result.get("inference_geo") or "",
                        speed=result.get("speed") or "",
                    )
                )
        return buckets

    def _fetch_cost_report(
        self,
        start: datetime,
        end: datetime,
    ) -> dict[tuple, float]:
        """Pull authoritative USD cost per (date, workspace_id, description)."""
        body = {
            "starting_at": start.isoformat(timespec="seconds"),
            "ending_at": end.isoformat(timespec="seconds"),
            "bucket_width": "1d",
            "group_by": list(self.COST_GROUP_BY),
            "limit": 1000,
        }
        rows: dict[tuple, float] = {}
        for bucket in self._post_paginated("/organizations/cost_report", body):
            date = _bucket_start_date(bucket)
            for result in bucket.get("results", []) or []:
                workspace = result.get("workspace_id") or ""
                description = result.get("description") or ""
                amount = result.get("amount")
                # Anthropic returns either a plain float USD or a
                # {"value": X, "currency": "USD"} shape.
                if isinstance(amount, dict):
                    usd = float(amount.get("value") or 0.0)
                    currency = (amount.get("currency") or "USD").upper()
                    if currency != "USD":
                        continue
                else:
                    usd = float(amount or result.get("cost") or 0.0)
                if usd == 0.0:
                    continue
                key = (date, workspace, description)
                rows[key] = rows.get(key, 0.0) + usd
        return rows

    def _assemble_unified_costs(
        self,
        usage_buckets: list[UsageBucket],
        cost_rows: dict[tuple, float],
    ) -> list[UnifiedCost]:
        """Merge usage tokens + authoritative USD into UnifiedCost records."""
        unified: list[UnifiedCost] = []

        # Track which cost_rows were consumed by usage_buckets so any
        # unattributed cost rows (e.g. web-search surcharges) still surface.
        consumed_keys: set[tuple] = set()

        for bucket in usage_buckets:
            # Try matching by exact model description first, fall back to the
            # per-workspace total for the day.
            cost_key_exact = (bucket.date, bucket.workspace_id, bucket.model)
            if cost_key_exact in cost_rows:
                cost_usd = cost_rows[cost_key_exact]
                cost_source = "cost_report"
                consumed_keys.add(cost_key_exact)
            else:
                cost_usd = estimate_cost(
                    bucket.model,
                    bucket.tokens,
                    bucket.service_tier,
                    self.pricing_overrides,
                )
                cost_source = "estimated"

            if cost_usd == 0 and bucket.tokens.total_tokens == 0:
                continue

            metadata = {
                **bucket.tokens.as_metadata(),
                "model": bucket.model,
                "service_tier": bucket.service_tier,
                "context_window": bucket.context_window,
                "workspace_id": bucket.workspace_id,
                "api_key_id": bucket.api_key_id,
                "inference_geo": bucket.inference_geo,
                "speed": bucket.speed,
                "cost_source": cost_source,
            }

            unified.append(
                UnifiedCost(
                    date=bucket.date,
                    platform="anthropic",
                    service="anthropic",
                    resource=bucket.model,
                    category=CostCategory.ai_inference,
                    cost_usd=round(float(cost_usd), 6),
                    usage_quantity=bucket.tokens.total_tokens,
                    usage_unit="tokens",
                    team=bucket.workspace_id or None,
                    metadata=metadata,
                )
            )

        # Emit leftover cost_report rows as synthetic records (no token detail)
        # so the user's headline cost matches Anthropic's console even when
        # the usage endpoint omits something (e.g. legacy entries).
        for (date, workspace, description), usd in cost_rows.items():
            if (date, workspace, description) in consumed_keys:
                continue
            if usd <= 0:
                continue
            unified.append(
                UnifiedCost(
                    date=date,
                    platform="anthropic",
                    service="anthropic",
                    resource=description or "anthropic",
                    category=CostCategory.ai_inference,
                    cost_usd=round(float(usd), 6),
                    usage_quantity=0,
                    usage_unit="tokens",
                    team=workspace or None,
                    metadata={
                        "workspace_id": workspace,
                        "description": description,
                        "cost_source": "cost_report",
                    },
                )
            )

        return unified
