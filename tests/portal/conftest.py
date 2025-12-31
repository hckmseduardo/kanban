"""Shared test fixtures for Kanban Portal API integration tests.

Supports two modes:
1. ASGI mode (default): Tests run in-process against the FastAPI app
2. HTTP mode: Tests call a real running API server

Set TEST_API_URL environment variable to enable HTTP mode.
Example: TEST_API_URL=https://api.example.com/api

Test credentials (for HTTP mode) are loaded from Azure Key Vault:
- test-user-email
- test-user-password
"""

import os
import sys
import uuid
import asyncio
from datetime import datetime
from typing import AsyncGenerator, Optional

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

# Determine test mode
TEST_API_URL = os.environ.get("TEST_API_URL")
USE_REAL_API = bool(TEST_API_URL)

# Add portal backend to path (for ASGI mode and imports)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../portal/backend'))

if not USE_REAL_API:
    # Set test environment for ASGI mode
    os.environ["TESTING"] = "true"
    os.environ["PORTAL_SECRET_KEY"] = "test-secret-key-for-testing-only"
    os.environ["CROSS_DOMAIN_SECRET"] = "test-cross-domain-secret"
    os.environ["REDIS_URL"] = "redis://redis:6379"
    os.environ["DOMAIN"] = "localhost"
    os.environ["PORT"] = "4443"
    os.environ["DATABASE_PATH"] = "/tmp/test_portal.json"


# =============================================================================
# Event Loop Configuration
# =============================================================================

@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for the test session"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# =============================================================================
# Application Fixture (ASGI mode only)
# =============================================================================

@pytest_asyncio.fixture(scope="session")
async def app():
    """Get the FastAPI application and initialize services (ASGI mode only)"""
    if USE_REAL_API:
        yield None
        return

    from app.main import app as fastapi_app
    from app.services.redis_service import redis_service

    # Connect to Redis before tests
    await redis_service.connect()

    yield fastapi_app

    # Disconnect after tests
    await redis_service.disconnect()


# =============================================================================
# Test Client Fixture - Supports both ASGI and HTTP modes
# =============================================================================

@pytest_asyncio.fixture(scope="session")
async def test_client(app) -> AsyncGenerator[AsyncClient, None]:
    """Create async HTTP client for testing.

    In ASGI mode: Uses ASGITransport to call the app in-process
    In HTTP mode: Uses real HTTP client to call the API server
    """
    if USE_REAL_API:
        # HTTP mode: Call real API server
        async with AsyncClient(base_url=TEST_API_URL, timeout=30.0) as client:
            yield client
    else:
        # ASGI mode: Call app in-process
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


# =============================================================================
# Test User Fixture - Mode-dependent
# =============================================================================

@pytest_asyncio.fixture(scope="session")
async def test_user(test_client):
    """Get or create test user.

    In ASGI mode: Creates user directly in database
    In HTTP mode: Authenticates with real Entra using test credentials
    """
    if USE_REAL_API:
        # HTTP mode: Authenticate with real credentials from Key Vault
        from app.config import settings, load_keyvault_secrets, Settings

        # Force load settings with Key Vault secrets
        base_settings = Settings()
        if base_settings.azure_key_vault_url:
            base_settings = load_keyvault_secrets(base_settings)

        email = base_settings.test_user_email
        password = base_settings.test_user_password

        if not email or not password:
            pytest.skip("Test credentials not configured in Key Vault")

        # Authenticate via test-login endpoint
        response = await test_client.post(
            "/auth/test-login",
            params={"email": email, "password": password}
        )

        if response.status_code != 200:
            pytest.fail(f"Test login failed: {response.text}")

        login_data = response.json()
        user_data = login_data["user"]
        user_data["_jwt_token"] = login_data["access_token"]

        yield user_data
    else:
        # ASGI mode: Create user directly in database
        from app.services.database_service import db_service

        user_id = str(uuid.uuid4())
        user_data = {
            "id": user_id,
            "email": f"test-{user_id[:8]}@example.com",
            "display_name": "Integration Test User",
            "avatar_url": None,
            "created_at": datetime.utcnow().isoformat(),
            "last_login_at": datetime.utcnow().isoformat()
        }

        db_service.create_user(user_data)
        yield user_data


# =============================================================================
# JWT Token Fixture
# =============================================================================

@pytest_asyncio.fixture(scope="session")
async def jwt_token(test_user) -> str:
    """Get JWT token for the test user.

    In HTTP mode: Uses token from test-login response
    In ASGI mode: Generates token directly
    """
    if USE_REAL_API:
        # Token was stored in test_user during authentication
        return test_user.get("_jwt_token")
    else:
        from app.auth.jwt import create_access_token
        return create_access_token(data={"sub": test_user["id"], "email": test_user["email"]})


@pytest_asyncio.fixture(scope="session")
async def jwt_headers(jwt_token) -> dict:
    """HTTP headers with JWT authorization"""
    return {"Authorization": f"Bearer {jwt_token}"}


# =============================================================================
# Portal API Token Fixture - Creates real token via API
# =============================================================================

@pytest_asyncio.fixture(scope="session")
async def portal_api_token(test_client, jwt_headers) -> str:
    """Create a Portal API token with full access via the API"""
    response = await test_client.post(
        "/portal/tokens",
        json={"name": "Integration Test Token", "scopes": ["*"]},
        headers=jwt_headers
    )

    assert response.status_code == 200, f"Failed to create portal token: {response.text}"
    token_data = response.json()
    return token_data["token"]


@pytest_asyncio.fixture(scope="session")
async def api_headers(portal_api_token) -> dict:
    """HTTP headers with Portal API token authorization"""
    return {"Authorization": f"Bearer {portal_api_token}"}


# =============================================================================
# Scoped Token Fixtures
# =============================================================================

@pytest_asyncio.fixture(scope="session")
async def read_only_token(test_client, jwt_headers) -> str:
    """Create a Portal API token with read-only scopes"""
    response = await test_client.post(
        "/portal/tokens",
        json={
            "name": "Read Only Token",
            "scopes": ["teams:read", "boards:read", "cards:read", "members:read"]
        },
        headers=jwt_headers
    )
    assert response.status_code == 200
    return response.json()["token"]


@pytest_asyncio.fixture(scope="session")
async def read_only_headers(read_only_token) -> dict:
    """HTTP headers with read-only Portal API token"""
    return {"Authorization": f"Bearer {read_only_token}"}


# =============================================================================
# Test Team Fixture - Creates real team via API with GUID slug
# =============================================================================

@pytest_asyncio.fixture(scope="session")
async def test_team(test_client, api_headers, test_user):
    """Create a test team via the API with GUID slug.

    Uses full UUID in slug to avoid conflicts with real teams.
    Team is deleted after all tests complete.
    """
    # Use full UUID to ensure uniqueness
    team_slug = f"test-{uuid.uuid4().hex}"
    team_name = f"Integration Test Team {team_slug[:12]}"

    # Create team via API
    response = await test_client.post(
        "/teams",
        json={
            "name": team_name,
            "slug": team_slug,
            "description": "Team created for integration testing - will be deleted automatically"
        },
        headers=api_headers
    )

    assert response.status_code == 200, f"Failed to create team: {response.text}"
    team_data = response.json()

    if not USE_REAL_API:
        # ASGI mode: Set team status directly in database
        from app.services.database_service import db_service
        team = db_service.get_team_by_slug(team_slug)
        if team and team.get("status") != "active":
            db_service.update_team(team["id"], {"status": "active"})
        team = db_service.get_team_by_slug(team_slug)
    else:
        # HTTP mode: Get team data from response
        team = team_data.get("team", team_data)
        team["slug"] = team_slug  # Ensure slug is in team data

    yield team

    # Cleanup: Delete team after all tests complete
    try:
        delete_response = await test_client.delete(
            f"/teams/{team_slug}",
            headers=api_headers
        )
        if delete_response.status_code not in [200, 202, 204, 404]:
            print(f"Warning: Team cleanup returned {delete_response.status_code}")
    except Exception as e:
        print(f"Warning: Failed to cleanup test team: {e}")

    # ASGI mode: Also cleanup from database directly as fallback
    if not USE_REAL_API:
        try:
            from app.services.database_service import db_service
            if team:
                db_service.delete_team(team["id"])
        except Exception:
            pass


# =============================================================================
# Additional Helper Fixtures
# =============================================================================

@pytest_asyncio.fixture
async def unique_slug() -> str:
    """Generate a unique slug for tests that need to create resources"""
    return f"test-{uuid.uuid4().hex[:12]}"


@pytest_asyncio.fixture
async def test_webhook_data() -> dict:
    """Standard webhook data for testing"""
    return {
        "name": f"Test Webhook {uuid.uuid4().hex[:8]}",
        "url": "https://httpbin.org/post",
        "events": ["card.created", "card.moved", "card.updated"],
        "secret": "test-webhook-secret",
        "active": True
    }


# =============================================================================
# Pytest Configuration
# =============================================================================

def pytest_configure(config):
    """Configure pytest markers"""
    config.addinivalue_line("markers", "integration: marks tests as integration tests")
    config.addinivalue_line("markers", "slow: marks tests as slow")

    # Log test mode
    if USE_REAL_API:
        print(f"\n*** Running tests against REAL API: {TEST_API_URL} ***\n")
    else:
        print("\n*** Running tests in ASGI mode (in-process) ***\n")
