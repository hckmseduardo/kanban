"""Kanban API Integration Tests

These tests run against the actual API and test the complete flow:
1. Create Portal API token
2. Create team
3. Create boards, columns, cards
4. Test card operations (move, archive, restore)
5. Test team member management
6. Cleanup

All tests use a real test user and Portal API token created in fixtures.
"""

import pytest
import uuid


# =============================================================================
# Portal Token Tests
# =============================================================================

class TestPortalTokens:
    """Test Portal API token management"""

    @pytest.mark.asyncio
    async def test_create_token(self, test_client, jwt_headers):
        """Create a new Portal API token"""
        response = await test_client.post(
            "/portal/tokens",
            json={"name": f"Test Token {uuid.uuid4().hex[:6]}", "scopes": ["teams:read"]},
            headers=jwt_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["token"].startswith("pk_")
        assert data["scopes"] == ["teams:read"]
        assert data["is_active"] is True

    @pytest.mark.asyncio
    async def test_list_tokens(self, test_client, jwt_headers):
        """List user's Portal API tokens"""
        response = await test_client.get("/portal/tokens", headers=jwt_headers)

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        # Should have at least the token created in fixture
        assert len(data) >= 1

    @pytest.mark.asyncio
    async def test_validate_token(self, test_client, portal_api_token):
        """Validate a Portal API token"""
        response = await test_client.post(
            "/portal/validate-token",
            params={"token": portal_api_token}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is True
        assert data["scopes"] == ["*"]

    @pytest.mark.asyncio
    async def test_validate_invalid_token(self, test_client):
        """Validate an invalid token returns valid=false"""
        response = await test_client.post(
            "/portal/validate-token",
            params={"token": "pk_invalid_token_12345"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is False


# =============================================================================
# Team Management Tests
# =============================================================================

class TestTeamManagement:
    """Test team CRUD operations"""

    @pytest.mark.asyncio
    async def test_list_teams(self, test_client, api_headers, test_team):
        """List user's teams"""
        response = await test_client.get("/teams", headers=api_headers)

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        # Should include the test team
        team_slugs = [t["slug"] for t in data]
        assert test_team["slug"] in team_slugs

    @pytest.mark.asyncio
    async def test_get_team(self, test_client, api_headers, test_team):
        """Get team by slug"""
        response = await test_client.get(
            f"/teams/{test_team['slug']}",
            headers=api_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["slug"] == test_team["slug"]
        assert data["name"] == "Integration Test Team"

    @pytest.mark.asyncio
    async def test_get_team_status(self, test_client, api_headers, test_team):
        """Get team provisioning status"""
        response = await test_client.get(
            f"/teams/{test_team['slug']}/status",
            headers=api_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert "status" in data

    @pytest.mark.asyncio
    async def test_update_team(self, test_client, api_headers, test_team):
        """Update team details"""
        new_description = f"Updated description {uuid.uuid4().hex[:6]}"

        response = await test_client.put(
            f"/teams/{test_team['slug']}",
            json={"description": new_description},
            headers=api_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["description"] == new_description

    @pytest.mark.asyncio
    async def test_create_duplicate_team_fails(self, test_client, api_headers, test_team):
        """Creating team with existing slug fails"""
        response = await test_client.post(
            "/teams",
            json={
                "name": "Duplicate Team",
                "slug": test_team["slug"],  # Same slug as existing team
                "description": "Should fail"
            },
            headers=api_headers
        )

        assert response.status_code == 409  # Conflict


# =============================================================================
# Team Members Tests
# =============================================================================

class TestTeamMembers:
    """Test team member management"""

    @pytest.mark.asyncio
    async def test_list_members(self, test_client, api_headers, test_team):
        """List team members"""
        response = await test_client.get(
            f"/teams/{test_team['slug']}/members",
            headers=api_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        # Should have at least the owner
        assert len(data) >= 1


# =============================================================================
# Complete Workflow Test
# =============================================================================

class TestCompleteWorkflow:
    """End-to-end workflow test using Portal API token"""

    @pytest.mark.asyncio
    async def test_complete_kanban_flow(self, test_client, api_headers, test_team):
        """
        Complete workflow test:
        1. List teams and verify test team exists
        2. Get team details
        3. List team members
        4. Update team description
        5. Verify update persisted
        """
        team_slug = test_team["slug"]

        # Step 1: List teams
        response = await test_client.get("/teams", headers=api_headers)
        assert response.status_code == 200
        teams = response.json()
        assert any(t["slug"] == team_slug for t in teams), "Test team not found in list"

        # Step 2: Get team details
        response = await test_client.get(f"/teams/{team_slug}", headers=api_headers)
        assert response.status_code == 200
        team = response.json()
        assert team["slug"] == team_slug

        # Step 3: List members
        response = await test_client.get(f"/teams/{team_slug}/members", headers=api_headers)
        assert response.status_code == 200
        members = response.json()
        assert len(members) >= 1

        # Step 4: Update team
        new_desc = f"Workflow test update {uuid.uuid4().hex[:6]}"
        response = await test_client.put(
            f"/teams/{team_slug}",
            json={"description": new_desc},
            headers=api_headers
        )
        assert response.status_code == 200

        # Step 5: Verify update
        response = await test_client.get(f"/teams/{team_slug}", headers=api_headers)
        assert response.status_code == 200
        updated_team = response.json()
        assert updated_team["description"] == new_desc


# =============================================================================
# Authentication Tests
# =============================================================================

class TestAuthentication:
    """Test authentication and authorization"""

    @pytest.mark.asyncio
    async def test_no_auth_returns_error(self, test_client):
        """Request without auth header returns 401/403"""
        response = await test_client.get("/teams")

        # FastAPI HTTPBearer returns 403 when no credentials
        assert response.status_code in [401, 403]

    @pytest.mark.asyncio
    async def test_invalid_token_returns_401(self, test_client):
        """Request with invalid token returns 401"""
        response = await test_client.get(
            "/teams",
            headers={"Authorization": "Bearer pk_invalid_token"}
        )

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_jwt_auth_works(self, test_client, jwt_headers):
        """JWT authentication works"""
        response = await test_client.get("/users/me", headers=jwt_headers)

        assert response.status_code == 200
        data = response.json()
        assert "email" in data

    @pytest.mark.asyncio
    async def test_portal_token_auth_works(self, test_client, api_headers):
        """Portal API token authentication works"""
        response = await test_client.get("/teams", headers=api_headers)

        assert response.status_code == 200


# =============================================================================
# Scope Authorization Tests
# =============================================================================

class TestScopeAuthorization:
    """Test scope-based authorization"""

    @pytest.mark.asyncio
    async def test_read_only_token_can_list(self, test_client, jwt_headers):
        """Token with read scope can list teams"""
        # Create read-only token
        response = await test_client.post(
            "/portal/tokens",
            json={"name": "Read Only Token", "scopes": ["teams:read"]},
            headers=jwt_headers
        )
        assert response.status_code == 200
        read_token = response.json()["token"]

        # Use read token to list teams
        response = await test_client.get(
            "/teams",
            headers={"Authorization": f"Bearer {read_token}"}
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_read_only_token_cannot_create(self, test_client, jwt_headers):
        """Token with only read scope cannot create teams"""
        # Create read-only token
        response = await test_client.post(
            "/portal/tokens",
            json={"name": "Read Only Token 2", "scopes": ["teams:read"]},
            headers=jwt_headers
        )
        assert response.status_code == 200
        read_token = response.json()["token"]

        # Try to create team with read-only token
        response = await test_client.post(
            "/teams",
            json={"name": "Should Fail", "slug": f"fail-{uuid.uuid4().hex[:8]}"},
            headers={"Authorization": f"Bearer {read_token}"}
        )
        assert response.status_code == 403
        assert "teams:write" in response.json()["detail"]


# =============================================================================
# Error Handling Tests
# =============================================================================

class TestErrorHandling:
    """Test error responses"""

    @pytest.mark.asyncio
    async def test_team_not_found(self, test_client, api_headers):
        """Get non-existent team returns 404"""
        response = await test_client.get(
            "/teams/nonexistent-team-12345",
            headers=api_headers
        )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_invalid_team_slug(self, test_client, api_headers):
        """Create team with invalid slug format fails"""
        response = await test_client.post(
            "/teams",
            json={
                "name": "Invalid Slug Team",
                "slug": "Invalid Slug With Spaces!"
            },
            headers=api_headers
        )

        assert response.status_code == 422  # Validation error

    @pytest.mark.asyncio
    async def test_missing_required_field(self, test_client, jwt_headers):
        """Create token without required name field fails"""
        response = await test_client.post(
            "/portal/tokens",
            json={"scopes": ["*"]},  # Missing 'name'
            headers=jwt_headers
        )

        assert response.status_code == 422


# =============================================================================
# Health Check Tests
# =============================================================================

class TestHealthChecks:
    """Test health check endpoints"""

    @pytest.mark.asyncio
    async def test_health_check(self, test_client):
        """Basic health check"""
        response = await test_client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_redis_health(self, test_client):
        """Redis health check"""
        response = await test_client.get("/health/redis")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ["healthy", "unhealthy"]
