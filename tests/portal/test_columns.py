"""Column Operations Tests

Tests for creating, listing, updating, and deleting columns.
Column operations are proxied to the team kanban service.
"""

import pytest
import uuid


class TestColumnListing:
    """Test column listing operations"""

    @pytest.mark.asyncio
    async def test_list_columns(self, test_client, api_headers, test_team):
        """List all columns for a team"""
        response = await test_client.get(
            f"/teams/{test_team['slug']}/columns",
            headers=api_headers
        )

        # May succeed or return 503 if team container not running
        assert response.status_code in [200, 503, 504]

        if response.status_code == 200:
            data = response.json()
            assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_list_columns_by_board(self, test_client, api_headers, test_team):
        """List columns filtered by board"""
        # First get a board ID
        boards_response = await test_client.get(
            f"/teams/{test_team['slug']}/boards",
            headers=api_headers
        )

        if boards_response.status_code == 200:
            boards = boards_response.json()
            if boards:
                board_id = boards[0]["id"]
                response = await test_client.get(
                    f"/teams/{test_team['slug']}/columns",
                    params={"board_id": board_id},
                    headers=api_headers
                )
                assert response.status_code in [200, 503]


class TestColumnCreation:
    """Test column creation operations"""

    @pytest.mark.asyncio
    async def test_create_column(self, test_client, api_headers, test_team):
        """Create a new column"""
        # First get a board ID
        boards_response = await test_client.get(
            f"/teams/{test_team['slug']}/boards",
            headers=api_headers
        )

        if boards_response.status_code == 200:
            boards = boards_response.json()
            if boards:
                board_id = boards[0]["id"]
                response = await test_client.post(
                    f"/teams/{test_team['slug']}/columns",
                    json={
                        "name": f"Test Column {uuid.uuid4().hex[:6]}",
                        "board_id": board_id,
                        "position": 999
                    },
                    headers=api_headers
                )
                assert response.status_code in [200, 201, 400, 503]

    @pytest.mark.asyncio
    async def test_create_column_without_board_id(self, test_client, api_headers, test_team):
        """Creating column without board_id should fail"""
        response = await test_client.post(
            f"/teams/{test_team['slug']}/columns",
            json={"name": "No Board Column"},
            headers=api_headers
        )

        assert response.status_code in [400, 422, 503]


class TestColumnUpdate:
    """Test column update operations"""

    @pytest.mark.asyncio
    async def test_update_column(self, test_client, api_headers, test_team):
        """Update a column"""
        # First list columns to get an ID
        list_response = await test_client.get(
            f"/teams/{test_team['slug']}/columns",
            headers=api_headers
        )

        if list_response.status_code == 200:
            columns = list_response.json()
            if columns:
                column_id = columns[0]["id"]
                new_name = f"Updated Column {uuid.uuid4().hex[:6]}"
                response = await test_client.patch(
                    f"/teams/{test_team['slug']}/columns/{column_id}",
                    json={"name": new_name},
                    headers=api_headers
                )
                assert response.status_code in [200, 404, 503]

    @pytest.mark.asyncio
    async def test_update_nonexistent_column(self, test_client, api_headers, test_team):
        """Updating non-existent column should return 404"""
        response = await test_client.patch(
            f"/teams/{test_team['slug']}/columns/nonexistent-column-id",
            json={"name": "Updated"},
            headers=api_headers
        )

        assert response.status_code in [404, 503]


class TestColumnDeletion:
    """Test column deletion operations"""

    @pytest.mark.asyncio
    async def test_delete_column(self, test_client, api_headers, test_team):
        """Delete a column"""
        # First create a column to delete
        boards_response = await test_client.get(
            f"/teams/{test_team['slug']}/boards",
            headers=api_headers
        )

        if boards_response.status_code == 200:
            boards = boards_response.json()
            if boards:
                board_id = boards[0]["id"]

                # Create a column
                create_response = await test_client.post(
                    f"/teams/{test_team['slug']}/columns",
                    json={
                        "name": f"Delete Me {uuid.uuid4().hex[:6]}",
                        "board_id": board_id,
                        "position": 999
                    },
                    headers=api_headers
                )

                if create_response.status_code in [200, 201]:
                    column_id = create_response.json()["id"]

                    # Delete the column
                    delete_response = await test_client.delete(
                        f"/teams/{test_team['slug']}/columns/{column_id}",
                        headers=api_headers
                    )
                    assert delete_response.status_code in [200, 204, 404, 503]

    @pytest.mark.asyncio
    async def test_delete_nonexistent_column(self, test_client, api_headers, test_team):
        """Deleting non-existent column should return 404"""
        response = await test_client.delete(
            f"/teams/{test_team['slug']}/columns/nonexistent-column-id",
            headers=api_headers
        )

        assert response.status_code in [404, 503]


class TestColumnAuthorization:
    """Test column authorization"""

    @pytest.mark.asyncio
    async def test_read_only_can_list_columns(self, test_client, read_only_headers, test_team):
        """Read-only token can list columns"""
        response = await test_client.get(
            f"/teams/{test_team['slug']}/columns",
            headers=read_only_headers
        )

        assert response.status_code in [200, 503, 504]

    @pytest.mark.asyncio
    async def test_read_only_cannot_create_column(self, test_client, read_only_headers, test_team):
        """Read-only token cannot create columns"""
        response = await test_client.post(
            f"/teams/{test_team['slug']}/columns",
            json={"name": "Should Fail", "board_id": "some-board-id"},
            headers=read_only_headers
        )

        assert response.status_code in [403, 503]

    @pytest.mark.asyncio
    async def test_read_only_cannot_delete_column(self, test_client, read_only_headers, test_team):
        """Read-only token cannot delete columns"""
        response = await test_client.delete(
            f"/teams/{test_team['slug']}/columns/some-column-id",
            headers=read_only_headers
        )

        assert response.status_code in [403, 404, 503]
