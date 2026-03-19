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


async def get_data_source(user_id: str):
    """Find a Snowflake connection — checks unified platform_connections first,
    then falls back to legacy snowflake_connections for backward compat."""

    # Check unified system first
    pc = await db.platform_connections.find_one({"user_id": user_id, "platform": "snowflake"})
    if pc:
        return _platform_conn_to_sf_doc(pc)

    # Legacy fallback
    return await db.snowflake_connections.find_one({"user_id": user_id, "is_active": True})


def _platform_conn_to_sf_doc(pc: dict) -> dict:
    """Adapt a platform_connections document to the conn_doc shape
    that build_sf_connection() and all snowflake.py functions expect."""
    from app.services.encryption import decrypt_value, encrypt_value

    creds = pc.get("credentials", {})

    # Decrypt the private key, then re-encrypt it as private_key_encrypted
    # (build_sf_connection expects to decrypt it itself)
    private_key_raw = creds.get("private_key", "")
    try:
        # It may already be encrypted from add_platform_connection
        private_key_decrypted = decrypt_value(private_key_raw)
        private_key_encrypted = private_key_raw  # Already encrypted
    except Exception:
        # Not encrypted, encrypt it for build_sf_connection
        private_key_encrypted = encrypt_value(private_key_raw)

    return {
        "account": creds.get("account", ""),
        "username": creds.get("user", ""),
        "auth_type": "keypair",
        "private_key_encrypted": private_key_encrypted,
        "warehouse": creds.get("warehouse", "COMPUTE_WH"),
        "database": creds.get("database", "SNOWFLAKE"),
        "schema_name": creds.get("schema_name", "ACCOUNT_USAGE"),
        "role": creds.get("role", "ACCOUNTADMIN"),
        "is_active": True,
        "connection_id": str(pc.get("_id", "")),
        "connection_name": pc.get("name", "Snowflake"),
        "user_id": pc.get("user_id", ""),
    }
