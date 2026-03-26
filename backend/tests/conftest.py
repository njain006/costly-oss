"""Shared test fixtures for Costly backend tests."""
import os
import sys
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Set required env vars BEFORE any app.* imports so app.config doesn't raise.
# cryptography is already a transitive dep so Fernet is always available.
# ---------------------------------------------------------------------------
from cryptography.fernet import Fernet

os.environ.setdefault("JWT_SECRET", "test-jwt-secret-key-must-be-32-chars-ok!")
os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")

# ---------------------------------------------------------------------------
# Stub heavy optional packages not installed in the unit-test environment.
# These are only needed at runtime in Docker; tests mock them out.
# ---------------------------------------------------------------------------
for _mod in ("snowflake", "snowflake.connector"):
    sys.modules.setdefault(_mod, MagicMock())

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def sample_dates():
    """Generate a list of date strings for the last 7 days."""
    today = datetime.utcnow().date()
    return [(today - timedelta(days=i)).isoformat() for i in range(6, -1, -1)]


@pytest.fixture
def aws_credentials():
    return {
        "aws_access_key_id": "AKIAIOSFODNN7EXAMPLE",
        "aws_secret_access_key": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        "region": "us-east-1",
    }


@pytest.fixture
def openai_credentials():
    return {"api_key": "sk-test-key-123", "org_id": "org-test-123"}


@pytest.fixture
def anthropic_credentials():
    return {"api_key": "sk-ant-admin-test-key-123"}


@pytest.fixture
def dbt_cloud_credentials():
    return {"api_token": "dbtc_test_token", "account_id": "12345"}


@pytest.fixture
def fivetran_credentials():
    return {"api_key": "fivetran_key", "api_secret": "fivetran_secret"}


@pytest.fixture
def bigquery_credentials():
    return {
        "project_id": "test-project",
        "service_account_json": '{"type":"service_account","client_email":"test@test.iam.gserviceaccount.com","private_key":"fake"}',
    }


@pytest.fixture
def databricks_credentials():
    return {
        "account_id": "test-account",
        "access_token": "dapi_test_token",
        "workspace_url": "https://test.cloud.databricks.com",
    }


@pytest.fixture
def github_credentials():
    return {"token": "ghp_test_token", "org": "test-org"}


@pytest.fixture
def gitlab_credentials():
    return {"token": "glpat-test-token", "instance_url": "https://gitlab.com"}


@pytest.fixture
def airbyte_credentials():
    return {"api_token": "airbyte_test_token"}


@pytest.fixture
def monte_carlo_credentials():
    return {"api_key_id": "mc_key_id", "api_token": "mc_token"}


@pytest.fixture
def looker_credentials():
    return {
        "client_id": "looker_client",
        "client_secret": "looker_secret",
        "instance_url": "https://test.looker.com",
    }


@pytest.fixture
def tableau_credentials():
    return {
        "server_url": "https://test.tableau.com",
        "token_name": "test_token",
        "token_secret": "test_secret",
        "site_id": "test_site",
    }


@pytest.fixture
def omni_credentials():
    return {"api_key": "omni_key", "instance_url": "https://test.omni.co"}


@pytest.fixture
def gemini_credentials():
    return {"api_key": "gemini_test_key"}



# ---------------------------------------------------------------------------
# API test infrastructure
# ---------------------------------------------------------------------------

def _make_mock_db():
    """Build a MagicMock that mimics the Motor async db collections we use."""
    db = MagicMock(name="mock_db")

    # users collection
    db.users.find_one = AsyncMock(return_value=None)
    db.users.insert_one = AsyncMock(return_value=MagicMock(inserted_id="abc"))
    db.users.update_one = AsyncMock(return_value=MagicMock(modified_count=1))

    # snowflake_connections collection
    _empty_cursor = MagicMock()
    _empty_cursor.to_list = AsyncMock(return_value=[])
    db.snowflake_connections.find = MagicMock(return_value=_empty_cursor)
    db.snowflake_connections.find_one = AsyncMock(return_value=None)
    db.snowflake_connections.insert_one = AsyncMock(return_value=MagicMock(inserted_id="abc"))
    db.snowflake_connections.delete_one = AsyncMock(return_value=MagicMock(deleted_count=1))
    db.snowflake_connections.update_many = AsyncMock(return_value=MagicMock(modified_count=0))
    db.snowflake_connections.update_one = AsyncMock(return_value=MagicMock(modified_count=1))

    # platform_connections collection
    db.platform_connections.find_one = AsyncMock(return_value=None)

    # password_reset_tokens collection
    db.password_reset_tokens.find_one = AsyncMock(return_value=None)
    db.password_reset_tokens.insert_one = AsyncMock(return_value=MagicMock(inserted_id="abc"))
    db.password_reset_tokens.update_one = AsyncMock(return_value=MagicMock(modified_count=1))

    return db


@pytest.fixture
def mock_db():
    """Patch db in every router/dep that directly imports it from app.database."""
    # Pre-import submodules so mock.patch can resolve them via getattr (required in Python 3.12+)
    import app.routers.auth  # noqa: F401
    import app.routers.connections  # noqa: F401
    import app.deps  # noqa: F401

    db = _make_mock_db()
    targets = [
        "app.routers.auth.db",
        "app.routers.connections.db",
        "app.deps.db",
    ]
    patches = [patch(t, db) for t in targets]
    for p in patches:
        p.start()
    yield db
    for p in patches:
        p.stop()


@pytest.fixture
async def api_client(mock_db):
    """
    Async HTTP test client for the FastAPI app.

    Startup tasks (create_indexes, APScheduler) are mocked out so tests
    don't require live MongoDB or Redis.
    """
    from httpx import AsyncClient, ASGITransport

    with patch("app.main.create_indexes", AsyncMock()), \
         patch("app.main._scheduler") as mock_sched:
        mock_sched.add_job = MagicMock()
        mock_sched.start = MagicMock()
        mock_sched.shutdown = MagicMock()

        from app.main import app
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client


@pytest.fixture
def auth_headers():
    """Valid Bearer token headers for a test user."""
    from datetime import timedelta
    from jose import jwt
    from app.config import settings

    token = jwt.encode(
        {
            "user_id": "user_testuser123456",
            "type": "access",
            "exp": datetime.utcnow() + timedelta(hours=1),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    return {"Authorization": f"Bearer {token}"}
