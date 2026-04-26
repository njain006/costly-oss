"""Tests for ``generate_demo_platform_connections`` — shape must match the
real ``/api/platforms`` endpoint so the Platforms page renders correctly.
"""
from __future__ import annotations

import pytest

from app.services.demo_platforms import (
    generate_demo_platform_connections,
    generate_demo_unified_costs,
)


REQUIRED_PLATFORM_KEYS = {
    "id",
    "platform",
    "name",
    "created_at",
    "last_synced",
    "pricing_overrides",
}


class TestPlatformConnections:
    def test_required_keys_match_production_shape(self):
        conns = generate_demo_platform_connections()
        for c in conns:
            missing = REQUIRED_PLATFORM_KEYS - c.keys()
            assert not missing, f"missing {missing}: {c}"

    def test_five_to_eight_platforms_connected(self):
        """Checklist: 5-8 connected platforms so the page doesn't look empty."""
        conns = generate_demo_platform_connections()
        assert 5 <= len(conns) <= 8

    def test_unique_ids_and_platforms(self):
        conns = generate_demo_platform_connections()
        ids = [c["id"] for c in conns]
        platforms = [c["platform"] for c in conns]
        assert len(set(ids)) == len(ids)
        assert len(set(platforms)) == len(platforms)

    def test_includes_core_platforms(self):
        conns = generate_demo_platform_connections()
        platforms = {c["platform"] for c in conns}
        # The demo story spans warehouse, AI APIs, and transformation — all
        # three tiers should have at least one representative.
        assert "snowflake" in platforms
        assert "aws" in platforms
        assert {"openai", "anthropic", "gemini"} & platforms
        assert "dbt_cloud" in platforms

    def test_pricing_overrides_realistic(self):
        """At least one connection should demonstrate custom/negotiated pricing."""
        conns = generate_demo_platform_connections()
        overrides = [c["pricing_overrides"] for c in conns if c["pricing_overrides"]]
        assert overrides, "expected at least one pricing override"

    def test_all_have_recent_sync(self):
        """Demo should look live — every platform should have a last_synced value."""
        conns = generate_demo_platform_connections()
        for c in conns:
            assert c["last_synced"] is not None

    def test_all_have_created_at(self):
        conns = generate_demo_platform_connections()
        for c in conns:
            assert c["created_at"] is not None


class TestUnifiedCosts:
    def test_unified_costs_basic_shape(self):
        """Sanity check that ``/api/demo/platforms/costs`` envelope is intact."""
        result = generate_demo_unified_costs(30)
        assert set(result.keys()) >= {
            "total_cost", "days", "by_platform", "by_category",
            "by_service", "daily_trend", "top_resources",
        }
        assert result["days"] == 30
        assert result["total_cost"] > 0

    def test_unified_costs_daily_trend_length_matches_days(self):
        result = generate_demo_unified_costs(14)
        assert len(result["daily_trend"]) == 14
