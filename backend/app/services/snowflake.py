import logging
import math
import re
import snowflake.connector
from contextlib import contextmanager
from datetime import datetime

from app.services.encryption import decrypt_value
from app.services.cache import cache
from app.utils.constants import CREDITS_MAP, CACHE_TTL
from app.utils.helpers import run_in_thread


def build_sf_connection(conn_doc: dict):
    params = {
        "account": conn_doc["account"],
        "user": conn_doc["username"],
        "warehouse": conn_doc["warehouse"],
        "database": conn_doc["database"],
        "schema": conn_doc["schema_name"],
        "login_timeout": 15,
        # ACCOUNT_USAGE scans can take minutes on large accounts.
        "network_timeout": 180,
        # ACCOUNT_USAGE timestamps are TIMESTAMP_LTZ; Snowflake bills by UTC
        # day. Pin the session to UTC so daily buckets match the invoice and
        # ORGANIZATION_USAGE no matter what the account default timezone is.
        "session_parameters": {"TIMEZONE": "UTC"},
    }
    # A blank role falls through to the user's Snowflake DEFAULT_ROLE
    # (COSTLY_SVC -> COSTLY_READER) instead of forcing ACCOUNTADMIN.
    if conn_doc.get("role"):
        params["role"] = conn_doc["role"]
    if conn_doc["auth_type"] == "password":
        params["password"] = decrypt_value(conn_doc["password_encrypted"])
    elif conn_doc["auth_type"] == "keypair":
        from cryptography.hazmat.primitives.serialization import (
            load_pem_private_key, Encoding, PrivateFormat, NoEncryption
        )
        from cryptography.hazmat.backends import default_backend
        key_str = decrypt_value(conn_doc["private_key_encrypted"])
        passphrase = None
        if conn_doc.get("private_key_passphrase_encrypted"):
            passphrase = decrypt_value(conn_doc["private_key_passphrase_encrypted"]).encode()
        pk = load_pem_private_key(key_str.encode(), password=passphrase, backend=default_backend())
        params["private_key"] = pk.private_bytes(Encoding.DER, PrivateFormat.PKCS8, NoEncryption())
    return _TolerantConnection(snowflake.connector.connect(**params))


logger = logging.getLogger(__name__)

# Snowflake "object does not exist or not authorized" — what a least-privilege
# role gets for ACCOUNT_USAGE views it was not granted (e.g. QUERY_HISTORY
# without GOVERNANCE_VIEWER).
_NOT_AUTHORIZED_ERRNO = 2003
# Statement cancelled by timeout. Tolerated like a denial for read-only
# ACCOUNT_USAGE checks, so one slow view on a big account skips that check
# instead of failing the page.
_TIMEOUT_ERRNOS = {604, 630}


class _NullRow(tuple):
    """Row stand-in for a denied query: any column reads as 0, so the
    aggregate lookups (COUNT/SUM via fetchone) fall through to "no data"."""

    def __getitem__(self, i):
        return 0


class _TolerantCursor:
    """Cursor proxy that degrades instead of failing a whole page when the
    role lacks access to one view. Denied queries yield no rows (fetchone
    yields a row of zeros) and are recorded in `missing_views`; every other
    error still raises."""

    def __init__(self, cur, missing_views: set, timed_out: set):
        self._cur = cur
        self._denied = False
        self._missing = missing_views
        self._timed_out = timed_out

    def execute(self, sql, *args, **kwargs):
        self._denied = False
        head0 = sql.lstrip().split(None, 1)[0].upper() if sql.strip() else ""
        self._last_tolerable = head0 in ("SELECT", "WITH") and "ACCOUNT_USAGE." in sql.upper()
        self._last_view = next((tok for tok in sql.split() if "ACCOUNT_USAGE." in tok.upper()),
                               "unknown view").strip(",;()")
        try:
            return self._cur.execute(sql, *args, **kwargs)
        except snowflake.connector.errors.ProgrammingError as e:
            # Only tolerate read-only metadata queries. Snowflake returns the
            # same errno for writes (e.g. ALTER WAREHOUSE) — those must raise.
            head = sql.lstrip().split(None, 1)[0].upper() if sql.strip() else ""
            errno = getattr(e, "errno", None)
            if (errno not in ({_NOT_AUTHORIZED_ERRNO} | _TIMEOUT_ERRNOS)
                    or head not in ("SELECT", "WITH")
                    or "ACCOUNT_USAGE." not in sql.upper()):
                raise
            if errno in _TIMEOUT_ERRNOS:
                view = next((tok for tok in sql.split() if "ACCOUNT_USAGE." in tok.upper()),
                            "unknown view").strip(",;()")
                self._timed_out.add(view)
                logger.warning("Snowflake query on %s timed out; skipping", view)
                self._denied = True
                return self
            # Snowflake names the denied object in the message; fall back to
            # the first ACCOUNT_USAGE view in the SQL.
            m = re.search(r"Object '([^']+)'", str(e))
            view = m.group(1) if m else next(
                (tok for tok in sql.split() if "ACCOUNT_USAGE." in tok.upper()), "unknown view"
            ).strip(",;()")
            self._missing.add(view)
            logger.warning("Snowflake role cannot read %s; returning no rows", view)
            self._denied = True
            return self

    def _fetch_timed_out(self, e) -> bool:
        # Large results can time out while fetching, not only on execute.
        if getattr(e, "errno", None) in _TIMEOUT_ERRNOS and getattr(self, "_last_tolerable", False):
            self._timed_out.add(self._last_view)
            logger.warning("Snowflake fetch on %s timed out; skipping", self._last_view)
            return True
        return False

    def fetchall(self):
        if self._denied:
            return []
        try:
            return self._cur.fetchall()
        except snowflake.connector.errors.ProgrammingError as e:
            if not self._fetch_timed_out(e):
                raise
            return []

    def fetchone(self):
        if self._denied:
            return _NullRow()
        try:
            return self._cur.fetchone()
        except snowflake.connector.errors.ProgrammingError as e:
            if not self._fetch_timed_out(e):
                raise
            return _NullRow()

    @property
    def description(self):
        return [] if self._denied else self._cur.description

    def __iter__(self):
        return iter(self.fetchall())

    def __getattr__(self, name):
        return getattr(self._cur, name)


class _TolerantConnection:
    def __init__(self, conn):
        self._conn = conn
        self.missing_views: set = set()
        self.timed_out_views: set = set()

    def cursor(self, *args, **kwargs):
        return _TolerantCursor(self._conn.cursor(*args, **kwargs), self.missing_views, self.timed_out_views)

    def __getattr__(self, name):
        return getattr(self._conn, name)


@contextmanager
def sf_connection(conn_doc: dict):
    """Context manager that ensures Snowflake connections are always closed.

    Views the role is not authorized for return empty results instead of
    failing the request, so a least-privilege role still gets every page
    that its grants can support."""
    conn = build_sf_connection(conn_doc)
    try:
        yield conn
    finally:
        conn.close()


def conn_to_response(doc: dict) -> dict:
    return {
        "connection_id": doc["connection_id"],
        "connection_name": doc["connection_name"],
        "account": doc["account"],
        "username": doc["username"],
        "auth_type": doc["auth_type"],
        "warehouse": doc["warehouse"],
        "database": doc["database"],
        "schema_name": doc["schema_name"],
        "role": doc["role"],
        "is_active": doc["is_active"],
        "test_status": doc.get("test_status"),
        "last_tested_at": doc.get("last_tested_at"),
        "created_at": doc["created_at"],
    }


AI_SERVICE_TYPES = ("AI_", "CORTEX", "SNOWFLAKE_COCO", "DOCUMENT_AI", "COPILOT")


def _override(conn_doc: dict, *keys):
    ov = conn_doc.get("pricing_overrides") or {}
    for k in keys:
        try:
            v = float(ov.get(k))
            if v > 0:
                return v
        except (TypeError, ValueError):
            continue
    return None


def _sync_get_credit_price(conn_doc: dict) -> float:
    """Compute $/credit. Order: explicit override, the account's contract rate
    from RATE_SHEET_DAILY (needs org billing access), then $3 list price."""
    price = _override(conn_doc, "credit_price_usd", "credit_price")
    if price:
        return price
    try:
        with sf_connection(conn_doc) as sf:
            cur = sf.cursor()
            cur.execute("""
                SELECT EFFECTIVE_RATE
                FROM SNOWFLAKE.ORGANIZATION_USAGE.RATE_SHEET_DAILY
                WHERE ACCOUNT_LOCATOR = CURRENT_ACCOUNT()
                  AND SERVICE_TYPE = 'WAREHOUSE_METERING'
                  AND USAGE_TYPE = 'compute'
                ORDER BY DATE DESC LIMIT 1
            """)
            row = cur.fetchone()
            return float(row[0]) if row and row[0] else 3.0
    except Exception:
        return 3.0


def service_credit_price(conn_doc: dict, service_type: str, credit_price: float) -> float:
    """$/credit for a METERING_DAILY_HISTORY service type. AI services
    (Cortex, AI functions, Copilot) are billed as AI credits, usually at a
    different rate than compute."""
    st = (service_type or "").upper()
    per = (conn_doc.get("pricing_overrides") or {}).get("service_type_prices") or {}
    if st in {k.upper() for k in per}:
        return float({k.upper(): v for k, v in per.items()}[st])
    if st.startswith(AI_SERVICE_TYPES):
        return _override(conn_doc, "ai_credit_price_usd", "ai_credit_price") or credit_price
    return credit_price


async def get_credit_price(conn_doc: dict) -> float:
    key = f"credit_price:{conn_doc['connection_id']}"
    cached = cache.get(key)
    if cached is not None:
        return cached
    price = await run_in_thread(_sync_get_credit_price, conn_doc)
    cache.set(key, price, CACHE_TTL["credit_price"])
    return price


def _daily_billed(cur, conn_doc: dict, days: int, credit_price: float) -> list[dict]:
    """Daily bill from METERING_DAILY_HISTORY: every service type (warehouses,
    cloud services net of the 10% allowance, serverless, AI), by UTC day,
    priced per service type. This is what the Snowflake invoice is built from;
    WAREHOUSE_METERING_HISTORY alone misses serverless/AI and overstates
    cloud services."""
    cur.execute(f"""
        SELECT USAGE_DATE, SERVICE_TYPE,
               SUM(CREDITS_USED_COMPUTE), SUM(CREDITS_USED_CLOUD_SERVICES),
               SUM(CREDITS_ADJUSTMENT_CLOUD_SERVICES), SUM(CREDITS_BILLED)
        FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_DAILY_HISTORY
        WHERE USAGE_DATE >= DATEADD('day', -{int(days)}, CURRENT_DATE())
        GROUP BY 1, 2 ORDER BY 1
    """)
    by_day: dict[str, dict] = {}
    for d, st, comp, cs, adj, billed in cur.fetchall():
        day = by_day.setdefault(str(d), {
            "date": str(d), "compute_cost": 0.0, "cloud_services_cost": 0.0,
            "serverless_cost": 0.0, "ai_cost": 0.0, "cost": 0.0, "credits": 0.0,
        })
        price = service_credit_price(conn_doc, st, credit_price)
        comp, cs, adj, billed = (float(x or 0) for x in (comp, cs, adj, billed))
        if st == "WAREHOUSE_METERING":
            day["compute_cost"] += comp * price
        elif str(st).upper().startswith(AI_SERVICE_TYPES):
            day["ai_cost"] += comp * price
        else:
            day["serverless_cost"] += comp * price
        day["cloud_services_cost"] += (cs + adj) * price
        day["cost"] += billed * price
        day["credits"] += billed
    out = []
    for day in by_day.values():
        out.append({k: (round(v, 2) if isinstance(v, float) else v) for k, v in day.items()})
    return out


def sync_dashboard(conn_doc: dict, days: int, credit_price: float) -> dict:
    with sf_connection(conn_doc) as sf:
        cur = sf.cursor()
        cost_trend = _daily_billed(cur, conn_doc, days, credit_price)
        cur.execute(f"""
            SELECT WAREHOUSE_NAME,
                   SUM(CREDITS_USED_COMPUTE) AS credits,
                   SUM(CREDITS_USED_COMPUTE * {credit_price}) AS cost,
                   SUM(CREDITS_ATTRIBUTED_COMPUTE_QUERIES) AS query_credits
            FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
            WHERE START_TIME >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
              AND WAREHOUSE_ID > 0  -- skip CLOUD_SERVICES_ONLY pseudo-warehouse
            GROUP BY 1 HAVING SUM(CREDITS_USED_COMPUTE) > 0 ORDER BY 2 DESC
        """)
        all_wh = [
            {"name": r[0], "credits": round(float(r[1] or 0), 2), "cost": round(float(r[2] or 0), 2),
             "idle_pct": round(100 * (1 - float(r[3] or 0) / float(r[1])), 1) if r[1] else 0.0}
            for r in cur.fetchall()
        ]
        top_warehouses = all_wh[:10]
        # Query-level metrics need GOVERNANCE_VIEWER on ACCOUNT_USAGE.QUERY_HISTORY.
        # If that grant is missing, degrade gracefully (show 0) instead of letting
        # one denied query blank the entire dashboard.
        total_queries = expensive_queries = failed_queries = 0
        try:
            cur.execute(f"""
                SELECT
                    COUNT(*) AS total_queries,
                    COUNT_IF(TOTAL_ELAPSED_TIME > 60000) AS expensive_queries,
                    COUNT_IF(EXECUTION_STATUS != 'SUCCESS') AS failed_queries
                FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                WHERE START_TIME >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
                  AND IS_CLIENT_GENERATED_STATEMENT = FALSE
            """)
            row = cur.fetchone()
            total_queries = int(row[0] or 0)
            expensive_queries = int(row[1] or 0)
            failed_queries = int(row[2] or 0)
        except Exception:
            logging.getLogger(__name__).warning(
                "QUERY_HISTORY unavailable for dashboard (needs GOVERNANCE_VIEWER)",
                exc_info=True,
            )

        # Per-user compute from QUERY_ATTRIBUTION_HISTORY (USAGE_VIEWER is
        # enough; no query text). Excludes warehouse idle time.
        cur.execute(f"""
            SELECT USER_NAME,
                   SUM(CREDITS_ATTRIBUTED_COMPUTE + COALESCE(CREDITS_USED_QUERY_ACCELERATION, 0)) AS credits,
                   COUNT(*) AS queries
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_ATTRIBUTION_HISTORY
            WHERE START_TIME >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
            GROUP BY 1 ORDER BY 2 DESC
        """)
        all_users = [
            {"user": r[0], "cost": round(float(r[1] or 0) * credit_price, 2), "queries": int(r[2] or 0)}
            for r in cur.fetchall()
        ]
        types = classify_users(cur, conn_doc, [u["user"] for u in all_users])
        for u in all_users:
            u["type"], u["type_source"] = types.get(u["user"], ("human", "guess"))
        cost_by_user_type = {"service": 0.0, "human": 0.0}
        for u in all_users:
            cost_by_user_type[u["type"]] = round(cost_by_user_type[u["type"]] + u["cost"], 2)
        top_users = all_users[:10]

        # Storage is billed on the daily average of bytes (table + stage +
        # fail-safe), per TB-month.
        storage_price_tb = _override(conn_doc, "storage_price_per_tb", "storage_price") or 23.0
        cur.execute(f"""
            SELECT MAX_BY(STORAGE_BYTES + STAGE_BYTES + FAILSAFE_BYTES, USAGE_DATE),
                   SUM(STORAGE_BYTES + STAGE_BYTES + FAILSAFE_BYTES)
            FROM SNOWFLAKE.ACCOUNT_USAGE.STORAGE_USAGE
            WHERE USAGE_DATE >= DATEADD('day', -{int(days)}, CURRENT_DATE())
        """)
        row = cur.fetchone()
        storage_gb = round(float(row[0] or 0) / 1024**3, 1) if row else 0.0
        # sum of daily bytes / days-per-month = TB-months
        storage_cost = round(float(row[1] or 0) / 1024**4 / 30.4 * storage_price_tb, 2) if row else 0.0

        qh_unavailable = view_unavailable(sf, "QUERY_HISTORY")
        queries_source = "query_history"
        if total_queries == 0:
            queries_source = "query_attribution"
            # QUERY_HISTORY denied: count from QUERY_ATTRIBUTION_HISTORY
            # (warehouse queries over ~100ms only).
            cur.execute(f"""
                SELECT COUNT(*) FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_ATTRIBUTION_HISTORY
                WHERE START_TIME >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
            """)
            total_queries = int((cur.fetchone() or [0])[0] or 0)

    raw_costs = [d["cost"] for d in cost_trend]
    anomalies = []
    for i in range(len(cost_trend)):
        window = raw_costs[max(0, i - 14):i] if i > 0 else raw_costs[:1]
        rolling_avg = sum(window) / len(window) if window else raw_costs[i]
        ratio = raw_costs[i] / rolling_avg if rolling_avg > 0 else 1.0
        cost_trend[i]["rolling_avg"] = round(rolling_avg, 2)
        if ratio >= 1.8 and i > 3:
            anomalies.append({
                "date": cost_trend[i]["date"],
                "cost": cost_trend[i]["cost"],
                "avg": round(rolling_avg, 2),
                "ratio": round(ratio, 2),
                "label": f"Cost spike: {cost_trend[i]['cost']:.0f} vs avg {rolling_avg:.0f}",
            })

    return {
        "total_cost": round(sum(d["cost"] for d in cost_trend) + storage_cost, 2),
        "compute_bill": round(sum(d["cost"] for d in cost_trend), 2),
        "storage_cost": storage_cost,
        "total_credits": round(sum(d["credits"] for d in cost_trend), 2),
        "active_warehouses": len(all_wh),
        "query_history_available": not qh_unavailable,
        # query_attribution counts only warehouse queries over ~100ms
        "queries_source": queries_source,
        "expensive_queries": expensive_queries,
        "query_count": total_queries,
        "failed_queries": failed_queries,
        "storage_gb": storage_gb,
        "cost_trend": cost_trend,
        "top_warehouses": top_warehouses,
        "top_users": top_users,
        "cost_by_user_type": cost_by_user_type,
        "connection_id": conn_doc.get("connection_id"),
        "credit_price": credit_price,
        "days": days,
        "anomalies": anomalies,
    }


def sync_costs(conn_doc: dict, days: int, credit_price: float) -> dict:
    with sf_connection(conn_doc) as sf:
        cur = sf.cursor()
        cur.execute(f"""
            SELECT DATE_TRUNC('day', START_TIME)::DATE AS day,
                   WAREHOUSE_NAME,
                   SUM(CREDITS_USED_COMPUTE * {credit_price}) AS cost,
                   SUM(CREDITS_USED_COMPUTE) AS credits
            FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
            WHERE START_TIME >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
              AND WAREHOUSE_ID > 0
            GROUP BY 1, 2 ORDER BY 1
        """)
        daily = [
            {"date": str(r[0]), "warehouse": r[1], "cost": round(float(r[2] or 0), 2), "credits": round(float(r[3] or 0), 2)}
            for r in cur.fetchall()
        ]
        # Warehouse compute attributed to each user's queries
        # (QUERY_ATTRIBUTION_HISTORY, USAGE_VIEWER). Excludes idle time.
        cur.execute(f"""
            SELECT USER_NAME,
                   SUM(CREDITS_ATTRIBUTED_COMPUTE + COALESCE(CREDITS_USED_QUERY_ACCELERATION, 0)) * {credit_price} AS cost,
                   COUNT(*) AS queries
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_ATTRIBUTION_HISTORY
            WHERE START_TIME >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
            GROUP BY 1 ORDER BY 2 DESC LIMIT 20
        """)
        by_user = [{"user": r[0], "cost": round(float(r[1] or 0), 2), "queries": r[2]} for r in cur.fetchall()]
        types = classify_users(cur, conn_doc, [u["user"] for u in by_user])
        for u in by_user:
            u["type"], u["type_source"] = types.get(u["user"], ("human", "guess"))
    return {"daily": daily, "by_user": by_user, "days": days}


def sync_queries(conn_doc: dict, days: int, page: int, limit: int) -> dict:
    with sf_connection(conn_doc) as sf:
        cur = sf.cursor()
        offset = (page - 1) * limit
        cur.execute(f"""
            SELECT COUNT(*) FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
            WHERE START_TIME >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
            AND EXECUTION_STATUS = 'SUCCESS'
        """)
        total = cur.fetchone()[0]
        cur.execute(f"""
            SELECT QUERY_ID, START_TIME, USER_NAME, WAREHOUSE_NAME,
                   TOTAL_ELAPSED_TIME, BYTES_SCANNED, ROWS_PRODUCED,
                   QUERY_TEXT, CREDITS_USED_CLOUD_SERVICES,
                   COMPILATION_TIME, EXECUTION_TIME,
                   QUEUED_PROVISIONING_TIME, QUEUED_OVERLOAD_TIME, QUEUED_REPAIR_TIME,
                   TRANSACTION_BLOCKED_TIME,
                   BYTES_SPILLED_TO_LOCAL_STORAGE, BYTES_SPILLED_TO_REMOTE_STORAGE,
                   PARTITIONS_SCANNED, PARTITIONS_TOTAL,
                   PERCENTAGE_SCANNED_FROM_CACHE,
                   QUERY_TYPE, ROLE_NAME
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
            WHERE START_TIME >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
            AND EXECUTION_STATUS = 'SUCCESS'
            AND IS_CLIENT_GENERATED_STATEMENT = FALSE
            ORDER BY TOTAL_ELAPSED_TIME DESC
            LIMIT {limit} OFFSET {offset}
        """)
        data = [
            {
                "query_id": r[0],
                "start_time": str(r[1]),
                "user": r[2],
                "warehouse": r[3],
                "duration_ms": int(r[4] or 0),
                "bytes_scanned": int(r[5] or 0),
                "rows_produced": int(r[6] or 0),
                "query_text": (r[7] or "")[:200],
                "credits": round(float(r[8] or 0), 6),
                "compilation_ms": int(r[9] or 0),
                "execution_ms": int(r[10] or 0),
                "queue_provision_ms": int(r[11] or 0),
                "queue_overload_ms": int(r[12] or 0),
                "queue_repair_ms": int(r[13] or 0),
                "blocked_ms": int(r[14] or 0),
                "spill_local_gb": round(float(r[15] or 0) / 1073741824, 2),
                "spill_remote_gb": round(float(r[16] or 0) / 1073741824, 2),
                "partitions_scanned": int(r[17] or 0),
                "partitions_total": int(r[18] or 0),
                "cache_hit_pct": round(float(r[19] or 0), 1),
                "query_type": r[20] or "SELECT",
                "role": r[21] or "",
            }
            for r in cur.fetchall()
        ]
    qh_unavailable = view_unavailable(sf, "QUERY_HISTORY")
    return {
        "data": data,
        "total": total,
        "page": page,
        "pages": max(1, math.ceil(total / limit)),
        "limit": limit,
        "days": days,
        "query_history_available": not qh_unavailable,
    }


def sync_storage(conn_doc: dict, days: int) -> dict:
    with sf_connection(conn_doc) as sf:
        cur = sf.cursor()
        cur.execute("""
            SELECT TABLE_CATALOG, TABLE_SCHEMA, TABLE_NAME,
               ACTIVE_BYTES / 1073741824.0             AS active_gb,
               TIME_TRAVEL_BYTES / 1073741824.0        AS time_travel_gb,
               FAILSAFE_BYTES / 1073741824.0           AS failsafe_gb,
               RETAINED_FOR_CLONE_BYTES / 1073741824.0 AS clone_gb,
               TABLE_CREATED, ID
        FROM SNOWFLAKE.ACCOUNT_USAGE.TABLE_STORAGE_METRICS
        WHERE DELETED = FALSE
        ORDER BY (ACTIVE_BYTES + TIME_TRAVEL_BYTES + FAILSAFE_BYTES) DESC NULLS LAST
        LIMIT 100
    """)
        rows = cur.fetchall()
        # LAST_ALTERED lives in ACCOUNT_USAGE.TABLES (OBJECT_VIEWER). Without
        # it we cannot tell stale tables apart, so we say "unknown" instead
        # of guessing from the creation date.
        last_altered: dict = {}
        ids = [int(r[8]) for r in rows if r[8] is not None]
        if ids:
            cur.execute(f"""
                SELECT TABLE_ID, LAST_ALTERED FROM SNOWFLAKE.ACCOUNT_USAGE.TABLES
                WHERE TABLE_ID IN ({",".join(str(i) for i in ids)}) AND DELETED IS NULL
            """)
            last_altered = {int(r[0]): r[1] for r in cur.fetchall()}
        now = datetime.utcnow()
        tables = []
        for r in rows:
            active_gb = round(float(r[3] or 0), 2)
            tt_gb = round(float(r[4] or 0), 2)
            fs_gb = round(float(r[5] or 0), 2)
            clone_gb = round(float(r[6] or 0), 2)
            created = str(r[7])[:10] if r[7] else None
            la = last_altered.get(int(r[8])) if r[8] is not None else None
            stale = None
            if la is not None:
                stale = (now - la.replace(tzinfo=None)).days > 90
            tables.append({
                "database": r[0], "schema": r[1], "table": r[2],
                "size_gb": round(active_gb + tt_gb + fs_gb + clone_gb, 2),
                "active_gb": active_gb,
                "time_travel_gb": tt_gb,
                "failsafe_gb": fs_gb,
                "clone_gb": clone_gb,
                "created": created,
                "last_altered": str(la)[:10] if la is not None else None,
                "stale": bool(stale),
                "stale_known": stale is not None,
            })
        cur.execute(f"""
            SELECT USAGE_DATE,
                   STORAGE_BYTES  / 1073741824.0 AS table_gb,
                   STAGE_BYTES    / 1073741824.0 AS stage_gb,
                   FAILSAFE_BYTES / 1073741824.0 AS failsafe_gb,
                   (STORAGE_BYTES + STAGE_BYTES + FAILSAFE_BYTES) / 1073741824.0 AS total_gb
            FROM SNOWFLAKE.ACCOUNT_USAGE.STORAGE_USAGE
            WHERE USAGE_DATE >= DATEADD('day', -{days}, CURRENT_DATE())
            ORDER BY USAGE_DATE
        """)
        trend = [
            {
                "date": str(r[0]),
                "table_gb": round(float(r[1] or 0), 1),
                "stage_gb": round(float(r[2] or 0), 1),
                "failsafe_gb": round(float(r[3] or 0), 1),
                "total_gb": round(float(r[4] or 0), 1),
            }
            for r in cur.fetchall()
        ]
        cur.execute(f"""
            SELECT DATABASE_NAME,
                   ROUND(AVG(AVERAGE_DATABASE_BYTES)              / 1073741824.0, 2) AS avg_db_gb,
                   ROUND(AVG(AVERAGE_FAILSAFE_BYTES)              / 1073741824.0, 2) AS avg_failsafe_gb,
                   ROUND(AVG(AVERAGE_HYBRID_TABLE_STORAGE_BYTES)  / 1073741824.0, 2) AS avg_hybrid_gb,
                   ROUND(MAX(AVERAGE_DATABASE_BYTES)              / 1073741824.0, 2) AS max_db_gb
            FROM SNOWFLAKE.ACCOUNT_USAGE.DATABASE_STORAGE_USAGE_HISTORY
            WHERE USAGE_DATE >= DATEADD('day', -{days}, CURRENT_DATE())
            GROUP BY 1
            HAVING AVG(AVERAGE_DATABASE_BYTES + AVERAGE_FAILSAFE_BYTES) > 0
            ORDER BY AVG(AVERAGE_DATABASE_BYTES + AVERAGE_FAILSAFE_BYTES) DESC
            LIMIT 20
        """)
        by_database = [
            {
                "database": r[0],
                "avg_db_gb": float(r[1] or 0),
                "avg_failsafe_gb": float(r[2] or 0),
                "avg_hybrid_gb": float(r[3] or 0),
                "max_db_gb": float(r[4] or 0),
                "total_gb": round(float(r[1] or 0) + float(r[2] or 0) + float(r[3] or 0), 2),
            }
            for r in cur.fetchall()
        ]
        # Account total = every table, stage and fail-safe byte (latest day),
        # not just the 100 largest tables listed above.
        total_gb = trend[-1]["total_gb"] if trend else round(sum(t["size_gb"] for t in tables), 2)
        price_tb = _override(conn_doc, "storage_price_per_tb", "storage_price") or 23.0
    return {
        "tables": tables,
        "total_gb": total_gb,
        "listed_tables_gb": round(sum(t["size_gb"] for t in tables), 2),
        "storage_price_per_tb": price_tb,
        "storage_cost_monthly": round(total_gb / 1024 * price_tb, 2),
        "trend": trend,
        "by_database": by_database,
        "days": days,
    }


def sync_warehouses(conn_doc: dict, days: int) -> dict:
    sf = build_sf_connection(conn_doc)
    cur = sf.cursor()
    warehouses = []
    seen = set()
    cur.execute("SHOW WAREHOUSES")
    cols = [d[0].lower() for d in cur.description]
    for row in cur.fetchall():
        rd = dict(zip(cols, row))
        size = rd.get("size", "")
        seen.add(rd.get("name", ""))
        warehouses.append({
            "name": rd.get("name", ""),
            "size": size,
            "state": rd.get("state", ""),
            "auto_suspend": int(rd.get("auto_suspend", 0) or 0),
            "min_cluster": int(rd.get("min_cluster_count", 1) or 1),
            "max_cluster": int(rd.get("max_cluster_count", 1) or 1),
            "credits_per_hour": CREDITS_MAP.get(size, CREDITS_MAP.get(size.title(), 1)),
            "config_visible": True,
        })
    # SHOW WAREHOUSES hides warehouses the role has no privilege on. List
    # the rest from metering, with size from the last resize event.
    display = {"XSMALL": "X-Small", "SMALL": "Small", "MEDIUM": "Medium", "LARGE": "Large",
               "XLARGE": "X-Large", "2XLARGE": "2X-Large", "3XLARGE": "3X-Large", "4XLARGE": "4X-Large"}
    configs = _warehouse_configs(cur)
    cur.execute(f"""
        SELECT DISTINCT WAREHOUSE_NAME FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
        WHERE START_TIME >= DATEADD('day', -{days}, CURRENT_TIMESTAMP()) AND WAREHOUSE_ID > 0
    """)
    for (name,) in cur.fetchall():
        if name in seen:
            continue
        size = display.get((configs.get(name) or {}).get("size") or "", "")
        warehouses.append({
            "name": name, "size": size or "unknown", "state": "unknown",
            "auto_suspend": 0, "min_cluster": 1, "max_cluster": 1,
            "credits_per_hour": CREDITS_MAP.get(size, 1) if size else 0,
            "config_visible": False,
        })
    cur.execute(f"""
        SELECT DATE_TRUNC('day', START_TIME)::DATE AS day,
               WAREHOUSE_NAME,
               SUM(CREDITS_USED_COMPUTE) AS credits
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
        WHERE START_TIME >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
        GROUP BY 1, 2 ORDER BY 1
    """)
    activity = [
        {"date": str(r[0]), "warehouse": r[1], "credits": round(float(r[2] or 0), 2)}
        for r in cur.fetchall()
    ]
    cur.execute(f"""
        SELECT DATE_TRUNC('day', START_TIME)::DATE AS day,
               WAREHOUSE_NAME,
               ROUND(AVG(AVG_RUNNING), 2)            AS avg_running,
               ROUND(AVG(AVG_QUEUED_LOAD), 3)        AS avg_queued,
               ROUND(AVG(AVG_QUEUED_PROVISIONING), 3) AS avg_provisioning
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_LOAD_HISTORY
        WHERE START_TIME >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
        GROUP BY 1, 2 ORDER BY 1
    """)
    load_history = [
        {"date": str(r[0]), "warehouse": r[1], "avg_running": float(r[2] or 0),
         "avg_queued": float(r[3] or 0), "avg_provisioning": float(r[4] or 0)}
        for r in cur.fetchall()
    ]
    cur.execute(f"""
        SELECT WAREHOUSE_NAME,
               COUNT(*)                                                            AS query_count,
               COUNT_IF(EXECUTION_STATUS != 'SUCCESS')                            AS failed_count,
               ROUND(AVG(PERCENTAGE_SCANNED_FROM_CACHE), 1)                       AS avg_cache_hit_pct,
               ROUND(AVG(BYTES_SPILLED_TO_LOCAL_STORAGE)  / 1073741824.0, 4)      AS avg_spill_local_gb,
               ROUND(AVG(BYTES_SPILLED_TO_REMOTE_STORAGE) / 1073741824.0, 4)      AS avg_spill_remote_gb,
               ROUND(AVG(TOTAL_ELAPSED_TIME) / 1000.0, 1)                         AS avg_duration_s
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE START_TIME >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          AND WAREHOUSE_NAME IS NOT NULL
          AND IS_CLIENT_GENERATED_STATEMENT = FALSE
        GROUP BY 1
        ORDER BY 2 DESC
    """)
    wh_stats = [
        {
            "name": r[0],
            "query_count": int(r[1] or 0),
            "failed_count": int(r[2] or 0),
            "avg_cache_hit_pct": round(float(r[3] or 0), 1),
            "avg_spill_local_gb": round(float(r[4] or 0), 4),
            "avg_spill_remote_gb": round(float(r[5] or 0), 4),
            "avg_duration_s": round(float(r[6] or 0), 1),
        }
        for r in cur.fetchall()
    ]
    sf.close()
    return {"warehouses": warehouses, "activity": activity, "load_history": load_history, "wh_stats": wh_stats, "days": days}


def sync_workloads(conn_doc: dict, days: int) -> dict:
    sf = build_sf_connection(conn_doc)
    cur = sf.cursor()
    cur.execute(f"""
        SELECT
            COALESCE(QUERY_PARAMETERIZED_HASH, MD5(QUERY_TEXT)) AS workload_id,
            ANY_VALUE(QUERY_TEXT) AS sample_query,
            COUNT(*) AS execution_count,
            ROUND(SUM(TOTAL_ELAPSED_TIME) / 1000.0, 1) AS total_seconds,
            ROUND(AVG(TOTAL_ELAPSED_TIME) / 1000.0, 1) AS avg_seconds,
            ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY TOTAL_ELAPSED_TIME) / 1000.0, 1) AS p95_seconds,
            SUM(CREDITS_USED_CLOUD_SERVICES) AS total_credits,
            SUM(BYTES_SCANNED) / 1073741824.0 AS total_gb_scanned,
            MIN(START_TIME) AS first_seen,
            MAX(START_TIME) AS last_seen,
            ANY_VALUE(USER_NAME) AS sample_user,
            ANY_VALUE(WAREHOUSE_NAME) AS sample_warehouse
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE START_TIME >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          AND EXECUTION_STATUS = 'SUCCESS'
          AND IS_CLIENT_GENERATED_STATEMENT = FALSE
        GROUP BY 1
        HAVING COUNT(*) >= 2
        ORDER BY SUM(TOTAL_ELAPSED_TIME) DESC
        LIMIT 100
    """)
    workloads = []
    for r in cur.fetchall():
        workloads.append({
            "workload_id": str(r[0] or "")[:16],
            "sample_query": (str(r[1] or ""))[:200],
            "execution_count": int(r[2] or 0),
            "total_seconds": round(float(r[3] or 0), 1),
            "avg_seconds": round(float(r[4] or 0), 1),
            "p95_seconds": round(float(r[5] or 0), 1),
            "total_credits": round(float(r[6] or 0), 6),
            "total_gb_scanned": round(float(r[7] or 0), 2),
            "first_seen": str(r[8]),
            "last_seen": str(r[9]),
            "sample_user": str(r[10] or ""),
            "sample_warehouse": str(r[11] or ""),
        })
    qh_unavailable = view_unavailable(sf, "QUERY_HISTORY")
    sf.close()
    return {
        "query_history_available": not qh_unavailable,
        "workloads": workloads,
        "total_workloads": len(workloads),
        "total_executions": sum(w["execution_count"] for w in workloads),
        "days": days,
    }


def sync_recommendations(conn_doc: dict, credit_price: float) -> list:
    sf = build_sf_connection(conn_doc)
    cur = sf.cursor()
    recs = []
    size_credits_per_hour = {
        "X-SMALL": 1, "XSMALL": 1, "SMALL": 2, "MEDIUM": 4,
        "LARGE": 8, "X-LARGE": 16, "XLARGE": 16,
        "2X-LARGE": 32, "3X-LARGE": 64, "4X-LARGE": 128,
    }

    # 1. Idle warehouse spend (metered minus query-attributed credits).
    #    Works with USAGE_VIEWER alone and uses real numbers instead of an
    #    assumed resume count.
    try:
        idle = sync_autosuspend_analysis(conn_doc, 30, credit_price)
    except Exception:
        logger.warning("idle analysis failed for recommendations", exc_info=True)
        idle = {"recommendations": []}
    for r in sorted(idle["recommendations"], key=lambda x: -x["idle_cost_monthly"]):
        if r["idle_cost_monthly"] < 50 or r["idle_pct"] < 30:
            continue
        name = r["warehouse"]
        est = r.get("savings_is_estimate")
        sql = r.get("ddl_command") or r.get("suggested_sql")
        savings = round(r["monthly_savings"]) if r["monthly_savings"] else None
        desc = (
            f"{name} was running with no queries {r['idle_pct']:.0f}% of the time it was on "
            f"(~${r['idle_cost_monthly']:,.0f}/month, {r['resume_count']:,} cluster starts in 30 days). "
        )
        if r.get("note"):
            desc += r["note"] + " "
        if est and sql:
            desc += f"Suggested, once you confirm the current setting: {sql} "
        if r.get("ddl_command"):
            desc += "Run the SQL below in Snowsight as the warehouse owner. It takes effect immediately and can be reverted the same way."
        elif not sql:
            desc += ("It already suspends within about a minute, so the idle comes from Snowflake "
                     "billing at least 60 seconds per start, times thousands of starts. Running the "
                     "callers less often or in batches will cut it.")
        recs.append({
            "id": f"rec_idle_{name}",
            "title": f"{name} is idle {r['idle_pct']:.0f}% of its runtime (~${r['idle_cost_monthly']:,.0f}/mo)",
            "description": desc,
            "category": "warehouse",
            "potential_savings": savings,
            "effort": "low",
            "priority": "high" if r["idle_cost_monthly"] >= 300 else "medium",
            # SQL only when the current setting is known, so every line in
            # the action plan has a real revert. Estimates show it as text.
            "ddl_command": None if est else (r.get("ddl_command") or r.get("suggested_sql")),
            "current_value": r.get("current_suspend_s"),
        })

    # 1b. AI (Cortex) spend spikes, by query tag. CORTEX_AISQL_USAGE_HISTORY
    #     is covered by USAGE_VIEWER.
    ai_price = service_credit_price(conn_doc, "AI_FUNCTIONS", credit_price)
    # The view (and its columns) vary by account age and region; treat any
    # failure as "no AI check" rather than failing every recommendation.
    try:
        cur.execute("""
            SELECT COALESCE(NULLIF(QUERY_TAG, ''), '(no tag)'), MODEL_NAME,
                   SUM(TOKEN_CREDITS), COUNT(DISTINCT QUERY_ID), MAX(USAGE_TIME)
            FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AISQL_USAGE_HISTORY
            WHERE USAGE_TIME >= DATEADD('day', -7, CURRENT_TIMESTAMP())
            GROUP BY 1, 2 HAVING SUM(TOKEN_CREDITS) > 5
            ORDER BY 3 DESC LIMIT 5
        """)
        ai_rows = cur.fetchall()
    except Exception:
        logger.warning("Cortex AI usage check skipped", exc_info=True)
        ai_rows = []
    if ai_rows:
        total = sum(float(r[2] or 0) for r in ai_rows) * ai_price
        lines = "; ".join(
            f"{r[0]} on {r[1] or 'embedding'}: ${float(r[2]) * ai_price:,.0f} ({r[3]} queries)" for r in ai_rows
        )
        recs.append({
            "id": "rec_ai_spend",
            "title": f"Cortex AI spend in the last 7 days: ${total:,.0f}",
            "description": (
                f"Largest AI function workloads by query tag and model: {lines}. "
                "AI functions bill per token and can spike in a single run. Check these were "
                "intended, and consider a smaller model or a sample for tests."
            ),
            "category": "ai",
            "potential_savings": None,
            "effort": "low",
            "priority": "high" if total >= 200 else "medium",
        })

    # 2. Repeated queries
    cur.execute("""
        SELECT
            ANY_VALUE(WAREHOUSE_NAME) AS warehouse,
            COUNT(*) AS run_count,
            SUM(TOTAL_ELAPSED_TIME) / 1000.0 AS total_seconds,
            ANY_VALUE(QUERY_TEXT) AS sample_query
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE START_TIME >= DATEADD('day', -7, CURRENT_TIMESTAMP())
          AND EXECUTION_STATUS = 'SUCCESS'
          AND IS_CLIENT_GENERATED_STATEMENT = FALSE
          AND QUERY_TYPE = 'SELECT'
        GROUP BY COALESCE(QUERY_PARAMETERIZED_HASH, MD5(QUERY_TEXT))
        HAVING COUNT(*) >= 10
        ORDER BY COUNT(*) DESC
        LIMIT 5
    """)
    repeated = cur.fetchall()
    if repeated:
        total_runs = sum(int(r[1]) for r in repeated)
        top = repeated[0]
        recs.append({
            "id": "rec_repeated_queries",
            "title": f"{total_runs} repeated SELECT queries detected - enable result caching",
            "description": (
                f"Top repeated query ran {int(top[1])}x in the last 7 days on {top[2]} "
                f"({round(float(top[2] or 0), 0):.0f}s total compute). "
                f"Sample: \"{(str(top[3]) or '')[:120]}...\". "
                f"Run ALTER WAREHOUSE {top[0]} SET USE_CACHED_RESULT = TRUE to serve identical queries from cache at zero compute cost."
            ),
            "category": "query",
            "potential_savings": None,
            "effort": "low",
            "priority": "high" if total_runs >= 50 else "medium",
        })

    # 3. Full table scans
    cur.execute("""
        SELECT
            WAREHOUSE_NAME,
            COUNT(*) AS cnt,
            ROUND(AVG(BYTES_SCANNED) / 1073741824.0, 1) AS avg_gb,
            ANY_VALUE(QUERY_TEXT) AS sample_query
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE START_TIME >= DATEADD('day', -7, CURRENT_TIMESTAMP())
          AND EXECUTION_STATUS = 'SUCCESS'
          AND PARTITIONS_SCANNED > 0
          AND PARTITIONS_TOTAL > 0
          AND PARTITIONS_SCANNED::FLOAT / PARTITIONS_TOTAL > 0.8
          AND BYTES_SCANNED > 1073741824
          AND QUERY_TYPE = 'SELECT'
        GROUP BY 1
        ORDER BY 2 DESC
        LIMIT 3
    """)
    full_scans = cur.fetchall()
    if full_scans:
        top = full_scans[0]
        total_scans = sum(int(r[1]) for r in full_scans)
        recs.append({
            "id": "rec_full_scans",
            "title": f"{total_scans} queries scanning >80% of partitions - add clustering keys",
            "description": (
                f"{int(top[1])} queries on {top[0]} are scanning >80% of table partitions "
                f"with avg {float(top[2] or 0):.1f} GB per query. "
                f"Adding clustering keys on frequently-filtered date or ID columns can reduce partition scans by 50-90%, "
                f"cutting both query time and compute cost."
            ),
            "category": "query",
            "potential_savings": None,
            "effort": "medium",
            "priority": "high" if total_scans > 30 else "medium",
        })

    # 4. Stale tables: no data or DDL change (LAST_ALTERED) in 90+ days.
    # Table age alone is not staleness — continuously loaded tables are old
    # too. If the role cannot read ACCOUNT_USAGE.TABLES, this yields no rows
    # (no recommendation) rather than a false one.
    cur.execute("""
        SELECT
            m.TABLE_CATALOG, m.TABLE_SCHEMA, m.TABLE_NAME,
            ROUND((m.ACTIVE_BYTES + m.TIME_TRAVEL_BYTES + m.FAILSAFE_BYTES) / 1073741824.0, 2) AS size_gb,
            t.LAST_ALTERED
        FROM SNOWFLAKE.ACCOUNT_USAGE.TABLE_STORAGE_METRICS m
        JOIN SNOWFLAKE.ACCOUNT_USAGE.TABLES t
          ON t.TABLE_ID = m.ID AND t.DELETED IS NULL
        WHERE m.DELETED = FALSE
          AND t.LAST_ALTERED < DATEADD('day', -90, CURRENT_TIMESTAMP())
          AND (m.ACTIVE_BYTES + m.TIME_TRAVEL_BYTES + m.FAILSAFE_BYTES) > 104857600
        ORDER BY (m.ACTIVE_BYTES + m.TIME_TRAVEL_BYTES + m.FAILSAFE_BYTES) DESC
        LIMIT 20
    """)
    stale = cur.fetchall()
    if stale:
        total_gb = round(sum(float(r[3] or 0) for r in stale), 1)
        savings = round(total_gb / 1024 * 23)  # $23 per TB-month
        names = ", ".join(f"{r[1]}.{r[2]}" for r in stale[:3])
        recs.append({
            "id": "rec_stale_tables",
            "title": f"Review {len(stale)} tables not modified for 90+ days ({total_gb} GB)",
            "description": (
                f"Found {len(stale)} tables with no data or schema changes in 90+ days, "
                f"occupying {total_gb} GB total. Examples: {names}{'...' if len(stale) > 3 else ''}. "
                f"Confirm they are not still read before dropping or archiving; "
                f"doing so could save ~${savings}/month in storage costs."
            ),
            "category": "storage",
            "potential_savings": savings if savings > 0 else None,
            "effort": "low",
            "priority": "medium" if total_gb > 50 else "low",
        })

    # 5. Slow queries
    cur.execute("""
        SELECT COUNT(*) AS cnt, ROUND(AVG(TOTAL_ELAPSED_TIME) / 1000.0, 0) AS avg_sec
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE START_TIME >= DATEADD('day', -7, CURRENT_TIMESTAMP())
          AND EXECUTION_STATUS = 'SUCCESS'
          AND TOTAL_ELAPSED_TIME > 300000
    """)
    row = cur.fetchone()
    slow_count = int(row[0] or 0) if row else 0
    avg_slow_sec = float(row[1] or 0) if row else 0
    if slow_count >= 5:
        recs.append({
            "id": "rec_slow_queries",
            "title": f"{slow_count} queries taking >5 minutes (avg {avg_slow_sec:.0f}s)",
            "description": (
                f"{slow_count} queries in the last 7 days ran longer than 5 minutes with an average of "
                f"{avg_slow_sec:.0f} seconds. Review the Query Performance page to identify patterns - "
                f"common causes include missing filters, Cartesian joins, or large result sets without LIMIT."
            ),
            "category": "query",
            "potential_savings": None,
            "effort": "medium",
            "priority": "medium" if slow_count >= 20 else "low",
        })

    sf.close()

    missing = sorted(getattr(sf, "missing_views", ()) or ())
    timed_out = sorted(getattr(sf, "timed_out_views", ()) or ())
    if missing or timed_out:
        hints = {
            "QUERY_HISTORY": "SNOWFLAKE.GOVERNANCE_VIEWER (exposes query text)",
            "ACCESS_HISTORY": "SNOWFLAKE.GOVERNANCE_VIEWER (exposes query text)",
            "TABLES": "SNOWFLAKE.OBJECT_VIEWER",
        }
        parts = []
        if missing:
            needs = sorted({h for v in missing for k, h in hints.items() if v.upper().endswith("." + k)})
            parts.append(f"The connected role cannot read {', '.join(missing)}"
                         + (f"; that needs {', '.join(needs)}." if needs else "."))
        if timed_out:
            parts.append(f"Queries on {', '.join(timed_out)} timed out (large account); they will be retried on the next refresh.")
        recs.append({
            "id": "rec_missing_grants",
            "title": f"{len(missing) + len(timed_out)} check{'' if len(missing) + len(timed_out) == 1 else 's'} skipped",
            "description": " ".join(parts) + " Skipped checks are not counted as healthy.",
            "category": "info",
            "potential_savings": None,
            "effort": "low",
            "priority": "low",
        })

    if not recs:
        recs.append({
            "id": "rec_all_good",
            "title": "No critical optimizations found",
            "description": "Your Snowflake usage looks efficient based on the last 7 days of data. Check back as more query history accumulates.",
            "category": "info",
            "potential_savings": None,
            "effort": "none",
            "priority": "low",
        })

    return recs


def sync_fetch_metric(conn_doc: dict, metric: str) -> float:
    sf = build_sf_connection(conn_doc)
    cur = sf.cursor()
    try:
        if metric == "daily_cost":
            cur.execute("""
                SELECT SUM(CREDITS_USED_COMPUTE)
                FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
                WHERE START_TIME >= CURRENT_DATE()
            """)
            row = cur.fetchone()
            credits = float(row[0] or 0) if row else 0.0
            return round(credits * 3.0, 2)
        elif metric == "hourly_credits":
            cur.execute("""
                SELECT SUM(CREDITS_USED_COMPUTE)
                FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
                WHERE START_TIME >= DATEADD('hour', -1, CURRENT_TIMESTAMP())
            """)
            row = cur.fetchone()
            return float(row[0] or 0) if row else 0.0
        elif metric == "expensive_query_count":
            cur.execute("""
                SELECT COUNT(*)
                FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                WHERE START_TIME >= DATEADD('hour', -1, CURRENT_TIMESTAMP())
                  AND TOTAL_ELAPSED_TIME > 300000
                  AND EXECUTION_STATUS = 'SUCCESS'
            """)
            row = cur.fetchone()
            return float(row[0] or 0) if row else 0.0
        elif metric == "failed_query_count":
            cur.execute("""
                SELECT COUNT(*)
                FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                WHERE START_TIME >= DATEADD('hour', -1, CURRENT_TIMESTAMP())
                  AND EXECUTION_STATUS = 'FAIL'
            """)
            row = cur.fetchone()
            return float(row[0] or 0) if row else 0.0
        elif metric == "storage_gb":
            cur.execute("""
                SELECT (STORAGE_BYTES + STAGE_BYTES + FAILSAFE_BYTES) / 1073741824.0
                FROM SNOWFLAKE.ACCOUNT_USAGE.STORAGE_USAGE
                ORDER BY USAGE_DATE DESC LIMIT 1
            """)
            row = cur.fetchone()
            return float(row[0] or 0) if row else 0.0
        return 0.0
    finally:
        sf.close()


def sync_workload_runs(conn_doc: dict, workload_id: str, days: int) -> dict:
    sf = build_sf_connection(conn_doc)
    cur = sf.cursor()
    cur.execute(f"""
        SELECT
            QUERY_ID, START_TIME, TOTAL_ELAPSED_TIME,
            USER_NAME, WAREHOUSE_NAME,
            BYTES_SCANNED, ROWS_PRODUCED,
            PERCENTAGE_SCANNED_FROM_CACHE
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE START_TIME >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          AND EXECUTION_STATUS = 'SUCCESS'
          AND COALESCE(QUERY_PARAMETERIZED_HASH, MD5(QUERY_TEXT)) = '{workload_id}'
        ORDER BY START_TIME DESC
        LIMIT 100
    """)
    rows = []
    for r in cur.fetchall():
        rows.append({
            "query_id": str(r[0]),
            "start_time": str(r[1]),
            "duration_ms": int(r[2] or 0),
            "user": str(r[3] or ""),
            "warehouse": str(r[4] or ""),
            "bytes_scanned": int(r[5] or 0),
            "rows_produced": int(r[6] or 0),
            "cache_hit_pct": round(float(r[7] or 0), 1),
        })
    sf.close()
    return {"runs": rows, "workload_id": workload_id}


def sync_debug_permissions(conn_doc: dict) -> dict:
    sf = build_sf_connection(conn_doc)
    cur = sf.cursor()
    results = {}
    checks = [
        ("QUERY_HISTORY", "SELECT COUNT(*) FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY WHERE START_TIME >= DATEADD('hour',-1,CURRENT_TIMESTAMP()) LIMIT 1"),
        ("WAREHOUSE_METERING_HISTORY", "SELECT COUNT(*) FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY WHERE START_TIME >= DATEADD('day',-1,CURRENT_TIMESTAMP()) LIMIT 1"),
        ("WAREHOUSE_LOAD_HISTORY", "SELECT COUNT(*) FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_LOAD_HISTORY WHERE START_TIME >= DATEADD('day',-1,CURRENT_TIMESTAMP()) LIMIT 1"),
        ("TABLE_STORAGE_METRICS", "SELECT COUNT(*) FROM SNOWFLAKE.ACCOUNT_USAGE.TABLE_STORAGE_METRICS WHERE DELETED=FALSE LIMIT 1"),
        ("STORAGE_USAGE", "SELECT COUNT(*) FROM SNOWFLAKE.ACCOUNT_USAGE.STORAGE_USAGE WHERE USAGE_DATE >= DATEADD('day',-7,CURRENT_DATE()) LIMIT 1"),
        ("DATABASE_STORAGE_USAGE_HISTORY", "SELECT COUNT(*) FROM SNOWFLAKE.ACCOUNT_USAGE.DATABASE_STORAGE_USAGE_HISTORY WHERE USAGE_DATE >= DATEADD('day',-7,CURRENT_DATE()) LIMIT 1"),
        ("METERING_HISTORY", "SELECT COUNT(*) FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY WHERE START_TIME >= DATEADD('day',-1,CURRENT_TIMESTAMP()) LIMIT 1"),
        ("METERING_DAILY_HISTORY", "SELECT COUNT(*) FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_DAILY_HISTORY WHERE SERVICE_TYPE='WAREHOUSE_METERING' LIMIT 1"),
        ("SHOW WAREHOUSES", "SHOW WAREHOUSES"),
    ]
    for name, sql in checks:
        try:
            cur.execute(sql)
            row = cur.fetchone()
            count = int(row[0]) if row and isinstance(row[0], (int, float)) else "ok"
            results[name] = {"status": "ok", "rows": count}
        except Exception as e:
            results[name] = {"status": "error", "error": str(e)[:200]}
    sf.close()
    return results


def sync_warehouse_sizing(conn_doc: dict, days: int, credit_price: float) -> dict:
    sf = build_sf_connection(conn_doc)
    cur = sf.cursor()

    # Size for every warehouse (SHOW WAREHOUSES, else last resize event)
    wh_configs = {k: v["size"] for k, v in _warehouse_configs(cur).items() if v["size"]}

    # Get utilization per warehouse
    cur.execute(f"""
        SELECT WAREHOUSE_NAME,
               AVG(AVG_RUNNING) AS avg_utilization
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_LOAD_HISTORY
        WHERE START_TIME >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
        GROUP BY 1
    """)
    utilization = {r[0]: round(float(r[1] or 0), 3) for r in cur.fetchall()}

    # Get spillage per warehouse
    cur.execute(f"""
        SELECT WAREHOUSE_NAME,
               ROUND(SUM(BYTES_SPILLED_TO_LOCAL_STORAGE) / 1073741824.0, 2) AS spill_local_gb,
               ROUND(SUM(BYTES_SPILLED_TO_REMOTE_STORAGE) / 1073741824.0, 2) AS spill_remote_gb
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE START_TIME >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          AND WAREHOUSE_NAME IS NOT NULL
        GROUP BY 1
    """)
    spillage = {r[0]: {"local": float(r[1] or 0), "remote": float(r[2] or 0)} for r in cur.fetchall()}

    # Get credits per warehouse
    cur.execute(f"""
        SELECT WAREHOUSE_NAME,
               SUM(CREDITS_USED_COMPUTE) AS total_credits
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
        WHERE START_TIME >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
        GROUP BY 1
    """)
    credits = {r[0]: float(r[1] or 0) for r in cur.fetchall()}
    # Spill comes from QUERY_HISTORY. Without it a "downsize" call would rest
    # on concurrency alone, which says nothing about whether queries need the
    # memory, so we only list sizes and make no recommendation.
    have_spill = not view_unavailable(sf, "QUERY_HISTORY")
    sf.close()
    wh_configs = {k: v for k, v in wh_configs.items() if credits.get(k, 0) > 0}

    size_order = ["XSMALL", "SMALL", "MEDIUM", "LARGE", "XLARGE", "2XLARGE", "3XLARGE", "4XLARGE", "5XLARGE", "6XLARGE"]
    size_credits = {"XSMALL": 1, "SMALL": 2, "MEDIUM": 4, "LARGE": 8, "XLARGE": 16, "2XLARGE": 32, "3XLARGE": 64, "4XLARGE": 128, "5XLARGE": 256, "6XLARGE": 512}

    def normalize_size(s):
        return s.replace("X-", "X").replace("-", "").upper()

    recommendations = []
    total_savings = 0.0

    for wh_name, current_size_raw in wh_configs.items():
        current_size = normalize_size(current_size_raw)
        util = utilization.get(wh_name, 0.0)
        spill = spillage.get(wh_name, {"local": 0, "remote": 0})
        wh_credits = credits.get(wh_name, 0)

        current_idx = size_order.index(current_size) if current_size in size_order else -1
        if current_idx < 0:
            continue

        recommended_size = current_size
        reason = "Current sizing appears appropriate"
        needs_change = False

        if not have_spill:
            reason = "Not evaluated: spill and query times need QUERY_HISTORY (GOVERNANCE_VIEWER)"
        elif util < 0.2 and spill["remote"] == 0 and spill["local"] == 0 and current_idx > 0:
            recommended_size = size_order[current_idx - 1]
            reason = f"Average utilization is {util:.0%} with no remote spillage — warehouse is over-provisioned"
            needs_change = True
        elif spill["remote"] > 1.0 and current_idx < len(size_order) - 1:
            recommended_size = size_order[current_idx + 1]
            reason = f"Remote spillage of {spill['remote']:.1f} GB detected — warehouse is undersized for workload"
            needs_change = True

        current_cph = size_credits.get(current_size, 1)
        recommended_cph = size_credits.get(recommended_size, 1)
        monthly_credits = wh_credits * (30 / max(days, 1))
        ratio = recommended_cph / current_cph if current_cph > 0 else 1
        monthly_savings = round((1 - ratio) * monthly_credits * credit_price, 2) if needs_change else 0.0
        total_savings += max(monthly_savings, 0)

        display_size_map = {"XSMALL": "X-Small", "SMALL": "Small", "MEDIUM": "Medium", "LARGE": "Large", "XLARGE": "X-Large", "2XLARGE": "2X-Large", "3XLARGE": "3X-Large", "4XLARGE": "4X-Large"}

        recommendations.append({
            "warehouse": wh_name,
            "current_size": display_size_map.get(current_size, current_size_raw),
            "recommended_size": display_size_map.get(recommended_size, recommended_size),
            "avg_utilization": util,
            "spill_local_gb": spill["local"],
            "spill_remote_gb": spill["remote"],
            "monthly_savings": max(monthly_savings, 0),
            "ddl_command": f"ALTER WAREHOUSE {wh_name} SET WAREHOUSE_SIZE = '{display_size_map.get(recommended_size, recommended_size)}';" if needs_change else None,
            "reason": reason,
            "needs_change": needs_change,
        })

    return {"recommendations": recommendations, "total_monthly_savings": round(total_savings, 2), "days": days}


# Name fragments that mark a Snowflake user as a service / integration
# account when Snowflake's own USERS.TYPE is not readable. Generic: common
# naming conventions plus widely used data tools.
_SERVICE_NAME_HINTS = (
    "_USER", "_SVC", "SVC_", "SERVICE", "_BOT", "_ETL", "_APP", "_API", "_INTEGRATION", "SYSTEM",
    "DBT", "AIRBYTE", "FIVETRAN", "STITCH", "HIGHTOUCH", "CENSUS", "SEGMENT", "RUDDERSTACK",
    "LOOKER", "TABLEAU", "OMNI", "SIGMA", "MODE_", "METABASE", "HEX", "POWERBI", "THOUGHTSPOT",
    "AIRFLOW", "DAGSTER", "PREFECT", "MATILLION", "MONTE_CARLO", "SELECT_", "SNOWPIPE", "WORKSHEETS_APP",
)


def classify_users(cur, conn_doc: dict, names: list) -> dict:
    """{user: (type, source)} with type 'service' | 'human'.

    Order: manual override on the connection (`user_types`), then Snowflake
    USERS.TYPE / login name (needs SECURITY_VIEWER), then a name heuristic."""
    manual = {str(k).upper(): v for k, v in (conn_doc.get("user_types") or {}).items()}
    out: dict = {}
    sf_info: dict = {}
    if names:
        cur.execute("""
            SELECT NAME, TYPE, LOGIN_NAME, EMAIL, HAS_PASSWORD
            FROM SNOWFLAKE.ACCOUNT_USAGE.USERS WHERE DELETED_ON IS NULL
        """)
        sf_info = {r[0]: r[1:] for r in cur.fetchall()}
    for n in names:
        key = str(n).upper()
        if manual.get(key) in ("service", "human"):
            out[n] = (manual[key], "manual")
            continue
        info = sf_info.get(n)
        if info:
            utype, login, email, has_pw = info
            if str(utype or "").upper() in ("SERVICE", "LEGACY_SERVICE"):
                out[n] = ("service", "snowflake")
                continue
            if str(utype or "").upper() == "PERSON" or "@" in str(login or "") or email:
                out[n] = ("human", "snowflake")
                continue
        out[n] = (("service" if any(h in key for h in _SERVICE_NAME_HINTS) else "human"), "guess")
    return out


def view_unavailable(sf, view: str) -> bool:
    """True when a query on `view` was denied OR timed out in this connection.
    Either way the data is missing, and checks must not treat it as empty."""
    names = set(getattr(sf, "missing_views", ())) | set(getattr(sf, "timed_out_views", ()))
    return any(view.upper() in v.upper() for v in names)


def quote_ident(name: str) -> str:
    """Quote a Snowflake identifier exactly as stored (case, special chars)."""
    return '"' + str(name).replace('"', '""') + '"'


# Auto-suspend settings (seconds) we replay query gaps against.
SUSPEND_CANDIDATES = (60, 120, 180, 300, 600, 900, 1800, 3600)


def idle_pct_val(idle: float, used: float) -> float:
    return 100 * idle / used if used else 0.0


def _warehouse_configs(cur) -> dict:
    """{name: {"size": "XSMALL"|None, "suspend": int|None}} for every
    warehouse we can learn about. SHOW WAREHOUSES only lists warehouses the
    role has a privilege on, so fall back to the last WAREHOUSE_CONSISTENT
    event (USAGE_VIEWER) for size. Auto-suspend is only in SHOW."""
    configs: dict = {}
    try:
        cur.execute("SHOW WAREHOUSES")
        cols = [d[0].lower() for d in cur.description]
        for row in cur.fetchall():
            rd = dict(zip(cols, row))
            configs[rd.get("name", "")] = {
                "size": str(rd.get("size", "") or "").upper().replace("X-", "X").replace("-", "") or None,
                # 0/NULL from SHOW means "never suspends" (known, and the
                # costliest case). None is reserved for "not visible".
                "suspend": int(rd.get("auto_suspend") or 0),
            }
    except Exception:
        logger.warning("SHOW WAREHOUSES failed", exc_info=True)
    cur.execute("""
        SELECT WAREHOUSE_NAME, MAX_BY(SIZE, TIMESTAMP)
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_EVENTS_HISTORY
        WHERE EVENT_NAME = 'WAREHOUSE_CONSISTENT' AND SIZE IS NOT NULL
          AND TIMESTAMP >= DATEADD('day', -90, CURRENT_TIMESTAMP())
        GROUP BY 1
    """)
    for name, size in cur.fetchall():
        c = configs.setdefault(name, {"size": None, "suspend": None})
        if not c["size"] and size:
            c["size"] = str(size).upper().replace("X-", "X").replace("-", "")
    return configs


def sync_autosuspend_analysis(conn_doc: dict, days: int, credit_price: float) -> dict:
    """Idle spend per warehouse plus auto-suspend tuning.

    Idle credits = CREDITS_USED_COMPUTE - CREDITS_ATTRIBUTED_COMPUTE_QUERIES
    (Snowflake's documented method; covers every metered warehouse with only
    USAGE_VIEWER). It includes the auto-suspend tail, the 60s minimum per
    resume, and gaps between queries. Auto-suspend recommendations need real
    inter-query gaps (QUERY_HISTORY) and the current setting (SHOW
    WAREHOUSES); without them we report idle spend but do not guess."""
    sf = build_sf_connection(conn_doc)
    cur = sf.cursor()
    configs = _warehouse_configs(cur)

    cur.execute(f"""
        SELECT WAREHOUSE_NAME,
               SUM(CREDITS_USED_COMPUTE),
               SUM(CREDITS_ATTRIBUTED_COMPUTE_QUERIES)
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
        WHERE START_TIME >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          AND WAREHOUSE_ID > 0
        GROUP BY 1 HAVING SUM(CREDITS_USED_COMPUTE) > 0
    """)
    metering = {r[0]: (float(r[1] or 0), float(r[2] or 0)) for r in cur.fetchall()}

    cur.execute(f"""
        SELECT WAREHOUSE_NAME, COUNT_IF(EVENT_NAME = 'RESUME_CLUSTER'),
               COUNT_IF(EVENT_NAME = 'RESUME_WAREHOUSE')
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_EVENTS_HISTORY
        WHERE TIMESTAMP >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          AND EVENT_NAME IN ('RESUME_WAREHOUSE', 'RESUME_CLUSTER')
        GROUP BY 1
    """)
    # Each cluster start pays its own auto-suspend tail, so count cluster
    # resumes (fall back to warehouse resumes on accounts that lack them).
    resumes = {r[0]: int(r[1] or r[2] or 0) for r in cur.fetchall()}

    # Idle seconds a given auto-suspend would bill, replayed over the real
    # gaps between queries: a gap shorter than the setting keeps the
    # warehouse running for the whole gap; a longer gap bills the setting,
    # then the warehouse sleeps. (Ignores the 60s minimum on restarts, which
    # is why 60s is the floor we ever recommend.)
    candidates = SUSPEND_CANDIDATES
    idle_cols = ",\n               ".join(f"SUM(LEAST(gap_s, {c}))" for c in candidates)
    cur.execute(f"""
        SELECT WAREHOUSE_NAME,
               PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY gap_s),
               PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY gap_s),
               {idle_cols}
        FROM (
            SELECT WAREHOUSE_NAME,
                   DATEDIFF('second', LAG(END_TIME) OVER (PARTITION BY WAREHOUSE_NAME ORDER BY END_TIME), START_TIME) AS gap_s
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
            WHERE START_TIME >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
              AND WAREHOUSE_NAME IS NOT NULL AND WAREHOUSE_SIZE IS NOT NULL
        ) gaps
        WHERE gap_s > 0
        GROUP BY 1
    """)
    gaps = {}
    idle_at: dict = {}
    for r in cur.fetchall():
        gaps[r[0]] = (round(float(r[1] or 0)), round(float(r[2] or 0)))
        idle_at[r[0]] = {c: float(v or 0) for c, v in zip(candidates, r[3:])}
    missing = sorted(getattr(sf, "missing_views", set()))
    sf.close()

    month = 30 / max(days, 1)
    size_credits = {"XSMALL": 1, "SMALL": 2, "MEDIUM": 4, "LARGE": 8, "XLARGE": 16,
                    "2XLARGE": 32, "3XLARGE": 64, "4XLARGE": 128, "5XLARGE": 256, "6XLARGE": 512}
    recommendations = []
    total_savings = total_idle = 0.0
    for wh, (used, attributed) in sorted(metering.items(), key=lambda kv: -kv[1][0]):
        cfg = configs.get(wh, {"size": None, "suspend": None})
        idle = max(used - attributed, 0.0)
        idle_cost_monthly = round(idle * credit_price * month, 2)
        total_idle += idle_cost_monthly
        p50, p75 = gaps.get(wh, (None, None))
        current = cfg["suspend"]
        recommended = None
        needs_change = False
        monthly_savings = 0.0
        never = current == 0
        if current and p75 and wh in idle_at and cfg["size"]:
            # Replay the real query gaps at the current setting and at 60s.
            # Use the largest candidate not above the current setting, so the
            # estimate is never more generous than reality.
            base = max((c for c in SUSPEND_CANDIDATES if c <= current), default=None)
            if base and base > 60:
                saved_s = idle_at[wh][base] - idle_at[wh][60]
                saved = saved_s / 3600 * size_credits.get(cfg["size"], 1) * month
                monthly_savings = round(min(saved * credit_price, idle_cost_monthly), 2)
                if monthly_savings >= 5:
                    recommended = 60
                    needs_change = True
                else:
                    monthly_savings = 0.0
        # Average idle seconds each cluster start costs. Roughly the
        # auto-suspend setting plus gaps between queries while awake.
        cph = size_credits.get(cfg["size"] or "", 0)
        n_res = resumes.get(wh, 0)
        idle_per_resume_s = round(idle / (n_res * cph) * 3600) if n_res and cph else None
        est = False
        low_suspend = False
        if never:
            # Never suspends: it bills every hour it is on, whether or not
            # queries run. Nearly all idle spend is recoverable.
            recommended = 60
            needs_change = True
            monthly_savings = idle_cost_monthly
        elif current and not p75 and n_res and cph:
            if current > 60:
                # Known setting: every cluster start keeps running `current`
                # seconds after its last query. 60s keeps the warehouse warm
                # for back-to-back queries and is Snowflake's minimum charge.
                recommended = 60
                needs_change = True
                saved = (current - 60) / 3600 * cph * n_res * month
                monthly_savings = round(min(saved * credit_price, idle_cost_monthly), 2)
            elif current < 60 and idle_pct_val(idle, used) >= 50:
                # Below 60s, each restart is still billed a full minute, so a
                # very short suspend on a frequently-called warehouse buys
                # restarts, not savings.
                low_suspend = True
        elif current is None and idle_per_resume_s and idle_per_resume_s > 120:
            # Setting unknown: estimate what a 60s auto-suspend would save,
            # assuming the extra idle is the suspend tail. An estimate, so
            # flagged as such and capped at the idle spend.
            recommended = 60
            needs_change = True
            est = True
            saved = (idle_per_resume_s - 60) / 3600 * cph * n_res * month
            monthly_savings = round(min(saved * credit_price, idle_cost_monthly), 2)
        total_savings += monthly_savings
        if never:
            note = ("Auto-suspend is off, so it bills every hour it is on. Up to the full idle spend "
                    "is recoverable with a 60s auto-suspend.")
        elif low_suspend:
            note = (f"Auto-suspend is {current}s, under Snowflake's 60s minimum charge per start, and it "
                    f"started {n_res:,} times. The idle is mostly that minimum. Fewer, batched calls "
                    "will save more than changing the setting; 60s is worth testing.")
            recommended = 60
        elif current and needs_change and p75:
            note = (f"Replaying every gap between its queries over the last {days} days: auto-suspend "
                    f"{current}s keeps it running through gaps that 60s would sleep through. "
                    f"Half the gaps are under {p50}s, so short bursts still stay warm.")
        elif current and needs_change and not p75:
            note = (f"Each of {n_res:,} cluster starts runs {current}s after its last query. "
                    f"60s would cut ~{current - 60}s per start.")
        elif est:
            note = (f"~{idle_per_resume_s}s idle per cluster start. Auto-suspend is not visible "
                    "to this role; savings assume it is the cause. Check before changing.")
        elif current is None:
            note = "Auto-suspend setting not visible to this role (needs MONITOR on the warehouse)."
        elif not p75:
            note = "Query gaps need QUERY_HISTORY (GOVERNANCE_VIEWER) to suggest a value."
        else:
            note = None
        recommendations.append({
            "warehouse": wh,
            "size": cfg["size"],
            "current_suspend_s": current,
            "recommended_suspend_s": recommended,
            "resume_count": resumes.get(wh, 0),
            "metered_credits": round(used, 2),
            "query_credits": round(attributed, 2),
            "idle_waste_credits": round(idle, 2),
            "idle_pct": round(100 * idle / used, 1) if used else 0.0,
            "idle_cost_monthly": idle_cost_monthly,
            "idle_per_resume_s": idle_per_resume_s,
            "savings_is_estimate": est,
            "monthly_savings": monthly_savings,
            # Only offer a one-click change when we know the current setting.
            "ddl_command": f"ALTER WAREHOUSE {quote_ident(wh)} SET AUTO_SUSPEND = {recommended};" if needs_change and not est else None,
            "suggested_sql": f"ALTER WAREHOUSE {quote_ident(wh)} SET AUTO_SUSPEND = {recommended};" if (needs_change or low_suspend) else None,
            "gap_p50_s": p50,
            "gap_p75_s": p75,
            "needs_change": needs_change,
            "note": note,
        })

    return {
        "recommendations": recommendations,
        "total_monthly_savings": round(total_savings, 2),
        "total_idle_cost_monthly": round(total_idle, 2),
        "missing_views": missing,
        "days": days,
    }


def sync_spillage(conn_doc: dict, days: int) -> dict:
    sf = build_sf_connection(conn_doc)
    cur = sf.cursor()

    cur.execute(f"""
        SELECT WAREHOUSE_NAME,
               COUNT(*) AS query_count,
               ROUND(SUM(BYTES_SPILLED_TO_LOCAL_STORAGE) / 1073741824.0, 2) AS spill_local_gb,
               ROUND(SUM(BYTES_SPILLED_TO_REMOTE_STORAGE) / 1073741824.0, 2) AS spill_remote_gb
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE START_TIME >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          AND (BYTES_SPILLED_TO_LOCAL_STORAGE > 0 OR BYTES_SPILLED_TO_REMOTE_STORAGE > 0)
          AND WAREHOUSE_NAME IS NOT NULL
        GROUP BY 1
        ORDER BY 3 DESC
    """)
    by_warehouse = [
        {"warehouse": r[0], "query_count": int(r[1] or 0), "spill_local_gb": float(r[2] or 0), "spill_remote_gb": float(r[3] or 0)}
        for r in cur.fetchall()
    ]

    cur.execute(f"""
        SELECT USER_NAME,
               COUNT(*) AS query_count,
               ROUND(SUM(BYTES_SPILLED_TO_LOCAL_STORAGE) / 1073741824.0, 2) AS spill_local_gb,
               ROUND(SUM(BYTES_SPILLED_TO_REMOTE_STORAGE) / 1073741824.0, 2) AS spill_remote_gb
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE START_TIME >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          AND (BYTES_SPILLED_TO_LOCAL_STORAGE > 0 OR BYTES_SPILLED_TO_REMOTE_STORAGE > 0)
        GROUP BY 1
        ORDER BY 3 DESC
    """)
    by_user = [
        {"user": r[0], "query_count": int(r[1] or 0), "spill_local_gb": float(r[2] or 0), "spill_remote_gb": float(r[3] or 0)}
        for r in cur.fetchall()
    ]

    cur.execute(f"""
        SELECT QUERY_ID, WAREHOUSE_NAME, USER_NAME, WAREHOUSE_SIZE,
               ROUND(BYTES_SPILLED_TO_LOCAL_STORAGE / 1073741824.0, 2) AS spill_local_gb,
               ROUND(BYTES_SPILLED_TO_REMOTE_STORAGE / 1073741824.0, 2) AS spill_remote_gb,
               TOTAL_ELAPSED_TIME / 1000.0 AS duration_s,
               QUERY_TEXT
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE START_TIME >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          AND (BYTES_SPILLED_TO_LOCAL_STORAGE > 0 OR BYTES_SPILLED_TO_REMOTE_STORAGE > 0)
        ORDER BY (BYTES_SPILLED_TO_LOCAL_STORAGE + BYTES_SPILLED_TO_REMOTE_STORAGE) DESC
        LIMIT 20
    """)
    top_queries = [
        {
            "query_id": r[0], "warehouse": r[1], "user": r[2], "warehouse_size": r[3],
            "spill_local_gb": float(r[4] or 0), "spill_remote_gb": float(r[5] or 0),
            "duration_s": round(float(r[6] or 0), 1), "query_text": (r[7] or "")[:200],
        }
        for r in cur.fetchall()
    ]
    sf.close()

    total_spill = round(sum(w["spill_local_gb"] + w["spill_remote_gb"] for w in by_warehouse), 2)
    affected_queries = sum(w["query_count"] for w in by_warehouse)

    return {
        "by_warehouse": by_warehouse,
        "by_user": by_user,
        "top_queries": top_queries,
        "summary": {
            "total_spill_gb": total_spill,
            "affected_queries": affected_queries,
            "affected_warehouses": len(by_warehouse),
        },
        "days": days,
    }


def sync_query_patterns(conn_doc: dict, days: int, credit_price: float) -> dict:
    sf = build_sf_connection(conn_doc)
    cur = sf.cursor()

    cur.execute(f"""
        SELECT
            COALESCE(QUERY_PARAMETERIZED_HASH, MD5(QUERY_TEXT)) AS pattern_hash,
            ANY_VALUE(QUERY_TEXT) AS example_query,
            COUNT(*) AS execution_count,
            SUM(CREDITS_USED_CLOUD_SERVICES) * {credit_price} AS total_cost_usd,
            ROUND(AVG(TOTAL_ELAPSED_TIME) / 1000.0, 1) AS avg_duration_s,
            ROUND(AVG(CASE WHEN PARTITIONS_TOTAL > 0 THEN PARTITIONS_SCANNED::FLOAT / PARTITIONS_TOTAL ELSE 0 END), 3) AS avg_scan_ratio,
            ROUND(AVG(BYTES_SPILLED_TO_LOCAL_STORAGE + BYTES_SPILLED_TO_REMOTE_STORAGE) / 1073741824.0, 3) AS avg_spill_gb,
            ROUND(AVG(PERCENTAGE_SCANNED_FROM_CACHE), 1) AS avg_cache_pct
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE START_TIME >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          AND EXECUTION_STATUS = 'SUCCESS'
          AND IS_CLIENT_GENERATED_STATEMENT = FALSE
        GROUP BY 1
        HAVING COUNT(*) >= 2
        ORDER BY total_cost_usd DESC
        LIMIT 100
    """)

    patterns = []
    total_cost = 0.0
    for r in cur.fetchall():
        cost = round(float(r[3] or 0), 2)
        total_cost += cost
        scan_ratio = float(r[5] or 0)
        avg_spill = float(r[6] or 0)
        cache_pct = float(r[7] or 0)

        flags = []
        recommendation = ""
        if cache_pct > 60:
            flags.append("cacheable")
            recommendation = "High cache hit rate — consider result caching or materialized views"
        if scan_ratio > 0.8:
            flags.append("full_scan")
            recommendation = "Scanning >80% of partitions — add clustering keys on filter columns"
        if avg_spill > 0:
            flags.append("spilling")
            if not recommendation:
                recommendation = "Query is spilling to disk — consider a larger warehouse or optimize query"
        if not recommendation:
            recommendation = "No immediate optimization needed"

        patterns.append({
            "pattern_hash": str(r[0] or "")[:16],
            "example_query": (str(r[1] or ""))[:200],
            "execution_count": int(r[2] or 0),
            "total_cost_usd": cost,
            "avg_duration_s": float(r[4] or 0),
            "avg_scan_ratio": scan_ratio,
            "avg_spill_gb": avg_spill,
            "avg_cache_pct": cache_pct,
            "flags": flags,
            "recommendation": recommendation,
        })
    sf.close()

    return {
        "patterns": patterns,
        "total_patterns": len(patterns),
        "total_cost_usd": round(total_cost, 2),
        "days": days,
    }


def sync_cost_attribution(conn_doc: dict, days: int, credit_price: float) -> dict:
    sf = build_sf_connection(conn_doc)
    cur = sf.cursor()

    # Proportional cost allocation by user
    cur.execute(f"""
        SELECT USER_NAME,
               SUM(TOTAL_ELAPSED_TIME) AS total_elapsed,
               COUNT(*) AS query_count
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE START_TIME >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          AND WAREHOUSE_NAME IS NOT NULL
          AND IS_CLIENT_GENERATED_STATEMENT = FALSE
        GROUP BY 1
        ORDER BY 2 DESC
    """)
    user_elapsed = {r[0]: {"elapsed": float(r[1] or 0), "queries": int(r[2] or 0)} for r in cur.fetchall()}

    # Total credits by warehouse
    cur.execute(f"""
        SELECT WAREHOUSE_NAME,
               SUM(CREDITS_USED_COMPUTE) AS total_credits
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
        WHERE START_TIME >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
        GROUP BY 1
    """)
    wh_credits = {r[0]: float(r[1] or 0) for r in cur.fetchall()}
    total_cost = sum(c * credit_price for c in wh_credits.values())
    total_elapsed_all = sum(v["elapsed"] for v in user_elapsed.values())

    by_user = []
    for user, data in sorted(user_elapsed.items(), key=lambda x: x[1]["elapsed"], reverse=True)[:20]:
        proportion = data["elapsed"] / total_elapsed_all if total_elapsed_all > 0 else 0
        cost = round(proportion * total_cost, 2)
        by_user.append({"user": user, "cost_usd": cost, "query_count": data["queries"], "pct": round(proportion * 100, 1)})

    # By role
    cur.execute(f"""
        SELECT ROLE_NAME,
               SUM(TOTAL_ELAPSED_TIME) AS total_elapsed,
               COUNT(*) AS query_count
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE START_TIME >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          AND WAREHOUSE_NAME IS NOT NULL
          AND IS_CLIENT_GENERATED_STATEMENT = FALSE
        GROUP BY 1
        ORDER BY 2 DESC LIMIT 20
    """)
    by_role = []
    for r in cur.fetchall():
        elapsed = float(r[1] or 0)
        proportion = elapsed / total_elapsed_all if total_elapsed_all > 0 else 0
        cost = round(proportion * total_cost, 2)
        by_role.append({"role": r[0], "cost_usd": cost, "query_count": int(r[2] or 0), "pct": round(proportion * 100, 1)})

    # By database
    cur.execute(f"""
        SELECT DATABASE_NAME,
               SUM(TOTAL_ELAPSED_TIME) AS total_elapsed,
               COUNT(*) AS query_count
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE START_TIME >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          AND WAREHOUSE_NAME IS NOT NULL
          AND DATABASE_NAME IS NOT NULL
          AND IS_CLIENT_GENERATED_STATEMENT = FALSE
        GROUP BY 1
        ORDER BY 2 DESC LIMIT 20
    """)
    by_database = []
    for r in cur.fetchall():
        elapsed = float(r[1] or 0)
        proportion = elapsed / total_elapsed_all if total_elapsed_all > 0 else 0
        cost = round(proportion * total_cost, 2)
        by_database.append({"database": r[0], "cost_usd": cost, "query_count": int(r[2] or 0), "pct": round(proportion * 100, 1)})

    # By warehouse (straightforward)
    by_warehouse = [
        {"warehouse": wh, "cost_usd": round(creds * credit_price, 2), "credits": round(creds, 2)}
        for wh, creds in sorted(wh_credits.items(), key=lambda x: x[1], reverse=True)
    ]

    # Top queries by estimated cost
    cur.execute(f"""
        SELECT QUERY_ID, USER_NAME, WAREHOUSE_NAME, ROLE_NAME,
               TOTAL_ELAPSED_TIME / 1000.0 AS duration_s,
               QUERY_TEXT,
               CREDITS_USED_CLOUD_SERVICES * {credit_price} AS est_cost
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE START_TIME >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          AND WAREHOUSE_NAME IS NOT NULL
          AND IS_CLIENT_GENERATED_STATEMENT = FALSE
        ORDER BY TOTAL_ELAPSED_TIME DESC
        LIMIT 20
    """)
    top_queries = [
        {
            "query_id": r[0], "user": r[1], "warehouse": r[2], "role": r[3],
            "duration_s": round(float(r[4] or 0), 1),
            "query_text": (r[5] or "")[:200],
            "est_cost_usd": round(float(r[6] or 0), 4),
        }
        for r in cur.fetchall()
    ]
    sf.close()

    return {
        "by_user": by_user,
        "by_role": by_role,
        "by_database": by_database,
        "by_warehouse": by_warehouse,
        "top_queries": top_queries,
        "total_cost_usd": round(total_cost, 2),
        "days": days,
    }


def sync_stale_tables(conn_doc: dict, days: int) -> dict:
    sf = build_sf_connection(conn_doc)
    cur = sf.cursor()

    # Get large tables
    cur.execute("""
        SELECT TABLE_CATALOG, TABLE_SCHEMA, TABLE_NAME,
               (ACTIVE_BYTES + TIME_TRAVEL_BYTES + FAILSAFE_BYTES) / 1073741824.0 AS size_gb,
               TABLE_CREATED
        FROM SNOWFLAKE.ACCOUNT_USAGE.TABLE_STORAGE_METRICS
        WHERE DELETED = FALSE
          AND (ACTIVE_BYTES + TIME_TRAVEL_BYTES + FAILSAFE_BYTES) > 1048576
        ORDER BY size_gb DESC
        LIMIT 200
    """)
    tables_raw = cur.fetchall()

    # Last read per table from ACCESS_HISTORY (Enterprise edition, needs
    # GOVERNANCE_VIEWER). Without it there is no safe way to call a table
    # unused: creation date says nothing about whether it is loaded or read
    # every day, so we report "unavailable" instead of guessing.
    window = max(days, 180)
    last_queried = {}
    access_ok = True
    try:
        cur.execute(f"""
            SELECT
                bos.value:"objectName"::STRING AS full_name,
                MAX(QUERY_START_TIME) AS last_queried
            FROM SNOWFLAKE.ACCOUNT_USAGE.ACCESS_HISTORY,
                 LATERAL FLATTEN(BASE_OBJECTS_ACCESSED) bos
            WHERE QUERY_START_TIME >= DATEADD('day', -{window}, CURRENT_TIMESTAMP())
            GROUP BY 1
        """)
        for r in cur.fetchall():
            last_queried[str(r[0]).upper()] = r[1]
    except Exception:
        access_ok = False
    if view_unavailable(sf, "ACCESS_HISTORY"):
        access_ok = False
    sf.close()

    price_tb = _override(conn_doc, "storage_price_per_tb", "storage_price") or 23.0
    if not access_ok:
        return {
            "stale_tables": [], "stale_count": 0, "stale_total_gb": 0,
            "stale_monthly_cost": 0, "days": days, "available": False,
            "reason": "Needs SNOWFLAKE.ACCOUNT_USAGE.ACCESS_HISTORY (database role "
                      "GOVERNANCE_VIEWER, Enterprise edition) to know when a table was last read.",
        }

    now = datetime.utcnow()
    stale_tables = []
    for r in tables_raw:
        db, schema, table = r[0], r[1], r[2]
        size_gb = round(float(r[3] or 0), 2)
        created = r[4]
        full_name = f"{db}.{schema}.{table}".upper()
        lq = last_queried.get(full_name)
        if lq is not None:
            days_since = (now - lq.replace(tzinfo=None)).days
        else:
            # Not read at all inside the lookback window. Only call it stale
            # if the table is older than the window.
            age = (now - created.replace(tzinfo=None)).days if hasattr(created, "year") else None
            days_since = window if age is not None and age > window else None
        if days_since is None or days_since <= 90:
            continue
        stale_tables.append({
            "database": db, "schema": schema, "table": table,
            "size_gb": size_gb,
            "last_queried": str(lq)[:19] if lq is not None else f"not read in {window}d",
            "days_since_queried": days_since,
            "monthly_cost": round(size_gb / 1024 * price_tb, 2),
            "recommendation": "Confirm owner, then drop or archive" if days_since >= 180 else "Review usage",
        })

    stale_tables.sort(key=lambda x: x["size_gb"], reverse=True)
    return {
        "stale_tables": stale_tables,
        "stale_count": len(stale_tables),
        "stale_total_gb": round(sum(t["size_gb"] for t in stale_tables), 2),
        "stale_monthly_cost": round(sum(t["monthly_cost"] for t in stale_tables), 2),
        "days": days,
        "available": True,
    }


def sync_execute_resize(conn_doc: dict, warehouse_name: str, new_size: str) -> dict:
    from app.utils.constants import VALID_WAREHOUSE_SIZES
    if new_size.upper().replace(" ", "-") not in [s.upper() for s in VALID_WAREHOUSE_SIZES] and new_size.replace(" ", "-") not in VALID_WAREHOUSE_SIZES:
        return {"success": False, "error": f"Invalid warehouse size: {new_size}"}

    try:
        sf = build_sf_connection(conn_doc)
        cur = sf.cursor()
        ddl = f"ALTER WAREHOUSE {warehouse_name} SET WAREHOUSE_SIZE = '{new_size}'"
        cur.execute(ddl)
        sf.close()
        return {"success": True, "ddl": ddl, "warehouse": warehouse_name, "new_size": new_size}
    except Exception as e:
        return {"success": False, "error": str(e)[:300]}


def sync_execute_autosuspend(conn_doc: dict, warehouse_name: str, seconds: int) -> dict:
    if not (0 <= seconds <= 86400):
        return {"success": False, "error": f"Invalid auto_suspend value: {seconds}"}

    try:
        sf = build_sf_connection(conn_doc)
        cur = sf.cursor()
        ddl = f"ALTER WAREHOUSE {warehouse_name} SET AUTO_SUSPEND = {seconds}"
        cur.execute(ddl)
        sf.close()
        return {"success": True, "ddl": ddl, "warehouse": warehouse_name, "seconds": seconds}
    except Exception as e:
        return {"success": False, "error": str(e)[:300]}
