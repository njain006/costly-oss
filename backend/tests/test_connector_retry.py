"""Tests for ``app.services.connectors.retry`` — the shared retry decorator."""
from __future__ import annotations

import asyncio
import random
from typing import Any, Callable
from unittest.mock import MagicMock

import httpx
import pytest

from app.services.connectors import retry as retry_mod
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
)
from app.services.connectors.retry import (
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_RETRY_STATUSES,
    NON_RETRYABLE_EXCEPTIONS,
    compute_backoff,
    raise_for_status_with_taxonomy,
    with_retry,
)


# ---------------------------------------------------------------------------
# Deterministic sleeper — record the sleep requests instead of actually sleeping.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _fast_sleep(monkeypatch):
    """Replace the module's sleepers with recorders. No real sleeping in tests."""
    sync_calls: list[float] = []

    def _sync(s: float) -> None:
        sync_calls.append(s)

    async def _async(s: float) -> None:
        sync_calls.append(s)

    monkeypatch.setattr(retry_mod.sleepers, "sync", _sync)
    monkeypatch.setattr(retry_mod.sleepers, "async_", _async)
    # Freeze jitter so tests can assert exact numbers when they disable it;
    # also give deterministic jitter when they don't.
    monkeypatch.setattr(retry_mod.random, "uniform", lambda a, b: 0.0)
    yield sync_calls


# ---------------------------------------------------------------------------
# compute_backoff
# ---------------------------------------------------------------------------


class TestComputeBackoff:
    def test_exponential_growth(self) -> None:
        assert compute_backoff(1, backoff_base=1.0, jitter=False) == 1.0
        assert compute_backoff(2, backoff_base=1.0, jitter=False) == 2.0
        assert compute_backoff(3, backoff_base=1.0, jitter=False) == 4.0
        assert compute_backoff(4, backoff_base=1.0, jitter=False) == 8.0

    def test_respects_cap(self) -> None:
        assert compute_backoff(10, backoff_base=1.0, backoff_cap=5.0, jitter=False) == 5.0

    def test_honors_min_sleep(self) -> None:
        # Retry-After 30s but base=1 → we should sleep at least 30
        assert compute_backoff(1, backoff_base=1.0, jitter=False, min_sleep=30.0) == 30.0

    def test_min_sleep_capped(self) -> None:
        assert (
            compute_backoff(1, backoff_base=1.0, backoff_cap=10.0, jitter=False, min_sleep=999.0)
            == 10.0
        )

    def test_invalid_attempt(self) -> None:
        with pytest.raises(ValueError):
            compute_backoff(0)
        with pytest.raises(ValueError):
            compute_backoff(-1)

    def test_jitter_adds_positive_value(self, monkeypatch) -> None:
        # Undo the global jitter freeze so this test actually exercises jitter.
        monkeypatch.setattr(retry_mod.random, "uniform", lambda a, b: 0.5)
        v = compute_backoff(1, backoff_base=1.0, jitter=True)
        assert v == pytest.approx(1.5)


# ---------------------------------------------------------------------------
# with_retry — sync
# ---------------------------------------------------------------------------


class TestWithRetrySync:
    def test_no_error_single_call(self) -> None:
        call_count = 0

        @with_retry(max_attempts=3)
        def good() -> str:
            nonlocal call_count
            call_count += 1
            return "ok"

        assert good() == "ok"
        assert call_count == 1

    def test_retries_on_rate_limited(self, _fast_sleep) -> None:
        attempts = 0

        @with_retry(max_attempts=3, backoff_base=0.01, jitter=False)
        def flaky() -> str:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise RateLimitedError(platform="x", endpoint="/y")
            return "recovered"

        assert flaky() == "recovered"
        assert attempts == 3
        # Slept between attempt 1→2 and 2→3 (not after attempt 3).
        assert len(_fast_sleep) == 2

    def test_retries_on_data_lagged(self) -> None:
        calls = 0

        @with_retry(max_attempts=4, backoff_base=0.01, jitter=False)
        def lag() -> str:
            nonlocal calls
            calls += 1
            if calls < 2:
                raise DataLaggedError(platform="aws")
            return "ok"

        assert lag() == "ok"
        assert calls == 2

    def test_retries_on_vendor_down(self) -> None:
        calls = 0

        @with_retry(max_attempts=3, backoff_base=0.01, jitter=False)
        def down() -> str:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise VendorDownError(platform="x")
            return "ok"

        assert down() == "ok"
        assert calls == 2

    def test_retries_on_httpx_request_error(self) -> None:
        calls = 0

        @with_retry(max_attempts=3, backoff_base=0.01, jitter=False)
        def net() -> str:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise httpx.ConnectError("conn refused")
            return "ok"

        assert net() == "ok"
        assert calls == 2

    @pytest.mark.parametrize(
        "exc_cls",
        [
            InvalidCredentialsError,
            ScopeMissingError,
            WarehouseNotFoundError,
            APIDisabledError,
            SchemaDriftError,
            QuotaExceededError,
        ],
    )
    def test_does_not_retry_on_permanent_errors(self, exc_cls: type) -> None:
        calls = 0

        @with_retry(max_attempts=5, backoff_base=0.01, jitter=False)
        def perm() -> None:
            nonlocal calls
            calls += 1
            raise exc_cls(platform="x")

        with pytest.raises(exc_cls):
            perm()
        assert calls == 1  # not retried

    def test_does_not_retry_on_random_exception(self) -> None:
        """Errors not in the retry set (e.g. ValueError) propagate immediately."""
        calls = 0

        @with_retry(max_attempts=5, backoff_base=0.01, jitter=False)
        def boom() -> None:
            nonlocal calls
            calls += 1
            raise ValueError("bad input")

        with pytest.raises(ValueError):
            boom()
        assert calls == 1

    def test_exhausts_and_converts_to_vendor_down(self) -> None:
        @with_retry(max_attempts=3, backoff_base=0.01, jitter=False)
        def always_rate_limited() -> None:
            raise RateLimitedError(platform="anthropic", endpoint="/x", vendor_code="429")

        with pytest.raises(VendorDownError) as excinfo:
            always_rate_limited()
        # Preserves platform/endpoint context.
        assert excinfo.value.platform == "anthropic"
        assert excinfo.value.endpoint == "/x"
        assert "exhausted" in excinfo.value.vendor_message.lower()

    def test_network_error_exhaustion_yields_vendor_down(self) -> None:
        @with_retry(max_attempts=2, backoff_base=0.01, jitter=False)
        def always_down() -> None:
            raise httpx.ConnectError("refused")

        with pytest.raises(VendorDownError) as excinfo:
            always_down()
        assert excinfo.value.vendor_code == "network_error"

    def test_honors_retry_after(self, _fast_sleep) -> None:
        calls = 0

        @with_retry(max_attempts=2, backoff_base=0.1, backoff_cap=60.0, jitter=False)
        def rl() -> None:
            nonlocal calls
            calls += 1
            raise RateLimitedError(platform="x", retry_after=5)

        with pytest.raises(VendorDownError):
            rl()
        # First retry sleep should be at least 5 (from Retry-After), even though
        # base backoff would be 0.1.
        assert _fast_sleep[0] == 5.0

    def test_max_attempts_one_raises_immediately(self) -> None:
        calls = 0

        @with_retry(max_attempts=1, backoff_base=0.01, jitter=False)
        def once() -> None:
            nonlocal calls
            calls += 1
            raise RateLimitedError(platform="x")

        with pytest.raises(VendorDownError):
            once()
        assert calls == 1

    def test_invalid_max_attempts_raises(self) -> None:
        with pytest.raises(ValueError):
            with_retry(max_attempts=0)(lambda: None)

    def test_preserves_function_metadata(self) -> None:
        @with_retry()
        def my_func(x: int) -> int:
            """Double it."""
            return x * 2

        assert my_func.__name__ == "my_func"
        assert my_func.__doc__ == "Double it."

    def test_passes_args_and_kwargs(self) -> None:
        @with_retry(max_attempts=2)
        def adder(a: int, b: int = 0) -> int:
            return a + b

        assert adder(1, b=2) == 3

    def test_non_retryable_wins_over_custom_retry_on(self) -> None:
        """Even if caller includes a non-retryable class in ``retry_on_errors``,
        the NON_RETRYABLE_EXCEPTIONS set wins."""
        calls = 0

        @with_retry(
            max_attempts=5,
            backoff_base=0.01,
            retry_on_errors=(InvalidCredentialsError,),  # caller mistake
        )
        def auth_fail() -> None:
            nonlocal calls
            calls += 1
            raise InvalidCredentialsError(platform="x")

        with pytest.raises(InvalidCredentialsError):
            auth_fail()
        assert calls == 1


# ---------------------------------------------------------------------------
# with_retry — async
# ---------------------------------------------------------------------------


class TestWithRetryAsync:
    def test_async_success(self) -> None:
        @with_retry(max_attempts=3, backoff_base=0.01, jitter=False)
        async def good() -> str:
            return "ok"

        assert asyncio.run(good()) == "ok"

    def test_async_retries_rate_limited(self) -> None:
        calls = 0

        @with_retry(max_attempts=3, backoff_base=0.01, jitter=False)
        async def flaky() -> str:
            nonlocal calls
            calls += 1
            if calls < 2:
                raise RateLimitedError(platform="x")
            return "ok"

        assert asyncio.run(flaky()) == "ok"
        assert calls == 2

    def test_async_does_not_retry_permanent(self) -> None:
        calls = 0

        @with_retry(max_attempts=3, backoff_base=0.01, jitter=False)
        async def perm() -> None:
            nonlocal calls
            calls += 1
            raise InvalidCredentialsError(platform="x")

        with pytest.raises(InvalidCredentialsError):
            asyncio.run(perm())
        assert calls == 1

    def test_async_exhaustion_converts_to_vendor_down(self) -> None:
        @with_retry(max_attempts=2, backoff_base=0.01, jitter=False)
        async def down() -> None:
            raise RateLimitedError(platform="x", endpoint="/y")

        with pytest.raises(VendorDownError) as excinfo:
            asyncio.run(down())
        assert excinfo.value.platform == "x"


# ---------------------------------------------------------------------------
# raise_for_status_with_taxonomy
# ---------------------------------------------------------------------------


def _mk_resp(status: int, *, text: str = "", headers: dict[str, str] | None = None):
    return httpx.Response(
        status_code=status,
        text=text,
        headers=headers or {},
        request=httpx.Request("GET", "https://example.com"),
    )


class TestRaiseForStatus:
    def test_2xx_no_raise(self) -> None:
        # Should NOT raise
        raise_for_status_with_taxonomy(_mk_resp(200, text="ok"), platform="x", endpoint="/y")
        raise_for_status_with_taxonomy(_mk_resp(204), platform="x", endpoint="/y")
        raise_for_status_with_taxonomy(_mk_resp(299), platform="x", endpoint="/y")

    def test_401_invalid_credentials(self) -> None:
        with pytest.raises(InvalidCredentialsError) as excinfo:
            raise_for_status_with_taxonomy(
                _mk_resp(401, text="bad token"), platform="anthropic", endpoint="/v1/x"
            )
        assert excinfo.value.platform == "anthropic"
        assert excinfo.value.vendor_code == "401"
        assert excinfo.value.vendor_message == "bad token"

    def test_403_scope_missing(self) -> None:
        with pytest.raises(ScopeMissingError):
            raise_for_status_with_taxonomy(
                _mk_resp(403, text="forbidden"), platform="aws", endpoint="/ce"
            )

    def test_404_warehouse_not_found(self) -> None:
        with pytest.raises(WarehouseNotFoundError):
            raise_for_status_with_taxonomy(
                _mk_resp(404), platform="snowflake", endpoint="/q"
            )

    def test_409_api_disabled(self) -> None:
        with pytest.raises(APIDisabledError):
            raise_for_status_with_taxonomy(
                _mk_resp(409), platform="gcp", endpoint="/bq"
            )

    def test_429_rate_limited_parses_retry_after(self) -> None:
        with pytest.raises(RateLimitedError) as excinfo:
            raise_for_status_with_taxonomy(
                _mk_resp(429, headers={"Retry-After": "42"}),
                platform="anthropic",
                endpoint="/v1/x",
            )
        assert excinfo.value.retry_after == 42

    def test_429_rate_limited_handles_missing_retry_after(self) -> None:
        with pytest.raises(RateLimitedError) as excinfo:
            raise_for_status_with_taxonomy(
                _mk_resp(429), platform="x", endpoint="/y"
            )
        assert excinfo.value.retry_after == 0

    def test_429_rate_limited_handles_non_int_retry_after(self) -> None:
        with pytest.raises(RateLimitedError) as excinfo:
            raise_for_status_with_taxonomy(
                _mk_resp(429, headers={"Retry-After": "Tue, 01 Jan 2030 00:00:00 GMT"}),
                platform="x",
                endpoint="/y",
            )
        assert excinfo.value.retry_after == 0  # HTTP-date form → fallback to 0

    def test_500_vendor_down(self) -> None:
        with pytest.raises(VendorDownError):
            raise_for_status_with_taxonomy(_mk_resp(500), platform="x", endpoint="/y")

    def test_503_vendor_down(self) -> None:
        with pytest.raises(VendorDownError):
            raise_for_status_with_taxonomy(_mk_resp(503), platform="x", endpoint="/y")

    def test_unknown_4xx_raises_base(self) -> None:
        with pytest.raises(CostlyConnectorError) as excinfo:
            raise_for_status_with_taxonomy(_mk_resp(418), platform="x", endpoint="/y")
        # Should be the BASE class, not a subclass
        assert type(excinfo.value) is CostlyConnectorError

    def test_truncates_long_vendor_message(self) -> None:
        long = "x" * 5000
        with pytest.raises(InvalidCredentialsError) as excinfo:
            raise_for_status_with_taxonomy(
                _mk_resp(401, text=long), platform="x", endpoint="/y"
            )
        assert len(excinfo.value.vendor_message) <= 500


# ---------------------------------------------------------------------------
# Module-level invariants
# ---------------------------------------------------------------------------


class TestModuleConstants:
    def test_default_retry_statuses_matches_spec(self) -> None:
        assert DEFAULT_RETRY_STATUSES == frozenset({429, 500, 502, 503, 504})

    def test_default_max_attempts(self) -> None:
        assert DEFAULT_MAX_ATTEMPTS == 5

    def test_non_retryable_contains_all_permanent(self) -> None:
        assert InvalidCredentialsError in NON_RETRYABLE_EXCEPTIONS
        assert ScopeMissingError in NON_RETRYABLE_EXCEPTIONS
        assert WarehouseNotFoundError in NON_RETRYABLE_EXCEPTIONS
        assert APIDisabledError in NON_RETRYABLE_EXCEPTIONS
        assert SchemaDriftError in NON_RETRYABLE_EXCEPTIONS
        assert QuotaExceededError in NON_RETRYABLE_EXCEPTIONS
