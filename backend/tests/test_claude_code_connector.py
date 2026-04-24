"""Tests for the Claude Code JSONL usage connector.

Covers:
- TokenUsage arithmetic and total property
- _resolve_pricing prefix-matching (including 4.7 / 4.6 / 4.5 / legacy)
- estimate_cost with each cache tier (read, write 5m, write 1h) and mixed
- _parse_turn for assistant rows, non-assistant rows, missing usage, bad timestamps
- iter_jsonl_turns across a synthetic multi-project projects_dir
- aggregate_costs bucketing (day × project × model) and `since` filtering
- project_name_from_cwd preferring cwd basename, falling back to dir name
- ClaudeCodeConnector test_connection: missing dir, empty dir, populated dir
- ClaudeCodeConnector.fetch_costs end-to-end
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.models.platform import CostCategory, UnifiedCost
from app.services.connectors.base import BaseConnector
from app.services.connectors.claude_code_connector import (
    CACHE_READ_MULTIPLIER,
    CACHE_WRITE_1H_MULTIPLIER,
    CACHE_WRITE_5M_MULTIPLIER,
    ClaudeCodeConnector,
    TokenUsage,
    _parse_turn,
    _resolve_pricing,
    aggregate_costs,
    estimate_cost,
    iter_jsonl_turns,
    project_name_from_cwd,
)


# ─── TokenUsage ──────────────────────────────────────────────────────


class TestTokenUsage:
    def test_total_sums_every_tier(self):
        usage = TokenUsage(
            input_tokens=10,
            output_tokens=20,
            cache_read_tokens=5,
            cache_write_5m_tokens=3,
            cache_write_1h_tokens=7,
        )
        assert usage.total == 45

    def test_add_returns_new_instance(self):
        a = TokenUsage(input_tokens=1, output_tokens=2)
        b = TokenUsage(input_tokens=10, cache_read_tokens=4)
        merged = a + b
        assert merged.input_tokens == 11
        assert merged.output_tokens == 2
        assert merged.cache_read_tokens == 4
        assert a.input_tokens == 1  # immutable — no mutation
        assert b.input_tokens == 10

    def test_add_with_non_tokenusage_returns_notimplemented(self):
        with pytest.raises(TypeError):
            _ = TokenUsage() + 5  # type: ignore[operator]


# ─── Pricing resolution ──────────────────────────────────────────────


class TestResolvePricing:
    @pytest.mark.parametrize(
        "model,expected_input",
        [
            ("claude-opus-4-7", 15.0),
            ("claude-opus-4-6", 15.0),
            ("claude-sonnet-4-6", 3.0),
            ("claude-sonnet-4", 3.0),
            ("claude-haiku-4-5", 1.0),
            ("claude-haiku-3-5", 0.80),
            ("claude-haiku-3", 0.25),
            ("claude-sonnet-3-5", 3.0),
        ],
    )
    def test_known_models(self, model: str, expected_input: float):
        assert _resolve_pricing(model)["input"] == expected_input

    def test_prefers_longer_prefix(self):
        """claude-haiku-4-5 must not fall through to claude-haiku-3 pricing."""
        assert _resolve_pricing("claude-haiku-4-5-20250101")["input"] == 1.0

    def test_opus_4_7_wins_over_opus_4(self):
        assert _resolve_pricing("claude-opus-4-7-beta")["input"] == 15.0

    def test_unknown_falls_back_to_sonnet(self):
        price = _resolve_pricing("some-brand-new-model")
        assert price["input"] == 3.0
        assert price["output"] == 15.0


# ─── estimate_cost ───────────────────────────────────────────────────


class TestEstimateCost:
    def test_input_and_output_only(self):
        # 1M input @ $3 + 1M output @ $15 = $18 for Sonnet-tier
        usage = TokenUsage(input_tokens=1_000_000, output_tokens=1_000_000)
        assert estimate_cost("claude-sonnet-4-6", usage) == 18.0

    def test_cache_read_applies_90pct_discount(self):
        # 1M cache_read tokens at Sonnet input ($3) × 0.10 = $0.30
        usage = TokenUsage(cache_read_tokens=1_000_000)
        expected = 3.0 * CACHE_READ_MULTIPLIER
        assert estimate_cost("claude-sonnet-4-6", usage) == pytest.approx(expected)

    def test_cache_write_5m_applies_25pct_premium(self):
        # 1M cache write (5m) at Sonnet input ($3) × 1.25 = $3.75
        usage = TokenUsage(cache_write_5m_tokens=1_000_000)
        expected = 3.0 * CACHE_WRITE_5M_MULTIPLIER
        assert estimate_cost("claude-sonnet-4-6", usage) == pytest.approx(expected)

    def test_cache_write_1h_applies_100pct_premium(self):
        # 1M cache write (1h) at Sonnet input ($3) × 2.0 = $6.00
        usage = TokenUsage(cache_write_1h_tokens=1_000_000)
        expected = 3.0 * CACHE_WRITE_1H_MULTIPLIER
        assert estimate_cost("claude-sonnet-4-6", usage) == pytest.approx(expected)

    def test_mixed_tiers_sum(self):
        # 100 input + 200 output + 50 cache_read + 30 cache_write_5m on Opus
        usage = TokenUsage(
            input_tokens=100,
            output_tokens=200,
            cache_read_tokens=50,
            cache_write_5m_tokens=30,
        )
        opus_input, opus_output = 15.0, 75.0
        per_million = 1_000_000.0
        expected = (
            100 * opus_input / per_million
            + 200 * opus_output / per_million
            + 50 * opus_input * CACHE_READ_MULTIPLIER / per_million
            + 30 * opus_input * CACHE_WRITE_5M_MULTIPLIER / per_million
        )
        assert estimate_cost("claude-opus-4-7", usage) == pytest.approx(round(expected, 6))

    def test_zero_usage_returns_zero(self):
        assert estimate_cost("claude-sonnet-4-6", TokenUsage()) == 0.0


# ─── project_name_from_cwd ──────────────────────────────────────────


class TestProjectNameFromCwd:
    def test_uses_cwd_basename_when_available(self):
        assert project_name_from_cwd("/Users/jain/src/career-ops", "-fallback-") == "career-ops"

    def test_falls_back_when_cwd_missing(self):
        assert project_name_from_cwd(None, "-Users-jain-src-career-ops") == "Users-jain-src-career-ops"

    def test_falls_back_when_cwd_empty(self):
        assert project_name_from_cwd("", "-fallback") == "fallback"


# ─── _parse_turn ─────────────────────────────────────────────────────


def _assistant_row(**overrides) -> dict:
    """Build a realistic assistant JSONL row. Override any field."""
    row = {
        "type": "assistant",
        "timestamp": "2026-04-01T12:00:00.000Z",
        "sessionId": "session-123",
        "cwd": "/Users/jain/src/myproj",
        "message": {
            "model": "claude-sonnet-4-6",
            "usage": {
                "input_tokens": 1000,
                "output_tokens": 500,
                "cache_read_input_tokens": 2000,
                "cache_creation_input_tokens": 3000,
                "cache_creation": {
                    "ephemeral_5m_input_tokens": 1000,
                    "ephemeral_1h_input_tokens": 2000,
                },
                "service_tier": "standard",
            },
        },
    }
    for k, v in overrides.items():
        if k == "usage":
            row["message"]["usage"] = {**row["message"]["usage"], **v}
        elif k == "model":
            row["message"]["model"] = v
        else:
            row[k] = v
    return row


class TestParseTurn:
    def test_parses_assistant_row_with_nested_cache_creation(self):
        parsed = _parse_turn(_assistant_row())
        assert parsed is not None
        ts, session, model, cwd, usage = parsed
        assert ts == datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc)
        assert session == "session-123"
        assert model == "claude-sonnet-4-6"
        assert cwd == "/Users/jain/src/myproj"
        assert usage.input_tokens == 1000
        assert usage.output_tokens == 500
        assert usage.cache_read_tokens == 2000
        assert usage.cache_write_5m_tokens == 1000
        assert usage.cache_write_1h_tokens == 2000

    def test_flat_cache_creation_input_tokens_treated_as_5m(self):
        """Older transcripts only emit the flat field; no nested breakdown."""
        row = _assistant_row()
        row["message"]["usage"].pop("cache_creation")
        parsed = _parse_turn(row)
        assert parsed is not None
        _, _, _, _, usage = parsed
        assert usage.cache_write_5m_tokens == 3000
        assert usage.cache_write_1h_tokens == 0

    def test_skips_non_assistant_rows(self):
        assert _parse_turn({"type": "user", "content": "hello"}) is None
        assert _parse_turn({"type": "attachment"}) is None
        assert _parse_turn({"type": "queue-operation"}) is None

    def test_skips_assistant_without_usage(self):
        row = _assistant_row()
        row["message"].pop("usage")
        assert _parse_turn(row) is None

    def test_skips_assistant_with_zero_total_tokens(self):
        row = _assistant_row(usage={
            "input_tokens": 0, "output_tokens": 0,
            "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
        })
        row["message"]["usage"]["cache_creation"] = {
            "ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 0,
        }
        assert _parse_turn(row) is None

    def test_skips_rows_missing_timestamp(self):
        row = _assistant_row()
        row.pop("timestamp")
        assert _parse_turn(row) is None

    def test_skips_rows_with_unparseable_timestamp(self):
        row = _assistant_row(timestamp="not-a-date")
        assert _parse_turn(row) is None


# ─── iter_jsonl_turns + aggregate_costs (integration with disk) ──────


@pytest.fixture
def fake_projects_dir(tmp_path: Path) -> Path:
    """Build a small two-project, two-session fixture mirroring Claude Code layout."""
    projects_dir = tmp_path / "projects"
    proj_a = projects_dir / "-Users-jain-src-proj-a"
    proj_b = projects_dir / "-Users-jain-src-proj-b"
    proj_a.mkdir(parents=True)
    proj_b.mkdir()

    # Project A, session 1 — two turns on April 1 (Sonnet)
    session_a = proj_a / "session-alpha.jsonl"
    with session_a.open("w") as f:
        f.write(json.dumps({
            "type": "user",  # noise — must be ignored
            "timestamp": "2026-04-01T10:00:00Z",
            "content": "hi",
        }) + "\n")
        f.write(json.dumps(_assistant_row(
            timestamp="2026-04-01T11:30:00Z",
            cwd="/Users/jain/src/proj-a",
            sessionId="session-alpha",
            model="claude-sonnet-4-6",
            usage={
                "input_tokens": 100, "output_tokens": 50,
                "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
            },
        )) + "\n")
        f.write(json.dumps(_assistant_row(
            timestamp="2026-04-01T12:30:00Z",
            cwd="/Users/jain/src/proj-a",
            sessionId="session-alpha",
            model="claude-sonnet-4-6",
            usage={
                "input_tokens": 200, "output_tokens": 100,
                "cache_read_input_tokens": 500, "cache_creation_input_tokens": 0,
            },
        )) + "\n")
        f.write("this line is malformed JSON and must be skipped\n")

    # Project A, session 2 — one turn on April 2 (Opus)
    session_a2 = proj_a / "session-beta.jsonl"
    with session_a2.open("w") as f:
        f.write(json.dumps(_assistant_row(
            timestamp="2026-04-02T08:00:00Z",
            cwd="/Users/jain/src/proj-a",
            sessionId="session-beta",
            model="claude-opus-4-7",
            usage={
                "input_tokens": 10, "output_tokens": 5,
                "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
            },
        )) + "\n")

    # Project B, session 1 — one turn on April 1 (Sonnet) — missing cwd
    session_b = proj_b / "session-gamma.jsonl"
    with session_b.open("w") as f:
        row = _assistant_row(
            timestamp="2026-04-01T15:00:00Z",
            sessionId="session-gamma",
            model="claude-sonnet-4-6",
            usage={
                "input_tokens": 50, "output_tokens": 25,
                "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
            },
        )
        row.pop("cwd")
        f.write(json.dumps(row) + "\n")

    # Non-JSONL noise file in a project dir — must be ignored
    (proj_b / "notes.txt").write_text("ignore me")

    return projects_dir


class TestIterJsonlTurnsAndAggregate:
    def test_iter_yields_only_assistant_rows_with_usage(self, fake_projects_dir: Path):
        turns = list(iter_jsonl_turns(fake_projects_dir))
        assert len(turns) == 4  # three in proj-a (1 skipped noise) + 1 in proj-b

    def test_iter_skips_malformed_json(self, fake_projects_dir: Path):
        # Already covered above; ensure no exception even with bad lines present.
        assert list(iter_jsonl_turns(fake_projects_dir))

    def test_aggregate_buckets_by_day_project_and_model(self, fake_projects_dir: Path):
        turns = list(iter_jsonl_turns(fake_projects_dir))
        costs = aggregate_costs(turns)
        # Buckets expected:
        #   (2026-04-01, proj-a, claude-sonnet-4-6)  ← two turns merged
        #   (2026-04-01, Users-jain-src-proj-b, claude-sonnet-4-6)  ← cwd missing
        #   (2026-04-02, proj-a, claude-opus-4-7)
        assert len(costs) == 3

        by_key = {(c.date, c.team, c.resource): c for c in costs}
        assert ("2026-04-01", "proj-a", "claude-sonnet-4-6") in by_key
        assert ("2026-04-02", "proj-a", "claude-opus-4-7") in by_key

        proj_a_day1 = by_key[("2026-04-01", "proj-a", "claude-sonnet-4-6")]
        # Merged: input=300, output=150, cache_read=500
        assert proj_a_day1.metadata["input_tokens"] == 300
        assert proj_a_day1.metadata["output_tokens"] == 150
        assert proj_a_day1.metadata["cache_read_tokens"] == 500

    def test_aggregate_since_filter_drops_older_turns(self, fake_projects_dir: Path):
        turns = list(iter_jsonl_turns(fake_projects_dir))
        cutoff = datetime(2026, 4, 2, 0, 0, 0, tzinfo=timezone.utc)
        costs = aggregate_costs(turns, since=cutoff)
        # Only the Apr-02 Opus turn in proj-a survives.
        assert len(costs) == 1
        assert costs[0].date == "2026-04-02"
        assert costs[0].resource == "claude-opus-4-7"

    def test_unified_cost_shape(self, fake_projects_dir: Path):
        turns = list(iter_jsonl_turns(fake_projects_dir))
        costs = aggregate_costs(turns)
        for c in costs:
            assert isinstance(c, UnifiedCost)
            assert c.platform == "claude_code"
            assert c.service == "claude_code"
            assert c.category == CostCategory.ai_inference
            assert c.usage_unit == "tokens"
            assert c.cost_usd > 0
            assert set(c.metadata) >= {
                "model", "project", "input_tokens", "output_tokens",
                "cache_read_tokens", "cache_write_5m_tokens", "cache_write_1h_tokens",
            }


# ─── ClaudeCodeConnector ─────────────────────────────────────────────


class TestClaudeCodeConnector:
    def test_is_base_connector(self):
        assert issubclass(ClaudeCodeConnector, BaseConnector)

    def test_platform_attribute(self):
        assert ClaudeCodeConnector.platform == "claude_code"

    def test_uses_default_projects_dir_when_credentials_empty(self):
        connector = ClaudeCodeConnector({})
        assert str(connector.projects_dir).endswith(".claude/projects")

    def test_uses_custom_projects_dir(self, tmp_path: Path):
        connector = ClaudeCodeConnector({"projects_dir": str(tmp_path)})
        assert connector.projects_dir == tmp_path

    def test_expands_tilde_in_projects_dir(self):
        connector = ClaudeCodeConnector({"projects_dir": "~/.claude/projects"})
        assert "~" not in str(connector.projects_dir)

    def test_test_connection_missing_dir(self, tmp_path: Path):
        connector = ClaudeCodeConnector({"projects_dir": str(tmp_path / "nope")})
        result = connector.test_connection()
        assert result["success"] is False
        assert "not found" in result["message"]

    def test_test_connection_empty_dir(self, tmp_path: Path):
        connector = ClaudeCodeConnector({"projects_dir": str(tmp_path)})
        result = connector.test_connection()
        assert result["success"] is False
        assert "No Claude Code session files" in result["message"]

    def test_test_connection_success(self, fake_projects_dir: Path):
        connector = ClaudeCodeConnector({"projects_dir": str(fake_projects_dir)})
        result = connector.test_connection()
        assert result["success"] is True
        assert "Found" in result["message"]

    def test_fetch_costs_respects_days_window(self, fake_projects_dir: Path):
        connector = ClaudeCodeConnector({"projects_dir": str(fake_projects_dir)})
        # Our fixture is pinned to April 2026; by 2026-04-23 all turns are 20+ days old.
        # Passing a large enough window should surface all 3 aggregated records.
        costs = connector.fetch_costs(days=365 * 5)
        assert len(costs) == 3

    def test_fetch_costs_with_small_window_returns_nothing_for_old_fixture(
        self, fake_projects_dir: Path
    ):
        """The fixture's April 2026 data is older than 7 days relative to `now`
        for any reasonable test-run date, so a small window yields no records."""
        connector = ClaudeCodeConnector({"projects_dir": str(fake_projects_dir)})
        # Use a 1-day window — should drop everything from April 1-2, 2026
        # (unless tests are somehow run before Apr 3 2026, which the CI isn't).
        now = datetime.now(tz=timezone.utc)
        if now > datetime(2026, 4, 3, tzinfo=timezone.utc):
            assert connector.fetch_costs(days=1) == []

    def test_fetch_costs_returns_unified_cost_records(self, fake_projects_dir: Path):
        connector = ClaudeCodeConnector({"projects_dir": str(fake_projects_dir)})
        costs = connector.fetch_costs(days=365 * 5)
        assert all(isinstance(c, UnifiedCost) for c in costs)
        assert all(c.platform == "claude_code" for c in costs)
