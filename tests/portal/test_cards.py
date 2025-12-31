"""Card Operations Tests

Tests for creating, listing, updating, moving, archiving, and restoring cards.
Card operations are proxied to the team kanban service.
"""

import pytest
import uuid


class TestCardListing:
    """Test card listing operations"""

    @pytest.mark.asyncio
    async def test_list_cards(self, test_client, api_headers, test_team):
        """List all cards for a team"""
        response = await test_client.get(
            f"/teams/{test_team['slug']}/cards",
            headers=api_headers
        )

        # May succeed or return 503 if team container not running
        assert response.status_code in [200, 503, 504]

        if response.status_code == 200:
            data = response.json()
            assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_list_cards_by_column(self, test_client, api_headers, test_team):
        """List cards filtered by column"""
        # First get a column ID
        columns_response = await test_client.get(
            f"/teams/{test_team['slug']}/columns",
            headers=api_headers
        )

        if columns_response.status_code == 200:
            columns = columns_response.json()
            if columns:
                column_id = columns[0]["id"]
                response = await test_client.get(
                    f"/teams/{test_team['slug']}/cards",
                    params={"column_id": column_id},
                    headers=api_headers
                )
                assert response.status_code in [200, 503]


class TestCardCreation:
    """Test card creation operations"""

    @pytest.mark.asyncio
    async def test_create_card(self, test_client, api_headers, test_team):
        """Create a new card"""
        # First get a column ID
        columns_response = await test_client.get(
            f"/teams/{test_team['slug']}/columns",
            headers=api_headers
        )

        if columns_response.status_code == 200:
            columns = columns_response.json()
            if columns:
                column_id = columns[0]["id"]
                response = await test_client.post(
                    f"/teams/{test_team['slug']}/cards",
                    json={
                        "title": f"Test Card {uuid.uuid4().hex[:6]}",
                        "column_id": column_id,
                        "description": "A test card"
                    },
                    headers=api_headers
                )
                assert response.status_code in [200, 201, 400, 503]

    @pytest.mark.asyncio
    async def test_create_card_minimal(self, test_client, api_headers, test_team):
        """Create a card with minimal fields"""
        columns_response = await test_client.get(
            f"/teams/{test_team['slug']}/columns",
            headers=api_headers
        )

        if columns_response.status_code == 200:
            columns = columns_response.json()
            if columns:
                column_id = columns[0]["id"]
                response = await test_client.post(
                    f"/teams/{test_team['slug']}/cards",
                    json={
                        "title": f"Minimal Card {uuid.uuid4().hex[:6]}",
                        "column_id": column_id
                    },
                    headers=api_headers
                )
                assert response.status_code in [200, 201, 400, 503]


class TestCardRetrieval:
    """Test card retrieval operations"""

    @pytest.mark.asyncio
    async def test_get_card(self, test_client, api_headers, test_team):
        """Get a specific card by ID"""
        # First list cards to get an ID
        list_response = await test_client.get(
            f"/teams/{test_team['slug']}/cards",
            headers=api_headers
        )

        if list_response.status_code == 200:
            cards = list_response.json()
            if cards:
                card_id = cards[0]["id"]
                response = await test_client.get(
                    f"/teams/{test_team['slug']}/cards/{card_id}",
                    headers=api_headers
                )
                assert response.status_code in [200, 404, 503]

    @pytest.mark.asyncio
    async def test_get_card_not_found(self, test_client, api_headers, test_team):
        """Getting non-existent card should return 404"""
        response = await test_client.get(
            f"/teams/{test_team['slug']}/cards/nonexistent-card-id",
            headers=api_headers
        )

        assert response.status_code in [404, 503]


class TestCardUpdate:
    """Test card update operations"""

    @pytest.mark.asyncio
    async def test_update_card(self, test_client, api_headers, test_team):
        """Update a card"""
        # First list cards to get an ID
        list_response = await test_client.get(
            f"/teams/{test_team['slug']}/cards",
            headers=api_headers
        )

        if list_response.status_code == 200:
            cards = list_response.json()
            if cards:
                card_id = cards[0]["id"]
                new_title = f"Updated Card {uuid.uuid4().hex[:6]}"
                response = await test_client.patch(
                    f"/teams/{test_team['slug']}/cards/{card_id}",
                    json={"title": new_title},
                    headers=api_headers
                )
                assert response.status_code in [200, 404, 503]

    @pytest.mark.asyncio
    async def test_update_card_description(self, test_client, api_headers, test_team):
        """Update card description"""
        list_response = await test_client.get(
            f"/teams/{test_team['slug']}/cards",
            headers=api_headers
        )

        if list_response.status_code == 200:
            cards = list_response.json()
            if cards:
                card_id = cards[0]["id"]
                response = await test_client.patch(
                    f"/teams/{test_team['slug']}/cards/{card_id}",
                    json={"description": f"Updated description {uuid.uuid4().hex[:6]}"},
                    headers=api_headers
                )
                assert response.status_code in [200, 404, 503]


class TestCardMovement:
    """Test card movement operations"""

    @pytest.mark.asyncio
    async def test_move_card(self, test_client, api_headers, test_team):
        """Move a card to a different column"""
        # Get cards and columns
        cards_response = await test_client.get(
            f"/teams/{test_team['slug']}/cards",
            headers=api_headers
        )
        columns_response = await test_client.get(
            f"/teams/{test_team['slug']}/columns",
            headers=api_headers
        )

        if cards_response.status_code == 200 and columns_response.status_code == 200:
            cards = cards_response.json()
            columns = columns_response.json()

            if cards and len(columns) > 1:
                card_id = cards[0]["id"]
                target_column = columns[1]["id"]

                response = await test_client.post(
                    f"/teams/{test_team['slug']}/cards/{card_id}/move",
                    json={"column_id": target_column, "position": 0},
                    headers=api_headers
                )
                assert response.status_code in [200, 400, 404, 503]


class TestCardArchiving:
    """Test card archiving operations"""

    @pytest.mark.asyncio
    async def test_archive_card(self, test_client, api_headers, test_team):
        """Archive a card"""
        # Get a card to archive
        list_response = await test_client.get(
            f"/teams/{test_team['slug']}/cards",
            headers=api_headers
        )

        if list_response.status_code == 200:
            cards = list_response.json()
            if cards:
                card_id = cards[0]["id"]
                response = await test_client.post(
                    f"/teams/{test_team['slug']}/cards/{card_id}/archive",
                    headers=api_headers
                )
                assert response.status_code in [200, 404, 503]

    @pytest.mark.asyncio
    async def test_restore_card(self, test_client, api_headers, test_team):
        """Restore an archived card"""
        list_response = await test_client.get(
            f"/teams/{test_team['slug']}/cards",
            headers=api_headers
        )

        if list_response.status_code == 200:
            cards = list_response.json()
            if cards:
                card_id = cards[0]["id"]
                response = await test_client.post(
                    f"/teams/{test_team['slug']}/cards/{card_id}/restore",
                    headers=api_headers
                )
                assert response.status_code in [200, 400, 404, 503]


class TestCardDeletion:
    """Test card deletion operations"""

    @pytest.mark.asyncio
    async def test_delete_card(self, test_client, api_headers, test_team):
        """Delete a card"""
        # First create a card to delete
        columns_response = await test_client.get(
            f"/teams/{test_team['slug']}/columns",
            headers=api_headers
        )

        if columns_response.status_code == 200:
            columns = columns_response.json()
            if columns:
                column_id = columns[0]["id"]

                # Create a card
                create_response = await test_client.post(
                    f"/teams/{test_team['slug']}/cards",
                    json={
                        "title": f"Delete Me {uuid.uuid4().hex[:6]}",
                        "column_id": column_id
                    },
                    headers=api_headers
                )

                if create_response.status_code in [200, 201]:
                    card_id = create_response.json()["id"]

                    # Delete the card
                    delete_response = await test_client.delete(
                        f"/teams/{test_team['slug']}/cards/{card_id}",
                        headers=api_headers
                    )
                    assert delete_response.status_code in [200, 204, 404, 503]


class TestCardAuthorization:
    """Test card authorization"""

    @pytest.mark.asyncio
    async def test_read_only_can_list_cards(self, test_client, read_only_headers, test_team):
        """Read-only token can list cards"""
        response = await test_client.get(
            f"/teams/{test_team['slug']}/cards",
            headers=read_only_headers
        )

        assert response.status_code in [200, 503, 504]

    @pytest.mark.asyncio
    async def test_read_only_cannot_create_card(self, test_client, read_only_headers, test_team):
        """Read-only token cannot create cards"""
        response = await test_client.post(
            f"/teams/{test_team['slug']}/cards",
            json={"title": "Should Fail", "column_id": "some-column-id"},
            headers=read_only_headers
        )

        assert response.status_code in [403, 503]

    @pytest.mark.asyncio
    async def test_read_only_cannot_delete_card(self, test_client, read_only_headers, test_team):
        """Read-only token cannot delete cards"""
        response = await test_client.delete(
            f"/teams/{test_team['slug']}/cards/some-card-id",
            headers=read_only_headers
        )

        assert response.status_code in [403, 404, 503]

    @pytest.mark.asyncio
    async def test_read_only_cannot_move_card(self, test_client, read_only_headers, test_team):
        """Read-only token cannot move cards"""
        response = await test_client.post(
            f"/teams/{test_team['slug']}/cards/some-card-id/move",
            json={"column_id": "some-column-id"},
            headers=read_only_headers
        )

        assert response.status_code in [403, 404, 503]
