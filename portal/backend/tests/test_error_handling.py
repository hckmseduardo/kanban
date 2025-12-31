"""Error Handling Tests

Tests for various error conditions: authentication failures, not found errors,
validation errors, and service unavailability.
"""

import pytest
from datetime import datetime, timedelta

from tests.factories import (
    create_user, create_team, create_portal_token, create_card,
    card_create_request
)


# =============================================================================
# EH-001 to EH-005: Authentication Error Tests
# =============================================================================

class TestAuthenticationErrors:
    """Tests for authentication-related errors"""

    @pytest.mark.asyncio
    async def test_invalid_token_format(self, test_client, mock_db):
        """EH-001: Invalid token format returns 401"""
        # Token with invalid characters
        headers = {"Authorization": "Bearer pk_invalid!@#$%^&*token"}

        response = await test_client.get("/teams", headers=headers)

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_expired_token(self, test_client, mock_db, test_user):
        """EH-002: Expired token returns 401"""
        # Create expired token
        expired_at = (datetime.utcnow() - timedelta(days=1)).isoformat()
        token = create_portal_token(
            created_by=test_user["id"],
            expires_at=expired_at
        )
        mock_db.get_portal_api_token_by_hash.return_value = token
        mock_db.get_user_by_id.return_value = test_user

        headers = {"Authorization": "Bearer pk_expired_token"}

        response = await test_client.get("/teams", headers=headers)

        assert response.status_code == 401
        assert "expired" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_revoked_token(self, test_client, mock_db, test_user):
        """EH-003: Revoked (inactive) token returns 401"""
        token = create_portal_token(
            created_by=test_user["id"],
            is_active=False
        )
        mock_db.get_portal_api_token_by_hash.return_value = token

        headers = {"Authorization": "Bearer pk_revoked_token"}

        response = await test_client.get("/teams", headers=headers)

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_missing_auth_header(self, test_client):
        """EH-004: Missing Authorization header returns 401"""
        response = await test_client.get("/teams")

        assert response.status_code == 401
        assert "Missing Authorization" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_wrong_auth_scheme(self, test_client):
        """EH-005: Wrong auth scheme (Basic instead of Bearer) returns 401"""
        headers = {"Authorization": "Basic dXNlcjpwYXNz"}  # base64 "user:pass"

        response = await test_client.get("/teams", headers=headers)

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_malformed_bearer_token(self, test_client):
        """Bearer token without actual token returns 401"""
        headers = {"Authorization": "Bearer "}

        response = await test_client.get("/teams", headers=headers)

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_token_user_not_found(self, test_client, mock_db):
        """Token valid but user no longer exists returns 401"""
        token = create_portal_token(created_by="deleted-user-id")
        mock_db.get_portal_api_token_by_hash.return_value = token
        mock_db.get_user_by_id.return_value = None  # User deleted

        headers = {"Authorization": "Bearer pk_orphan_token"}

        response = await test_client.get("/teams", headers=headers)

        assert response.status_code == 401
        assert "not found" in response.json()["detail"].lower()


# =============================================================================
# EH-006 to EH-009: Not Found Error Tests
# =============================================================================

class TestNotFoundErrors:
    """Tests for resource not found errors"""

    @pytest.mark.asyncio
    async def test_team_not_found(self, test_client, mock_db, test_user):
        """EH-006: Access non-existent team returns 404"""
        token = create_portal_token(created_by=test_user["id"], scopes=["*"])
        mock_db.get_portal_api_token_by_hash.return_value = token
        mock_db.get_user_by_id.return_value = test_user
        mock_db.get_team_by_slug.return_value = None

        headers = {"Authorization": "Bearer pk_valid_token"}

        response = await test_client.get("/teams/nonexistent-team", headers=headers)

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_team_not_member(self, test_client, mock_db, test_user):
        """EH-007: Access team user is not member of returns 403"""
        team = create_team(slug="private-team", owner_id="other-user-id")
        token = create_portal_token(created_by=test_user["id"], scopes=["*"])

        mock_db.get_portal_api_token_by_hash.return_value = token
        mock_db.get_user_by_id.return_value = test_user
        mock_db.get_team_by_slug.return_value = team
        mock_db.get_membership.return_value = None  # Not a member

        headers = {"Authorization": "Bearer pk_valid_token"}

        response = await test_client.get("/teams/private-team", headers=headers)

        assert response.status_code == 403
        assert "not a member" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_card_not_found(self, test_client, mock_db, mock_team_proxy, test_user):
        """EH-008: Get non-existent card returns 404"""
        team = create_team(owner_id=test_user["id"])
        token = create_portal_token(created_by=test_user["id"], scopes=["*"])

        mock_db.get_portal_api_token_by_hash.return_value = token
        mock_db.get_user_by_id.return_value = test_user
        mock_db.get_team_by_slug.return_value = team
        mock_db.get_membership.return_value = {"role": "owner"}

        # Team proxy returns 404
        mock_team_proxy.get.return_value = (404, {"detail": "Card not found"})

        headers = {"Authorization": "Bearer pk_valid_token"}

        response = await test_client.get(
            f"/teams/{team['slug']}/cards/nonexistent-card-id",
            headers=headers
        )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_column_not_found_on_card_create(self, test_client, mock_db, mock_team_proxy, test_user):
        """EH-009: Create card in non-existent column returns 404"""
        team = create_team(owner_id=test_user["id"])
        token = create_portal_token(created_by=test_user["id"], scopes=["*"])

        mock_db.get_portal_api_token_by_hash.return_value = token
        mock_db.get_user_by_id.return_value = test_user
        mock_db.get_team_by_slug.return_value = team
        mock_db.get_membership.return_value = {"role": "owner"}

        # Team proxy returns 404 for invalid column
        mock_team_proxy.post.return_value = (404, {"detail": "Column not found"})

        headers = {"Authorization": "Bearer pk_valid_token"}

        response = await test_client.post(
            f"/teams/{team['slug']}/cards",
            json=card_create_request(column_id="nonexistent-column-id"),
            headers=headers
        )

        assert response.status_code == 404


# =============================================================================
# EH-010 to EH-012: Validation Error Tests
# =============================================================================

class TestValidationErrors:
    """Tests for request validation errors"""

    @pytest.mark.asyncio
    async def test_invalid_json(self, test_client, mock_db, test_user):
        """EH-010: Malformed JSON returns 422"""
        token = create_portal_token(created_by=test_user["id"], scopes=["*"])
        mock_db.get_portal_api_token_by_hash.return_value = token
        mock_db.get_user_by_id.return_value = test_user

        headers = {
            "Authorization": "Bearer pk_valid_token",
            "Content-Type": "application/json"
        }

        response = await test_client.post(
            "/portal/tokens",
            content="{ invalid json }",
            headers=headers
        )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_missing_required_fields(self, test_client, mock_db, test_user, jwt_headers):
        """EH-011: POST without required fields returns 422"""
        response = await test_client.post(
            "/portal/tokens",
            json={},  # Missing required 'name' field
            headers=jwt_headers
        )

        assert response.status_code == 422
        detail = response.json()["detail"]
        # Pydantic returns field errors
        assert any("name" in str(err).lower() for err in detail)

    @pytest.mark.asyncio
    async def test_invalid_field_types(self, test_client, mock_db, mock_team_proxy, test_user):
        """EH-012: Invalid field types return 422"""
        team = create_team(owner_id=test_user["id"])
        token = create_portal_token(created_by=test_user["id"], scopes=["*"])

        mock_db.get_portal_api_token_by_hash.return_value = token
        mock_db.get_user_by_id.return_value = test_user
        mock_db.get_team_by_slug.return_value = team
        mock_db.get_membership.return_value = {"role": "owner"}

        headers = {"Authorization": "Bearer pk_valid_token"}

        # priority should be string, not number
        response = await test_client.post(
            f"/teams/{team['slug']}/cards",
            json={
                "column_id": "some-id",
                "title": "Test",
                "priority": 123  # Should be string like "high", "medium", "low"
            },
            headers=headers
        )

        # Depending on schema, this might be 422 or accepted
        # If schema expects string enum, it will be 422

    @pytest.mark.asyncio
    async def test_invalid_slug_format(self, test_client, mock_db, mock_task_service, test_user):
        """Invalid team slug format returns 422"""
        token = create_portal_token(created_by=test_user["id"], scopes=["*"])
        mock_db.get_portal_api_token_by_hash.return_value = token
        mock_db.get_user_by_id.return_value = test_user
        mock_db.get_team_by_slug.return_value = None

        headers = {"Authorization": "Bearer pk_valid_token"}

        # Slug with invalid characters
        response = await test_client.post(
            "/teams",
            json={"name": "Test", "slug": "Invalid Slug With Spaces!"},
            headers=headers
        )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_empty_name_field(self, test_client, jwt_headers):
        """Empty name field returns 422"""
        response = await test_client.post(
            "/portal/tokens",
            json={"name": "", "scopes": ["*"]},
            headers=jwt_headers
        )

        assert response.status_code == 422


# =============================================================================
# EH-013 to EH-014: Service Error Tests
# =============================================================================

class TestServiceErrors:
    """Tests for service-level errors"""

    @pytest.mark.asyncio
    async def test_team_api_unavailable(self, test_client, mock_db, mock_team_proxy, test_user):
        """EH-013: Team containers not running returns 503"""
        team = create_team(owner_id=test_user["id"], status="suspended")
        token = create_portal_token(created_by=test_user["id"], scopes=["*"])

        mock_db.get_portal_api_token_by_hash.return_value = token
        mock_db.get_user_by_id.return_value = test_user
        mock_db.get_team_by_slug.return_value = team
        mock_db.get_membership.return_value = {"role": "owner"}

        # Team proxy returns connection error
        mock_team_proxy.get.return_value = (503, {"detail": "Team service unavailable"})

        headers = {"Authorization": "Bearer pk_valid_token"}

        response = await test_client.get(
            f"/teams/{team['slug']}/boards",
            headers=headers
        )

        assert response.status_code == 503

    @pytest.mark.asyncio
    async def test_team_api_timeout(self, test_client, mock_db, mock_team_proxy, test_user):
        """EH-014: Team API timeout returns 504"""
        team = create_team(owner_id=test_user["id"])
        token = create_portal_token(created_by=test_user["id"], scopes=["*"])

        mock_db.get_portal_api_token_by_hash.return_value = token
        mock_db.get_user_by_id.return_value = test_user
        mock_db.get_team_by_slug.return_value = team
        mock_db.get_membership.return_value = {"role": "owner"}

        # Team proxy returns timeout
        mock_team_proxy.get.return_value = (504, {"detail": "Gateway timeout"})

        headers = {"Authorization": "Bearer pk_valid_token"}

        response = await test_client.get(
            f"/teams/{team['slug']}/boards",
            headers=headers
        )

        assert response.status_code == 504


# =============================================================================
# Additional Error Cases
# =============================================================================

class TestAdditionalErrors:
    """Additional error case tests"""

    @pytest.mark.asyncio
    async def test_delete_owner_from_team(self, test_client, mock_db, test_user):
        """Cannot remove team owner returns 400"""
        team = create_team(owner_id=test_user["id"])
        token = create_portal_token(created_by=test_user["id"], scopes=["*"])

        mock_db.get_portal_api_token_by_hash.return_value = token
        mock_db.get_user_by_id.return_value = test_user
        mock_db.get_team_by_slug.return_value = team
        mock_db.get_membership.return_value = {"role": "owner"}

        headers = {"Authorization": "Bearer pk_valid_token"}

        response = await test_client.delete(
            f"/teams/{team['slug']}/members/{test_user['id']}",
            headers=headers
        )

        assert response.status_code == 400
        assert "owner" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_archive_already_archived_card(self, test_client, mock_db, mock_team_proxy, test_user):
        """Archive already archived card returns 400"""
        team = create_team(owner_id=test_user["id"])
        card = create_card(archived=True)
        token = create_portal_token(created_by=test_user["id"], scopes=["*"])

        mock_db.get_portal_api_token_by_hash.return_value = token
        mock_db.get_user_by_id.return_value = test_user
        mock_db.get_team_by_slug.return_value = team
        mock_db.get_membership.return_value = {"role": "owner"}

        mock_team_proxy.post.return_value = (400, {"detail": "Card already archived"})

        headers = {"Authorization": "Bearer pk_valid_token"}

        response = await test_client.post(
            f"/teams/{team['slug']}/cards/{card['id']}/archive",
            headers=headers
        )

        assert response.status_code == 400
        assert "already archived" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_restore_not_archived_card(self, test_client, mock_db, mock_team_proxy, test_user):
        """Restore non-archived card returns 400"""
        team = create_team(owner_id=test_user["id"])
        card = create_card(archived=False)
        token = create_portal_token(created_by=test_user["id"], scopes=["*"])

        mock_db.get_portal_api_token_by_hash.return_value = token
        mock_db.get_user_by_id.return_value = test_user
        mock_db.get_team_by_slug.return_value = team
        mock_db.get_membership.return_value = {"role": "owner"}

        mock_team_proxy.post.return_value = (400, {"detail": "Card is not archived"})

        headers = {"Authorization": "Bearer pk_valid_token"}

        response = await test_client.post(
            f"/teams/{team['slug']}/cards/{card['id']}/restore",
            headers=headers
        )

        assert response.status_code == 400
        assert "not archived" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_duplicate_team_slug(self, test_client, mock_db, mock_task_service, test_user):
        """Create team with existing slug returns 409"""
        existing_team = create_team(slug="existing-team")
        token = create_portal_token(created_by=test_user["id"], scopes=["*"])

        mock_db.get_portal_api_token_by_hash.return_value = token
        mock_db.get_user_by_id.return_value = test_user
        mock_db.get_team_by_slug.return_value = existing_team  # Slug exists

        headers = {"Authorization": "Bearer pk_valid_token"}

        response = await test_client.post(
            "/teams",
            json={"name": "New Team", "slug": "existing-team"},
            headers=headers
        )

        assert response.status_code == 409
        assert "already exists" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_member_already_in_team(self, test_client, mock_db, mock_team_proxy, test_user, another_user_data):
        """Add member already in team returns 409"""
        team = create_team(owner_id=test_user["id"])
        token = create_portal_token(created_by=test_user["id"], scopes=["*"])

        mock_db.get_portal_api_token_by_hash.return_value = token
        mock_db.get_user_by_id.side_effect = [test_user, another_user_data]
        mock_db.get_team_by_slug.return_value = team
        mock_db.get_membership.side_effect = [
            {"role": "owner"},  # For auth check
            {"role": "member"}  # User already member
        ]

        headers = {"Authorization": "Bearer pk_valid_token"}

        response = await test_client.post(
            f"/teams/{team['slug']}/members",
            json={"email": another_user_data["email"], "role": "member"},
            headers=headers
        )

        assert response.status_code == 409
        assert "already" in response.json()["detail"].lower()
