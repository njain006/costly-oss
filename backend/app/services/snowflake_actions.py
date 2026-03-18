"""Snowflake DDL execution service for cost optimization actions.

Each function validates inputs, executes DDL via the Snowflake connection,
and logs the action to the warehouse_actions MongoDB collection.
"""

import re
from datetime import datetime

from app.database import db
from app.services.snowflake import build_sf_connection
from app.utils.constants import VALID_WAREHOUSE_SIZES
from app.utils.helpers import run_in_thread


_VALID_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

VALID_SIZES_UPPER = {s.upper() for s in VALID_WAREHOUSE_SIZES}


def _validate_warehouse_name(name: str) -> str | None:
    """Return an error message if the warehouse name is invalid, else None."""
    if not name or not _VALID_NAME_RE.match(name):
        return f"Invalid warehouse name: '{name}'. Must be alphanumeric/underscore."
    return None


def _validate_size(size: str) -> str | None:
    """Return an error message if the size is invalid, else None."""
    normalized = size.upper().replace(" ", "-")
    if normalized not in VALID_SIZES_UPPER:
        return f"Invalid warehouse size: '{size}'. Valid: {', '.join(sorted(VALID_WAREHOUSE_SIZES))}"
    return None


async def _log_action(
    user_id: str,
    action: str,
    warehouse: str,
    params: dict,
    success: bool,
    message: str,
):
    """Log an action to the warehouse_actions MongoDB collection."""
    await db.warehouse_actions.insert_one({
        "user_id": user_id,
        "action": action,
        "warehouse": warehouse,
        "params": params,
        "timestamp": datetime.utcnow(),
        "success": success,
        "message": message,
    })


def _sync_execute_ddl(conn_doc: dict, ddl: str) -> dict:
    """Execute a single DDL statement against Snowflake (blocking)."""
    sf = build_sf_connection(conn_doc)
    try:
        cur = sf.cursor()
        cur.execute(ddl)
        return {"success": True}
    finally:
        sf.close()


async def resize_warehouse(source: dict, warehouse_name: str, new_size: str, user_id: str = None) -> dict:
    """ALTER WAREHOUSE {name} SET WAREHOUSE_SIZE = '{new_size}'"""
    err = _validate_warehouse_name(warehouse_name)
    if err:
        return {"success": False, "message": err, "action": "resize", "warehouse": warehouse_name}

    err = _validate_size(new_size)
    if err:
        return {"success": False, "message": err, "action": "resize", "warehouse": warehouse_name}

    ddl = f"ALTER WAREHOUSE {warehouse_name} SET WAREHOUSE_SIZE = '{new_size.upper()}'"
    try:
        await run_in_thread(_sync_execute_ddl, source, ddl)
        result = {
            "success": True,
            "message": f"Warehouse {warehouse_name} resized to {new_size.upper()}",
            "action": "resize",
            "warehouse": warehouse_name,
        }
    except Exception as e:
        result = {
            "success": False,
            "message": str(e)[:300],
            "action": "resize",
            "warehouse": warehouse_name,
        }

    if user_id:
        await _log_action(user_id, "resize", warehouse_name, {"new_size": new_size}, result["success"], result["message"])
    return result


async def set_autosuspend(source: dict, warehouse_name: str, seconds: int, user_id: str = None) -> dict:
    """ALTER WAREHOUSE {name} SET AUTO_SUSPEND = {seconds}"""
    err = _validate_warehouse_name(warehouse_name)
    if err:
        return {"success": False, "message": err, "action": "set_autosuspend", "warehouse": warehouse_name}

    if not (0 <= seconds <= 86400):
        return {
            "success": False,
            "message": f"Invalid auto_suspend value: {seconds}. Must be 0-86400.",
            "action": "set_autosuspend",
            "warehouse": warehouse_name,
        }

    ddl = f"ALTER WAREHOUSE {warehouse_name} SET AUTO_SUSPEND = {seconds}"
    try:
        await run_in_thread(_sync_execute_ddl, source, ddl)
        result = {
            "success": True,
            "message": f"Warehouse {warehouse_name} auto-suspend set to {seconds}s",
            "action": "set_autosuspend",
            "warehouse": warehouse_name,
        }
    except Exception as e:
        result = {
            "success": False,
            "message": str(e)[:300],
            "action": "set_autosuspend",
            "warehouse": warehouse_name,
        }

    if user_id:
        await _log_action(user_id, "set_autosuspend", warehouse_name, {"seconds": seconds}, result["success"], result["message"])
    return result


async def suspend_warehouse(source: dict, warehouse_name: str, user_id: str = None) -> dict:
    """ALTER WAREHOUSE {name} SUSPEND"""
    err = _validate_warehouse_name(warehouse_name)
    if err:
        return {"success": False, "message": err, "action": "suspend", "warehouse": warehouse_name}

    ddl = f"ALTER WAREHOUSE {warehouse_name} SUSPEND"
    try:
        await run_in_thread(_sync_execute_ddl, source, ddl)
        result = {
            "success": True,
            "message": f"Warehouse {warehouse_name} suspended",
            "action": "suspend",
            "warehouse": warehouse_name,
        }
    except Exception as e:
        result = {
            "success": False,
            "message": str(e)[:300],
            "action": "suspend",
            "warehouse": warehouse_name,
        }

    if user_id:
        await _log_action(user_id, "suspend", warehouse_name, {}, result["success"], result["message"])
    return result


async def resume_warehouse(source: dict, warehouse_name: str, user_id: str = None) -> dict:
    """ALTER WAREHOUSE {name} RESUME"""
    err = _validate_warehouse_name(warehouse_name)
    if err:
        return {"success": False, "message": err, "action": "resume", "warehouse": warehouse_name}

    ddl = f"ALTER WAREHOUSE {warehouse_name} RESUME"
    try:
        await run_in_thread(_sync_execute_ddl, source, ddl)
        result = {
            "success": True,
            "message": f"Warehouse {warehouse_name} resumed",
            "action": "resume",
            "warehouse": warehouse_name,
        }
    except Exception as e:
        result = {
            "success": False,
            "message": str(e)[:300],
            "action": "resume",
            "warehouse": warehouse_name,
        }

    if user_id:
        await _log_action(user_id, "resume", warehouse_name, {}, result["success"], result["message"])
    return result


async def set_scaling_policy(
    source: dict, warehouse_name: str, min_clusters: int, max_clusters: int, user_id: str = None
) -> dict:
    """ALTER WAREHOUSE SET MIN_CLUSTER_COUNT/MAX_CLUSTER_COUNT"""
    err = _validate_warehouse_name(warehouse_name)
    if err:
        return {"success": False, "message": err, "action": "set_scaling_policy", "warehouse": warehouse_name}

    if not (1 <= min_clusters <= 10) or not (1 <= max_clusters <= 10):
        return {
            "success": False,
            "message": f"Cluster counts must be between 1 and 10. Got min={min_clusters}, max={max_clusters}.",
            "action": "set_scaling_policy",
            "warehouse": warehouse_name,
        }
    if min_clusters > max_clusters:
        return {
            "success": False,
            "message": f"min_clusters ({min_clusters}) cannot exceed max_clusters ({max_clusters}).",
            "action": "set_scaling_policy",
            "warehouse": warehouse_name,
        }

    ddl = (
        f"ALTER WAREHOUSE {warehouse_name} SET "
        f"MIN_CLUSTER_COUNT = {min_clusters} MAX_CLUSTER_COUNT = {max_clusters}"
    )
    try:
        await run_in_thread(_sync_execute_ddl, source, ddl)
        result = {
            "success": True,
            "message": f"Warehouse {warehouse_name} scaling set to {min_clusters}-{max_clusters} clusters",
            "action": "set_scaling_policy",
            "warehouse": warehouse_name,
        }
    except Exception as e:
        result = {
            "success": False,
            "message": str(e)[:300],
            "action": "set_scaling_policy",
            "warehouse": warehouse_name,
        }

    if user_id:
        await _log_action(
            user_id, "set_scaling_policy", warehouse_name,
            {"min_clusters": min_clusters, "max_clusters": max_clusters},
            result["success"], result["message"],
        )
    return result
