"""
API route tests for the Costly FastAPI backend.

These are unit-level tests: MongoDB is replaced with AsyncMock fixtures,
startup tasks (create_indexes, APScheduler) are patched out, and no live
Snowflake / Redis connection is required.

Fixtures are defined in conftest.py:
  - mock_db       : patches db in all routers + deps
  - api_client    : httpx.AsyncClient backed by the ASGI app
  - auth_headers  : valid Bearer token for user_testuser123456
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timedelta

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TEST_USER_ID = "user_testuser123456"
TEST_EMAIL = "test@example.com"
TEST_NAME = "Test User"


def _hashed_password(plain: str) -> str:
    """Return a bcrypt hash for the given plaintext password."""
    from passlib.context import CryptContext
    return CryptContext(schemes=["bcrypt"], deprecated="auto").hash(plain)


def _make_user_doc(password: str = "Passw0rd!", disabled: bool = False) -> dict:
    return {
        "user_id": TEST_USER_ID,
        "email": TEST_EMAIL,
        "name": TEST_NAME,
        "password_hash": _hashed_password(password),
        "is_disabled": disabled,
        "role": None,
    }


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

class TestHealthCheck:
    async def test_returns_ok(self, api_client):
        r = await api_client.get("/api/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert "version" in body


# ---------------------------------------------------------------------------
# Auth — /api/auth/*
# ---------------------------------------------------------------------------

class TestAuthRegister:
    async def test_success(self, api_client, mock_db):
        """New email registers and returns tokens + user info."""
        mock_db.users.find_one = AsyncMock(return_value=None)

        r = await api_client.post("/api/auth/register", json={
            "email": "new@example.com",
            "password": "Passw0rd!",
            "name": "New User",
        })

        assert r.status_code == 200
        body = r.json()
        assert "token" in body
        assert "refresh_token" in body
        assert body["email"] == "new@example.com"
        assert body["name"] == "New User"
        assert body["user_id"].startswith("user_")

    async def test_duplicate_email_returns_400(self, api_client, mock_db):
        """Registering with an existing email returns 400."""
        mock_db.users.find_one = AsyncMock(return_value={"email": TEST_EMAIL})

        r = await api_client.post("/api/auth/register", json={
            "email": TEST_EMAIL,
            "password": "Passw0rd!",
            "name": TEST_NAME,
        })

        assert r.status_code == 400
        assert "already registered" in r.json()["detail"]

    async def test_missing_fields_returns_422(self, api_client):
        """Missing required fields returns 422 Unprocessable Entity."""
        r = await api_client.post("/api/auth/register", json={"email": "a@b.com"})
        assert r.status_code == 422


class TestAuthLogin:
    async def test_success(self, api_client, mock_db):
        """Valid credentials return tokens and user info."""
        mock_db.users.find_one = AsyncMock(return_value=_make_user_doc("Passw0rd!"))

        r = await api_client.post("/api/auth/login", json={
            "email": TEST_EMAIL,
            "password": "Passw0rd!",
        })

        assert r.status_code == 200
        body = r.json()
        assert "token" in body
        assert "refresh_token" in body
        assert body["user_id"] == TEST_USER_ID

    async def test_wrong_password_returns_401(self, api_client, mock_db):
        """Wrong password returns 401."""
        mock_db.users.find_one = AsyncMock(return_value=_make_user_doc("Passw0rd!"))

        r = await api_client.post("/api/auth/login", json={
            "email": TEST_EMAIL,
            "password": "wrong",
        })

        assert r.status_code == 401

    async def test_unknown_email_returns_401(self, api_client, mock_db):
        """Non-existent email returns 401."""
        mock_db.users.find_one = AsyncMock(return_value=None)

        r = await api_client.post("/api/auth/login", json={
            "email": "nobody@example.com",
            "password": "Passw0rd!",
        })

        assert r.status_code == 401

    async def test_disabled_account_returns_403(self, api_client, mock_db):
        """Disabled accounts are rejected with 403."""
        mock_db.users.find_one = AsyncMock(return_value=_make_user_doc("Passw0rd!", disabled=True))

        r = await api_client.post("/api/auth/login", json={
            "email": TEST_EMAIL,
            "password": "Passw0rd!",
        })

        assert r.status_code == 403


class TestAuthRefresh:
    def _refresh_token(self) -> str:
        from jose import jwt
        from app.config import settings
        return jwt.encode(
            {
                "user_id": TEST_USER_ID,
                "type": "refresh",
                "exp": datetime.utcnow() + timedelta(days=7),
            },
            settings.jwt_secret,
            algorithm=settings.jwt_algorithm,
        )

    async def test_valid_refresh_token_returns_new_tokens(self, api_client, mock_db):
        mock_db.users.find_one = AsyncMock(return_value=_make_user_doc())

        r = await api_client.post("/api/auth/refresh", json={
            "refresh_token": self._refresh_token(),
        })

        assert r.status_code == 200
        body = r.json()
        assert "token" in body
        assert "refresh_token" in body

    async def test_access_token_as_refresh_returns_401(self, api_client):
        """Submitting an access token where a refresh token is expected fails."""
        from jose import jwt
        from app.config import settings
        access = jwt.encode(
            {"user_id": TEST_USER_ID, "type": "access", "exp": datetime.utcnow() + timedelta(hours=1)},
            settings.jwt_secret,
            algorithm=settings.jwt_algorithm,
        )
        r = await api_client.post("/api/auth/refresh", json={"refresh_token": access})
        assert r.status_code == 401

    async def test_expired_token_returns_401(self, api_client):
        """Expired refresh tokens are rejected."""
        from jose import jwt
        from app.config import settings
        expired = jwt.encode(
            {"user_id": TEST_USER_ID, "type": "refresh", "exp": datetime.utcnow() - timedelta(seconds=1)},
            settings.jwt_secret,
            algorithm=settings.jwt_algorithm,
        )
        r = await api_client.post("/api/auth/refresh", json={"refresh_token": expired})
        assert r.status_code == 401

    async def test_garbage_token_returns_401(self, api_client):
        r = await api_client.post("/api/auth/refresh", json={"refresh_token": "not.a.token"})
        assert r.status_code == 401


class TestAuthChangePassword:
    async def test_success(self, api_client, mock_db, auth_headers):
        mock_db.users.find_one = AsyncMock(return_value=_make_user_doc("OldPass1!"))

        r = await api_client.post("/api/auth/change-password", headers=auth_headers, json={
            "current_password": "OldPass1!",
            "new_password": "NewPass2@",
        })

        assert r.status_code == 200
        assert "successfully" in r.json()["message"]

    async def test_wrong_current_password_returns_400(self, api_client, mock_db, auth_headers):
        mock_db.users.find_one = AsyncMock(return_value=_make_user_doc("OldPass1!"))

        r = await api_client.post("/api/auth/change-password", headers=auth_headers, json={
            "current_password": "wrong",
            "new_password": "NewPass2@",
        })

        assert r.status_code == 400

    async def test_new_password_too_short_returns_400(self, api_client, mock_db, auth_headers):
        mock_db.users.find_one = AsyncMock(return_value=_make_user_doc("OldPass1!"))

        r = await api_client.post("/api/auth/change-password", headers=auth_headers, json={
            "current_password": "OldPass1!",
            "new_password": "short",
        })

        assert r.status_code == 400

    async def test_requires_auth(self, api_client):
        r = await api_client.post("/api/auth/change-password", json={
            "current_password": "a",
            "new_password": "b",
        })
        assert r.status_code in (401, 422)


class TestAuthForgotPassword:
    async def test_always_returns_200(self, api_client, mock_db):
        """Response is identical whether email exists or not (prevents enumeration)."""
        mock_db.users.find_one = AsyncMock(return_value=None)

        r = await api_client.post("/api/auth/forgot-password", json={"email": "any@example.com"})
        assert r.status_code == 200
        assert "reset link" in r.json()["message"]


# ---------------------------------------------------------------------------
# Auth guard
# ---------------------------------------------------------------------------

class TestAuthGuard:
    async def test_missing_token_returns_401_or_422(self, api_client):
        """Protected endpoints reject requests with no Authorization header."""
        r = await api_client.get("/api/connections")
        assert r.status_code in (401, 422)

    async def test_invalid_token_returns_401(self, api_client):
        r = await api_client.get("/api/connections", headers={"Authorization": "Bearer garbage"})
        assert r.status_code == 401

    async def test_refresh_token_not_accepted_for_api_access(self, api_client):
        from jose import jwt
        from app.config import settings
        refresh = jwt.encode(
            {"user_id": TEST_USER_ID, "type": "refresh", "exp": datetime.utcnow() + timedelta(days=7)},
            settings.jwt_secret,
            algorithm=settings.jwt_algorithm,
        )
        r = await api_client.get("/api/connections", headers={"Authorization": f"Bearer {refresh}"})
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# Connections — /api/connections/*
# ---------------------------------------------------------------------------

class TestConnectionsList:
    async def test_empty_returns_list(self, api_client, mock_db, auth_headers):
        r = await api_client.get("/api/connections", headers=auth_headers)
        assert r.status_code == 200
        assert r.json() == []

    async def test_returns_existing_connections(self, api_client, mock_db, auth_headers):
        conn_doc = {
            "connection_id": "conn_abc123456789",
            "connection_name": "Prod",
            "account": "myaccount",
            "username": "svc_user",
            "auth_type": "keypair",
            "warehouse": "COMPUTE_WH",
            "database": "SNOWFLAKE",
            "schema_name": "ACCOUNT_USAGE",
            "role": "ACCOUNTADMIN",
            "is_active": True,
            "test_status": None,
            "last_tested_at": None,
            "created_at": "2025-01-01T00:00:00",
        }
        cursor = MagicMock()
        cursor.to_list = AsyncMock(return_value=[conn_doc])
        mock_db.snowflake_connections.find = MagicMock(return_value=cursor)

        r = await api_client.get("/api/connections", headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert len(body) == 1
        assert body[0]["connection_id"] == "conn_abc123456789"


class TestConnectionCreate:
    _KEYPAIR_PAYLOAD = {
        "connection_name": "Test Conn",
        "account": "myaccount",
        "username": "svc_user",
        "auth_type": "keypair",
        "private_key": "-----BEGIN PRIVATE KEY-----\nfake_key_data\n-----END PRIVATE KEY-----",
        "warehouse": "COMPUTE_WH",
        "database": "SNOWFLAKE",
        "schema_name": "ACCOUNT_USAGE",
        "role": "ACCOUNTADMIN",
    }

    async def test_keypair_creates_connection(self, api_client, mock_db, auth_headers):
        r = await api_client.post("/api/connections", headers=auth_headers, json=self._KEYPAIR_PAYLOAD)

        assert r.status_code == 200
        body = r.json()
        assert body["connection_name"] == "Test Conn"
        assert body["account"] == "myaccount"
        assert body["auth_type"] == "keypair"
        assert body["connection_id"].startswith("conn_")

    async def test_password_auth_type_returns_400(self, api_client, mock_db, auth_headers):
        payload = {**self._KEYPAIR_PAYLOAD, "auth_type": "password", "password": "secret"}
        r = await api_client.post("/api/connections", headers=auth_headers, json=payload)
        assert r.status_code == 400

    async def test_keypair_without_private_key_returns_400(self, api_client, mock_db, auth_headers):
        payload = {k: v for k, v in self._KEYPAIR_PAYLOAD.items() if k != "private_key"}
        r = await api_client.post("/api/connections", headers=auth_headers, json=payload)
        assert r.status_code == 400

    async def test_requires_auth(self, api_client):
        r = await api_client.post("/api/connections", json=self._KEYPAIR_PAYLOAD)
        assert r.status_code in (401, 422)


class TestConnectionDelete:
    async def test_success(self, api_client, mock_db, auth_headers):
        mock_db.snowflake_connections.delete_one = AsyncMock(
            return_value=MagicMock(deleted_count=1)
        )
        r = await api_client.delete("/api/connections/conn_abc123", headers=auth_headers)
        assert r.status_code == 200
        assert "deleted" in r.json()["message"]

    async def test_not_found_returns_404(self, api_client, mock_db, auth_headers):
        mock_db.snowflake_connections.delete_one = AsyncMock(
            return_value=MagicMock(deleted_count=0)
        )
        r = await api_client.delete("/api/connections/nonexistent", headers=auth_headers)
        assert r.status_code == 404


class TestConnectionStatus:
    async def test_no_connection(self, api_client, mock_db, auth_headers):
        """No Snowflake connection in either system → has_connection: false."""
        mock_db.snowflake_connections.find_one = AsyncMock(return_value=None)
        mock_db.platform_connections.find_one = AsyncMock(return_value=None)

        r = await api_client.get("/api/connections/status", headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["has_connection"] is False
        assert body["active_connection"] is None

    async def test_with_legacy_connection(self, api_client, mock_db, auth_headers):
        """Legacy snowflake_connections row is detected."""
        mock_db.snowflake_connections.find_one = AsyncMock(return_value={
            "connection_id": "conn_legacy123",
            "user_id": TEST_USER_ID,
            "is_active": True,
        })

        r = await api_client.get("/api/connections/status", headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["has_connection"] is True
        assert body["active_connection"] == "conn_legacy123"


# ---------------------------------------------------------------------------
# Dashboard — /api/dashboard
# ---------------------------------------------------------------------------

class TestDashboard:
    async def test_no_snowflake_connection_returns_zero_demo(self, api_client, mock_db, auth_headers):
        """
        When the user has no Snowflake connection (neither unified nor legacy),
        the dashboard returns a zeroed-out response with demo: True — no
        Snowflake query is attempted.
        """
        mock_db.platform_connections.find_one = AsyncMock(return_value=None)
        mock_db.snowflake_connections.find_one = AsyncMock(return_value=None)

        r = await api_client.get("/api/dashboard", headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["total_cost"] == 0
        assert body["demo"] is True

    async def test_days_param_is_respected(self, api_client, mock_db, auth_headers):
        """The days query param is forwarded (returned in no-source response)."""
        mock_db.platform_connections.find_one = AsyncMock(return_value=None)
        mock_db.snowflake_connections.find_one = AsyncMock(return_value=None)

        r = await api_client.get("/api/dashboard?days=7", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["days"] == 7

    async def test_invalid_days_param_returns_422(self, api_client, auth_headers):
        r = await api_client.get("/api/dashboard?days=0", headers=auth_headers)
        assert r.status_code == 422

    async def test_requires_auth(self, api_client):
        r = await api_client.get("/api/dashboard")
        assert r.status_code in (401, 422)
