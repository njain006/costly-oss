from fastapi import Depends, HTTPException, Header
from jose import JWTError, jwt

from app.config import settings
from app.database import db


async def get_current_user(authorization: str = Header(...)):
    try:
        if not authorization.startswith("Bearer "):
            raise HTTPException(401, "Invalid auth header format")
        token = authorization[7:]
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        if payload.get("type") == "refresh":
            raise HTTPException(401, "Cannot use refresh token for API access")
        return payload["user_id"]
    except JWTError:
        raise HTTPException(401, "Invalid or expired token")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(401, "Authentication failed")


async def get_current_admin_user(user_id: str = Depends(get_current_user)):
    user = await db.users.find_one({"user_id": user_id})
    if not user or user.get("role") != "admin":
        raise HTTPException(403, "Admin access required")
    return user_id


async def get_data_source(user_id: str, connection_id: str | None = None):
    """Find a Snowflake connection — checks unified platform_connections first,
    then falls back to legacy snowflake_connections for backward compat.

    With `connection_id`, return that account (404 if it is not the user's).
    Without it, the most recently synced account."""
    if connection_id:
        from bson import ObjectId
        try:
            oid = ObjectId(connection_id)
        except Exception:
            raise HTTPException(404, "Snowflake connection not found")
        pc = await db.platform_connections.find_one({"_id": oid, "user_id": user_id, "platform": "snowflake"})
        if not pc:
            raise HTTPException(404, "Snowflake connection not found")
        return _platform_conn_to_sf_doc(pc)

    # Check unified system first
    pc = await db.platform_connections.find_one(
        {"user_id": user_id, "platform": "snowflake"},
        sort=[("last_synced", -1), ("created_at", -1)],
    )
    if pc:
        return _platform_conn_to_sf_doc(pc)

    # Legacy fallback
    return await db.snowflake_connections.find_one({"user_id": user_id, "is_active": True})


def cache_scope(user_id: str, source: dict | None) -> str:
    """Cache-key prefix for one user's one Snowflake account."""
    cid = (source or {}).get("connection_id") or str((source or {}).get("_id") or "default")
    return f"{user_id}:{cid}"


async def all_snowflake_sources() -> list[dict]:
    """Every Snowflake account to run background jobs against: all
    platform_connections, plus legacy snowflake_connections for users who
    have no platform connection yet. Each doc carries user_id and
    connection_id."""
    out = []
    users_with_platform = set()
    async for pc in db.platform_connections.find({"platform": "snowflake"}):
        out.append(_platform_conn_to_sf_doc(pc))
        users_with_platform.add(pc.get("user_id"))
    async for c in db.snowflake_connections.find({"is_active": True}):
        if c.get("user_id") not in users_with_platform:
            out.append({**c, "connection_id": str(c.get("_id", ""))})
    return out


def _platform_conn_to_sf_doc(pc: dict) -> dict:
    """Adapt a platform_connections document to the conn_doc shape
    that build_sf_connection() and all snowflake.py functions expect."""
    from app.services.encryption import decrypt_value, encrypt_value

    creds = pc.get("credentials", {})

    def _dec(value: str) -> str:
        """Fields in `credentials` may be encrypted (e.g. user) or stored plain
        (e.g. account). Decrypt when we can, otherwise use the value as-is."""
        if not value:
            return value
        try:
            return decrypt_value(value)
        except Exception:
            return value

    # Decrypt the private key, then re-encrypt it as private_key_encrypted
    # (build_sf_connection expects to decrypt it itself)
    private_key_raw = creds.get("private_key", "")
    try:
        # It may already be encrypted from add_platform_connection
        decrypt_value(private_key_raw)
        private_key_encrypted = private_key_raw  # Already encrypted
    except Exception:
        # Not encrypted, encrypt it for build_sf_connection
        private_key_encrypted = encrypt_value(private_key_raw)

    return {
        "account": _dec(creds.get("account", "")),
        "username": _dec(creds.get("user", "")),
        "auth_type": "keypair",
        "private_key_encrypted": private_key_encrypted,
        "warehouse": _dec(creds.get("warehouse", "")) or "COMPUTE_WH",
        "database": _dec(creds.get("database", "")) or "SNOWFLAKE",
        "schema_name": _dec(creds.get("schema_name", "")) or "ACCOUNT_USAGE",
        "role": _dec(creds.get("role", "")),
        "is_active": True,
        "connection_id": str(pc.get("_id", "")),
        "connection_name": pc.get("name", "Snowflake"),
        "user_id": pc.get("user_id", ""),
        "pricing_overrides": creds.get("pricing_overrides") or pc.get("pricing_overrides") or {},
        "user_types": pc.get("user_types") or {},
    }
