"""Anomaly detection engine for unified cost data.

One spike is one anomaly. For each of the last 7 days the detector checks
total, per-platform and per-resource spend against a TRAILING baseline (the
days before it, so a spike never inflates its own baseline). The checks for
total spend (z-score, day-over-day, week-over-week) are merged into a single
anomaly per day that lists every signal that fired.

The likely cause is computed, not guessed: every anomaly carries `drivers`,
the cost lines (platform / service / resource) that rose the most against
their own trailing average that day, and `cause`, a sentence built from them.

Anomalies are stored in the `anomalies` collection and surfaced via API.
"""

import math
from collections import defaultdict
from datetime import datetime, timedelta

from app.database import db


# ── Thresholds ────────────────────────────────────────────────────────────────

ZSCORE_THRESHOLD = 2.0          # Standard deviations above the trailing mean
DOD_SPIKE_PCT = 0.50            # 50% day-over-day increase
WOW_SPIKE_PCT = 0.30            # 30% week-over-week increase
MIN_COST_FOR_ALERT = 5.0        # Ignore series averaging under $5/day
MIN_DELTA_USD = 5.0             # Ignore spikes smaller than $5 above baseline
LOOKBACK_DAYS = 30              # Trailing window for the baseline
RECENT_DAYS = 7                 # Days checked for new anomalies
MIN_HISTORY = 7                 # Days of history needed before judging a day
EXPLAINED_SHARE = 0.8           # A platform/resource that explains 80%+ of a
                                # total spike is reported inside it, not again
MAX_DRIVERS = 3


# ── Pure helpers (unit-tested) ───────────────────────────────────────────────

def _dates_between(start: str, end: str) -> list[str]:
    d0 = datetime.strptime(start, "%Y-%m-%d")
    d1 = datetime.strptime(end, "%Y-%m-%d")
    return [(d0 + timedelta(days=i)).strftime("%Y-%m-%d") for i in range((d1 - d0).days + 1)]


def _shift(date: str, days: int) -> str:
    return (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=days)).strftime("%Y-%m-%d")


def trailing_stats(series: dict, date: str, all_dates: list) -> tuple | None:
    """Mean and stddev of the LOOKBACK_DAYS before `date`, zero-filled.

    Days with no row count as $0 (a resource that did not run cost nothing).
    Returns None when there is not enough history to judge the day."""
    prior = [d for d in all_dates if d < date][-LOOKBACK_DAYS:]
    if len(prior) < MIN_HISTORY:
        return None
    vals = [series.get(d, 0.0) for d in prior]
    mean = sum(vals) / len(vals)
    std = math.sqrt(sum((v - mean) ** 2 for v in vals) / len(vals))
    return mean, std


def find_drivers(lines: dict, date: str, all_dates: list, limit: int = MAX_DRIVERS) -> list[dict]:
    """Cost lines that rose the most on `date` vs their own trailing mean.

    `lines` maps (platform, service, resource) -> {date: cost}."""
    out = []
    for (platform, service, resource), series in lines.items():
        stats = trailing_stats(series, date, all_dates)
        base = stats[0] if stats else 0.0
        cost = series.get(date, 0.0)
        delta = cost - base
        if delta >= 1.0:
            out.append({
                "platform": platform, "service": service, "resource": resource,
                "cost": round(cost, 2), "baseline": round(base, 2), "delta": round(delta, 2),
            })
    out.sort(key=lambda d: -d["delta"])
    return out[:limit]


def describe_drivers(drivers: list, total_delta: float) -> str:
    if not drivers:
        return ("No single cost line stands out; the rise is spread across many small ones. "
                "Open Investigate for the full breakdown.")
    parts = []
    for d in drivers:
        name = d["resource"] or d["service"] or d["platform"]
        where = d["service"] or d["platform"]
        label = f"{name} ({where})" if where and where != name else name
        parts.append(f"{label} +${d['delta']:,.0f} (${d['cost']:,.0f} vs ${d['baseline']:,.0f}/day usual)")
    share = sum(d["delta"] for d in drivers) / total_delta if total_delta > 0 else 0
    lead = "Mostly" if share >= 0.8 else "Largest increases:"
    return f"{lead} " + "; ".join(parts) + "."


def total_signals(totals: dict, date: str, all_dates: list) -> tuple:
    """Which total-spend checks fire on `date`. Returns (signals, stats)."""
    signals = []
    cost = totals.get(date, 0.0)
    stats = trailing_stats(totals, date, all_dates)
    if stats:
        mean, std = stats
        if mean >= MIN_COST_FOR_ALERT and std > 0:
            z = (cost - mean) / std
            if z >= ZSCORE_THRESHOLD:
                signals.append({
                    "type": "zscore_spike", "zscore": round(z, 2),
                    "message": f"{z:.1f} standard deviations above the {LOOKBACK_DAYS}-day average",
                })
    prev = totals.get(_shift(date, -1))
    if prev is not None and prev >= MIN_COST_FOR_ALERT and (cost - prev) / prev >= DOD_SPIKE_PCT:
        signals.append({
            "type": "day_over_day_spike", "pct_change": round((cost - prev) / prev * 100, 1),
            "message": f"up {(cost - prev) / prev * 100:.0f}% on the previous day (${prev:,.0f})",
        })
    wk = totals.get(_shift(date, -7))
    if wk is not None and wk >= MIN_COST_FOR_ALERT and (cost - wk) / wk >= WOW_SPIKE_PCT:
        signals.append({
            "type": "week_over_week_spike", "pct_change": round((cost - wk) / wk * 100, 1),
            "message": f"up {(cost - wk) / wk * 100:.0f}% on the same day last week (${wk:,.0f})",
        })
    return signals, stats


def _series_spike(series: dict, date: str, all_dates: list):
    stats = trailing_stats(series, date, all_dates)
    if not stats:
        return None
    mean, std = stats
    cost = series.get(date, 0.0)
    if mean < MIN_COST_FOR_ALERT or std == 0 or cost - mean < MIN_DELTA_USD:
        return None
    z = (cost - mean) / std
    return (cost, mean, z) if z >= ZSCORE_THRESHOLD else None


def detect(rows: list[dict], user_id: str, today: str | None = None) -> list[dict]:
    """Detect anomalies from cost rows ({date, platform, service, resource, cost_usd})."""
    if not rows:
        return []
    totals: dict = defaultdict(float)
    by_platform: dict = defaultdict(lambda: defaultdict(float))
    by_resource: dict = defaultdict(lambda: defaultdict(float))
    lines: dict = defaultdict(lambda: defaultdict(float))
    for r in rows:
        d, cost = r["date"], float(r.get("cost_usd") or 0)
        p, s, res = r.get("platform") or "", r.get("service") or "", r.get("resource") or ""
        totals[d] += cost
        by_platform[p][d] += cost
        if res:
            by_resource[(p, res)][d] += cost
        lines[(p, s, res)][d] += cost

    all_dates = _dates_between(min(totals), max(totals))
    today = today or datetime.utcnow().strftime("%Y-%m-%d")
    # Today's data is still arriving (billing views lag hours), so skip it.
    recent = [d for d in all_dates if d < today][-RECENT_DAYS:]
    out = []

    def make(date, scope, platform, resource, cost, mean, severity, message, signals, scoped_lines):
        drivers = find_drivers(scoped_lines, date, all_dates)
        delta = cost - mean
        return {
            "user_id": user_id, "date": date, "type": "spike", "scope": scope,
            "platform": platform, "resource": resource, "severity": severity,
            "cost": round(cost, 2), "baseline_mean": round(mean, 2),
            "pct_change": round(delta / mean * 100, 1) if mean > 0 else None,
            "zscore": next((s["zscore"] for s in signals if s.get("zscore") is not None), None),
            "signals": signals, "message": message,
            "drivers": drivers, "cause": describe_drivers(drivers, delta),
        }

    for date in recent:
        cost = totals.get(date, 0.0)
        signals, stats = total_signals(totals, date, all_dates)
        total_delta = None
        if signals and stats and cost - stats[0] >= MIN_DELTA_USD:
            mean = stats[0]
            total_delta = cost - mean
            high = any(s.get("zscore", 0) >= 3 or s.get("pct_change", 0) >= 100 for s in signals)
            msg = (f"Total spend ${cost:,.0f} vs ${mean:,.0f}/day usual: "
                   + "; ".join(s["message"] for s in signals) + ".")
            out.append(make(date, "total", "", "", cost, mean, "high" if high else "medium",
                            msg, signals, lines))

        def explained(delta):
            # Already reported (and explained) by the total-spend anomaly.
            return total_delta is not None and delta >= EXPLAINED_SHARE * total_delta

        for platform, series in by_platform.items():
            hit = _series_spike(series, date, all_dates)
            if not hit:
                continue
            c, mean, z = hit
            if explained(c - mean) or (len(by_platform) == 1 and total_delta is not None):
                continue
            msg = (f"{platform} spend ${c:,.0f} vs ${mean:,.0f}/day usual "
                   f"({z:.1f} standard deviations above its {LOOKBACK_DAYS}-day average).")
            plines = {k: v for k, v in lines.items() if k[0] == platform}
            out.append(make(date, "platform", platform, "", c, mean, "high" if z >= 3 else "medium",
                            msg, [{"type": "zscore_spike", "zscore": round(z, 2), "message": msg}], plines))

        for (platform, resource), series in by_resource.items():
            hit = _series_spike(series, date, all_dates)
            if not hit:
                continue
            c, mean, z = hit
            if explained(c - mean):
                continue
            msg = (f"{resource} cost ${c:,.0f} vs ${mean:,.0f}/day usual "
                   f"({z:.1f} standard deviations above its {LOOKBACK_DAYS}-day average).")
            rlines = {k: v for k, v in lines.items() if k[0] == platform and k[2] == resource}
            out.append(make(date, "resource", platform, resource, c, mean, "high" if z >= 3 else "medium",
                            msg, [{"type": "zscore_spike", "zscore": round(z, 2), "message": msg}], rlines))
    return merge_episodes(out)


EPISODE_GAP_DAYS = 2            # spikes this close together are one episode


def merge_episodes(anomalies: list[dict]) -> list[dict]:
    """A cost that stays high for several days is one ongoing anomaly, not one
    per day. Consecutive spikes on the same target (allowing a quiet day in
    between) merge into an episode keyed by its first day, so the record is
    stable while the episode continues."""
    groups: dict = defaultdict(list)
    for a in sorted(anomalies, key=lambda a: a["date"]):
        groups[(a["scope"], a["platform"], a["resource"])].append(a)
    out = []
    for items in groups.values():
        episode = [items[0]]
        for a in items[1:]:
            gap = (datetime.strptime(a["date"], "%Y-%m-%d")
                   - datetime.strptime(episode[-1]["date"], "%Y-%m-%d")).days
            if gap <= EPISODE_GAP_DAYS:
                episode.append(a)
            else:
                out.append(_episode(episode))
                episode = [a]
        out.append(_episode(episode))
    return sorted(out, key=lambda a: a["date"], reverse=True)


def _episode(items: list[dict]) -> dict:
    if len(items) == 1:
        a = items[0]
        return {**a, "end_date": a["date"], "days": 1, "extra_cost": round(a["cost"] - a["baseline_mean"], 2)}
    first, last = items[0], items[-1]
    extra = sum(a["cost"] - a["baseline_mean"] for a in items)
    n = len(items)
    target = first["resource"] or first["platform"] or "Total spend"
    avg_extra = extra / n
    # Baseline from before the episode started; later days' baselines are
    # already pulled up by the episode itself.
    base = first["baseline_mean"]
    pct = round(avg_extra / base * 100, 1) if base > 0 else None
    msg = (f"{target} has run ${avg_extra:,.0f}/day above its usual ${base:,.0f}/day on {n} days "
           f"since {first['date']} (latest ${last['cost']:,.0f} on {last['date']}); "
           f"${extra:,.0f} extra so far.")
    drivers = last["drivers"]
    if first["scope"] == "resource" and len(drivers) <= 1:
        cause = (f"A step up in {target} itself, starting {first['date']}. Check what changed then: "
                 "new or heavier jobs, a schedule change, more data, or a warehouse setting.")
    else:
        cause = last["cause"]
    return {
        **last,
        "date": first["date"], "end_date": last["date"], "days": n,
        "severity": "high" if any(a["severity"] == "high" for a in items) else "medium",
        "cost": round(avg_extra + base, 2), "baseline_mean": round(base, 2), "pct_change": pct,
        "extra_cost": round(extra, 2),
        "signals": [s for a in items for s in a["signals"]][-10:],
        "message": msg, "cause": cause,
    }


# ── Core detection ────────────────────────────────────────────────────────────

async def detect_anomalies_for_user(user_id: str) -> list[dict]:
    """Run detection for one user. Returns the anomalies (also persisted)."""
    since = (datetime.utcnow() - timedelta(days=LOOKBACK_DAYS + RECENT_DAYS + 1)).strftime("%Y-%m-%d")
    rows = await db.unified_costs.aggregate([
        {"$match": {"user_id": user_id, "date": {"$gte": since}}},
        {"$group": {
            "_id": {"date": "$date", "platform": "$platform", "service": "$service", "resource": "$resource"},
            "cost_usd": {"$sum": "$cost_usd"},
        }},
    ]).to_list(50000)
    flat = [{**r["_id"], "cost_usd": r["cost_usd"]} for r in rows]
    anomalies = detect(flat, user_id)
    await _persist_anomalies(user_id, anomalies)
    return anomalies


# ── Persistence ───────────────────────────────────────────────────────────────

async def _persist_anomalies(user_id: str, anomalies: list[dict]):
    """Upsert one document per user+date+scope+platform+resource.

    First-seen time and acknowledgement survive re-detection ($setOnInsert),
    so a re-scan never resets "acknowledged" or makes old spikes look new.
    Documents in the old one-per-check format are removed."""
    from pymongo import UpdateOne

    await db.anomalies.delete_many({"user_id": user_id, "type": {"$ne": "spike"}})
    now = datetime.utcnow().isoformat()
    ops = []
    for a in anomalies:
        key = {k: a[k] for k in ("user_id", "date", "scope", "platform", "resource")}
        ops.append(UpdateOne(
            key,
            {"$set": a, "$setOnInsert": {"detected_at": now, "acknowledged": False}},
            upsert=True,
        ))
    if ops:
        result = await db.anomalies.bulk_write(ops)
        if result.upserted_count:
            print(f"[ANOMALY] {result.upserted_count} new anomalies for user {user_id[:8]}...")


async def detect_anomalies_all_users():
    """Run anomaly detection for all users with cost data."""
    user_ids = await db.unified_costs.distinct("user_id")
    total = 0
    for user_id in user_ids:
        try:
            total += len(await detect_anomalies_for_user(user_id))
        except Exception as e:
            print(f"[ANOMALY] Error for user {user_id[:8]}...: {e}")
    print(f"[ANOMALY] Detection complete. {total} anomalies across {len(user_ids)} users.")


# ── API helpers ───────────────────────────────────────────────────────────────

async def get_anomalies(user_id: str, days: int = 30, acknowledged: bool | None = None) -> list[dict]:
    """Get anomalies for a user, optionally filtered."""
    since = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    query: dict = {"user_id": user_id, "date": {"$gte": since}}
    if acknowledged is not None:
        query["acknowledged"] = acknowledged

    cursor = db.anomalies.find(query).sort("date", -1)
    results = await cursor.to_list(200)
    for r in results:
        r["_id"] = str(r["_id"])
    return results


async def acknowledge_anomaly(user_id: str, anomaly_id: str) -> bool:
    """Mark an anomaly as acknowledged."""
    from bson import ObjectId
    result = await db.anomalies.update_one(
        {"_id": ObjectId(anomaly_id), "user_id": user_id},
        {"$set": {"acknowledged": True, "acknowledged_at": datetime.utcnow().isoformat()}},
    )
    return result.modified_count > 0
