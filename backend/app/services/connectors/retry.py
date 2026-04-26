"""Unified retry / backoff decorator for every Costly connector.

Every outbound HTTP call to a vendor API MUST go through ``@with_retry`` so
the retry / backoff / jitter policy is enforced in exactly one place. The 15
existing connectors have ad-hoc ``try / except`` blocks that silently swallow
429s or retry immediately — this module replaces all of them.

Ground-truth reference: ``docs/connector-ground-truth.md`` — "Unified Retry /
Backoff Policy" section.

Policy (defaults)
-----------------

* **Exponential backoff** with full jitter: ``min(backoff_cap, backoff_base *
  2**attempt + random(0, backoff_base))`` seconds.
* **Retry on** HTTP status codes ``{429, 500, 502, 503, 504}`` and the
  taxonomy classes :class:`RateLimitedError`, :class:`DataLaggedError`,
  :class:`VendorDownError` — plus ``httpx.RequestError`` for connection-level
  failures.
* **Do not retry on** :class:`InvalidCredentialsError`, :class:`ScopeMissingError`,
  :class:`WarehouseNotFoundError`, :class:`APIDisabledError`, :class:`SchemaDriftError`,
  :class:`QuotaExceededError`. These are permanent — retrying only burns quota.
* **Honor** vendor ``Retry-After`` header by setting ``exc.retry_after`` on the
  :class:`RateLimitedError` — the decorator respects it as the MINIMUM sleep for
  that attempt (still capped by ``backoff_cap``).
* **Abort after** ``max_attempts`` tries — convert a persistent 5xx into
  :class:`VendorDownError` so the router-level handler returns a clean 502.

Usage
-----

Decorate any function that performs vendor I/O::

    from app.services.connectors.retry import with_retry

    @with_retry(max_attempts=5)
    def fetch_page(self, cursor: str) -> dict:
        resp = httpx.get(self._url, headers=self._headers, params={"cursor": cursor})
        if resp.status_code == 429:
            raise RateLimitedError(
                platform="anthropic",
                endpoint="/v1/organizations/usage_report/messages",
                vendor_code="429",
                retry_after=int(resp.headers.get("Retry-After", "60")),
            )
        resp.raise_for_status()
        return resp.json()

``@with_retry`` works on sync AND async functions — it sniffs
``inspect.iscoroutinefunction`` and dispatches accordingly.

For HTTP-status-based retry (when you'd rather not raise a taxonomy error
inside the function), use :func:`raise_for_status_with_taxonomy` inside the
decorated function — it maps HTTP status to the right taxonomy class:

.. code-block:: python

    @with_retry()
    def fetch(self):
        resp = httpx.get(...)
        raise_for_status_with_taxonomy(resp, platform="aws", endpoint="/ce")
        return resp.json()
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import logging
import random
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional, TypeVar

import httpx

from app.services.connectors.errors import (
    APIDisabledError,
    CostlyConnectorError,
    DataLaggedError,
    InvalidCredentialsError,
    QuotaExceededError,
    RateLimitedError,
    ScopeMissingError,
    SchemaDriftError,
    VendorDownError,
    WarehouseNotFoundError,
    is_retryable,
)

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_BACKOFF_BASE = 1.0  # seconds
DEFAULT_BACKOFF_CAP = 60.0  # hard cap per sleep (seconds)
DEFAULT_JITTER = True
DEFAULT_RETRY_STATUSES: frozenset[int] = frozenset({429, 500, 502, 503, 504})

# Classes that are PERMANENT failures — never retry.
NON_RETRYABLE_EXCEPTIONS: tuple[type, ...] = (
    InvalidCredentialsError,
    ScopeMissingError,
    WarehouseNotFoundError,
    APIDisabledError,
    SchemaDriftError,
    QuotaExceededError,
)


# ---------------------------------------------------------------------------
# Sleep pluggability (makes tests deterministic)
# ---------------------------------------------------------------------------


@dataclass
class _SleepProviders:
    """Wrap ``time.sleep`` and ``asyncio.sleep`` so tests can swap them.

    Swapping via a single module-level attribute beats monkey-patching
    ``time`` in every test.
    """

    sync: Callable[[float], None]
    async_: Callable[[float], Awaitable[None]]


sleepers = _SleepProviders(sync=time.sleep, async_=asyncio.sleep)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def compute_backoff(
    attempt: int,
    *,
    backoff_base: float = DEFAULT_BACKOFF_BASE,
    backoff_cap: float = DEFAULT_BACKOFF_CAP,
    jitter: bool = DEFAULT_JITTER,
    min_sleep: float = 0.0,
) -> float:
    """Return the number of seconds to sleep before ``attempt`` (1-indexed).

    Formula: ``min(cap, base * 2**(attempt-1)) + jitter``.

    The ``min_sleep`` floor is used to honor vendor ``Retry-After`` headers —
    the returned sleep is never below ``min_sleep`` (but still capped by
    ``backoff_cap``).

    Exposed for testability.
    """
    if attempt < 1:
        raise ValueError("attempt must be >= 1")
    # Exponential base. 2**(attempt-1) so attempt=1 → base, attempt=2 → 2x, ...
    raw = backoff_base * (2 ** (attempt - 1))
    capped = min(backoff_cap, raw)
    if jitter:
        # Full jitter in [0, backoff_base] so small backoffs still spread out.
        capped = capped + random.uniform(0, backoff_base)
    sleep_for = max(min_sleep, capped)
    # Re-cap in case min_sleep exceeded backoff_cap — never sleep forever.
    return min(backoff_cap, sleep_for)


def raise_for_status_with_taxonomy(
    response: "httpx.Response",
    *,
    platform: str,
    endpoint: str,
) -> None:
    """Map an ``httpx.Response`` onto the taxonomy.

    Called inside a ``@with_retry``-decorated function, this lets connector
    code delegate the vendor-code → taxonomy mapping to one place.

    Raises nothing on ``2xx``. Raises the appropriate :class:`CostlyConnectorError`
    subclass otherwise.
    """
    sc = response.status_code
    if 200 <= sc < 300:
        return

    vendor_message = response.text[:500] if response.text else ""

    if sc == 401:
        raise InvalidCredentialsError(
            platform=platform,
            endpoint=endpoint,
            vendor_code=str(sc),
            vendor_message=vendor_message,
        )
    if sc == 403:
        raise ScopeMissingError(
            platform=platform,
            endpoint=endpoint,
            vendor_code=str(sc),
            vendor_message=vendor_message,
        )
    if sc == 404:
        raise WarehouseNotFoundError(
            platform=platform,
            endpoint=endpoint,
            vendor_code=str(sc),
            vendor_message=vendor_message,
        )
    if sc == 409:
        raise APIDisabledError(
            platform=platform,
            endpoint=endpoint,
            vendor_code=str(sc),
            vendor_message=vendor_message,
        )
    if sc == 429:
        retry_after_raw = response.headers.get("Retry-After", "")
        try:
            retry_after = int(retry_after_raw) if retry_after_raw else 0
        except ValueError:
            retry_after = 0
        raise RateLimitedError(
            platform=platform,
            endpoint=endpoint,
            vendor_code=str(sc),
            vendor_message=vendor_message,
            retry_after=retry_after,
        )
    if 500 <= sc < 600:
        raise VendorDownError(
            platform=platform,
            endpoint=endpoint,
            vendor_code=str(sc),
            vendor_message=vendor_message,
        )
    # Unknown 4xx — treat as permanent so we don't hammer the vendor.
    raise CostlyConnectorError(
        platform=platform,
        endpoint=endpoint,
        vendor_code=str(sc),
        vendor_message=vendor_message,
    )


# ---------------------------------------------------------------------------
# The decorator
# ---------------------------------------------------------------------------


def _should_retry(exc: BaseException, retry_on_errors: tuple[type, ...]) -> bool:
    """Return ``True`` if ``exc`` is in the retry set and NOT in the no-retry set.

    The no-retry set always wins — a custom subclass of ``RateLimitedError`` is
    retryable, but anything matching :data:`NON_RETRYABLE_EXCEPTIONS` is not,
    even if the caller inadvertently included it in ``retry_on_errors``.
    """
    if isinstance(exc, NON_RETRYABLE_EXCEPTIONS):
        return False
    return isinstance(exc, retry_on_errors)


def _min_sleep_for_exc(exc: BaseException) -> float:
    """Extract a ``Retry-After``-style hint from ``exc``.

    :class:`RateLimitedError` carries ``retry_after``; other errors have none.
    """
    if isinstance(exc, RateLimitedError) and exc.retry_after:
        return float(exc.retry_after)
    return 0.0


def _convert_to_vendor_down(exc: BaseException, attempt: int) -> VendorDownError:
    """Wrap a transient error that exhausted retries in :class:`VendorDownError`.

    Preserves the vendor context for the router-level handler.
    """
    if isinstance(exc, CostlyConnectorError):
        return VendorDownError(
            platform=exc.platform,
            endpoint=exc.endpoint,
            vendor_code=exc.vendor_code or "retry_exhausted",
            vendor_message=(
                f"retries exhausted after {attempt} attempts: {exc.vendor_message}"
            ).strip(": "),
        )
    # Network-level failure (e.g. httpx.ConnectError). No vendor context.
    return VendorDownError(
        vendor_code="network_error",
        vendor_message=f"retries exhausted after {attempt} attempts: {exc}",
    )


def with_retry(
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    *,
    backoff_base: float = DEFAULT_BACKOFF_BASE,
    backoff_cap: float = DEFAULT_BACKOFF_CAP,
    jitter: bool = DEFAULT_JITTER,
    retry_on_errors: Optional[tuple[type, ...]] = None,
    retry_on_statuses: frozenset[int] = DEFAULT_RETRY_STATUSES,  # noqa: ARG001
) -> Callable[[F], F]:
    """Decorator that retries transient vendor errors with exponential backoff.

    Parameters
    ----------
    max_attempts:
        Total attempts including the first. Default 5.
    backoff_base:
        Seconds. Sleep for attempt N is ``base * 2**(N-1)``, capped by
        ``backoff_cap``. Default 1.0.
    backoff_cap:
        Hard per-sleep cap. Default 60s.
    jitter:
        When True (default), add ``random(0, base)`` seconds to each sleep.
    retry_on_errors:
        Tuple of exception classes to retry on. Defaults to the taxonomy's
        transient set (:func:`app.services.connectors.errors.is_retryable`)
        plus ``httpx.RequestError`` for network-level faults.
    retry_on_statuses:
        Informational — accepted so callers can document their intent, but
        HTTP-status mapping is the caller's responsibility (usually via
        :func:`raise_for_status_with_taxonomy`). Default is
        ``{429, 500, 502, 503, 504}``.

    Works on both sync and async functions.
    """

    if retry_on_errors is None:
        retry_on_errors = (
            RateLimitedError,
            DataLaggedError,
            VendorDownError,
            httpx.RequestError,
        )

    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")

    def decorator(func: F) -> F:
        is_async = inspect.iscoroutinefunction(func)

        if is_async:

            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                last_exc: Optional[BaseException] = None
                for attempt in range(1, max_attempts + 1):
                    try:
                        return await func(*args, **kwargs)
                    except Exception as exc:  # noqa: BLE001
                        last_exc = exc
                        if not _should_retry(exc, retry_on_errors):
                            raise
                        if attempt == max_attempts:
                            break
                        sleep_for = compute_backoff(
                            attempt,
                            backoff_base=backoff_base,
                            backoff_cap=backoff_cap,
                            jitter=jitter,
                            min_sleep=_min_sleep_for_exc(exc),
                        )
                        logger.warning(
                            "connector retry attempt=%d/%d sleep=%.2fs err=%s",
                            attempt,
                            max_attempts,
                            sleep_for,
                            type(exc).__name__,
                        )
                        await sleepers.async_(sleep_for)
                # Exhausted.
                assert last_exc is not None  # noqa: S101 — control-flow invariant
                raise _convert_to_vendor_down(last_exc, max_attempts) from last_exc

            return async_wrapper  # type: ignore[return-value]

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exc: Optional[BaseException] = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
                    if not _should_retry(exc, retry_on_errors):
                        raise
                    if attempt == max_attempts:
                        break
                    sleep_for = compute_backoff(
                        attempt,
                        backoff_base=backoff_base,
                        backoff_cap=backoff_cap,
                        jitter=jitter,
                        min_sleep=_min_sleep_for_exc(exc),
                    )
                    logger.warning(
                        "connector retry attempt=%d/%d sleep=%.2fs err=%s",
                        attempt,
                        max_attempts,
                        sleep_for,
                        type(exc).__name__,
                    )
                    sleepers.sync(sleep_for)
            assert last_exc is not None  # noqa: S101
            raise _convert_to_vendor_down(last_exc, max_attempts) from last_exc

        return sync_wrapper  # type: ignore[return-value]

    return decorator


__all__ = [
    "with_retry",
    "compute_backoff",
    "raise_for_status_with_taxonomy",
    "is_retryable",
    "DEFAULT_MAX_ATTEMPTS",
    "DEFAULT_BACKOFF_BASE",
    "DEFAULT_BACKOFF_CAP",
    "DEFAULT_RETRY_STATUSES",
    "NON_RETRYABLE_EXCEPTIONS",
    "sleepers",
]
