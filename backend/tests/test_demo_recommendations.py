"""Tests for ``generate_demo_recommendations`` — shape, mix, and GitHub PR
body previews.
"""
from __future__ import annotations

import pytest

from app.services.demo import generate_demo_recommendations


REQUIRED_KEYS = {
    "id",
    "title",
    "description",
    "category",
    "potential_savings",
    "effort",
    "priority",
}


class TestShape:
    def test_required_keys_per_recommendation(self):
        recs = generate_demo_recommendations()
        for r in recs:
            missing = REQUIRED_KEYS - r.keys()
            assert not missing, f"missing {missing}: {r}"

    def test_at_least_five_recommendations(self):
        recs = generate_demo_recommendations()
        assert len(recs) >= 5

    def test_unique_ids(self):
        recs = generate_demo_recommendations()
        ids = [r["id"] for r in recs]
        assert len(ids) == len(set(ids))

    def test_valid_priority_values(self):
        recs = generate_demo_recommendations()
        for r in recs:
            assert r["priority"] in {"high", "medium", "low"}

    def test_valid_effort_values(self):
        recs = generate_demo_recommendations()
        for r in recs:
            assert r["effort"] in {"low", "medium", "high"}


class TestPriorityMix:
    def test_has_high_medium_and_low_priority(self):
        """The checklist calls for a mix of impact levels."""
        recs = generate_demo_recommendations()
        priorities = {r["priority"] for r in recs}
        assert priorities == {"high", "medium", "low"}

    def test_multiple_categories_covered(self):
        recs = generate_demo_recommendations()
        categories = {r["category"] for r in recs}
        # Warehouse, query, storage should all be represented.
        assert {"warehouse", "query", "storage"} <= categories


class TestPrPreview:
    def test_high_priority_items_have_pr_preview(self):
        """The 'Apply via GitHub PR' flow needs a rendered body for high-impact fixes."""
        recs = generate_demo_recommendations()
        high = [r for r in recs if r["priority"] == "high"]
        assert high, "expected at least one high-priority recommendation"
        for r in high:
            assert r.get("pr_preview") is not None, r
            pr = r["pr_preview"]
            assert "title" in pr and pr["title"]
            assert "body" in pr and "##" in pr["body"]  # markdown sections
            assert "files_changed" in pr and isinstance(pr["files_changed"], list)
            assert "diff_lines" in pr

    def test_high_priority_items_have_ddl_command(self):
        recs = generate_demo_recommendations()
        high = [r for r in recs if r["priority"] == "high"]
        for r in high:
            assert r.get("ddl_command"), r

    def test_low_priority_items_may_omit_ddl(self):
        """Low priority items can be manual / non-DDL without PR preview."""
        recs = generate_demo_recommendations()
        low = [r for r in recs if r["priority"] == "low"]
        assert low, "expected at least one low-priority recommendation"
        # At least one low-priority item should document that it's manual.
        assert any(r.get("ddl_command") is None for r in low)


class TestDeterminism:
    def test_two_calls_return_identical(self):
        a = generate_demo_recommendations()
        b = generate_demo_recommendations()
        assert a == b


class TestSavingsBudget:
    def test_total_potential_savings_reasonable(self):
        recs = generate_demo_recommendations()
        total = sum(r["potential_savings"] for r in recs)
        # Should be in a believable monthly range for a mid-sized setup.
        assert 500 < total < 3000, f"total savings {total} looks off"
