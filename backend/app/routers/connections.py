import uuid
import time
from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends

from app.database import db
from app.deps import get_current_user
from app.models.connection import SnowflakeConnectionCreate
from app.services.encryption import encrypt_value
from app.services.snowflake import build_sf_connection, conn_to_response
from app.services.cache import cache
from app.utils.helpers import run_in_thread

router = APIRouter(prefix="/api/connections", tags=["connections"])


@router.get("/status")
async def connection_status(user_id: str = Depends(get_current_user)):
    # Check both unified and legacy systems
    conn = await db.snowflake_connections.find_one({"user_id": user_id, "is_active": True})
    pc = await db.platform_connections.find_one({"user_id": user_id, "platform": "snowflake"})
    has = conn is not None or pc is not None
    conn_id = conn["connection_id"] if conn else (str(pc["_id"]) if pc else None)
    return {
        "has_connection": has,
        "active_connection": conn_id,
    }


@router.get("")
async def list_connections(user_id: str = Depends(get_current_user)):
    conns = await db.snowflake_connections.find({"user_id": user_id}).to_list(100)
    return [conn_to_response(c) for c in conns]


@router.post("")
async def create_connection(conn: SnowflakeConnectionCreate, user_id: str = Depends(get_current_user)):
    if conn.auth_type != "keypair":
        raise HTTPException(400, "Only key-pair authentication is supported")
    conn_id = f"conn_{uuid.uuid4().hex[:12]}"
    doc = {
        "connection_id": conn_id,
        "user_id": user_id,
        "connection_name": conn.connection_name.strip(),
        "account": conn.account.strip().lower().replace(".snowflakecomputing.com", ""),
        "username": conn.username.strip(),
        "auth_type": "keypair",
        "warehouse": conn.warehouse.strip(),
        "database": conn.database.strip(),
        "schema_name": conn.schema_name.strip(),
        "role": conn.role.strip(),
        "is_active": True,
        "test_status": None,
        "last_tested_at": None,
        "created_at": datetime.utcnow().isoformat(),
    }
    if conn.auth_type == "keypair":
        if not conn.private_key:
            raise HTTPException(400, "Private key is required for keypair auth")
        doc["private_key_encrypted"] = encrypt_value(conn.private_key)
        if conn.private_key_passphrase:
            doc["private_key_passphrase_encrypted"] = encrypt_value(conn.private_key_passphrase)
    await db.snowflake_connections.update_many({"user_id": user_id}, {"$set": {"is_active": False}})
    await db.snowflake_connections.insert_one(doc)
    cache.clear_prefix(f"{user_id}:")
    return conn_to_response(doc)


@router.delete("/{conn_id}")
async def delete_connection(conn_id: str, user_id: str = Depends(get_current_user)):
    result = await db.snowflake_connections.delete_one({"connection_id": conn_id, "user_id": user_id})
    if result.deleted_count == 0:
        raise HTTPException(404, "Connection not found")
    cache.clear_prefix(f"{user_id}:")
    return {"message": "Connection deleted"}


@router.post("/{conn_id}/test")
async def test_connection(conn_id: str, user_id: str = Depends(get_current_user)):
    conn_doc = await db.snowflake_connections.find_one({"connection_id": conn_id, "user_id": user_id})
    if not conn_doc:
        raise HTTPException(404, "Connection not found")
    start = time.time()

    def _do_test(doc):
        sf = build_sf_connection(doc)
        cur = sf.cursor()
        cur.execute("SELECT CURRENT_TIMESTAMP()")
        cur.fetchone()
        sf.close()

    try:
        await run_in_thread(_do_test, conn_doc)
        latency_ms = int((time.time() - start) * 1000)
        await db.snowflake_connections.update_one(
            {"connection_id": conn_id},
            {"$set": {"test_status": "success", "last_tested_at": datetime.utcnow().isoformat()}},
        )
        return {"success": True, "message": "Connection successful", "latency_ms": latency_ms}
    except Exception as e:
        latency_ms = int((time.time() - start) * 1000)
        await db.snowflake_connections.update_one(
            {"connection_id": conn_id},
            {"$set": {"test_status": "failed", "last_tested_at": datetime.utcnow().isoformat()}},
        )
        return {"success": False, "message": str(e), "latency_ms": latency_ms}


@router.post("/{conn_id}/activate")
async def activate_connection(conn_id: str, user_id: str = Depends(get_current_user)):
    await db.snowflake_connections.update_many({"user_id": user_id}, {"$set": {"is_active": False}})
    result = await db.snowflake_connections.update_one(
        {"connection_id": conn_id, "user_id": user_id},
        {"$set": {"is_active": True}},
    )
    if result.modified_count == 0:
        raise HTTPException(404, "Connection not found")
    cache.clear_prefix(f"{user_id}:")
    return {"message": "Connection activated"}
