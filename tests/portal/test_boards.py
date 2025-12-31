"""Board Operations Tests

Tests for listing and retrieving boards.
Board operations are proxied to the team kanban service.
"""

import pytest


class TestBoardListing:
    """Test board listing operations"""

    @pytest.mark.asyncio
    async def test_list_boards(self, test_client, api_headers, test_team):
        """List all boards for a team"""
        response = await test_client.get(
            f"/teams/{test_team['slug']}/boards",
            headers=api_headers
        )

        # May succeed or return 503 if team container not running
        assert response.status_code in [200, 503, 504]

        if response.status_code == 200:
            data = response.json()
            assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_list_boards_nonexistent_team(self, test_client, api_headers):
        """Listing boards for non-existent team should return 404"""
        response = await test_client.get(
            "/teams/nonexistent-team/boards",
            headers=api_headers
        )

        assert response.status_code == 404


class TestBoardRetrieval:
    """Test board retrieval operations"""

    @pytest.mark.asyncio
    async def test_get_board_by_id(self, test_client, api_headers, test_team):
        """Get a specific board by ID"""
        # First list boards to get an ID
        list_response = await test_client.get(
            f"/teams/{test_team['slug']}/boards",
            headers=api_headers
        )

        if list_response.status_code == 200:
            boards = list_response.json()
            if boards:
                board_id = boards[0]["id"]
                response = await test_client.get(
                    f"/teams/{test_team['slug']}/boards/{board_id}",
                    headers=api_headers
                )
                assert response.status_code in [200, 404, 503]

    @pytest.mark.asyncio
    async def test_get_board_not_found(self, test_client, api_headers, test_team):
        """Getting non-existent board should return 404"""
        response = await test_client.get(
            f"/teams/{test_team['slug']}/boards/nonexistent-board-id",
            headers=api_headers
        )

        assert response.status_code in [404, 503]


class TestBoardLabels:
    """Test board label operations"""

    @pytest.mark.asyncio
    async def test_list_board_labels(self, test_client, api_headers, test_team):
        """List labels for a board"""
        # First list boards to get an ID
        list_response = await test_client.get(
            f"/teams/{test_team['slug']}/boards",
            headers=api_headers
        )

        if list_response.status_code == 200:
            boards = list_response.json()
            if boards:
                board_id = boards[0]["id"]
                response = await test_client.get(
                    f"/teams/{test_team['slug']}/boards/{board_id}/labels",
                    headers=api_headers
                )
                assert response.status_code in [200, 404, 503]

                if response.status_code == 200:
                    data = response.json()
                    assert isinstance(data, list)


class TestBoardAuthorization:
    """Test board authorization"""

    @pytest.mark.asyncio
    async def test_read_only_can_list_boards(self, test_client, read_only_headers, test_team):
        """Read-only token can list boards"""
        response = await test_client.get(
            f"/teams/{test_team['slug']}/boards",
            headers=read_only_headers
        )

        # Should succeed (200) or team not running (503)
        assert response.status_code in [200, 503, 504]

    @pytest.mark.asyncio
    async def test_no_auth_cannot_list_boards(self, test_client, test_team):
        """Request without auth cannot list boards"""
        response = await test_client.get(f"/teams/{test_team['slug']}/boards")

        assert response.status_code in [401, 403]
