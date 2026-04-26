"""Unified error taxonomy for every Costly connector.

All connectors MUST raise one of the exception classes defined here instead of
leaking vendor-specific exceptions (``httpx.HTTPError``, ``boto3.ClientError``,
``google.api_core.exceptions.*``, raw ``Exception`` / ``RuntimeError``). This
gives us:

* a **router-level handler** (``register_connector_exception_handler``) that
  converts any connector error into a structured JSON response with a stable
  ``code``, human ``message`` and ``remediation_url``;
* a **retry decorator** (:mod:`app.services.connectors.retry`) that decides
  retry-vs-fail purely from the exception class — no string matching on vendor
  messages;
* **typed tests** — tests can ``pytest.raises(RateLimitedError)`` without
  coupling to vendor wire formats.

Ground-truth reference: ``docs/connector-ground-truth.md`` — "Unified Error
Taxonomy" section.

Usage
-----

.. code-block:: python

    from app.services.connectors.errors import (
        RateLimitedError, ScopeMissingError,
    )

    if resp.status_code == 429:
        raise RateLimitedError(
            platform="anthropic",
            endpoint="/v1/organizations/usage_report/messages",
            vendor_code="429",
            vendor_message=resp.text[:200],
            retry_after=int(resp.headers.get("Retry-After", "60")),
        )
    if resp.status_code == 403:
        raise ScopeMissingError(
            platform="anthropic",
            endpoint="/v1/organizations/usage_report/messages",
            vendor_code="403",
            vendor_message="Admin scope required",
            required_scope="admin",
        )

Wiring the handler into FastAPI
-------------------------------

.. code-block:: python

    from app.services.connectors.errors import register_connector_exception_handler

    app = FastAPI()
    register_connector_exception_handler(app)

On the wire, every connector error surfaces as::

    HTTP 429
    {
      "error": {
        "code": "rate_limited",
        "message": "Rate limited by anthropic",
        "platform": "anthropic",
        "endpoint": "/v1/organizations/usage_report/messages",
        "vendor_code": "429",
        "vendor_message": "...",
        "remediation_url": "https://docs.costly.dev/errors/rate_limited",
        "retry_after": 60
      }
    }
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

DEFAULT_DOCS_BASE = "https://docs.costly.dev/errors"


@dataclass
class CostlyConnectorError(Exception):
    """Base class for every connector-originated error.

    Attributes are intentionally kept as plain Python primitives so the error
    can be JSON-serialized by the router-level handler without any
    ``pydantic.BaseModel.model_dump`` gymnastics.

    Note: we use ``@dataclass(eq=False)`` semantics by NOT freezing so pytest
    ``raises`` matches by ``isinstance`` (frozen exceptions don't play well
    with ``Exception.__init__``). The error data is treated as read-only by
    convention — do not mutate after construction.
    """

    platform: str = ""
    endpoint: str = ""
    vendor_code: str = ""
    vendor_message: str = ""
    remediation_hint: str = ""
    # Additional context a connector may attach. Kept verbatim; not rendered
    # into the public response unless the subclass chooses to.
    extra: dict = field(default_factory=dict)

    # --- HTTP surface (override per subclass) --------------------------------
    #: HTTP status code the router should use when raising this error. Subclasses
    #: override this to give clients an actionable status (e.g. 429 for
    #: ``RateLimitedError``, 401 for ``InvalidCredentialsError``).
    http_status: int = 502

    #: Short machine-readable code that appears in the response envelope. Stable
    #: across wire versions — external tooling may switch on it.
    code: str = "connector_error"

    def __post_init__(self) -> None:
        # Make Exception.args reflect the rendered message so the default
        # ``repr()`` / logging output is useful even without custom handling.
        super().__init__(self._default_message())

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def _default_message(self) -> str:
        if self.vendor_message:
            return f"{self.code}: {self.platform} — {self.vendor_message}"
        return f"{self.code}: {self.platform}"

    @property
    def remediation_url(self) -> str:
        """Canonical docs URL for this error code.

        Customers can override ``DEFAULT_DOCS_BASE`` by subclassing, but the
        default is a ``docs.costly.dev/errors/<code>`` page we commit to
        hosting.
        """
        return f"{DEFAULT_DOCS_BASE}/{self.code}"

    def to_dict(self) -> dict[str, Any]:
        """Render as the JSON body returned by the router-level handler.

        Subclasses may extend to add extra fields (e.g. ``retry_after``).
        """
        body: dict[str, Any] = {
            "code": self.code,
            "message": str(self),
            "platform": self.platform,
            "endpoint": self.endpoint,
            "vendor_code": self.vendor_code,
            "vendor_message": self.vendor_message,
            "remediation_url": self.remediation_url,
        }
        if self.remediation_hint:
            body["remediation_hint"] = self.remediation_hint
        return body


# ---------------------------------------------------------------------------
# Concrete error classes
# ---------------------------------------------------------------------------


@dataclass
class InvalidCredentialsError(CostlyConnectorError):
    """Credentials are syntactically valid but the vendor rejected them.

    Maps to HTTP ``401``. **Not retryable**.
    """

    code: str = "invalid_credentials"
    http_status: int = 401


@dataclass
class ScopeMissingError(CostlyConnectorError):
    """Credentials authenticated but lack the scope/role required for the call.

    Example: regular OpenAI API key used for Admin Usage API, or an AWS IAM
    user without ``ce:GetCostAndUsage``.

    Maps to HTTP ``403``. **Not retryable**.
    """

    required_scope: str = ""
    code: str = "scope_missing"
    http_status: int = 403

    def to_dict(self) -> dict[str, Any]:
        body = super().to_dict()
        if self.required_scope:
            body["required_scope"] = self.required_scope
        return body


@dataclass
class WarehouseNotFoundError(CostlyConnectorError):
    """The requested warehouse / workspace / project doesn't exist or is hidden.

    For example: Snowflake role can't see the warehouse, or a dbt Cloud job id
    was deleted.

    Maps to HTTP ``404``. **Not retryable**.
    """

    resource_name: str = ""
    code: str = "warehouse_not_found"
    http_status: int = 404

    def to_dict(self) -> dict[str, Any]:
        body = super().to_dict()
        if self.resource_name:
            body["resource_name"] = self.resource_name
        return body


@dataclass
class RateLimitedError(CostlyConnectorError):
    """Vendor returned 429 (or equivalent).

    Carries ``retry_after`` seconds (honor the vendor ``Retry-After`` header
    when present; otherwise pass a sane default). **Retryable** per the retry
    decorator's default policy.
    """

    retry_after: int = 0
    code: str = "rate_limited"
    http_status: int = 429

    def to_dict(self) -> dict[str, Any]:
        body = super().to_dict()
        if self.retry_after:
            body["retry_after"] = self.retry_after
        return body


@dataclass
class APIDisabledError(CostlyConnectorError):
    """The vendor API is disabled on this account (feature-flag / billing tier).

    Example: BigQuery Admin API not enabled for project, or AWS Cost Explorer
    not enabled. Distinct from :class:`ScopeMissingError` — the credential can
    be perfectly valid and scoped; the API simply isn't turned on.

    Maps to HTTP ``409``. **Not retryable** — surface actionable remediation to
    the end user ("enable Cost Explorer in the AWS console").
    """

    code: str = "api_disabled"
    http_status: int = 409


@dataclass
class DataLaggedError(CostlyConnectorError):
    """Vendor responded 200 but the data window isn't ready yet.

    Examples: AWS Cost Explorer returns empty results for "yesterday" until
    ~24h post-midnight UTC; GitHub Actions billing lags 6-24h. This is NOT a
    failure — the retry decorator treats it as retryable with a longer backoff
    because the data will arrive eventually.

    Maps to HTTP ``503`` **Retryable**.
    """

    code: str = "data_lagged"
    http_status: int = 503


@dataclass
class VendorDownError(CostlyConnectorError):
    """Vendor returned 5xx after backoff exhausted, or a connection failure.

    Maps to HTTP ``502``. Already-retried (the retry decorator converts
    persistent 5xx into this). **Not retryable** at the handler level.
    """

    code: str = "vendor_down"
    http_status: int = 502


@dataclass
class SchemaDriftError(CostlyConnectorError):
    """Vendor response missing an expected field — shape has drifted.

    Tells ops that the connector code needs to be updated. **Not retryable**.
    """

    missing_field: str = ""
    code: str = "schema_drift"
    http_status: int = 502

    def to_dict(self) -> dict[str, Any]:
        body = super().to_dict()
        if self.missing_field:
            body["missing_field"] = self.missing_field
        return body


@dataclass
class QuotaExceededError(CostlyConnectorError):
    """Connector exhausted the account's daily query/export quota.

    Distinct from :class:`RateLimitedError` — rate limits reset in seconds; a
    quota resets on a calendar boundary (UTC day for most vendors). **Not
    retryable** within the same day.
    """

    reset_at: Optional[str] = None  # ISO-8601 timestamp, if known
    code: str = "quota_exceeded"
    http_status: int = 429

    def to_dict(self) -> dict[str, Any]:
        body = super().to_dict()
        if self.reset_at:
            body["reset_at"] = self.reset_at
        return body


# ---------------------------------------------------------------------------
# Router-level exception handler
# ---------------------------------------------------------------------------


def _render_json_response(exc: CostlyConnectorError):
    """Build a ``JSONResponse`` for the given error.

    Isolated so tests can assert on it without pulling in a FastAPI app.
    """
    # Imported inside the function so this module stays importable from
    # non-web contexts (scheduled jobs, CLI tools, unit tests).
    from fastapi.responses import JSONResponse  # noqa: WPS433 (local import ok)

    headers: Optional[dict[str, str]] = None
    if isinstance(exc, RateLimitedError) and exc.retry_after:
        headers = {"Retry-After": str(exc.retry_after)}

    return JSONResponse(
        status_code=exc.http_status,
        content={"error": exc.to_dict()},
        headers=headers,
    )


def register_connector_exception_handler(app: Any) -> None:
    """Register a FastAPI exception handler that converts any
    :class:`CostlyConnectorError` into the structured envelope documented
    above.

    Call once during app setup::

        from fastapi import FastAPI
        from app.services.connectors.errors import (
            register_connector_exception_handler,
        )

        app = FastAPI()
        register_connector_exception_handler(app)
    """

    @app.exception_handler(CostlyConnectorError)
    async def _handler(_request, exc: CostlyConnectorError):  # noqa: WPS430
        return _render_json_response(exc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def is_retryable(exc: BaseException) -> bool:
    """Return ``True`` if the error class is one the retry decorator should
    retry on.

    Mirrors the decorator's default ``retry_on_errors`` set. Kept here (not in
    ``retry.py``) so the taxonomy owns the "is this kind of failure transient?"
    decision — the retry module just consumes it.
    """
    return isinstance(
        exc,
        (RateLimitedError, DataLaggedError, VendorDownError),
    )


__all__ = [
    "CostlyConnectorError",
    "InvalidCredentialsError",
    "ScopeMissingError",
    "WarehouseNotFoundError",
    "RateLimitedError",
    "APIDisabledError",
    "DataLaggedError",
    "VendorDownError",
    "SchemaDriftError",
    "QuotaExceededError",
    "register_connector_exception_handler",
    "is_retryable",
    "DEFAULT_DOCS_BASE",
]
