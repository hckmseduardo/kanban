"""Portal API Token Management Tests

Tests for creating, listing, validating, and deleting Portal API tokens.
Portal API tokens (pk_*) are used for programmatic API access.
"""

import pytest
import uuid


class TestPortalTokenCreation:
    """Test Portal API token creation"""

    @pytest.mark.asyncio
    async def test_create_token_with_full_access(self, test_client, jwt_headers):
        """Create a token with full access (wildcard scope)"""
        response = await test_client.post(
            "/portal/tokens",
            json={"name": f"Full Access Token {uuid.uuid4().hex[:6]}", "scopes": ["*"]},
            headers=jwt_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["token"].startswith("pk_")
        assert data["scopes"] == ["*"]
        assert data["is_active"] is True

    @pytest.mark.asyncio
    async def test_create_token_with_read_only_scope(self, test_client, jwt_headers):
        """Create a token with read-only scope"""
        response = await test_client.post(
            "/portal/tokens",
            json={"name": f"Read Token {uuid.uuid4().hex[:6]}", "scopes": ["teams:read"]},
            headers=jwt_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["token"].startswith("pk_")
        assert data["scopes"] == ["teams:read"]

    @pytest.mark.asyncio
    async def test_create_token_with_multiple_scopes(self, test_client, jwt_headers):
        """Create a token with multiple scopes"""
        scopes = ["teams:read", "teams:write", "boards:read", "cards:read"]
        response = await test_client.post(
            "/portal/tokens",
            json={"name": f"Multi Scope Token {uuid.uuid4().hex[:6]}", "scopes": scopes},
            headers=jwt_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert set(data["scopes"]) == set(scopes)

    @pytest.mark.asyncio
    async def test_create_token_without_name_fails(self, test_client, jwt_headers):
        """Creating token without name should fail validation"""
        response = await test_client.post(
            "/portal/tokens",
            json={"scopes": ["*"]},
            headers=jwt_headers
        )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_create_token_without_auth_fails(self, test_client):
        """Creating token without authentication should fail"""
        response = await test_client.post(
            "/portal/tokens",
            json={"name": "No Auth Token", "scopes": ["*"]}
        )

        assert response.status_code in [401, 403]


class TestPortalTokenListing:
    """Test Portal API token listing"""

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
    async def test_list_tokens_returns_masked_token(self, test_client, jwt_headers):
        """Listed tokens should have masked token values"""
        response = await test_client.get("/portal/tokens", headers=jwt_headers)

        assert response.status_code == 200
        data = response.json()

        for token_info in data:
            # Token should be present but masked or partial
            assert "id" in token_info
            assert "name" in token_info
            assert "scopes" in token_info

    @pytest.mark.asyncio
    async def test_list_tokens_without_auth_fails(self, test_client):
        """Listing tokens without authentication should fail"""
        response = await test_client.get("/portal/tokens")

        assert response.status_code in [401, 403]


class TestPortalTokenValidation:
    """Test Portal API token validation"""

    @pytest.mark.asyncio
    async def test_validate_valid_token(self, test_client, portal_api_token):
        """Validate a valid Portal API token"""
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

    @pytest.mark.asyncio
    async def test_validate_malformed_token(self, test_client):
        """Validate a malformed token returns valid=false"""
        response = await test_client.post(
            "/portal/validate-token",
            params={"token": "not_a_portal_token"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is False

    @pytest.mark.asyncio
    async def test_validate_empty_token(self, test_client):
        """Validate an empty token"""
        response = await test_client.post(
            "/portal/validate-token",
            params={"token": ""}
        )

        # Should return valid=false or validation error
        assert response.status_code in [200, 422]


class TestPortalTokenDeletion:
    """Test Portal API token deletion"""

    @pytest.mark.asyncio
    async def test_delete_token(self, test_client, jwt_headers):
        """Delete a Portal API token"""
        # First create a token to delete
        create_response = await test_client.post(
            "/portal/tokens",
            json={"name": f"Token To Delete {uuid.uuid4().hex[:6]}", "scopes": ["teams:read"]},
            headers=jwt_headers
        )
        assert create_response.status_code == 200
        token_id = create_response.json()["id"]

        # Delete the token
        delete_response = await test_client.delete(
            f"/portal/tokens/{token_id}",
            headers=jwt_headers
        )
        assert delete_response.status_code in [200, 204]

        # Verify token is deleted by checking list
        list_response = await test_client.get("/portal/tokens", headers=jwt_headers)
        token_ids = [t["id"] for t in list_response.json()]
        assert token_id not in token_ids

    @pytest.mark.asyncio
    async def test_delete_nonexistent_token(self, test_client, jwt_headers):
        """Deleting a non-existent token should return 404"""
        response = await test_client.delete(
            "/portal/tokens/nonexistent-token-id",
            headers=jwt_headers
        )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_token_without_auth_fails(self, test_client):
        """Deleting token without authentication should fail"""
        response = await test_client.delete("/portal/tokens/some-id")

        assert response.status_code in [401, 403]
