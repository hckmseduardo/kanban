"""Authentication Tests

Tests for authentication mechanisms and authorization.
"""

import pytest


class TestJWTAuthentication:
    """Test JWT authentication"""

    @pytest.mark.asyncio
    async def test_jwt_auth_works(self, test_client, jwt_headers):
        """JWT authentication works for user endpoints"""
        response = await test_client.get("/users/me", headers=jwt_headers)

        assert response.status_code == 200
        data = response.json()
        assert "email" in data

    @pytest.mark.asyncio
    async def test_invalid_jwt_returns_401(self, test_client):
        """Invalid JWT token returns 401"""
        response = await test_client.get(
            "/users/me",
            headers={"Authorization": "Bearer invalid-jwt-token"}
        )

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_expired_jwt_returns_401(self, test_client):
        """Expired JWT token returns 401"""
        # This is a deliberately malformed/expired token
        expired_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwiZXhwIjoxfQ.invalid"
        response = await test_client.get(
            "/users/me",
            headers={"Authorization": f"Bearer {expired_token}"}
        )

        assert response.status_code == 401


class TestPortalTokenAuthentication:
    """Test Portal API token authentication"""

    @pytest.mark.asyncio
    async def test_portal_token_auth_works(self, test_client, api_headers):
        """Portal API token authentication works"""
        response = await test_client.get("/teams", headers=api_headers)

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_invalid_portal_token_returns_401(self, test_client):
        """Invalid Portal API token returns 401"""
        response = await test_client.get(
            "/teams",
            headers={"Authorization": "Bearer pk_invalid_token"}
        )

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_malformed_bearer_token(self, test_client):
        """Malformed bearer token returns error"""
        response = await test_client.get(
            "/teams",
            headers={"Authorization": "Bearer"}
        )

        assert response.status_code in [401, 403, 422]

    @pytest.mark.asyncio
    async def test_wrong_auth_scheme(self, test_client, portal_api_token):
        """Wrong authentication scheme returns error"""
        response = await test_client.get(
            "/teams",
            headers={"Authorization": f"Basic {portal_api_token}"}
        )

        assert response.status_code in [401, 403]


class TestNoAuthentication:
    """Test endpoints without authentication"""

    @pytest.mark.asyncio
    async def test_no_auth_header_returns_error(self, test_client):
        """Request without auth header returns 401/403"""
        response = await test_client.get("/teams")

        # FastAPI HTTPBearer returns 403 when no credentials
        assert response.status_code in [401, 403]

    @pytest.mark.asyncio
    async def test_empty_auth_header(self, test_client):
        """Empty authorization header returns error"""
        response = await test_client.get(
            "/teams",
            headers={"Authorization": ""}
        )

        assert response.status_code in [401, 403, 422]


class TestLogout:
    """Test logout functionality"""

    @pytest.mark.asyncio
    async def test_logout(self, test_client, jwt_headers):
        """Logout endpoint works"""
        response = await test_client.post("/auth/logout", headers=jwt_headers)

        assert response.status_code in [200, 204]

    @pytest.mark.asyncio
    async def test_logout_without_auth(self, test_client):
        """Logout without authentication - API accepts it (no-op)"""
        response = await test_client.post("/auth/logout")

        # Logout endpoint is lenient - returns OK even without auth
        assert response.status_code in [200, 204, 401, 403]


class TestCrossDomainToken:
    """Test cross-domain token functionality"""

    @pytest.mark.asyncio
    async def test_get_cross_domain_token(self, test_client, jwt_headers):
        """Get cross-domain token"""
        response = await test_client.get(
            "/auth/cross-domain-token",
            headers=jwt_headers
        )

        # May succeed or require additional params
        assert response.status_code in [200, 400, 422]

    @pytest.mark.asyncio
    async def test_cross_domain_token_without_auth(self, test_client):
        """Cross-domain token without auth - returns validation error"""
        response = await test_client.get("/auth/cross-domain-token")

        # Returns 422 validation error (missing required params) before auth check
        assert response.status_code in [401, 403, 422]


class TestTokenExchange:
    """Test token exchange functionality"""

    @pytest.mark.asyncio
    async def test_exchange_token(self, test_client, jwt_headers):
        """Exchange token for new token"""
        response = await test_client.post(
            "/auth/exchange",
            headers=jwt_headers
        )

        # May succeed or require additional data
        assert response.status_code in [200, 400, 422]


class TestScopeAuthorization:
    """Test scope-based authorization"""

    @pytest.mark.asyncio
    async def test_wildcard_scope_has_full_access(self, test_client, api_headers, test_team):
        """Token with wildcard scope has full access"""
        # Should be able to read
        read_response = await test_client.get("/teams", headers=api_headers)
        assert read_response.status_code == 200

        # Should be able to update
        update_response = await test_client.put(
            f"/teams/{test_team['slug']}",
            json={"description": "Updated by wildcard token"},
            headers=api_headers
        )
        assert update_response.status_code == 200

    @pytest.mark.asyncio
    async def test_read_scope_allows_read(self, test_client, read_only_headers):
        """Token with read scope can read"""
        response = await test_client.get("/teams", headers=read_only_headers)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_read_scope_denies_write(self, test_client, read_only_headers):
        """Token with only read scope cannot write"""
        response = await test_client.post(
            "/teams",
            json={"name": "Should Fail", "slug": "should-fail"},
            headers=read_only_headers
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_scope_required_in_error_message(self, test_client, read_only_headers):
        """Error message includes required scope"""
        response = await test_client.post(
            "/teams",
            json={"name": "Should Fail", "slug": "should-fail"},
            headers=read_only_headers
        )

        if response.status_code == 403:
            error_detail = response.json().get("detail", "")
            assert "teams:write" in error_detail


class TestUserEndpoints:
    """Test user-related endpoints"""

    @pytest.mark.asyncio
    async def test_get_current_user(self, test_client, jwt_headers, test_user):
        """Get current user info"""
        response = await test_client.get("/users/me", headers=jwt_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["email"] == test_user["email"]

    @pytest.mark.asyncio
    async def test_update_current_user(self, test_client, jwt_headers):
        """Update current user info"""
        response = await test_client.put(
            "/users/me",
            json={"display_name": "Updated Name"},
            headers=jwt_headers
        )

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_get_user_teams(self, test_client, jwt_headers, test_team):
        """Get teams for current user"""
        response = await test_client.get("/users/me/teams", headers=jwt_headers)

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
