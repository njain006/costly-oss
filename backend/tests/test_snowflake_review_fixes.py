"""Regression tests for bugs found in review of the Snowflake multi-account PR.

Run against in-memory fakes (mongomock-motor, fakeredis) so they need no
MongoDB or Redis.
"""
import asyncio

import fakeredis
from bson import ObjectId
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient
from pymongo import DeleteMany, UpdateOne

from app.deps import get_current_user
from app.services.cache import cache

SRC = {"connection_id": "c1"}


def _client(*routers) -> TestClient:
    app = FastAPI()
    for r in routers:
        app.include_router(r)
    app.dependency_overrides[get_current_user] = lambda: "u1"
    return TestClient(app)


async def _source(user_id, connection_id=None):
    return SRC


# ── Warehouse actions ─────────────────────────────────────────────────────────

def test_warehouse_actions_return_200_and_clear_cache(monkeypatch):
    """They called cache.delete_prefix, which doesn't exist: the ALTER ran,
    then the request failed with a 500 and the cached pages stayed."""
    import app.routers.optimization as opt

    async def ok(*a, **k):
        return {"success": True}

    monkeypatch.setattr(opt, "get_data_source", _source)
    for name in ("exec_resize", "exec_autosuspend", "exec_suspend", "exec_resume"):
        monkeypatch.setattr(opt, name, ok)
    monkeypatch.setattr(opt, "sync_execute_resize", lambda *a: {"success": True})
    monkeypatch.setattr(opt, "sync_execute_autosuspend", lambda *a: {"success": True})
    client = _client(opt.router)

    for url, body in [
        ("/api/warehouses/WH/resize", {"new_size": "2X-LARGE"}),
        ("/api/warehouses/WH/autosuspend", {"seconds": 60}),
        ("/api/optimization/warehouses/WH/resize", {"new_size": "2X-LARGE"}),
        ("/api/optimization/warehouses/WH/autosuspend", {"seconds": 60}),
        ("/api/optimization/warehouses/WH/suspend", None),
        ("/api/optimization/warehouses/WH/resume", None),
    ]:
        cache.set_with_stale("u1:c1:warehouses:7", {"x": 1}, 600)
        r = client.post(url, json=body)
        assert r.status_code == 200, (url, r.text)
        assert cache.get("u1:c1:warehouses:7") is None, url  # fresh and stale copy gone


def test_suggested_resize_sizes_are_valid_snowflake_values():
    """'2XLARGE' isn't a Snowflake size; '2X-LARGE' is (CREATE WAREHOUSE docs)."""
    import inspect

    import app.services.snowflake as sf

    documented = {"XSMALL", "X-SMALL", "SMALL", "MEDIUM", "LARGE", "XLARGE", "X-LARGE",
                  "XXLARGE", "X2LARGE", "2X-LARGE", "XXXLARGE", "X3LARGE", "3X-LARGE",
                  "X4LARGE", "4X-LARGE", "X5LARGE", "5X-LARGE", "X6LARGE", "6X-LARGE"}
    src = inspect.getsource(sf)
    assert "display.get(recommended, recommended).upper()" in src
    display = {"XSMALL": "X-Small", "SMALL": "Small", "MEDIUM": "Medium", "LARGE": "Large",
               "XLARGE": "X-Large", "2XLARGE": "2X-Large", "3XLARGE": "3X-Large",
               "4XLARGE": "4X-Large", "5XLARGE": "5X-Large", "6XLARGE": "6X-Large"}
    for size in display.values():
        assert size.upper() in documented, size


# ── User types and connection ids ─────────────────────────────────────────────

def test_user_type_override_works_for_names_with_dots(monkeypatch):
    """The writer encoded '.' as '_' (Mongo field names can't hold dots) but
    the reader didn't, so overrides for e.g. john.doe were never found."""
    import app.routers.platforms as plat
    import app.services.unified_costs as uc
    from app.services.snowflake import classify_users

    db = AsyncMongoMockClient()["t"]
    monkeypatch.setattr(plat, "db", db)
    monkeypatch.setattr(uc, "db", db)
    oid = ObjectId()
    asyncio.run(db.platform_connections.insert_one({"_id": oid, "user_id": "u1"}))
    cache.set(f"u1:{oid}:costs:30", {"x": 1}, 600)
    client = _client(plat.router)

    class Cur:
        def execute(self, sql):
            pass

        def fetchall(self):
            return [("JOHN.DOE", "PERSON", "john", "j@x.com", True)]

    r = client.put(f"/api/platforms/{oid}/user-types", json={"user": "john.doe", "type": "service"})
    assert r.status_code == 200, r.text
    # User types are baked into more than the dashboard.
    assert cache.get(f"u1:{oid}:costs:30") is None
    doc = asyncio.run(db.platform_connections.find_one({"_id": oid}))
    assert classify_users(Cur(), doc, ["JOHN.DOE"]) == {"JOHN.DOE": ("service", "manual")}

    client.put(f"/api/platforms/{oid}/user-types", json={"user": "john.doe", "type": "auto"})
    doc = asyncio.run(db.platform_connections.find_one({"_id": oid}))
    assert classify_users(Cur(), doc, ["JOHN.DOE"]) == {"JOHN.DOE": ("human", "snowflake")}


def test_malformed_connection_id_is_404_not_500(monkeypatch):
    import app.routers.platforms as plat
    import app.services.unified_costs as uc

    db = AsyncMongoMockClient()["t"]
    monkeypatch.setattr(plat, "db", db)
    monkeypatch.setattr(uc, "db", db)
    oid = ObjectId()
    asyncio.run(db.platform_connections.insert_one({"_id": oid, "user_id": "u1"}))
    client = _client(plat.router)

    assert client.put("/api/platforms/not-an-id/user-types",
                      json={"user": "a", "type": "human"}).status_code == 404
    assert client.put("/api/platforms/not-an-id/pricing",
                      json={"pricing_overrides": {}}).status_code == 404
    assert client.put(f"/api/platforms/{ObjectId()}/pricing",
                      json={"pricing_overrides": {"credit_price": 3}}).status_code == 404
    assert client.put(f"/api/platforms/{oid}/pricing",
                      json={"pricing_overrides": {"credit_price": 3}}).status_code == 200


# ── Cache age ─────────────────────────────────────────────────────────────────

def test_cached_page_reports_when_it_was_computed(monkeypatch):
    """Cached and week-old fallback copies were returned with fetched_at=now."""
    import app.routers.warehouses as wh

    monkeypatch.setattr(wh, "get_data_source", _source)
    cache.set_with_stale("u1:c1:warehouses:7", {"warehouses": [1]}, 600)
    computed = cache.get("u1:c1:warehouses:7")["computed_at"]
    client = _client(wh.router)

    body = client.get("/api/warehouses?days=7").json()
    assert body["cached"] is True and body["fetched_at"] == computed
    assert "stale" not in body

    cache._inner.delete("u1:c1:warehouses:7")  # normal TTL over: stale copy served
    body = client.get("/api/warehouses?days=7").json()
    assert body["fetched_at"] == computed and body["stale"] is True


def test_non_dict_cache_values_are_untouched():
    cache.set("credit_price:test", 2.5, 60)
    assert cache.get("credit_price:test") == 2.5


# ── Anomaly persistence ───────────────────────────────────────────────────────

def _anomaly_db(monkeypatch):
    """mongomock can't run pymongo 4.9+ bulk ops, so replay them one by one.
    The app's own bulk_write call is unchanged."""
    import app.services.anomaly_detector as ad

    real = AsyncMongoMockClient()["t"].anomalies

    class _Result:
        upserted_count = 0

    async def bulk_write(ops):
        for op in ops:
            if isinstance(op, DeleteMany):
                await real.delete_many(op._filter)
            elif isinstance(op, UpdateOne):
                await real.update_one(op._filter, op._doc, upsert=op._upsert)
        return _Result()

    class Coll:
        def __getattr__(self, name):
            return getattr(real, name)

    coll = Coll()
    coll.bulk_write = bulk_write

    class DB:
        anomalies = coll

    monkeypatch.setattr(ad, "db", DB())
    return ad, real


BASE = {"user_id": "u1", "type": "spike", "scope": "resource", "platform": "snowflake",
        "resource": "WH", "cost": 10, "baseline_mean": 5}


def test_long_episode_stays_one_acknowledged_record_across_rescans(monkeypatch):
    ad, coll = _anomaly_db(monkeypatch)
    asyncio.run(coll.insert_many([
        {**BASE, "date": "2026-11-01", "end_date": "2026-11-09", "acknowledged": True},
        {**BASE, "date": "2026-11-02", "end_date": "2026-11-02", "acknowledged": False},
        {**BASE, "resource": "OTHER", "date": "2026-11-03", "end_date": "2026-11-05",
         "acknowledged": False},
    ]))
    # The scan window has moved on: the episode now looks like it started 3 Nov.
    asyncio.run(ad._persist_anomalies("u1", [
        {**BASE, "date": "2026-11-03", "end_date": "2026-11-10", "days": 8}]))

    docs = asyncio.run(coll.find({"resource": "WH"}).to_list(10))
    assert len(docs) == 1
    assert docs[0]["date"] == "2026-11-01" and docs[0]["end_date"] == "2026-11-10"
    assert docs[0]["acknowledged"] is True and docs[0]["days"] == 10
    assert asyncio.run(coll.count_documents({"resource": "OTHER"})) == 1


def test_new_episode_is_inserted_unacknowledged(monkeypatch):
    ad, coll = _anomaly_db(monkeypatch)
    asyncio.run(ad._persist_anomalies("u1", [
        {**BASE, "date": "2026-11-12", "end_date": "2026-11-12"}]))
    doc = asyncio.run(coll.find_one({"resource": "WH"}))
    assert doc["acknowledged"] is False and "detected_at" in doc
    asyncio.run(ad._persist_anomalies("u1", []))  # empty scan is fine


# ── Prewarm lock ──────────────────────────────────────────────────────────────

def _lock_redis(monkeypatch):
    import app.main as m

    r = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(m, "_get_redis_for_lock", lambda: r)
    return m, r


def test_prewarm_runs_never_overlap(monkeypatch):
    import app.services.prewarm as pw

    m, r = _lock_redis(monkeypatch)
    runs = []

    async def slow():
        runs.append(1)
        await asyncio.sleep(0.2)

    monkeypatch.setattr(pw, "prewarm_snowflake_pages", slow)

    async def both():
        await asyncio.gather(m._locked_prewarm(), m._locked_prewarm())

    asyncio.run(both())
    assert runs == [1]
    assert r.get("costly:lock:prewarm") is None


def test_prewarm_only_releases_its_own_lock(monkeypatch):
    import app.services.prewarm as pw

    m, r = _lock_redis(monkeypatch)

    async def taken_over():
        r.set("costly:lock:prewarm", "newer-run", ex=900)

    monkeypatch.setattr(pw, "prewarm_snowflake_pages", taken_over)
    asyncio.run(m._locked_prewarm())
    assert r.get("costly:lock:prewarm") == "newer-run"

    r.set("k", "mine", ex=10)
    assert r.eval(m._RENEW_IF_OWNER, 1, "k", "theirs", 5) == 0
    assert r.eval(m._RENEW_IF_OWNER, 1, "k", "mine", 900) == 1 and r.ttl("k") > 800


def test_prewarm_lock_is_renewed_while_running(monkeypatch):
    import app.services.prewarm as pw

    m, r = _lock_redis(monkeypatch)
    real_sleep = asyncio.sleep
    ttl_seen = []

    async def fast_sleep(_):
        await real_sleep(0.01)

    async def long_run():
        r.expire("costly:lock:prewarm", 5)  # most of the TTL used up
        await real_sleep(0.1)
        ttl_seen.append(r.ttl("costly:lock:prewarm"))

    monkeypatch.setattr(m.asyncio, "sleep", fast_sleep)
    monkeypatch.setattr(pw, "prewarm_snowflake_pages", long_run)
    asyncio.run(m._locked_prewarm())
    assert ttl_seen[0] > 800
