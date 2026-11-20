"""Anomaly detector: one anomaly per spike, trailing baseline, computed cause."""
from datetime import datetime, timedelta

from app.services.anomaly_detector import detect, find_drivers, trailing_stats

START = datetime(2026, 10, 1)


def _day(i):
    return (START + timedelta(days=i)).strftime("%Y-%m-%d")


def _rows(days=31, spike_day=None, spike_line=("snowflake", "snowflake_cortex", "AI functions"), spike=500.0):
    rows = []
    for i in range(days):
        # Steady compute with a little noise, plus a small AI line.
        rows.append({"date": _day(i), "platform": "snowflake", "service": "snowflake_compute",
                     "resource": "WH_A", "cost_usd": 100 + (i % 3)})
        rows.append({"date": _day(i), "platform": "snowflake", "service": "snowflake_cortex",
                     "resource": "AI functions", "cost_usd": 2.0})
        if i == spike_day:
            p, s, r = spike_line
            rows.append({"date": _day(i), "platform": p, "service": s, "resource": r, "cost_usd": spike})
    return rows


def test_one_spike_is_one_anomaly_with_computed_cause():
    rows = _rows(spike_day=29)
    out = detect(rows, "u1", today=_day(31))
    totals = [a for a in out if a["scope"] == "total"]
    assert len(totals) == 1, "z-score, day-over-day and week-over-week merge into one"
    a = totals[0]
    assert a["date"] == _day(29)
    assert {s["type"] for s in a["signals"]} == {"zscore_spike", "day_over_day_spike", "week_over_week_spike"}
    # The single-platform and the AI-line resource spikes are explained by the total one.
    assert len(out) == 1
    assert a["drivers"][0]["resource"] == "AI functions"
    assert a["drivers"][0]["delta"] > 490
    assert a["cause"].startswith("Mostly AI functions")


def test_baseline_is_trailing_and_excludes_the_spike_day():
    rows = _rows(spike_day=29)
    a = detect(rows, "u1", today=_day(31))[0]
    assert 100 < a["baseline_mean"] < 105  # not pulled up by the $500 spike


def test_today_is_skipped_because_data_is_partial():
    rows = _rows(days=31, spike_day=30)
    assert detect(rows, "u1", today=_day(30)) == []
    assert detect(rows, "u1", today=_day(31))


def test_needs_history_before_judging():
    rows = _rows(days=5, spike_day=4)
    assert detect(rows, "u1", today=_day(6)) == []


def test_resource_spike_inside_a_quiet_total_is_reported_alone():
    rows = []
    for i in range(31):
        rows.append({"date": _day(i), "platform": "snowflake", "service": "compute",
                     "resource": "BIG", "cost_usd": 1000 + (i % 5) * 100})
        rows.append({"date": _day(i), "platform": "snowflake", "service": "compute",
                     "resource": "SMALL", "cost_usd": 10 + (i % 2) + (40 if i == 27 else 0)})
    out = detect(rows, "u1", today=_day(31))
    assert [(a["scope"], a["resource"]) for a in out] == [("resource", "SMALL")]
    assert out[0]["drivers"][0]["resource"] == "SMALL"


def test_missing_days_count_as_zero():
    series = {_day(i): 10.0 for i in range(0, 20, 2)}
    dates = [_day(i) for i in range(21)]
    mean, _ = trailing_stats(series, _day(20), dates)
    assert mean == 5.0


def test_drivers_rank_by_increase_not_size():
    dates = [_day(i) for i in range(11)]
    lines = {
        ("p", "s", "big_steady"): {d: 1000.0 for d in dates},
        ("p", "s", "small_jump"): {**{d: 1.0 for d in dates}, dates[-1]: 60.0},
    }
    drivers = find_drivers(lines, dates[-1], dates)
    assert [d["resource"] for d in drivers] == ["small_jump"]


def test_sustained_rise_is_one_episode():
    rows = []
    for i in range(31):
        rows.append({"date": _day(i), "platform": "snowflake", "service": "compute",
                     "resource": "WH", "cost_usd": 100 + (i % 3) * 2 + (40 if i >= 25 else 0)})
    out = detect(rows, "u1", today=_day(31))
    eps = out  # one cost line, so the total-spend card reports it
    assert len(eps) == 1
    e = eps[0]
    assert e["date"] == _day(25) and e["days"] >= 3
    assert e["extra_cost"] > 100
    assert "since " + _day(25) in e["message"]


# ── Long episodes across re-scans ─────────────────────────────────────────────

from app.services.anomaly_detector import reconcile_episodes


def _ep(date, end, ack=None, _id=None, resource="WH"):
    d = {"user_id": "u", "type": "spike", "scope": "resource", "platform": "snowflake",
         "resource": resource, "date": date, "end_date": end, "days": 1}
    if ack is not None:
        d["acknowledged"] = ack
    if _id is not None:
        d["_id"] = _id
    return d


def test_episode_keeps_original_first_day_when_window_moves_on():
    # Stored as d1..d9; the next scan only sees it from d3.
    out, drop = reconcile_episodes([_ep("2026-11-03", "2026-11-10")],
                                   [_ep("2026-11-01", "2026-11-09", ack=False, _id=1)])
    assert [a["date"] for a in out] == ["2026-11-01"]
    assert out[0]["days"] == 10
    assert drop == []


def test_acknowledging_any_copy_hides_the_episode_and_extra_copies_are_removed():
    existing = [_ep("2026-11-01", "2026-11-09", ack=True, _id=1),
                _ep("2026-11-03", "2026-11-10", ack=False, _id=2)]
    out, drop = reconcile_episodes([_ep("2026-11-04", "2026-11-11")], existing)
    assert out[0]["date"] == "2026-11-01"
    assert out[0]["acknowledged"] is True
    assert drop == [2]


def test_separate_episodes_and_other_targets_are_untouched():
    existing = [_ep("2026-10-01", "2026-10-02", ack=True, _id=1),           # long ago
                _ep("2026-11-03", "2026-11-05", ack=True, _id=2, resource="OTHER")]
    out, drop = reconcile_episodes([_ep("2026-11-04", "2026-11-06")], existing)
    assert out[0]["date"] == "2026-11-04"
    assert "acknowledged" not in out[0]
    assert drop == []


def test_later_stored_copy_is_folded_into_an_earlier_new_episode():
    out, drop = reconcile_episodes([_ep("2026-11-01", "2026-11-05")],
                                   [_ep("2026-11-03", "2026-11-04", ack=False, _id=7)])
    assert out[0]["date"] == "2026-11-01"
    assert drop == [7]
