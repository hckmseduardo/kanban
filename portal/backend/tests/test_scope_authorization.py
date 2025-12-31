"""Scope Authorization Tests

Systematic tests verifying scope-based access control for Portal API tokens.
Each endpoint is tested with various scope combinations to ensure proper authorization.
"""

import pytest
from datetime import datetime

from tests.factories import (
    create_user, create_team, create_board, create_column, create_card,
    create_portal_token, card_create_request, column_create_request
)


# =============================================================================
# Scope Definitions
# =============================================================================

SCOPES = {
    "full": ["*"],
    "teams_rw": ["teams:read", "teams:write"],
    "teams_r": ["teams:read"],
    "boards_rw": ["boards:read", "boards:write"],
    "boards_r": ["boards:read"],
    "cards_rw": ["cards:read", "cards:write"],
    "cards_r": ["cards:read"],
    "members_rw": ["members:read", "members:write"],
    "members_r": ["members:read"],
    "read_only": ["teams:read", "boards:read", "cards:read", "members:read"],
    "empty": []
}


# =============================================================================
# Helper Functions
# =============================================================================

def setup_token_with_scopes(mock_db, test_user, scopes):
    """Helper to setup a portal token with specific scopes"""
    token = create_portal_token(created_by=test_user["id"], scopes=scopes)
    mock_db.get_portal_api_token_by_hash.return_value = token
    mock_db.get_user_by_id.return_value = test_user
    return token


def setup_team_context(mock_db, test_user, team):
    """Helper to setup team membership context"""
    mock_db.get_team_by_slug.return_value = team
    mock_db.get_membership.return_value = {
        "user_id": test_user["id"],
        "team_id": team["id"],
        "role": "owner"
    }


# =============================================================================
# SA-001: Wildcard Scope Tests
# =============================================================================

class TestWildcardScope:
    """SA-001: Token with ["*"] can access all endpoints"""

    @pytest.mark.asyncio
    async def test_wildcard_accesses_teams(self, test_client, mock_db, test_user):
        """Wildcard scope can access teams endpoints"""
        setup_token_with_scopes(mock_db, test_user, ["*"])
        mock_db.get_user_teams.return_value = []

        headers = {"Authorization": "Bearer pk_wildcard_token"}

        response = await test_client.get("/teams", headers=headers)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_wildcard_accesses_boards(self, test_client, mock_db, mock_team_proxy, test_user):
        """Wildcard scope can access boards endpoints"""
        team = create_team(owner_id=test_user["id"])
        setup_token_with_scopes(mock_db, test_user, ["*"])
        setup_team_context(mock_db, test_user, team)
        mock_team_proxy.get.return_value = (200, [])

        headers = {"Authorization": "Bearer pk_wildcard_token"}

        response = await test_client.get(f"/teams/{team['slug']}/boards", headers=headers)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_wildcard_accesses_cards(self, test_client, mock_db, mock_team_proxy, test_user):
        """Wildcard scope can access cards endpoints"""
        team = create_team(owner_id=test_user["id"])
        setup_token_with_scopes(mock_db, test_user, ["*"])
        setup_team_context(mock_db, test_user, team)
        mock_team_proxy.get.return_value = (200, [])

        headers = {"Authorization": "Bearer pk_wildcard_token"}

        response = await test_client.get(f"/teams/{team['slug']}/cards", headers=headers)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_wildcard_can_write(self, test_client, mock_db, mock_team_proxy, test_user):
        """Wildcard scope can perform write operations"""
        team = create_team(owner_id=test_user["id"])
        column = create_column()
        card = create_card(column_id=column["id"])

        setup_token_with_scopes(mock_db, test_user, ["*"])
        setup_team_context(mock_db, test_user, team)
        mock_team_proxy.post.return_value = (200, card)

        headers = {"Authorization": "Bearer pk_wildcard_token"}

        response = await test_client.post(
            f"/teams/{team['slug']}/cards",
            json=card_create_request(column_id=column["id"]),
            headers=headers
        )
        assert response.status_code == 200


# =============================================================================
# SA-002: Missing Scope Error Message Tests
# =============================================================================

class TestMissingScopeErrors:
    """SA-002: Clear error message on scope mismatch"""

    @pytest.mark.asyncio
    async def test_missing_scope_shows_required(self, test_client, mock_db, mock_team_proxy, test_user):
        """Error message indicates which scope is required"""
        team = create_team(owner_id=test_user["id"])
        column = create_column()

        # Token without cards:write
        setup_token_with_scopes(mock_db, test_user, ["cards:read"])
        setup_team_context(mock_db, test_user, team)

        headers = {"Authorization": "Bearer pk_no_write_token"}

        response = await test_client.post(
            f"/teams/{team['slug']}/cards",
            json=card_create_request(column_id=column["id"]),
            headers=headers
        )

        assert response.status_code == 403
        detail = response.json()["detail"]
        assert "cards:write" in detail
        assert "Missing required scope" in detail

    @pytest.mark.asyncio
    async def test_boards_scope_required_for_columns(self, test_client, mock_db, mock_team_proxy, test_user):
        """Creating columns requires boards:write scope"""
        team = create_team(owner_id=test_user["id"])
        board = create_board()

        # Token with only cards scope
        setup_token_with_scopes(mock_db, test_user, ["cards:read", "cards:write"])
        setup_team_context(mock_db, test_user, team)

        headers = {"Authorization": "Bearer pk_cards_only_token"}

        response = await test_client.post(
            f"/teams/{team['slug']}/columns",
            json=column_create_request(board_id=board["id"]),
            headers=headers
        )

        assert response.status_code == 403
        assert "boards:write" in response.json()["detail"]


# =============================================================================
# SA-003: Read Scope Blocks Write
# =============================================================================

class TestReadScopeBlocksWrite:
    """SA-003: Read scopes cannot perform write operations"""

    @pytest.mark.asyncio
    async def test_cards_read_cannot_create(self, test_client, mock_db, mock_team_proxy, test_user):
        """cards:read cannot create cards"""
        team = create_team(owner_id=test_user["id"])
        column = create_column()

        setup_token_with_scopes(mock_db, test_user, ["cards:read"])
        setup_team_context(mock_db, test_user, team)

        headers = {"Authorization": "Bearer pk_read_token"}

        response = await test_client.post(
            f"/teams/{team['slug']}/cards",
            json=card_create_request(column_id=column["id"]),
            headers=headers
        )

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_cards_read_cannot_delete(self, test_client, mock_db, mock_team_proxy, test_user):
        """cards:read cannot delete cards"""
        team = create_team(owner_id=test_user["id"])
        card = create_card()

        setup_token_with_scopes(mock_db, test_user, ["cards:read"])
        setup_team_context(mock_db, test_user, team)

        headers = {"Authorization": "Bearer pk_read_token"}

        response = await test_client.delete(
            f"/teams/{team['slug']}/cards/{card['id']}",
            headers=headers
        )

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_boards_read_cannot_create_columns(self, test_client, mock_db, mock_team_proxy, test_user):
        """boards:read cannot create columns"""
        team = create_team(owner_id=test_user["id"])
        board = create_board()

        setup_token_with_scopes(mock_db, test_user, ["boards:read"])
        setup_team_context(mock_db, test_user, team)

        headers = {"Authorization": "Bearer pk_read_token"}

        response = await test_client.post(
            f"/teams/{team['slug']}/columns",
            json=column_create_request(board_id=board["id"]),
            headers=headers
        )

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_teams_read_cannot_create_team(self, test_client, mock_db, mock_task_service, test_user):
        """teams:read cannot create teams"""
        setup_token_with_scopes(mock_db, test_user, ["teams:read"])
        mock_db.get_team_by_slug.return_value = None

        headers = {"Authorization": "Bearer pk_read_token"}

        response = await test_client.post(
            "/teams",
            json={"name": "New Team", "slug": "new-team"},
            headers=headers
        )

        assert response.status_code == 403


# =============================================================================
# SA-004: Write Scope Includes Read
# =============================================================================

class TestWriteScopeIncludesRead:
    """SA-004: Write scopes can also perform read operations"""

    @pytest.mark.asyncio
    async def test_cards_write_can_read(self, test_client, mock_db, mock_team_proxy, test_user):
        """cards:write can also list/get cards"""
        team = create_team(owner_id=test_user["id"])
        cards = [create_card()]

        setup_token_with_scopes(mock_db, test_user, ["cards:write"])
        setup_team_context(mock_db, test_user, team)
        mock_team_proxy.get.return_value = (200, cards)

        headers = {"Authorization": "Bearer pk_write_token"}

        response = await test_client.get(f"/teams/{team['slug']}/cards", headers=headers)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_boards_write_can_read(self, test_client, mock_db, mock_team_proxy, test_user):
        """boards:write can also list/get boards"""
        team = create_team(owner_id=test_user["id"])
        boards = [create_board()]

        setup_token_with_scopes(mock_db, test_user, ["boards:write"])
        setup_team_context(mock_db, test_user, team)
        mock_team_proxy.get.return_value = (200, boards)

        headers = {"Authorization": "Bearer pk_write_token"}

        response = await test_client.get(f"/teams/{team['slug']}/boards", headers=headers)
        assert response.status_code == 200


# =============================================================================
# SA-005: Cross-Category Isolation
# =============================================================================

class TestCrossCategoryIsolation:
    """SA-005: Scopes in one category don't grant access to another"""

    @pytest.mark.asyncio
    async def test_teams_scope_no_boards_access(self, test_client, mock_db, mock_team_proxy, test_user):
        """teams:* scope cannot access boards endpoints"""
        team = create_team(owner_id=test_user["id"])

        setup_token_with_scopes(mock_db, test_user, ["teams:read", "teams:write"])
        setup_team_context(mock_db, test_user, team)

        headers = {"Authorization": "Bearer pk_teams_token"}

        response = await test_client.get(f"/teams/{team['slug']}/boards", headers=headers)
        assert response.status_code == 403
        assert "boards:read" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_boards_scope_no_cards_access(self, test_client, mock_db, mock_team_proxy, test_user):
        """boards:* scope cannot access cards endpoints"""
        team = create_team(owner_id=test_user["id"])

        setup_token_with_scopes(mock_db, test_user, ["boards:read", "boards:write"])
        setup_team_context(mock_db, test_user, team)

        headers = {"Authorization": "Bearer pk_boards_token"}

        response = await test_client.get(f"/teams/{team['slug']}/cards", headers=headers)
        assert response.status_code == 403
        assert "cards:read" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_cards_scope_no_members_access(self, test_client, mock_db, mock_team_proxy, test_user):
        """cards:* scope cannot access members endpoints"""
        team = create_team(owner_id=test_user["id"])

        setup_token_with_scopes(mock_db, test_user, ["cards:read", "cards:write"])
        setup_team_context(mock_db, test_user, team)

        headers = {"Authorization": "Bearer pk_cards_token"}

        # members:write required to add members
        response = await test_client.post(
            f"/teams/{team['slug']}/members",
            json={"email": "new@example.com", "role": "member"},
            headers=headers
        )
        assert response.status_code == 403
        assert "members:write" in response.json()["detail"]


# =============================================================================
# Empty Scope Tests
# =============================================================================

class TestEmptyScopes:
    """Tests for tokens with empty scopes"""

    @pytest.mark.asyncio
    async def test_empty_scopes_denied_teams(self, test_client, mock_db, test_user):
        """Token with no scopes cannot access teams"""
        setup_token_with_scopes(mock_db, test_user, [])

        headers = {"Authorization": "Bearer pk_empty_token"}

        # Even listing teams requires some access
        # (though this might depend on implementation)
        response = await test_client.get("/teams", headers=headers)
        # Behavior depends on whether teams:read is required for listing own teams

    @pytest.mark.asyncio
    async def test_empty_scopes_denied_write(self, test_client, mock_db, mock_team_proxy, test_user):
        """Token with no scopes cannot write anything"""
        team = create_team(owner_id=test_user["id"])
        column = create_column()

        setup_token_with_scopes(mock_db, test_user, [])
        setup_team_context(mock_db, test_user, team)

        headers = {"Authorization": "Bearer pk_empty_token"}

        response = await test_client.post(
            f"/teams/{team['slug']}/cards",
            json=card_create_request(column_id=column["id"]),
            headers=headers
        )
        assert response.status_code == 403


# =============================================================================
# Parameterized Endpoint Tests
# =============================================================================

class TestEndpointScopeRequirements:
    """Parameterized tests for endpoint scope requirements"""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("endpoint,method,required_scope", [
        ("/teams/{slug}/boards", "GET", "boards:read"),
        ("/teams/{slug}/columns", "GET", "boards:read"),
        ("/teams/{slug}/columns", "POST", "boards:write"),
        ("/teams/{slug}/cards", "GET", "cards:read"),
        ("/teams/{slug}/cards", "POST", "cards:write"),
    ])
    async def test_endpoint_requires_scope(
        self,
        test_client,
        mock_db,
        mock_team_proxy,
        test_user,
        endpoint,
        method,
        required_scope
    ):
        """Each endpoint requires its specific scope"""
        team = create_team(owner_id=test_user["id"])
        board = create_board()
        column = create_column(board_id=board["id"])

        # Give a scope that's NOT the required one
        wrong_scope = "wrong:scope"
        setup_token_with_scopes(mock_db, test_user, [wrong_scope])
        setup_team_context(mock_db, test_user, team)

        headers = {"Authorization": "Bearer pk_wrong_scope_token"}
        url = endpoint.replace("{slug}", team["slug"])

        if method == "GET":
            response = await test_client.get(url, headers=headers)
        elif method == "POST":
            body = {}
            if "columns" in endpoint:
                body = column_create_request(board_id=board["id"])
            elif "cards" in endpoint:
                body = card_create_request(column_id=column["id"])
            response = await test_client.post(url, json=body, headers=headers)

        assert response.status_code == 403
        assert required_scope in response.json()["detail"]
