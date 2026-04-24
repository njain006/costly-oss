"""OpenAI API usage connector.

Pulls token usage and spend from OpenAI's Organization Usage and Costs APIs.
Requires an Admin API key (platform.openai.com → Organization → Admin Keys).

Design:
  * Preferred source of truth for ``cost_usd`` is the Costs API
    (``/v1/organization/costs``), which returns dollar amounts authoritatively.
  * Token / request dimensions come from the eight per-bucket Usage endpoints
    (completions, embeddings, moderations, images, audio_speeches,
    audio_transcriptions, vector_stores, code_interpreter_sessions).
  * Per-bucket token counts fall back to local pricing (``MODEL_PRICING``) when
    the Costs API is unavailable.

Pricing data (April 2026) is sourced from OpenAI's public pricing page:
https://platform.openai.com/docs/pricing and cross-referenced with LiteLLM's
model_prices_and_context_window.json. Rates are per 1M tokens except
``per_image`` / ``per_minute`` / ``per_1m_chars`` fields.

References:
  - https://platform.openai.com/docs/api-reference/usage
  - https://platform.openai.com/docs/api-reference/usage/costs
  - https://platform.openai.com/docs/guides/batch  (50% batch discount)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

import httpx

from app.models.platform import CostCategory, UnifiedCost
from app.services.connectors.base import BaseConnector

logger = logging.getLogger(__name__)

USAGE_ENDPOINTS: tuple[str, ...] = (
    "completions",
    "embeddings",
    "moderations",
    "images",
    "audio_speeches",
    "audio_transcriptions",
    "vector_stores",
    "code_interpreter_sessions",
)

# Batch API discount applied to both input and output legs.
BATCH_DISCOUNT = 0.5

# Default group_by dimensions per endpoint (vector_stores and
# code_interpreter_sessions only expose project_id).
_FULL_GROUP_BY = ("model", "project_id", "user_id", "api_key_id", "batch")
_PROJECT_ONLY = ("project_id",)
ENDPOINT_GROUP_BY: dict[str, tuple[str, ...]] = {
    "completions": _FULL_GROUP_BY,
    "embeddings": ("model", "project_id", "user_id", "api_key_id"),
    "moderations": ("model", "project_id", "user_id", "api_key_id"),
    "images": ("model", "project_id", "user_id", "api_key_id", "size", "source"),
    "audio_speeches": ("model", "project_id", "user_id", "api_key_id"),
    "audio_transcriptions": ("model", "project_id", "user_id", "api_key_id"),
    "vector_stores": _PROJECT_ONLY,
    "code_interpreter_sessions": _PROJECT_ONLY,
}


@dataclass(frozen=True)
class ModelPricing:
    """Pricing for a single model SKU.

    All token rates are USD per 1M tokens. ``cached_input`` defaults to ``input``
    when no cached rate is advertised (i.e. no prompt-cache discount).
    """

    input: float = 0.0
    output: float = 0.0
    cached_input: Optional[float] = None
    per_image: float = 0.0
    per_minute: float = 0.0  # whisper-1 per audio minute
    per_1m_chars: float = 0.0  # tts-1/hd per 1M characters
    per_session: float = 0.0  # code_interpreter_sessions
    per_gb_month: float = 0.0  # vector_stores storage

    def effective_cached(self) -> float:
        return self.input if self.cached_input is None else self.cached_input


# ---------------------------------------------------------------------------
# 2026 pricing table (USD per 1M tokens unless noted).
# Kept in one place so tests and pricing_overrides can inspect / extend it.
# ---------------------------------------------------------------------------
MODEL_PRICING: dict[str, ModelPricing] = {
    # GPT-5 family (Aug 2025+). 90% prompt-cache discount on input.
    "gpt-5": ModelPricing(input=1.25, cached_input=0.125, output=10.0),
    "gpt-5-mini": ModelPricing(input=0.25, cached_input=0.025, output=2.0),
    "gpt-5-nano": ModelPricing(input=0.05, cached_input=0.005, output=0.40),
    "gpt-5-chat-latest": ModelPricing(input=1.25, cached_input=0.125, output=10.0),
    # GPT-4.1 family (long-context, 1M window).
    "gpt-4.1": ModelPricing(input=2.0, cached_input=0.50, output=8.0),
    "gpt-4.1-mini": ModelPricing(input=0.40, cached_input=0.10, output=1.60),
    "gpt-4.1-nano": ModelPricing(input=0.10, cached_input=0.025, output=0.40),
    # GPT-4o / GPT-4 legacy.
    "gpt-4o": ModelPricing(input=2.50, cached_input=1.25, output=10.0),
    "gpt-4o-mini": ModelPricing(input=0.15, cached_input=0.075, output=0.60),
    "gpt-4o-audio-preview": ModelPricing(input=2.50, cached_input=1.25, output=10.0),
    "gpt-4-turbo": ModelPricing(input=10.0, output=30.0),
    "gpt-4": ModelPricing(input=30.0, output=60.0),
    "gpt-3.5-turbo": ModelPricing(input=0.50, output=1.50),
    # Reasoning (o-series). Jun 2025 o3 ~80% price drop, o4-mini released.
    "o1": ModelPricing(input=15.0, cached_input=7.50, output=60.0),
    "o1-mini": ModelPricing(input=1.10, cached_input=0.55, output=4.40),
    "o1-pro": ModelPricing(input=150.0, output=600.0),
    "o3": ModelPricing(input=2.0, cached_input=0.50, output=8.0),
    "o3-mini": ModelPricing(input=1.10, cached_input=0.55, output=4.40),
    "o3-pro": ModelPricing(input=20.0, output=80.0),
    "o4": ModelPricing(input=4.0, cached_input=1.0, output=16.0),
    "o4-mini": ModelPricing(input=1.10, cached_input=0.275, output=4.40),
    # Computer-use agent.
    "computer-use-preview": ModelPricing(input=3.0, cached_input=0.75, output=12.0),
    # Embeddings (no output tokens billed).
    "text-embedding-3-small": ModelPricing(input=0.02),
    "text-embedding-3-large": ModelPricing(input=0.13),
    "text-embedding-ada-002": ModelPricing(input=0.10),
    # Moderation (free as of April 2026 but keep an explicit zero to avoid
    # fallback pricing).
    "omni-moderation-latest": ModelPricing(),
    "text-moderation-latest": ModelPricing(),
    # Images — billed per-image. Token fields stay 0 so text tokens on edits
    # are charged via the Costs API.
    "dall-e-3": ModelPricing(per_image=0.040),  # 1024x1024 standard
    "dall-e-2": ModelPricing(per_image=0.020),  # 1024x1024
    "gpt-image-1": ModelPricing(input=5.0, cached_input=1.25, output=40.0, per_image=0.040),
    # Audio.
    "whisper-1": ModelPricing(per_minute=0.006),
    "tts-1": ModelPricing(per_1m_chars=15.0),
    "tts-1-hd": ModelPricing(per_1m_chars=30.0),
    # Storage / session products.
    "code-interpreter": ModelPricing(per_session=0.03),
    "code_interpreter": ModelPricing(per_session=0.03),
    "vector-store": ModelPricing(per_gb_month=0.10),
    "vector_store": ModelPricing(per_gb_month=0.10),
}

_FALLBACK = ModelPricing(input=2.50, cached_input=1.25, output=10.0)


# Strip common date-suffixes OpenAI appends to model IDs (e.g. gpt-4o-2024-08-06).
_DATE_SUFFIX_RE = re.compile(r"-(?:\d{8}|\d{4}-\d{2}-\d{2}|\d{4})$")


def _normalize_model(model: str) -> str:
    s = (model or "").strip().lower()
    return _DATE_SUFFIX_RE.sub("", s)


def _resolve_pricing(
    model: str,
    overrides: Optional[dict] = None,
) -> ModelPricing:
    """Resolve pricing for a model identifier.

    Lookup order:
      1. ``pricing_overrides[model]`` (exact match), then longest-prefix match.
      2. ``MODEL_PRICING`` exact match on the date-stripped model string.
      3. ``MODEL_PRICING`` anchored-prefix match (``gpt-4o-mini`` matches
         ``gpt-4o-mini-2024-07-18`` but ``gpt-4`` does NOT match
         ``gpt-4o-mini``).
      4. ``_FALLBACK`` (GPT-4o rates).
    """

    normalized = _normalize_model(model)

    if overrides:
        resolved = _resolve_from_overrides(normalized, overrides)
        if resolved is not None:
            return resolved

    # Exact match on the full normalized model.
    if normalized in MODEL_PRICING:
        return MODEL_PRICING[normalized]

    # Anchored prefix match: walk keys longest-first, require that the model
    # either equals the key or extends it with a "-" (so "gpt-4" will NOT
    # match "gpt-4o-mini", and "gpt-4o" will NOT match "gpt-4o-mini").
    for key in sorted(MODEL_PRICING.keys(), key=lambda k: -len(k)):
        if normalized == key or normalized.startswith(key + "-"):
            return MODEL_PRICING[key]

    return _FALLBACK


def _resolve_from_overrides(
    normalized_model: str, overrides: dict
) -> Optional[ModelPricing]:
    """Look up an override for ``normalized_model``. Exact match wins; then
    longest-prefix anchored match.
    """
    # Exact match.
    if normalized_model in overrides:
        return _coerce_override(overrides[normalized_model])

    # Anchored-prefix match.
    keys = sorted(
        (k for k in overrides if isinstance(overrides.get(k), (dict, ModelPricing))),
        key=lambda k: -len(k),
    )
    for key in keys:
        k = key.lower()
        if normalized_model == k or normalized_model.startswith(k + "-"):
            return _coerce_override(overrides[key])
    return None


def _coerce_override(raw: Any) -> ModelPricing:
    if isinstance(raw, ModelPricing):
        return raw
    if isinstance(raw, dict):
        return ModelPricing(
            input=float(raw.get("input", 0.0) or 0.0),
            output=float(raw.get("output", 0.0) or 0.0),
            cached_input=(
                float(raw["cached_input"])
                if raw.get("cached_input") is not None
                else None
            ),
            per_image=float(raw.get("per_image", 0.0) or 0.0),
            per_minute=float(raw.get("per_minute", 0.0) or 0.0),
            per_1m_chars=float(raw.get("per_1m_chars", 0.0) or 0.0),
            per_session=float(raw.get("per_session", 0.0) or 0.0),
            per_gb_month=float(raw.get("per_gb_month", 0.0) or 0.0),
        )
    raise TypeError(f"pricing override must be dict or ModelPricing, got {type(raw)!r}")


@dataclass(frozen=True)
class TokenUsage:
    """Canonical per-line usage record before conversion to ``UnifiedCost``."""

    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    reasoning_tokens: int = 0
    input_audio_tokens: int = 0
    output_audio_tokens: int = 0
    images: int = 0
    characters: int = 0
    seconds: float = 0.0
    num_sessions: int = 0
    usage_bytes: int = 0
    num_requests: int = 0
    batch: bool = False


def estimate_cost(
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cached_input_tokens: int = 0,
    reasoning_tokens: int = 0,
    images: int = 0,
    characters: int = 0,
    seconds: float = 0.0,
    num_sessions: int = 0,
    usage_bytes: int = 0,
    is_batch: bool = False,
    pricing_overrides: Optional[dict] = None,
) -> float:
    """Estimate cost in USD for a single usage line.

    - ``input_tokens`` is total input *including* cached prompt tokens (per the
      Usage API contract). Uncached tokens are ``input_tokens - cached_input``.
    - Reasoning tokens (o-series, gpt-5) are billed at the output rate.
    - Batch API rows get a 50% discount applied to input/output legs.
    """
    p = _resolve_pricing(model, pricing_overrides)

    uncached = max(0, input_tokens - cached_input_tokens)
    cached = max(0, min(input_tokens, cached_input_tokens))

    input_cost = (uncached / 1_000_000) * p.input
    cached_cost = (cached / 1_000_000) * p.effective_cached()
    output_cost = ((output_tokens + max(0, reasoning_tokens)) / 1_000_000) * p.output

    if is_batch:
        discount = BATCH_DISCOUNT
        input_cost *= discount
        cached_cost *= discount
        output_cost *= discount

    # Non-token dimensions are NOT subject to batch discount (OpenAI doesn't
    # publish a batch rate for audio/image endpoints).
    image_cost = images * p.per_image
    audio_minutes_cost = (seconds / 60.0) * p.per_minute
    tts_cost = (characters / 1_000_000) * p.per_1m_chars
    session_cost = num_sessions * p.per_session
    storage_cost = (usage_bytes / 1_073_741_824) * p.per_gb_month  # GiB

    total = (
        input_cost
        + cached_cost
        + output_cost
        + image_cost
        + audio_minutes_cost
        + tts_cost
        + session_cost
        + storage_cost
    )
    return round(total, 6)


# Backwards compatibility for existing callers / tests.
def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    return estimate_cost(model, input_tokens=input_tokens, output_tokens=output_tokens)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _fmt_date(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def _as_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "batch")
    return bool(v)


def _merge_metadata(
    bucket_type: str, result: dict, batch_flag: bool
) -> dict:
    """Carry through all OpenAI group_by attribution fields so downstream
    consumers can tag/filter by project/user/api key.
    """
    md: dict[str, Any] = {"type": bucket_type, "batch": batch_flag}
    for k in (
        "model",
        "project_id",
        "user_id",
        "api_key_id",
        "service_tier",
        "size",
        "source",
    ):
        v = result.get(k)
        if v not in (None, ""):
            md[k] = v
    return md


def _category_for(bucket_type: str) -> CostCategory:
    # Every OpenAI SKU is inference-adjacent; keep the category uniform so
    # unified dashboards don't fragment AI inference across sub-categories.
    return CostCategory.ai_inference


# Pretty resource names for the non-model endpoints.
_DEFAULT_RESOURCE = {
    "vector_stores": "vector_store",
    "code_interpreter_sessions": "code_interpreter",
    "audio_speeches": "tts",
    "audio_transcriptions": "whisper",
    "images": "images",
    "moderations": "moderations",
}


class OpenAIConnector(BaseConnector):
    """OpenAI usage + cost connector."""

    platform = "openai"

    # HTTP timeouts.
    _CONNECT_TIMEOUT = 10
    _FETCH_TIMEOUT = 30
    # Pagination safety cap (365 daily buckets * ~50 group combinations is
    # well under this; we hard-stop to avoid runaway loops on malformed APIs).
    _MAX_PAGES = 200

    def __init__(self, credentials: dict):
        super().__init__(credentials)
        self.api_key: str = credentials["api_key"]
        self.org_id: Optional[str] = credentials.get("org_id")
        self.base_url: str = credentials.get(
            "base_url", "https://api.openai.com/v1"
        ).rstrip("/")
        # In-connector pricing overrides (also applied centrally by
        # unified_costs._apply_pricing_overrides, but supporting both levels
        # lets programmatic callers inject custom rates without DB setup).
        self.pricing_overrides: dict = credentials.get("pricing_overrides") or {}

    # ---------------------------------------------------------------
    # Connection test
    # ---------------------------------------------------------------
    def _headers(self) -> dict:
        h = {"Authorization": f"Bearer {self.api_key}"}
        if self.org_id:
            h["OpenAI-Organization"] = self.org_id
        return h

    def test_connection(self) -> dict:
        """Validate the API key and Admin scope.

        Returns distinct messages for:
          - 401 Unauthorized (invalid key)
          - 403 Forbidden     (key is valid but lacks admin scope)
          - 429 Too Many Reqs (rate limited)
          - network / other   (exception)
        """
        try:
            resp = httpx.get(
                f"{self.base_url}/models",
                headers=self._headers(),
                timeout=self._CONNECT_TIMEOUT,
            )
        except httpx.RequestError as exc:
            return {"success": False, "message": f"Network error: {exc}"}
        except Exception as exc:  # pragma: no cover — defensive
            return {"success": False, "message": str(exc)}

        if resp.status_code == 401:
            return {"success": False, "message": "Invalid API key (HTTP 401)"}
        if resp.status_code == 429:
            return {
                "success": False,
                "message": "Rate limited by OpenAI (HTTP 429) — retry later",
            }
        if resp.status_code != 200:
            return {
                "success": False,
                "message": f"HTTP {resp.status_code}: {resp.text[:200]}",
            }

        # Key is valid. Probe the Usage endpoint to check Admin scope.
        try:
            end = _utc_now()
            start = end - timedelta(days=1)
            usage_resp = httpx.get(
                f"{self.base_url}/organization/usage/completions",
                headers=self._headers(),
                params={
                    "start_time": int(start.timestamp()),
                    "end_time": int(end.timestamp()),
                    "bucket_width": "1d",
                    "limit": 1,
                },
                timeout=self._CONNECT_TIMEOUT,
            )
        except httpx.RequestError:
            # Core auth already succeeded — usage probe failure is non-fatal.
            return {
                "success": True,
                "message": "OpenAI API connection successful (usage probe failed)",
            }

        if usage_resp.status_code == 403:
            return {
                "success": False,
                "message": (
                    "Connected, but this key is not an Admin key. "
                    "Cost ingestion requires an Admin API key from "
                    "platform.openai.com → Organization → Admin keys."
                ),
            }
        if usage_resp.status_code == 401:
            return {"success": False, "message": "Admin key required (HTTP 401 on usage)"}
        if usage_resp.status_code == 429:
            return {
                "success": True,
                "message": "Connected; usage probe rate-limited (HTTP 429)",
            }
        if usage_resp.status_code != 200:
            return {
                "success": True,
                "message": (
                    f"Connected; usage probe returned HTTP "
                    f"{usage_resp.status_code}"
                ),
            }
        return {"success": True, "message": "OpenAI API connection successful"}

    # ---------------------------------------------------------------
    # fetch_costs
    # ---------------------------------------------------------------
    def fetch_costs(self, days: int = 30) -> list[UnifiedCost]:
        """Fetch costs for the last ``days`` days.

        Strategy:
          1. Pull token / request dimensions from every Usage bucket.
          2. Pull authoritative $ amounts from the Costs endpoint.
          3. Merge — prefer Costs $ when both are present (keyed by
             date + model + grouping dims).
        """
        end = _utc_now()
        start = end - timedelta(days=days)

        usage_records: list[UnifiedCost] = []
        try:
            usage_records = self._fetch_from_usage_api(start, end)
        except Exception as exc:
            logger.warning("OpenAI usage API fetch failed: %s", exc)

        costs_records: list[UnifiedCost] = []
        try:
            costs_records = self._fetch_from_costs_api(start, end)
        except Exception as exc:
            logger.warning("OpenAI costs API fetch failed: %s", exc)

        if not usage_records and not costs_records:
            return []

        return self._merge_usage_and_costs(usage_records, costs_records)

    # ---------------------------------------------------------------
    # Usage API
    # ---------------------------------------------------------------
    def _fetch_from_usage_api(
        self, start: datetime, end: datetime
    ) -> list[UnifiedCost]:
        records: list[UnifiedCost] = []
        for bucket_type in USAGE_ENDPOINTS:
            try:
                records.extend(self._fetch_usage_bucket(bucket_type, start, end))
            except Exception as exc:
                logger.warning(
                    "OpenAI usage bucket %s failed: %s", bucket_type, exc
                )
                continue
        return records

    def _fetch_usage_bucket(
        self, bucket_type: str, start: datetime, end: datetime
    ) -> list[UnifiedCost]:
        url = f"{self.base_url}/organization/usage/{bucket_type}"
        params: dict[str, Any] = {
            "start_time": int(start.timestamp()),
            "end_time": int(end.timestamp()),
            "bucket_width": "1d",
            "group_by": list(ENDPOINT_GROUP_BY[bucket_type]),
            "limit": 31,
        }
        out: list[UnifiedCost] = []
        for page in self._paginate(url, params):
            out.extend(self._convert_usage_page(bucket_type, page))
        return out

    def _convert_usage_page(
        self, bucket_type: str, page: dict
    ) -> list[UnifiedCost]:
        records: list[UnifiedCost] = []
        for bucket in page.get("data", []) or []:
            bucket_start = bucket.get("start_time", 0) or 0
            date = _fmt_date(bucket_start) if bucket_start else _fmt_date(
                int(_utc_now().timestamp())
            )
            for result in bucket.get("results", []) or []:
                usage = self._parse_usage_result(bucket_type, result)
                if usage is None:
                    continue
                cost = self._estimate_usage_cost(usage)
                raw_model = usage.model or _DEFAULT_RESOURCE.get(
                    bucket_type, bucket_type
                )
                # Strip date suffix so rollups aggregate across model
                # snapshots (gpt-4o-2024-08-06, gpt-4o-2024-11-20, …).
                resource = _normalize_model(raw_model) or raw_model
                total_quantity, unit = self._quantity_and_unit(usage)
                meta = _merge_metadata(bucket_type, result, usage.batch)
                # Prefer normalized (date-stripped) model for downstream
                # aggregation joins — the raw string remains on ``raw_model``.
                if "model" in meta:
                    meta["raw_model"] = meta["model"]
                    meta["model"] = resource
                records.append(
                    UnifiedCost(
                        date=date,
                        platform="openai",
                        service="openai",
                        resource=resource,
                        category=_category_for(bucket_type),
                        cost_usd=cost,
                        usage_quantity=total_quantity,
                        usage_unit=unit,
                        project=result.get("project_id"),
                        metadata={
                            **meta,
                            "input_tokens": usage.input_tokens,
                            "output_tokens": usage.output_tokens,
                            "cached_input_tokens": usage.cached_input_tokens,
                            "reasoning_tokens": usage.reasoning_tokens,
                            "input_audio_tokens": usage.input_audio_tokens,
                            "output_audio_tokens": usage.output_audio_tokens,
                            "images": usage.images,
                            "characters": usage.characters,
                            "seconds": usage.seconds,
                            "num_sessions": usage.num_sessions,
                            "usage_bytes": usage.usage_bytes,
                            "num_requests": usage.num_requests,
                            "source_api": "usage",
                        },
                    )
                )
        return records

    def _parse_usage_result(
        self, bucket_type: str, result: dict
    ) -> Optional[TokenUsage]:
        model = result.get("model") or _DEFAULT_RESOURCE.get(bucket_type, bucket_type)
        usage = TokenUsage(
            model=model,
            input_tokens=int(result.get("input_tokens", 0) or 0),
            output_tokens=int(result.get("output_tokens", 0) or 0),
            cached_input_tokens=int(result.get("input_cached_tokens", 0) or 0),
            reasoning_tokens=int(result.get("output_reasoning_tokens", 0) or 0),
            input_audio_tokens=int(result.get("input_audio_tokens", 0) or 0),
            output_audio_tokens=int(result.get("output_audio_tokens", 0) or 0),
            images=int(result.get("images", 0) or 0),
            characters=int(result.get("characters", 0) or 0),
            seconds=float(result.get("seconds", 0) or 0),
            num_sessions=int(result.get("num_sessions", 0) or 0),
            usage_bytes=int(result.get("usage_bytes", 0) or 0),
            num_requests=int(result.get("num_model_requests", 0) or 0),
            batch=_as_bool(result.get("batch", False)),
        )
        # Drop completely empty rows (some buckets return zero-result buckets
        # when no activity in the period).
        if (
            usage.input_tokens == 0
            and usage.output_tokens == 0
            and usage.images == 0
            and usage.characters == 0
            and usage.seconds == 0
            and usage.num_sessions == 0
            and usage.usage_bytes == 0
            and usage.num_requests == 0
        ):
            return None
        return usage

    def _estimate_usage_cost(self, usage: TokenUsage) -> float:
        return estimate_cost(
            usage.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cached_input_tokens=usage.cached_input_tokens,
            reasoning_tokens=usage.reasoning_tokens,
            images=usage.images,
            characters=usage.characters,
            seconds=usage.seconds,
            num_sessions=usage.num_sessions,
            usage_bytes=usage.usage_bytes,
            is_batch=usage.batch,
            pricing_overrides=self.pricing_overrides,
        )

    @staticmethod
    def _quantity_and_unit(usage: TokenUsage) -> tuple[float, str]:
        tokens = usage.input_tokens + usage.output_tokens
        if tokens:
            return (tokens, "tokens")
        if usage.images:
            return (usage.images, "images")
        if usage.characters:
            return (usage.characters, "characters")
        if usage.seconds:
            return (usage.seconds, "seconds")
        if usage.num_sessions:
            return (usage.num_sessions, "sessions")
        if usage.usage_bytes:
            return (usage.usage_bytes, "bytes")
        if usage.num_requests:
            return (usage.num_requests, "requests")
        return (0.0, "")

    # ---------------------------------------------------------------
    # Costs API
    # ---------------------------------------------------------------
    def _fetch_from_costs_api(
        self, start: datetime, end: datetime
    ) -> list[UnifiedCost]:
        """Authoritative $ amounts. ``amount.value`` is returned in *dollars*.

        Historically this connector divided by 100 under the mistaken
        assumption the API returned cents; the correction here multiplies
        ingested cost by 100x (i.e. reports actual spend).
        """
        url = f"{self.base_url}/organization/costs"
        params: dict[str, Any] = {
            "start_time": int(start.timestamp()),
            "end_time": int(end.timestamp()),
            "bucket_width": "1d",
            "group_by": ["line_item", "project_id"],
            "limit": 180,
        }
        records: list[UnifiedCost] = []
        for page in self._paginate(url, params):
            for bucket in page.get("data", []) or []:
                bucket_start = bucket.get("start_time", 0) or 0
                date = _fmt_date(bucket_start) if bucket_start else _fmt_date(
                    int(_utc_now().timestamp())
                )
                for result in bucket.get("results", []) or []:
                    amount = result.get("amount") or {}
                    value = amount.get("value")
                    if value is None:
                        continue
                    cost_usd = float(value)
                    if amount.get("currency", "usd").lower() != "usd":
                        # Costs API returns dollars; other currencies are rare
                        # but preserve them in metadata rather than silently
                        # converting.
                        pass
                    line_item = result.get("line_item") or "openai"
                    model = self._model_from_line_item(line_item)
                    records.append(
                        UnifiedCost(
                            date=date,
                            platform="openai",
                            service="openai",
                            resource=model or line_item,
                            category=CostCategory.ai_inference,
                            cost_usd=round(cost_usd, 6),
                            usage_quantity=0,
                            usage_unit="",
                            project=result.get("project_id"),
                            metadata={
                                "model": model,
                                "line_item": line_item,
                                "project_id": result.get("project_id"),
                                "currency": amount.get("currency", "usd"),
                                "source_api": "costs",
                            },
                        )
                    )
        return records

    @staticmethod
    def _model_from_line_item(line_item: Optional[str]) -> Optional[str]:
        """OpenAI Costs API line items look like 'gpt-4o-mini, input' etc.

        Return the model portion if identifiable, else None.
        """
        if not line_item:
            return None
        # Common OpenAI line item formatting: "<model>, <dimension>"
        return line_item.split(",")[0].strip() or None

    # ---------------------------------------------------------------
    # Merge Usage + Costs
    # ---------------------------------------------------------------
    def _merge_usage_and_costs(
        self,
        usage_records: list[UnifiedCost],
        costs_records: list[UnifiedCost],
    ) -> list[UnifiedCost]:
        """Prefer Costs API $ for each (date, model, project) key and
        overlay usage-derived token dimensions into the metadata.
        """
        if not costs_records:
            return usage_records
        if not usage_records:
            return costs_records

        def key(r: UnifiedCost) -> tuple[str, str, str]:
            model = (r.metadata.get("model") or r.resource or "").lower()
            project = r.project or r.metadata.get("project_id") or ""
            return (r.date, model, project)

        usage_by_key: dict[tuple[str, str, str], list[UnifiedCost]] = {}
        for u in usage_records:
            usage_by_key.setdefault(key(u), []).append(u)

        merged: list[UnifiedCost] = []
        consumed: set[tuple[str, str, str]] = set()

        for c in costs_records:
            k = key(c)
            matches = usage_by_key.get(k, [])
            if matches:
                consumed.add(k)
                # Aggregate token dimensions across matching usage rows.
                agg_tokens = sum(
                    int(m.metadata.get("input_tokens", 0) or 0)
                    + int(m.metadata.get("output_tokens", 0) or 0)
                    for m in matches
                )
                agg_cached = sum(
                    int(m.metadata.get("cached_input_tokens", 0) or 0)
                    for m in matches
                )
                agg_reasoning = sum(
                    int(m.metadata.get("reasoning_tokens", 0) or 0)
                    for m in matches
                )
                agg_input = sum(
                    int(m.metadata.get("input_tokens", 0) or 0) for m in matches
                )
                agg_output = sum(
                    int(m.metadata.get("output_tokens", 0) or 0) for m in matches
                )
                merged_meta = {
                    **c.metadata,
                    "input_tokens": agg_input,
                    "output_tokens": agg_output,
                    "cached_input_tokens": agg_cached,
                    "reasoning_tokens": agg_reasoning,
                    "estimated_cost_usd": sum(m.cost_usd for m in matches),
                }
                merged.append(
                    c.model_copy(
                        update={
                            "usage_quantity": agg_tokens or c.usage_quantity,
                            "usage_unit": "tokens" if agg_tokens else c.usage_unit,
                            "metadata": merged_meta,
                        }
                    )
                )
            else:
                merged.append(c)

        # Append usage rows that had no matching Costs entry (e.g. vector
        # stores which don't always appear under costs).
        for k, rows in usage_by_key.items():
            if k in consumed:
                continue
            merged.extend(rows)

        return merged

    # ---------------------------------------------------------------
    # Pagination
    # ---------------------------------------------------------------
    def _paginate(
        self, url: str, params: dict[str, Any]
    ) -> Iterable[dict]:
        """Yield each response page. Follows ``next_page`` cursors."""
        current_params = dict(params)
        for _ in range(self._MAX_PAGES):
            resp = httpx.get(
                url,
                headers=self._headers(),
                params=current_params,
                timeout=self._FETCH_TIMEOUT,
            )
            if resp.status_code != 200:
                logger.info(
                    "OpenAI %s returned HTTP %s: %s",
                    url,
                    resp.status_code,
                    resp.text[:200],
                )
                return
            try:
                page = resp.json()
            except ValueError:
                return
            yield page
            if not page.get("has_more"):
                return
            cursor = page.get("next_page")
            if not cursor:
                return
            current_params = dict(params)
            current_params["page"] = cursor
