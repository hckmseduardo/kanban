"""Shared test fixtures for Kanban Portal API integration tests.

These tests run against the actual API with real database and services.
Test team uses full GUID to avoid conflicts with real teams.
"""

import os
import sys
import uuid
import asyncio
from datetime import datetime
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

# Add portal backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../portal/backend'))

# Set test environment
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
# Application Fixture
# =============================================================================

@pytest_asyncio.fixture(scope="session")
async def app():
    """Get the FastAPI application and initialize services"""
    from app.main import app as fastapi_app
    from app.services.redis_service import redis_service

    # Connect to Redis before tests
    await redis_service.connect()

    yield fastapi_app

    # Disconnect after tests
    await redis_service.disconnect()


@pytest_asyncio.fixture(scope="session")
async def test_client(app) -> AsyncGenerator[AsyncClient, None]:
    """Create async HTTP client for testing - session scoped for reuse"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


# =============================================================================
# Test User Fixture - Creates a real user in the database
# =============================================================================

@pytest_asyncio.fixture(scope="session")
async def test_user():
    """Create a test user directly in the database"""
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

    # Create user in database
    db_service.create_user(user_data)

    yield user_data

    # Note: User cleanup not needed - test database is temporary (/tmp/test_portal.json)


# =============================================================================
# JWT Token Fixture
# =============================================================================

@pytest_asyncio.fixture(scope="session")
async def jwt_token(test_user) -> str:
    """Generate a valid JWT token for the test user"""
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
    from app.services.database_service import db_service

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

    # For integration tests, we need to set the team status to active
    team = db_service.get_team_by_slug(team_slug)
    if team and team.get("status") != "active":
        db_service.update_team(team["id"], {"status": "active"})

    # Refresh team data
    team = db_service.get_team_by_slug(team_slug)

    yield team

    # Cleanup: Delete team after all tests complete
    try:
        delete_response = await test_client.delete(
            f"/teams/{team_slug}",
            headers=api_headers
        )
        if delete_response.status_code not in [200, 204, 404]:
            print(f"Warning: Team cleanup returned {delete_response.status_code}")
    except Exception as e:
        print(f"Warning: Failed to cleanup test team: {e}")

    # Also cleanup from database directly as fallback
    try:
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
