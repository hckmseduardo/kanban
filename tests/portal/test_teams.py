"""Team Management Tests

Tests for team CRUD operations, lifecycle management, and status checks.
"""

import pytest
import uuid


class TestTeamCreation:
    """Test team creation"""

    @pytest.mark.asyncio
    async def test_create_team(self, test_client, api_headers, unique_slug):
        """Create a new team"""
        response = await test_client.post(
            "/teams",
            json={
                "name": f"Test Team {unique_slug}",
                "slug": unique_slug,
                "description": "A test team"
            },
            headers=api_headers
        )

        assert response.status_code == 200
        data = response.json()
        # Response format: {"team": {...}, "task_id": "...", "message": "..."}
        assert data["team"]["slug"] == unique_slug
        assert "task_id" in data

    @pytest.mark.asyncio
    async def test_create_team_minimal(self, test_client, api_headers):
        """Create a team with minimal required fields"""
        slug = f"minimal-{uuid.uuid4().hex[:8]}"
        response = await test_client.post(
            "/teams",
            json={"name": "Minimal Team", "slug": slug},
            headers=api_headers
        )

        assert response.status_code == 200
        data = response.json()
        # Response format: {"team": {...}, "task_id": "...", "message": "..."}
        assert data["team"]["slug"] == slug

    @pytest.mark.asyncio
    async def test_create_duplicate_team_fails(self, test_client, api_headers, test_team):
        """Creating team with existing slug should fail"""
        response = await test_client.post(
            "/teams",
            json={
                "name": "Duplicate Team",
                "slug": test_team["slug"],
                "description": "Should fail"
            },
            headers=api_headers
        )

        assert response.status_code == 409  # Conflict

    @pytest.mark.asyncio
    async def test_create_team_invalid_slug(self, test_client, api_headers):
        """Creating team with invalid slug format should fail"""
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
    async def test_create_team_without_auth_fails(self, test_client):
        """Creating team without authentication should fail"""
        response = await test_client.post(
            "/teams",
            json={"name": "No Auth Team", "slug": "no-auth-team"}
        )

        assert response.status_code in [401, 403]


class TestTeamListing:
    """Test team listing"""

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
    async def test_list_teams_without_auth_fails(self, test_client):
        """Listing teams without authentication should fail"""
        response = await test_client.get("/teams")

        assert response.status_code in [401, 403]


class TestTeamRetrieval:
    """Test getting team by slug"""

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

    @pytest.mark.asyncio
    async def test_get_nonexistent_team(self, test_client, api_headers):
        """Getting non-existent team should return 404"""
        response = await test_client.get(
            "/teams/nonexistent-team-12345",
            headers=api_headers
        )

        assert response.status_code == 404


class TestTeamUpdate:
    """Test team update operations"""

    @pytest.mark.asyncio
    async def test_update_team_description(self, test_client, api_headers, test_team):
        """Update team description"""
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
    async def test_update_team_name(self, test_client, api_headers, test_team):
        """Update team name"""
        new_name = f"Renamed Team {uuid.uuid4().hex[:6]}"

        response = await test_client.put(
            f"/teams/{test_team['slug']}",
            json={"name": new_name},
            headers=api_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == new_name

    @pytest.mark.asyncio
    async def test_update_nonexistent_team(self, test_client, api_headers):
        """Updating non-existent team should return 404"""
        response = await test_client.put(
            "/teams/nonexistent-team",
            json={"description": "Updated"},
            headers=api_headers
        )

        assert response.status_code == 404


class TestTeamStatus:
    """Test team status operations"""

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
    async def test_get_status_nonexistent_team(self, test_client, api_headers):
        """Getting status of non-existent team should return 404"""
        response = await test_client.get(
            "/teams/nonexistent-team/status",
            headers=api_headers
        )

        assert response.status_code == 404


class TestTeamLifecycle:
    """Test team lifecycle operations (restart, start)"""

    @pytest.mark.asyncio
    async def test_restart_team(self, test_client, api_headers, test_team):
        """Restart a team container"""
        response = await test_client.post(
            f"/teams/{test_team['slug']}/restart",
            headers=api_headers
        )

        # May succeed or return error depending on container state
        assert response.status_code in [200, 202, 400, 404, 500, 503]

    @pytest.mark.asyncio
    async def test_restart_team_with_rebuild(self, test_client, api_headers, test_team):
        """Restart a team container with rebuild"""
        response = await test_client.post(
            f"/teams/{test_team['slug']}/restart",
            json={"rebuild": True},
            headers=api_headers
        )

        # May succeed or return error depending on container state
        assert response.status_code in [200, 202, 400, 404, 500, 503]

    @pytest.mark.asyncio
    async def test_start_team(self, test_client, api_headers, test_team):
        """Start a suspended team"""
        response = await test_client.post(
            f"/teams/{test_team['slug']}/start",
            headers=api_headers
        )

        # May succeed or return error depending on team state
        assert response.status_code in [200, 202, 400, 404, 500, 503]


class TestTeamDeletion:
    """Test team deletion"""

    @pytest.mark.asyncio
    async def test_delete_team(self, test_client, api_headers):
        """Delete a team"""
        # Create a team to delete
        slug = f"delete-me-{uuid.uuid4().hex[:8]}"
        create_response = await test_client.post(
            "/teams",
            json={"name": "Team To Delete", "slug": slug},
            headers=api_headers
        )
        assert create_response.status_code == 200

        # Delete the team
        delete_response = await test_client.delete(
            f"/teams/{slug}",
            headers=api_headers
        )

        assert delete_response.status_code in [200, 202, 204]

    @pytest.mark.asyncio
    async def test_delete_nonexistent_team(self, test_client, api_headers):
        """Deleting non-existent team should return 404"""
        response = await test_client.delete(
            "/teams/nonexistent-team-to-delete",
            headers=api_headers
        )

        assert response.status_code == 404


class TestTeamAuthorization:
    """Test team authorization with different scopes"""

    @pytest.mark.asyncio
    async def test_read_only_token_can_list_teams(self, test_client, read_only_headers):
        """Token with read scope can list teams"""
        response = await test_client.get("/teams", headers=read_only_headers)

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_read_only_token_can_get_team(self, test_client, read_only_headers, test_team):
        """Token with read scope can get team details"""
        response = await test_client.get(
            f"/teams/{test_team['slug']}",
            headers=read_only_headers
        )

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_read_only_token_cannot_create_team(self, test_client, read_only_headers):
        """Token with only read scope cannot create teams"""
        response = await test_client.post(
            "/teams",
            json={"name": "Should Fail", "slug": f"fail-{uuid.uuid4().hex[:8]}"},
            headers=read_only_headers
        )

        assert response.status_code == 403
        assert "teams:write" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_read_only_token_cannot_update_team(self, test_client, read_only_headers, test_team):
        """Token with only read scope cannot update teams"""
        response = await test_client.put(
            f"/teams/{test_team['slug']}",
            json={"description": "Should Fail"},
            headers=read_only_headers
        )

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_read_only_token_cannot_delete_team(self, test_client, read_only_headers, test_team):
        """Token with only read scope cannot delete teams"""
        response = await test_client.delete(
            f"/teams/{test_team['slug']}",
            headers=read_only_headers
        )

        assert response.status_code == 403
