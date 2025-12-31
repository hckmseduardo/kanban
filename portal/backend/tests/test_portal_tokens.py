"""Portal API Token Management Tests

Tests for creating, listing, deleting, and validating Portal API tokens.
Token creation requires JWT authentication; token usage for API access.
"""

import pytest
from datetime import datetime, timedelta

from tests.factories import create_user, create_portal_token, portal_token_create_request


# =============================================================================
# PT-001 to PT-006: Token Creation Tests
# =============================================================================

class TestPortalTokenCreation:
    """Tests for POST /portal/tokens"""

    @pytest.mark.asyncio
    async def test_create_token_with_jwt(self, test_client, jwt_headers, mock_db, test_user):
        """PT-001: Create token using JWT auth returns pk_* token"""
        mock_db.create_portal_api_token.return_value = {
            "id": "token-123",
            "name": "My Token",
            "scopes": ["*"],
            "created_by": test_user["id"],
            "created_at": datetime.utcnow().isoformat(),
            "expires_at": None,
            "last_used_at": None,
            "is_active": True
        }

        response = await test_client.post(
            "/portal/tokens",
            json=portal_token_create_request(name="My Token", scopes=["*"]),
            headers=jwt_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "My Token"
        assert data["scopes"] == ["*"]
        assert data["token"].startswith("pk_")
        assert data["is_active"] is True

    @pytest.mark.asyncio
    async def test_create_token_with_specific_scopes(self, test_client, jwt_headers, mock_db, test_user):
        """PT-002: Create token with specific scopes"""
        scopes = ["teams:read", "boards:write"]
        mock_db.create_portal_api_token.return_value = {
            "id": "token-123",
            "name": "Limited Token",
            "scopes": scopes,
            "created_by": test_user["id"],
            "created_at": datetime.utcnow().isoformat(),
            "expires_at": None,
            "last_used_at": None,
            "is_active": True
        }

        response = await test_client.post(
            "/portal/tokens",
            json=portal_token_create_request(name="Limited Token", scopes=scopes),
            headers=jwt_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["scopes"] == scopes

    @pytest.mark.asyncio
    async def test_create_token_with_wildcard(self, test_client, jwt_headers, mock_db, test_user):
        """PT-003: Create token with wildcard scope grants full access"""
        mock_db.create_portal_api_token.return_value = {
            "id": "token-123",
            "name": "Full Access",
            "scopes": ["*"],
            "created_by": test_user["id"],
            "created_at": datetime.utcnow().isoformat(),
            "expires_at": None,
            "last_used_at": None,
            "is_active": True
        }

        response = await test_client.post(
            "/portal/tokens",
            json=portal_token_create_request(name="Full Access", scopes=["*"]),
            headers=jwt_headers
        )

        assert response.status_code == 200
        assert response.json()["scopes"] == ["*"]

    @pytest.mark.asyncio
    async def test_create_token_without_auth(self, test_client):
        """PT-005: Create token without Authorization header returns 403"""
        response = await test_client.post(
            "/portal/tokens",
            json=portal_token_create_request()
        )

        # FastAPI HTTPBearer returns 403 when no credentials provided
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_create_token_with_invalid_jwt(self, test_client):
        """PT-006: Create token with malformed JWT returns 401"""
        response = await test_client.post(
            "/portal/tokens",
            json=portal_token_create_request(),
            headers={"Authorization": "Bearer invalid.jwt.token"}
        )

        assert response.status_code == 401


# =============================================================================
# PT-007 to PT-008: Token Listing Tests
# =============================================================================

class TestPortalTokenListing:
    """Tests for GET /portal/tokens"""

    @pytest.mark.asyncio
    async def test_list_tokens(self, test_client, jwt_headers, mock_db, test_user):
        """PT-007: List user's tokens returns array"""
        tokens = [
            create_portal_token(name="Token 1", created_by=test_user["id"]),
            create_portal_token(name="Token 2", created_by=test_user["id"])
        ]
        mock_db.get_all_portal_api_tokens.return_value = tokens

        response = await test_client.get("/portal/tokens", headers=jwt_headers)

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert data[0]["name"] == "Token 1"
        assert data[1]["name"] == "Token 2"

    @pytest.mark.asyncio
    async def test_list_tokens_empty(self, test_client, jwt_headers, mock_db):
        """PT-007b: List tokens when user has none returns empty array"""
        mock_db.get_all_portal_api_tokens.return_value = []

        response = await test_client.get("/portal/tokens", headers=jwt_headers)

        assert response.status_code == 200
        assert response.json() == []

    @pytest.mark.asyncio
    async def test_list_tokens_only_shows_own(self, test_client, jwt_headers, mock_db, test_user, another_user_data):
        """PT-008: User cannot see other users' tokens"""
        # Mock returns only the current user's tokens (filtered by created_by)
        user_tokens = [create_portal_token(name="My Token", created_by=test_user["id"])]
        mock_db.get_all_portal_api_tokens.return_value = user_tokens

        response = await test_client.get("/portal/tokens", headers=jwt_headers)

        assert response.status_code == 200
        data = response.json()
        # Should only see own tokens
        for token in data:
            assert token["created_by"] == test_user["id"]


# =============================================================================
# PT-009 to PT-011: Token Deletion Tests
# =============================================================================

class TestPortalTokenDeletion:
    """Tests for DELETE /portal/tokens/{token_id}"""

    @pytest.mark.asyncio
    async def test_delete_token(self, test_client, jwt_headers, mock_db, test_user):
        """PT-009: Delete a token by ID invalidates it"""
        token = create_portal_token(token_id="token-to-delete", created_by=test_user["id"])
        mock_db.get_portal_api_token_by_id.return_value = token
        mock_db.delete_portal_api_token.return_value = True

        response = await test_client.delete("/portal/tokens/token-to-delete", headers=jwt_headers)

        assert response.status_code == 200
        assert response.json()["message"] == "Token deleted"
        mock_db.delete_portal_api_token.assert_called_once_with("token-to-delete")

    @pytest.mark.asyncio
    async def test_delete_token_not_owner(self, test_client, jwt_headers, mock_db, another_user_data):
        """PT-010: Delete token owned by another user returns 403"""
        # Token belongs to another user
        token = create_portal_token(token_id="others-token", created_by=another_user_data["id"])
        mock_db.get_portal_api_token_by_id.return_value = token

        response = await test_client.delete("/portal/tokens/others-token", headers=jwt_headers)

        assert response.status_code == 403
        assert "Not authorized" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_delete_nonexistent_token(self, test_client, jwt_headers, mock_db):
        """PT-011: Delete non-existent token returns 404"""
        mock_db.get_portal_api_token_by_id.return_value = None

        response = await test_client.delete("/portal/tokens/nonexistent", headers=jwt_headers)

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()


# =============================================================================
# PT-012 to PT-015: Token Validation Tests
# =============================================================================

class TestPortalTokenValidation:
    """Tests for POST /portal/validate-token"""

    @pytest.mark.asyncio
    async def test_validate_token_valid(self, test_client, mock_db, test_user):
        """PT-012: Validate a valid pk_* token returns valid=true"""
        token = create_portal_token(created_by=test_user["id"], scopes=["teams:read"])
        mock_db.get_portal_api_token_by_hash.return_value = token
        mock_db.get_user_by_id.return_value = test_user
        mock_db.update_portal_api_token_last_used.return_value = True

        response = await test_client.post(
            "/portal/validate-token",
            params={"token": "pk_valid_test_token"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is True
        assert data["user_id"] == test_user["id"]
        assert data["scopes"] == ["teams:read"]

    @pytest.mark.asyncio
    async def test_validate_token_expired(self, test_client, mock_db, test_user):
        """PT-013: Validate an expired token returns valid=false"""
        expired_at = (datetime.utcnow() - timedelta(days=1)).isoformat()
        token = create_portal_token(created_by=test_user["id"], expires_at=expired_at)
        mock_db.get_portal_api_token_by_hash.return_value = token
        mock_db.get_user_by_id.return_value = test_user

        response = await test_client.post(
            "/portal/validate-token",
            params={"token": "pk_expired_token"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is False
        assert "expired" in data["detail"].lower()

    @pytest.mark.asyncio
    async def test_validate_token_revoked(self, test_client, mock_db, test_user):
        """PT-014: Validate a deleted/inactive token returns valid=false"""
        token = create_portal_token(created_by=test_user["id"], is_active=False)
        mock_db.get_portal_api_token_by_hash.return_value = token

        response = await test_client.post(
            "/portal/validate-token",
            params={"token": "pk_revoked_token"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is False
        assert "inactive" in data["detail"].lower()

    @pytest.mark.asyncio
    async def test_validate_token_invalid_format(self, test_client):
        """PT-015: Validate non-pk_* token returns valid=false"""
        response = await test_client.post(
            "/portal/validate-token",
            params={"token": "invalid_token_no_prefix"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is False
        assert "not a portal" in data["detail"].lower()

    @pytest.mark.asyncio
    async def test_validate_token_not_found(self, test_client, mock_db):
        """PT-015b: Validate token not in database returns valid=false"""
        mock_db.get_portal_api_token_by_hash.return_value = None

        response = await test_client.post(
            "/portal/validate-token",
            params={"token": "pk_nonexistent_token"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is False
        assert "not found" in data["detail"].lower()

    @pytest.mark.asyncio
    async def test_validate_token_with_team_membership(self, test_client, mock_db, test_user):
        """PT-012b: Validate token with team_slug returns membership role"""
        token = create_portal_token(created_by=test_user["id"])
        team = {"id": "team-123", "slug": "my-team"}
        membership = {"user_id": test_user["id"], "team_id": team["id"], "role": "admin"}

        mock_db.get_portal_api_token_by_hash.return_value = token
        mock_db.get_user_by_id.return_value = test_user
        mock_db.get_team_by_slug.return_value = team
        mock_db.get_membership.return_value = membership
        mock_db.update_portal_api_token_last_used.return_value = True

        response = await test_client.post(
            "/portal/validate-token",
            params={"token": "pk_valid_token", "team_slug": "my-team"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is True
        assert data["team_member_role"] == "admin"
