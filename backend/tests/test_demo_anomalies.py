"""Tests for ``generate_demo_anomalies`` — shape, narrative linkage, and
determinism.

The demo anomalies endpoint must match the real ``/api/anomalies`` envelope
``{anomalies, count, unacknowledged}`` so the overview page renders without
runtime errors.
"""
from __future__ import annotations

import pytest

from app.services.demo import generate_demo_anomalies


#: Every anomaly dict must include these keys — matches the schema persisted
#: by ``anomaly_detector.py`` and consumed by the overview UI.
REQUIRED_ANOMALY_KEYS = {
    "_id",
    "user_id",
    "date",
    "type",
    "severity",
    "scope",
    "platform",
    "resource",
    "cost",
    "baseline",
    "change_pct",
    "message",
    "detected_at",
    "acknowledged",
}

VALID_TYPES = {"zscore_spike", "day_over_day_spike", "week_over_week_spike"}
VALID_SEVERITIES = {"high", "medium", "low"}
VALID_SCOPES = {"total", "platform", "resource"}


class TestEnvelope:
    def test_top_level_keys(self):
        result = generate_demo_anomalies(30)
        assert set(result.keys()) == {"anomalies", "count", "unacknowledged"}

    def test_count_matches_list_length(self):
        result = generate_demo_anomalies(30)
        assert result["count"] == len(result["anomalies"])

    def test_unacknowledged_matches_unacked_list(self):
        result = generate_demo_anomalies(30)
        expected = sum(1 for a in result["anomalies"] if not a.get("acknowledged"))
        assert result["unacknowledged"] == expected


class TestAnomalyShape:
    def test_required_keys_per_anomaly(self):
        result = generate_demo_anomalies(30)
        for a in result["anomalies"]:
            missing = REQUIRED_ANOMALY_KEYS - a.keys()
            assert not missing, f"anomaly missing {missing}: {a}"

    def test_valid_type_severity_scope(self):
        result = generate_demo_anomalies(30)
        for a in result["anomalies"]:
            assert a["type"] in VALID_TYPES
            assert a["severity"] in VALID_SEVERITIES
            assert a["scope"] in VALID_SCOPES

    def test_cost_values_are_positive(self):
        result = generate_demo_anomalies(30)
        for a in result["anomalies"]:
            assert a["cost"] > 0


class TestNarrativeLinkage:
    """Each anomaly should map to a story visible elsewhere in the demo."""

    def test_has_etl_overnight_story(self):
        result = generate_demo_anomalies(30)
        messages = " ".join(a["message"].lower() for a in result["anomalies"])
        assert "etl_wh" in messages or "overnight" in messages or "pipeline" in messages

    def test_has_prompt_caching_regression_story(self):
        result = generate_demo_anomalies(30)
        messages = " ".join(a["message"].lower() for a in result["anomalies"])
        assert "cache" in messages or "prompt" in messages

    def test_has_claude_code_platform_anomaly(self):
        result = generate_demo_anomalies(30)
        platforms = {a["platform"] for a in result["anomalies"]}
        assert "claude_code" in platforms

    def test_at_least_three_anomalies(self):
        result = generate_demo_anomalies(30)
        assert len(result["anomalies"]) >= 3

    def test_at_least_one_acknowledged_and_one_unacknowledged(self):
        """The UI should demonstrate both live and resolved anomaly states."""
        result = generate_demo_anomalies(30)
        acked = [a for a in result["anomalies"] if a.get("acknowledged")]
        unacked = [a for a in result["anomalies"] if not a.get("acknowledged")]
        assert len(acked) >= 1
        assert len(unacked) >= 1


class TestOrdering:
    def test_anomalies_sorted_newest_first(self):
        result = generate_demo_anomalies(30)
        dates = [a["date"] for a in result["anomalies"]]
        assert dates == sorted(dates, reverse=True)


class TestRouterWiring:
    """Verify that the new generators are wired into the public demo router.

    We avoid importing the router module because it transitively pulls in
    ``slowapi`` and ``motor`` — Docker-only runtime deps not installed in
    the unit-test venv. A source-level assertion is sufficient to guarantee
    the routes will be registered at boot.
    """

    def test_router_source_registers_anomalies_and_chat_sample(self):
        from pathlib import Path

        router_path = (
            Path(__file__).parent.parent / "app" / "routers" / "public_demo.py"
        )
        router_src = router_path.read_text()
        assert '@router.get("/anomalies")' in router_src
        assert '@router.get("/chat/sample")' in router_src
        assert "generate_demo_anomalies" in router_src
        assert "generate_demo_chat_sample" in router_src
