"""Shared test fixtures for Kanban Portal API tests"""

import os
import sys
import uuid
import asyncio
from datetime import datetime
from typing import Generator, AsyncGenerator
from unittest.mock import MagicMock, AsyncMock, patch

import pytest
import pytest_asyncio

# Set test environment before importing app
os.environ["TESTING"] = "true"
os.environ["PORTAL_SECRET_KEY"] = "test-secret-key-for-testing-only"
os.environ["CROSS_DOMAIN_SECRET"] = "test-cross-domain-secret"
os.environ["REDIS_URL"] = "redis://localhost:6379"
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
# Mock Database Service
# =============================================================================

@pytest.fixture
def mock_db():
    """Mock database service for unit tests.

    Patches db_service in all modules that import it.
    """
    mock = MagicMock()

    # Setup default return values for common methods
    mock.get_user_by_id.return_value = None
    mock.get_user_by_email.return_value = None
    mock.get_team_by_slug.return_value = None
    mock.get_team_by_id.return_value = None
    mock.get_membership.return_value = None
    mock.get_user_teams.return_value = []
    mock.get_team_members.return_value = []
    mock.get_all_portal_api_tokens.return_value = []
    mock.get_portal_api_token_by_hash.return_value = None
    mock.get_portal_api_token_by_id.return_value = None
    mock.create_portal_api_token.return_value = {}
    mock.create_team.return_value = {}
    mock.create_membership.return_value = True
    mock.delete_portal_api_token.return_value = True
    mock.update_portal_api_token_last_used.return_value = True

    # Patch at all import locations
    with patch('app.auth.jwt.db_service', mock), \
         patch('app.auth.unified.db_service', mock), \
         patch('app.routes.portal_api.db_service', mock), \
         patch('app.routes.teams.db_service', mock), \
         patch('app.routes.users.db_service', mock):
        yield mock


# =============================================================================
# Mock Redis Service
# =============================================================================

@pytest.fixture
def mock_redis():
    """Mock Redis service"""
    mock = MagicMock()
    mock.ping = AsyncMock(return_value=True)
    mock.connect = AsyncMock()
    mock.disconnect = AsyncMock()
    mock.enqueue_task = AsyncMock(return_value=str(uuid.uuid4()))

    with patch('app.services.redis_service.redis_service', mock), \
         patch('app.main.redis_service', mock):
        yield mock


# =============================================================================
# Mock Task Service
# =============================================================================

@pytest.fixture
def mock_task_service():
    """Mock task service"""
    mock = MagicMock()
    mock.create_team_provision_task = AsyncMock(return_value=str(uuid.uuid4()))
    mock.create_team_delete_task = AsyncMock(return_value=str(uuid.uuid4()))
    mock.create_team_restart_task = AsyncMock(return_value=str(uuid.uuid4()))

    with patch('app.routes.teams.task_service', mock):
        yield mock


# =============================================================================
# Mock Team Proxy
# =============================================================================

@pytest.fixture
def mock_team_proxy():
    """Mock team proxy service for team API calls"""
    mock = MagicMock()

    # Default successful responses - use AsyncMock for async methods
    mock.request = AsyncMock(return_value=(200, {"data": []}))
    mock.get = AsyncMock(return_value=(200, {"data": []}))
    mock.post = AsyncMock(return_value=(200, {"id": str(uuid.uuid4())}))
    mock.patch = AsyncMock(return_value=(200, {"updated": True}))
    mock.delete = AsyncMock(return_value=(200, {"deleted": True}))

    with patch('app.routes.team_api.team_proxy', mock):
        yield mock


# =============================================================================
# Application and Client Fixtures
# =============================================================================

@pytest_asyncio.fixture
async def app(mock_redis):
    """Get the FastAPI application with mocked Redis"""
    from app.main import app as fastapi_app
    return fastapi_app


@pytest_asyncio.fixture
async def test_client(app, mock_db) -> AsyncGenerator:
    """Create async HTTP client for testing"""
    from httpx import AsyncClient, ASGITransport

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


# =============================================================================
# User Fixtures
# =============================================================================

@pytest.fixture
def test_user_data() -> dict:
    """Generate test user data"""
    user_id = str(uuid.uuid4())
    return {
        "id": user_id,
        "email": f"testuser-{user_id[:8]}@example.com",
        "display_name": "Test User",
        "avatar_url": None,
        "created_at": datetime.utcnow().isoformat(),
        "last_login_at": datetime.utcnow().isoformat()
    }


@pytest.fixture
def test_user(mock_db, test_user_data) -> dict:
    """Create a test user in the mocked database"""
    mock_db.get_user_by_id.return_value = test_user_data
    mock_db.get_user_by_email.return_value = test_user_data
    return test_user_data


@pytest.fixture
def another_user_data() -> dict:
    """Generate another test user data"""
    user_id = str(uuid.uuid4())
    return {
        "id": user_id,
        "email": f"another-{user_id[:8]}@example.com",
        "display_name": "Another User",
        "avatar_url": None,
        "created_at": datetime.utcnow().isoformat(),
        "last_login_at": datetime.utcnow().isoformat()
    }


# =============================================================================
# JWT Token Fixtures
# =============================================================================

@pytest.fixture
def jwt_token(test_user) -> str:
    """Generate a valid JWT token for the test user"""
    from app.auth.jwt import create_access_token
    return create_access_token(data={"sub": test_user["id"], "email": test_user["email"]})


@pytest.fixture
def jwt_headers(jwt_token) -> dict:
    """HTTP headers with JWT authorization"""
    return {"Authorization": f"Bearer {jwt_token}"}


@pytest.fixture
def another_jwt_token(another_user_data) -> str:
    """Generate a JWT token for another user"""
    from app.auth.jwt import create_access_token
    return create_access_token(data={"sub": another_user_data["id"], "email": another_user_data["email"]})


# =============================================================================
# Portal API Token Fixtures
# =============================================================================

@pytest.fixture
def portal_token_data(test_user) -> dict:
    """Generate portal API token data"""
    token_id = str(uuid.uuid4())
    return {
        "id": token_id,
        "name": "Test Token",
        "token_hash": "fakehash123",
        "scopes": ["*"],
        "created_by": test_user["id"],
        "created_at": datetime.utcnow().isoformat(),
        "expires_at": None,
        "last_used_at": None,
        "is_active": True
    }


# =============================================================================
# Team Fixtures
# =============================================================================

@pytest.fixture
def test_team_data(test_user) -> dict:
    """Generate test team data"""
    team_id = str(uuid.uuid4())
    return {
        "id": team_id,
        "slug": f"test-team-{team_id[:8]}",
        "name": "Test Team",
        "description": "A test team for testing",
        "owner_id": test_user["id"],
        "status": "active",
        "created_at": datetime.utcnow().isoformat(),
        "provisioned_at": datetime.utcnow().isoformat()
    }


# =============================================================================
# Board Fixtures
# =============================================================================

@pytest.fixture
def test_board_data(test_user) -> dict:
    """Generate test board data"""
    board_id = str(uuid.uuid4())
    return {
        "id": board_id,
        "name": "Test Board",
        "description": "A test board",
        "visibility": "team",
        "owner_id": test_user["id"],
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat()
    }


@pytest.fixture
def test_column_data(test_board_data) -> list:
    """Generate test column data"""
    return [
        {
            "id": str(uuid.uuid4()),
            "board_id": test_board_data["id"],
            "name": "To Do",
            "position": 0,
            "wip_limit": None,
            "created_at": datetime.utcnow().isoformat()
        },
        {
            "id": str(uuid.uuid4()),
            "board_id": test_board_data["id"],
            "name": "In Progress",
            "position": 1,
            "wip_limit": 3,
            "created_at": datetime.utcnow().isoformat()
        },
        {
            "id": str(uuid.uuid4()),
            "board_id": test_board_data["id"],
            "name": "Done",
            "position": 2,
            "wip_limit": None,
            "created_at": datetime.utcnow().isoformat()
        }
    ]


@pytest.fixture
def test_card_data(test_column_data, test_user) -> dict:
    """Generate test card data"""
    card_id = str(uuid.uuid4())
    return {
        "id": card_id,
        "column_id": test_column_data[0]["id"],
        "title": "Test Card",
        "description": "A test card description",
        "position": 0,
        "priority": "medium",
        "labels": [],
        "assignee_id": None,
        "due_date": None,
        "archived": False,
        "created_by": test_user["id"],
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat()
    }


# =============================================================================
# Utility Functions
# =============================================================================

def portal_token_headers(token: str = "pk_test_token") -> dict:
    """HTTP headers with Portal API token authorization"""
    return {"Authorization": f"Bearer {token}"}


async def wait_for_condition(condition_fn, timeout=5, interval=0.1):
    """Wait for a condition to be true"""
    elapsed = 0
    while elapsed < timeout:
        if await condition_fn():
            return True
        await asyncio.sleep(interval)
        elapsed += interval
    return False


# =============================================================================
# Pytest Configuration
# =============================================================================

def pytest_configure(config):
    """Configure pytest markers"""
    config.addinivalue_line("markers", "integration: marks tests as integration tests")
    config.addinivalue_line("markers", "slow: marks tests as slow")
    config.addinivalue_line("markers", "unit: marks tests as unit tests")
