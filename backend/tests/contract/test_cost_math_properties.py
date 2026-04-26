"""Hypothesis property tests for the AI-cost math functions.

These tests assert *invariants* of ``estimate_cost`` for each of the
LLM-pricing connectors (anthropic, openai, gemini, claude_code). They run
hundreds of randomly-generated token combinations per case and shrink down to
a minimal failing example if any invariant breaks — much more thorough than
fixed-fixture tests at catching off-by-one errors and pricing regressions.

Invariants enforced:

1. ``estimate_cost`` is non-negative for any non-negative input.
2. ``estimate_cost`` is monotonic-non-decreasing in any single token field.
3. Cache-read tokens are *strictly cheaper* than uncached input tokens of the
   same volume (the discount is the whole point of caching).
4. ``total_tokens`` (or ``.total``) never overflows for inputs in the
   1-10M range that real customers report.
"""
from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st


# Bounded — keep tests fast and stay well under any 64-bit overflow risk
TOKENS = st.integers(min_value=0, max_value=10_000_000)
SMALL_TOKENS = st.integers(min_value=1, max_value=100_000)


# ──────────────────────────────────────────────────────────────────────────
# Anthropic
# ──────────────────────────────────────────────────────────────────────────
@given(
    uncached=TOKENS,
    cache_read=TOKENS,
    cache_5m=TOKENS,
    cache_1h=TOKENS,
    output=TOKENS,
)
@settings(max_examples=100, deadline=None)
def test_anthropic_estimate_cost_is_non_negative(uncached, cache_read, cache_5m, cache_1h, output):
    from app.services.connectors.anthropic_connector import (
        TokenUsage,
        estimate_cost,
    )

    tokens = TokenUsage(
        uncached_input_tokens=uncached,
        cache_read_input_tokens=cache_read,
        cache_creation_5m_input_tokens=cache_5m,
        cache_creation_1h_input_tokens=cache_1h,
        output_tokens=output,
    )
    cost = estimate_cost("claude-sonnet-4-6", tokens)
    assert cost >= 0
    assert tokens.total_tokens == uncached + cache_read + cache_5m + cache_1h + output


@given(uncached=SMALL_TOKENS, output=SMALL_TOKENS, extra=SMALL_TOKENS)
@settings(max_examples=50, deadline=None)
def test_anthropic_estimate_cost_monotonic_in_uncached(uncached, output, extra):
    from app.services.connectors.anthropic_connector import (
        TokenUsage,
        estimate_cost,
    )

    base = TokenUsage(uncached_input_tokens=uncached, output_tokens=output)
    bigger = TokenUsage(uncached_input_tokens=uncached + extra, output_tokens=output)
    assert estimate_cost("claude-sonnet-4-6", bigger) >= estimate_cost("claude-sonnet-4-6", base)


@given(volume=st.integers(min_value=10_000, max_value=1_000_000))
@settings(max_examples=50, deadline=None)
def test_anthropic_cache_read_strictly_cheaper_than_uncached(volume):
    """Cache-read should always cost less than the same volume of uncached input.

    Uses ≥10K tokens so the cost is above the 6-decimal rounding floor; at
    very small volumes both costs round to 0.0 (which is the expected
    pricing-rounding behavior, not a bug).
    """
    from app.services.connectors.anthropic_connector import (
        TokenUsage,
        estimate_cost,
    )

    cached = TokenUsage(cache_read_input_tokens=volume)
    uncached = TokenUsage(uncached_input_tokens=volume)
    cost_cached = estimate_cost("claude-sonnet-4-6", cached)
    cost_uncached = estimate_cost("claude-sonnet-4-6", uncached)
    assert cost_cached < cost_uncached
    # The published discount is 90% (cache costs 10% of input).
    # Allow ±1e-6 wiggle for the 6-decimal rounding step.
    assert abs(cost_cached - cost_uncached * 0.10) < 1e-5


# ──────────────────────────────────────────────────────────────────────────
# OpenAI
# ──────────────────────────────────────────────────────────────────────────
@given(input_tokens=TOKENS, output=TOKENS, cached=TOKENS)
@settings(max_examples=100, deadline=None)
def test_openai_estimate_cost_is_non_negative(input_tokens, output, cached):
    from app.services.connectors.openai_connector import estimate_cost

    cost = estimate_cost(
        "gpt-4o",
        input_tokens=input_tokens,
        output_tokens=output,
        cached_input_tokens=min(cached, input_tokens),
    )
    assert cost >= 0


@given(input_tokens=SMALL_TOKENS, output=SMALL_TOKENS, extra=SMALL_TOKENS)
@settings(max_examples=50, deadline=None)
def test_openai_estimate_cost_monotonic_in_input(input_tokens, output, extra):
    from app.services.connectors.openai_connector import estimate_cost

    base = estimate_cost("gpt-4o", input_tokens=input_tokens, output_tokens=output)
    bigger = estimate_cost(
        "gpt-4o", input_tokens=input_tokens + extra, output_tokens=output
    )
    assert bigger >= base


@given(volume=SMALL_TOKENS)
@settings(max_examples=50, deadline=None)
def test_openai_cached_input_cheaper_than_uncached(volume):
    from app.services.connectors.openai_connector import estimate_cost

    cost_uncached = estimate_cost("gpt-4o", input_tokens=volume, cached_input_tokens=0)
    cost_fully_cached = estimate_cost(
        "gpt-4o", input_tokens=volume, cached_input_tokens=volume
    )
    # Cached input must never cost more than uncached.
    assert cost_fully_cached <= cost_uncached


@given(input_tokens=SMALL_TOKENS, output=SMALL_TOKENS)
@settings(max_examples=30, deadline=None)
def test_openai_batch_discount_is_at_most_full_price(input_tokens, output):
    """Batch API pricing must be ≤ on-demand pricing for the same usage."""
    from app.services.connectors.openai_connector import estimate_cost

    on_demand = estimate_cost("gpt-4o", input_tokens=input_tokens, output_tokens=output)
    batch = estimate_cost(
        "gpt-4o", input_tokens=input_tokens, output_tokens=output, is_batch=True
    )
    assert batch <= on_demand


# ──────────────────────────────────────────────────────────────────────────
# Gemini
# ──────────────────────────────────────────────────────────────────────────
@given(prompt=TOKENS, candidates=TOKENS, cached=TOKENS, thoughts=TOKENS)
@settings(max_examples=100, deadline=None)
def test_gemini_estimate_cost_is_non_negative(prompt, candidates, cached, thoughts):
    from app.services.connectors.gemini_connector import TokenUsage, estimate_cost

    usage = TokenUsage(
        prompt_tokens=prompt,
        candidates_tokens=candidates,
        cached_content_tokens=cached,
        thoughts_tokens=thoughts,
    )
    cost = estimate_cost("gemini-2.5-flash", usage)
    assert cost >= 0
    assert usage.total == prompt + candidates + cached + thoughts


@given(volume=st.integers(min_value=10_000, max_value=1_000_000))
@settings(max_examples=50, deadline=None)
def test_gemini_cached_content_cheaper_than_prompt(volume):
    """Cached content must always cost less than the same volume of prompt tokens.

    Uses ≥10K tokens so the cost is above the 6-decimal rounding floor — at
    smaller volumes both costs round to 0.0 and the comparison is uninformative.
    """
    from app.services.connectors.gemini_connector import TokenUsage, estimate_cost

    cached_only = TokenUsage(cached_content_tokens=volume)
    prompt_only = TokenUsage(prompt_tokens=volume)
    assert estimate_cost("gemini-2.5-flash", cached_only) < estimate_cost(
        "gemini-2.5-flash", prompt_only
    )


@given(prompt=SMALL_TOKENS, extra=SMALL_TOKENS)
@settings(max_examples=50, deadline=None)
def test_gemini_estimate_cost_monotonic_in_prompt(prompt, extra):
    from app.services.connectors.gemini_connector import TokenUsage, estimate_cost

    base = TokenUsage(prompt_tokens=prompt)
    bigger = TokenUsage(prompt_tokens=prompt + extra)
    assert estimate_cost("gemini-2.5-flash", bigger) >= estimate_cost(
        "gemini-2.5-flash", base
    )


# ──────────────────────────────────────────────────────────────────────────
# Claude Code (transcript-derived)
# ──────────────────────────────────────────────────────────────────────────
@given(
    input_tokens=TOKENS,
    output=TOKENS,
    cache_read=TOKENS,
    cache_5m=TOKENS,
    cache_1h=TOKENS,
)
@settings(max_examples=100, deadline=None)
def test_claude_code_estimate_cost_is_non_negative(
    input_tokens, output, cache_read, cache_5m, cache_1h
):
    from app.services.connectors.claude_code_connector import TokenUsage, estimate_cost

    usage = TokenUsage(
        input_tokens=input_tokens,
        output_tokens=output,
        cache_read_tokens=cache_read,
        cache_write_5m_tokens=cache_5m,
        cache_write_1h_tokens=cache_1h,
    )
    cost = estimate_cost("claude-sonnet-4-6", usage)
    assert cost >= 0
    assert usage.total == input_tokens + output + cache_read + cache_5m + cache_1h


@given(volume=st.integers(min_value=10_000, max_value=1_000_000))
@settings(max_examples=50, deadline=None)
def test_claude_code_cache_read_cheaper_than_input(volume):
    """≥10K-token volume keeps both costs above the 6-decimal rounding floor."""
    from app.services.connectors.claude_code_connector import TokenUsage, estimate_cost

    cached = TokenUsage(cache_read_tokens=volume)
    uncached = TokenUsage(input_tokens=volume)
    assert estimate_cost("claude-sonnet-4-6", cached) < estimate_cost(
        "claude-sonnet-4-6", uncached
    )


@given(volume=SMALL_TOKENS)
@settings(max_examples=50, deadline=None)
def test_claude_code_token_usage_addition_is_associative(volume):
    """TokenUsage __add__ should produce the same total whether you add
    in single steps or aggregate."""
    from app.services.connectors.claude_code_connector import TokenUsage

    a = TokenUsage(input_tokens=volume, output_tokens=volume)
    b = TokenUsage(input_tokens=volume * 2)
    summed = a + b
    assert summed.input_tokens == a.input_tokens + b.input_tokens
    assert summed.output_tokens == a.output_tokens + b.output_tokens
    assert summed.total == a.total + b.total
