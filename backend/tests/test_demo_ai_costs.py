"""Tests for ``generate_demo_ai_costs`` — shape + determinism + tool_use breakdown.

The AI costs generator is the core of the /ai-costs page in demo mode, so it
must:
  * Be deterministic (two calls with the same ``days`` produce identical output)
  * Match the public ``/api/ai-costs`` response shape exactly
  * Include the ``tool_use`` breakdown so the UI can render a per-tool chart
  * Tell the prompt-caching story (days 19-23 have a cache regression)
"""
from __future__ import annotations

import pytest

from app.services.demo import (
    _CLAUDE_CODE_TOOL_MIX,
    generate_demo_ai_costs,
)


# ── Required top-level keys from the production endpoint ─────────────────────
AI_COSTS_TOP_KEYS = {
    "kpis",
    "providers",
    "daily_spend",
    "daily_tokens",
    "cost_per_1k_trend",
    "model_breakdown",
    "recommendations",
    "tool_use",
}

KPI_KEYS = {
    "total_cost",
    "total_tokens",
    "avg_cost_per_1k",
    "mom_change",
    "model_count",
    "provider_count",
    "cache_hit_rate",
    "cache_savings_usd",
    "cache_read_tokens",
    "cache_write_tokens",
}


class TestShape:
    def test_top_level_keys_match_production(self):
        result = generate_demo_ai_costs(30)
        assert set(result.keys()) == AI_COSTS_TOP_KEYS

    def test_kpi_keys_match_production(self):
        result = generate_demo_ai_costs(30)
        assert set(result["kpis"].keys()) == KPI_KEYS

    def test_daily_spend_entry_shape(self):
        result = generate_demo_ai_costs(30)
        entry = result["daily_spend"][0]
        assert set(entry.keys()) == {"date", "anthropic", "claude_code", "openai", "gemini"}

    def test_daily_tokens_entry_shape(self):
        result = generate_demo_ai_costs(30)
        entry = result["daily_tokens"][0]
        assert set(entry.keys()) == {"date", "cache_read", "cache_write", "input", "output", "total"}

    def test_provider_entry_shape(self):
        result = generate_demo_ai_costs(30)
        prov = result["providers"][0]
        assert set(prov.keys()) == {
            "platform", "cost", "tokens", "input_tokens", "output_tokens", "cost_per_1k",
        }

    def test_exactly_four_providers(self):
        result = generate_demo_ai_costs(30)
        platforms = {p["platform"] for p in result["providers"]}
        assert platforms == {"anthropic", "claude_code", "openai", "gemini"}


class TestDeterminism:
    def test_two_calls_same_days_identical(self):
        a = generate_demo_ai_costs(30)
        b = generate_demo_ai_costs(30)
        # Strip out fields that might vary if the implementation ever introduces
        # non-determinism — today both should match perfectly.
        assert a == b

    def test_snapshot_kpis_30_days(self):
        """Snapshot of key KPI values — guards against accidental drift."""
        result = generate_demo_ai_costs(30)
        kpis = result["kpis"]
        # Totals are a function of the seeded RNG + the story-telling spike.
        # Pin them to sensible ranges so small tweaks don't break the test
        # but large regressions do.
        assert 4000 < kpis["total_cost"] < 10000
        assert kpis["provider_count"] == 4
        assert kpis["model_count"] == 8
        assert 0 < kpis["cache_hit_rate"] < 100
        assert kpis["cache_read_tokens"] > kpis["cache_write_tokens"]

    def test_respects_days_parameter(self):
        r7 = generate_demo_ai_costs(7)
        r30 = generate_demo_ai_costs(30)
        assert len(r7["daily_spend"]) == 7
        assert len(r30["daily_spend"]) == 30
        assert len(r7["daily_tokens"]) == 7
        assert len(r30["daily_tokens"]) == 30


class TestToolUse:
    def test_tool_use_top_level_present(self):
        result = generate_demo_ai_costs(30)
        assert "tool_use" in result
        assert "daily" in result["tool_use"]
        assert "totals" in result["tool_use"]

    def test_tool_use_daily_length_matches_days(self):
        result = generate_demo_ai_costs(15)
        assert len(result["tool_use"]["daily"]) == 15

    def test_tool_use_daily_covers_all_tools(self):
        result = generate_demo_ai_costs(7)
        expected_tools = {t[0] for t in _CLAUDE_CODE_TOOL_MIX}
        for row in result["tool_use"]["daily"]:
            for tool_name in expected_tools:
                assert tool_name in row, f"missing {tool_name}"
                assert f"{tool_name}_calls" in row
                assert f"{tool_name}_avg_seconds" in row

    def test_tool_use_totals_shape(self):
        result = generate_demo_ai_costs(30)
        totals = result["tool_use"]["totals"]
        assert len(totals) == len(_CLAUDE_CODE_TOOL_MIX)
        for entry in totals:
            assert set(entry.keys()) == {"tool", "cost", "calls", "avg_seconds", "pct"}
            assert entry["cost"] >= 0
            assert entry["calls"] >= 0

    def test_tool_use_totals_sorted_by_cost_desc(self):
        result = generate_demo_ai_costs(30)
        costs = [t["cost"] for t in result["tool_use"]["totals"]]
        assert costs == sorted(costs, reverse=True)

    def test_bash_and_edit_dominate_tool_costs(self):
        """The tool mix puts Bash at ~32% and Edit at ~24% — verify they top the chart."""
        result = generate_demo_ai_costs(30)
        top_two = {t["tool"] for t in result["tool_use"]["totals"][:2]}
        assert top_two == {"Bash", "Edit"}

    def test_tool_use_totals_roughly_sum_to_claude_code_total(self):
        """Sum of per-tool cost should approximate the claude_code daily total."""
        result = generate_demo_ai_costs(30)
        cc_total = sum(d["claude_code"] for d in result["daily_spend"])
        tool_total = sum(t["cost"] for t in result["tool_use"]["totals"])
        # Jitter + rounding keep these close but not identical.
        assert abs(cc_total - tool_total) / cc_total < 0.05


class TestStory:
    def test_cache_regression_window_19_to_23_present(self):
        """Days 19-23 should show elevated claude_code spend (the regression)."""
        result = generate_demo_ai_costs(30)
        spend = result["daily_spend"]
        regression_avg = sum(d["claude_code"] for d in spend[19:24]) / 5
        baseline_avg = sum(d["claude_code"] for d in spend[:19]) / 19
        assert regression_avg > baseline_avg * 1.3, (
            f"regression window {regression_avg:.0f} should be >>"
            f" baseline {baseline_avg:.0f}"
        )

    def test_recommendations_mention_cache_regression(self):
        result = generate_demo_ai_costs(30)
        titles = [r["title"].lower() for r in result["recommendations"]]
        assert any("cache" in t for t in titles)
