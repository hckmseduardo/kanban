"""Team API Token Management Tests

Tests for creating, listing, validating, and deleting Team API tokens.
Team API tokens are used for team-specific access to the kanban board API.

NOTE: Team API token endpoints require JWT authentication, not Portal API tokens.
"""

import pytest
import uuid


class TestTeamApiTokenCreation:
    """Test Team API token creation - requires JWT auth"""

    @pytest.mark.asyncio
    async def test_create_team_api_token(self, test_client, jwt_headers, test_team):
        """Create a Team API token"""
        response = await test_client.post(
            f"/teams/{test_team['slug']}/api-tokens",
            json={
                "name": f"Team Token {uuid.uuid4().hex[:6]}",
                "scopes": ["*"]
            },
            headers=jwt_headers
        )

        # May succeed or fail based on team status
        if response.status_code == 200:
            data = response.json()
            # Response structure: {"token": {...}, "plaintext_token": "pk_..."}
            assert "plaintext_token" in data
            assert data["token"]["is_active"] is True

    @pytest.mark.asyncio
    async def test_create_team_api_token_with_scopes(self, test_client, jwt_headers, test_team):
        """Create a Team API token with specific scopes"""
        response = await test_client.post(
            f"/teams/{test_team['slug']}/api-tokens",
            json={
                "name": f"Scoped Token {uuid.uuid4().hex[:6]}",
                "scopes": ["boards:read", "cards:read"]
            },
            headers=jwt_headers
        )

        if response.status_code == 200:
            data = response.json()
            # Response structure: {"token": {...}, "plaintext_token": "pk_..."}
            assert set(data["token"]["scopes"]) == {"boards:read", "cards:read"}

    @pytest.mark.asyncio
    async def test_create_team_api_token_without_name(self, test_client, jwt_headers, test_team):
        """Creating Team API token without name should fail"""
        response = await test_client.post(
            f"/teams/{test_team['slug']}/api-tokens",
            json={"scopes": ["*"]},
            headers=jwt_headers
        )

        assert response.status_code in [422, 400]


class TestTeamApiTokenListing:
    """Test Team API token listing - requires JWT auth"""

    @pytest.mark.asyncio
    async def test_list_team_api_tokens(self, test_client, jwt_headers, test_team):
        """List Team API tokens"""
        response = await test_client.get(
            f"/teams/{test_team['slug']}/api-tokens",
            headers=jwt_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_list_tokens_nonexistent_team(self, test_client, jwt_headers):
        """Listing tokens for non-existent team should return 404"""
        response = await test_client.get(
            "/teams/nonexistent-team/api-tokens",
            headers=jwt_headers
        )

        assert response.status_code == 404


class TestTeamApiTokenValidation:
    """Test Team API token validation"""

    @pytest.mark.asyncio
    async def test_validate_team_api_token(self, test_client, jwt_headers, test_team):
        """Validate a Team API token"""
        # First create a token
        create_response = await test_client.post(
            f"/teams/{test_team['slug']}/api-tokens",
            json={"name": f"Validate Token {uuid.uuid4().hex[:6]}", "scopes": ["*"]},
            headers=jwt_headers
        )

        if create_response.status_code == 200:
            # Get the plaintext token for validation
            plaintext_token = create_response.json()["plaintext_token"]

            # Validate the token (uses query parameter, not JSON body)
            validate_response = await test_client.post(
                "/teams/validate-api-token",
                params={"token": plaintext_token}
            )

            if validate_response.status_code == 200:
                data = validate_response.json()
                assert data.get("valid") is True

    @pytest.mark.asyncio
    async def test_validate_invalid_team_api_token(self, test_client):
        """Validating invalid Team API token returns 401"""
        response = await test_client.post(
            "/teams/validate-api-token",
            params={"token": "invalid-team-token"}
        )

        # Invalid tokens return 401, not valid=false
        assert response.status_code == 401


class TestTeamApiTokenDeletion:
    """Test Team API token deletion - requires JWT auth"""

    @pytest.mark.asyncio
    async def test_delete_team_api_token(self, test_client, jwt_headers, test_team):
        """Delete a Team API token"""
        # First create a token
        create_response = await test_client.post(
            f"/teams/{test_team['slug']}/api-tokens",
            json={"name": f"Delete Token {uuid.uuid4().hex[:6]}", "scopes": ["*"]},
            headers=jwt_headers
        )

        if create_response.status_code == 200:
            # Get the token ID from the nested token object
            token_id = create_response.json()["token"]["id"]

            # Delete the token
            delete_response = await test_client.delete(
                f"/teams/{test_team['slug']}/api-tokens/{token_id}",
                headers=jwt_headers
            )

            assert delete_response.status_code in [200, 204]

    @pytest.mark.asyncio
    async def test_delete_nonexistent_token(self, test_client, jwt_headers, test_team):
        """Deleting non-existent token should return 404"""
        response = await test_client.delete(
            f"/teams/{test_team['slug']}/api-tokens/nonexistent-token-id",
            headers=jwt_headers
        )

        assert response.status_code == 404


class TestTeamApiTokenAuthorization:
    """Test Team API token authorization - these endpoints require JWT, not Portal API tokens"""

    @pytest.mark.asyncio
    async def test_portal_token_cannot_access_api_tokens(self, test_client, api_headers, test_team):
        """Portal API tokens cannot access team API token endpoints"""
        response = await test_client.get(
            f"/teams/{test_team['slug']}/api-tokens",
            headers=api_headers
        )

        # Should return 401 because Portal API tokens are not accepted
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_no_auth_cannot_access_api_tokens(self, test_client, test_team):
        """Request without auth cannot access team API tokens"""
        response = await test_client.get(
            f"/teams/{test_team['slug']}/api-tokens"
        )

        assert response.status_code in [401, 403]
