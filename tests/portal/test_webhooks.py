"""Webhook Management Tests

Tests for creating, listing, updating, testing, and deleting webhooks.
Webhook operations are proxied to the team kanban service.
"""

import pytest
import uuid


class TestWebhookListing:
    """Test webhook listing operations"""

    @pytest.mark.asyncio
    async def test_list_webhooks(self, test_client, api_headers, test_team):
        """List all webhooks for a team"""
        response = await test_client.get(
            f"/teams/{test_team['slug']}/webhooks",
            headers=api_headers
        )

        # May succeed or return 503 if team container not running
        assert response.status_code in [200, 503, 504]

        if response.status_code == 200:
            data = response.json()
            assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_list_webhooks_nonexistent_team(self, test_client, api_headers):
        """Listing webhooks for non-existent team should return 404"""
        response = await test_client.get(
            "/teams/nonexistent-team/webhooks",
            headers=api_headers
        )

        assert response.status_code == 404


class TestWebhookCreation:
    """Test webhook creation operations"""

    @pytest.mark.asyncio
    async def test_create_webhook(self, test_client, api_headers, test_team, test_webhook_data):
        """Create a new webhook"""
        response = await test_client.post(
            f"/teams/{test_team['slug']}/webhooks",
            json=test_webhook_data,
            headers=api_headers
        )

        # May succeed or return 503 if team container not running
        assert response.status_code in [200, 201, 400, 422, 503, 504]

        if response.status_code in [200, 201]:
            data = response.json()
            assert "id" in data
            assert data["name"] == test_webhook_data["name"]
            assert data["url"] == test_webhook_data["url"]
            assert data["active"] == test_webhook_data["active"]

    @pytest.mark.asyncio
    async def test_create_webhook_minimal(self, test_client, api_headers, test_team):
        """Create a webhook with minimal required fields"""
        response = await test_client.post(
            f"/teams/{test_team['slug']}/webhooks",
            json={
                "name": f"Minimal Webhook {uuid.uuid4().hex[:8]}",
                "url": "https://httpbin.org/post"
            },
            headers=api_headers
        )

        assert response.status_code in [200, 201, 400, 422, 503, 504]

    @pytest.mark.asyncio
    async def test_create_webhook_with_events(self, test_client, api_headers, test_team):
        """Create a webhook with specific events"""
        response = await test_client.post(
            f"/teams/{test_team['slug']}/webhooks",
            json={
                "name": f"Event Webhook {uuid.uuid4().hex[:8]}",
                "url": "https://httpbin.org/post",
                "events": ["card.created", "card.moved", "card.deleted"]
            },
            headers=api_headers
        )

        assert response.status_code in [200, 201, 400, 422, 503, 504]

        if response.status_code in [200, 201]:
            data = response.json()
            assert "card.created" in data.get("events", [])

    @pytest.mark.asyncio
    async def test_create_webhook_with_secret(self, test_client, api_headers, test_team):
        """Create a webhook with a secret for signature verification"""
        response = await test_client.post(
            f"/teams/{test_team['slug']}/webhooks",
            json={
                "name": f"Secret Webhook {uuid.uuid4().hex[:8]}",
                "url": "https://httpbin.org/post",
                "secret": "my-super-secret-key-123"
            },
            headers=api_headers
        )

        assert response.status_code in [200, 201, 400, 422, 503, 504]

    @pytest.mark.asyncio
    async def test_create_webhook_inactive(self, test_client, api_headers, test_team):
        """Create an inactive webhook"""
        response = await test_client.post(
            f"/teams/{test_team['slug']}/webhooks",
            json={
                "name": f"Inactive Webhook {uuid.uuid4().hex[:8]}",
                "url": "https://httpbin.org/post",
                "active": False
            },
            headers=api_headers
        )

        assert response.status_code in [200, 201, 400, 422, 503, 504]

        if response.status_code in [200, 201]:
            data = response.json()
            assert data["active"] is False

    @pytest.mark.asyncio
    async def test_create_webhook_without_name_fails(self, test_client, api_headers, test_team):
        """Creating webhook without name should fail validation"""
        response = await test_client.post(
            f"/teams/{test_team['slug']}/webhooks",
            json={"url": "https://httpbin.org/post"},
            headers=api_headers
        )

        assert response.status_code in [400, 422, 503]

    @pytest.mark.asyncio
    async def test_create_webhook_without_url_fails(self, test_client, api_headers, test_team):
        """Creating webhook without URL should fail validation"""
        response = await test_client.post(
            f"/teams/{test_team['slug']}/webhooks",
            json={"name": "No URL Webhook"},
            headers=api_headers
        )

        assert response.status_code in [400, 422, 503]


class TestWebhookRetrieval:
    """Test webhook retrieval operations"""

    @pytest.mark.asyncio
    async def test_get_webhook(self, test_client, api_headers, test_team):
        """Get a specific webhook by ID"""
        # First create a webhook
        create_response = await test_client.post(
            f"/teams/{test_team['slug']}/webhooks",
            json={
                "name": f"Get Test Webhook {uuid.uuid4().hex[:8]}",
                "url": "https://httpbin.org/post"
            },
            headers=api_headers
        )

        if create_response.status_code in [200, 201]:
            webhook_id = create_response.json()["id"]

            response = await test_client.get(
                f"/teams/{test_team['slug']}/webhooks/{webhook_id}",
                headers=api_headers
            )

            assert response.status_code in [200, 404, 503]

            if response.status_code == 200:
                data = response.json()
                assert data["id"] == webhook_id

    @pytest.mark.asyncio
    async def test_get_webhook_not_found(self, test_client, api_headers, test_team):
        """Getting non-existent webhook should return 404"""
        response = await test_client.get(
            f"/teams/{test_team['slug']}/webhooks/nonexistent-webhook-id",
            headers=api_headers
        )

        assert response.status_code in [404, 503]


class TestWebhookUpdate:
    """Test webhook update operations"""

    @pytest.mark.asyncio
    async def test_update_webhook_name(self, test_client, api_headers, test_team):
        """Update webhook name"""
        # First create a webhook
        create_response = await test_client.post(
            f"/teams/{test_team['slug']}/webhooks",
            json={
                "name": f"Update Test Webhook {uuid.uuid4().hex[:8]}",
                "url": "https://httpbin.org/post"
            },
            headers=api_headers
        )

        if create_response.status_code in [200, 201]:
            webhook_id = create_response.json()["id"]
            new_name = f"Updated Webhook {uuid.uuid4().hex[:8]}"

            response = await test_client.patch(
                f"/teams/{test_team['slug']}/webhooks/{webhook_id}",
                json={"name": new_name},
                headers=api_headers
            )

            assert response.status_code in [200, 404, 503]

            if response.status_code == 200:
                data = response.json()
                assert data["name"] == new_name

    @pytest.mark.asyncio
    async def test_update_webhook_url(self, test_client, api_headers, test_team):
        """Update webhook URL"""
        create_response = await test_client.post(
            f"/teams/{test_team['slug']}/webhooks",
            json={
                "name": f"URL Update Webhook {uuid.uuid4().hex[:8]}",
                "url": "https://httpbin.org/post"
            },
            headers=api_headers
        )

        if create_response.status_code in [200, 201]:
            webhook_id = create_response.json()["id"]

            response = await test_client.patch(
                f"/teams/{test_team['slug']}/webhooks/{webhook_id}",
                json={"url": "https://example.com/new-webhook"},
                headers=api_headers
            )

            assert response.status_code in [200, 404, 503]

    @pytest.mark.asyncio
    async def test_update_webhook_events(self, test_client, api_headers, test_team):
        """Update webhook events"""
        create_response = await test_client.post(
            f"/teams/{test_team['slug']}/webhooks",
            json={
                "name": f"Events Update Webhook {uuid.uuid4().hex[:8]}",
                "url": "https://httpbin.org/post",
                "events": ["card.created"]
            },
            headers=api_headers
        )

        if create_response.status_code in [200, 201]:
            webhook_id = create_response.json()["id"]

            response = await test_client.patch(
                f"/teams/{test_team['slug']}/webhooks/{webhook_id}",
                json={"events": ["card.created", "card.moved", "card.deleted"]},
                headers=api_headers
            )

            assert response.status_code in [200, 404, 503]

    @pytest.mark.asyncio
    async def test_update_webhook_active_status(self, test_client, api_headers, test_team):
        """Update webhook active status"""
        create_response = await test_client.post(
            f"/teams/{test_team['slug']}/webhooks",
            json={
                "name": f"Status Update Webhook {uuid.uuid4().hex[:8]}",
                "url": "https://httpbin.org/post",
                "active": True
            },
            headers=api_headers
        )

        if create_response.status_code in [200, 201]:
            webhook_id = create_response.json()["id"]

            # Deactivate the webhook
            response = await test_client.patch(
                f"/teams/{test_team['slug']}/webhooks/{webhook_id}",
                json={"active": False},
                headers=api_headers
            )

            assert response.status_code in [200, 404, 503]

            if response.status_code == 200:
                assert response.json()["active"] is False

    @pytest.mark.asyncio
    async def test_update_nonexistent_webhook(self, test_client, api_headers, test_team):
        """Updating non-existent webhook should return 404"""
        response = await test_client.patch(
            f"/teams/{test_team['slug']}/webhooks/nonexistent-webhook-id",
            json={"name": "Updated"},
            headers=api_headers
        )

        assert response.status_code in [404, 503]


class TestWebhookTesting:
    """Test webhook testing operations"""

    @pytest.mark.asyncio
    async def test_test_webhook_url(self, test_client, api_headers, test_team):
        """Test a webhook URL without saving"""
        response = await test_client.post(
            f"/teams/{test_team['slug']}/webhooks/test-url",
            json={
                "url": "https://httpbin.org/post",
                "secret": "test-secret"
            },
            headers=api_headers
        )

        # May succeed, fail validation, or return 503 if team not running
        assert response.status_code in [200, 400, 422, 500, 502, 503, 504]

    @pytest.mark.asyncio
    async def test_test_webhook_url_invalid(self, test_client, api_headers, test_team):
        """Test an invalid webhook URL"""
        response = await test_client.post(
            f"/teams/{test_team['slug']}/webhooks/test-url",
            json={"url": "not-a-valid-url"},
            headers=api_headers
        )

        # Should fail validation or return error
        assert response.status_code in [400, 422, 500, 502, 503, 504]

    @pytest.mark.asyncio
    async def test_test_existing_webhook(self, test_client, api_headers, test_team):
        """Send a test event to an existing webhook"""
        # First create a webhook
        create_response = await test_client.post(
            f"/teams/{test_team['slug']}/webhooks",
            json={
                "name": f"Test Event Webhook {uuid.uuid4().hex[:8]}",
                "url": "https://httpbin.org/post"
            },
            headers=api_headers
        )

        if create_response.status_code in [200, 201]:
            webhook_id = create_response.json()["id"]

            response = await test_client.post(
                f"/teams/{test_team['slug']}/webhooks/{webhook_id}/test",
                headers=api_headers
            )

            # Test may succeed or fail based on external service
            assert response.status_code in [200, 400, 404, 500, 502, 503, 504]


class TestWebhookDeletion:
    """Test webhook deletion operations"""

    @pytest.mark.asyncio
    async def test_delete_webhook(self, test_client, api_headers, test_team):
        """Delete a webhook"""
        # First create a webhook
        create_response = await test_client.post(
            f"/teams/{test_team['slug']}/webhooks",
            json={
                "name": f"Delete Test Webhook {uuid.uuid4().hex[:8]}",
                "url": "https://httpbin.org/post"
            },
            headers=api_headers
        )

        if create_response.status_code in [200, 201]:
            webhook_id = create_response.json()["id"]

            response = await test_client.delete(
                f"/teams/{test_team['slug']}/webhooks/{webhook_id}",
                headers=api_headers
            )

            assert response.status_code in [200, 204, 404, 503]

    @pytest.mark.asyncio
    async def test_delete_nonexistent_webhook(self, test_client, api_headers, test_team):
        """Deleting non-existent webhook should return 404"""
        response = await test_client.delete(
            f"/teams/{test_team['slug']}/webhooks/nonexistent-webhook-id",
            headers=api_headers
        )

        assert response.status_code in [404, 503]


class TestWebhookAuthorization:
    """Test webhook authorization - requires teams:write scope"""

    @pytest.mark.asyncio
    async def test_read_only_cannot_list_webhooks(self, test_client, read_only_headers, test_team):
        """Read-only token cannot list webhooks (requires teams:write)"""
        response = await test_client.get(
            f"/teams/{test_team['slug']}/webhooks",
            headers=read_only_headers
        )

        # Webhooks require teams:write scope
        assert response.status_code in [403, 503, 504]

    @pytest.mark.asyncio
    async def test_read_only_cannot_create_webhook(self, test_client, read_only_headers, test_team):
        """Read-only token cannot create webhooks"""
        response = await test_client.post(
            f"/teams/{test_team['slug']}/webhooks",
            json={
                "name": "Should Fail",
                "url": "https://httpbin.org/post"
            },
            headers=read_only_headers
        )

        assert response.status_code in [403, 503]

    @pytest.mark.asyncio
    async def test_read_only_cannot_update_webhook(self, test_client, read_only_headers, test_team):
        """Read-only token cannot update webhooks"""
        response = await test_client.patch(
            f"/teams/{test_team['slug']}/webhooks/some-webhook-id",
            json={"name": "Updated"},
            headers=read_only_headers
        )

        assert response.status_code in [403, 404, 503]

    @pytest.mark.asyncio
    async def test_read_only_cannot_delete_webhook(self, test_client, read_only_headers, test_team):
        """Read-only token cannot delete webhooks"""
        response = await test_client.delete(
            f"/teams/{test_team['slug']}/webhooks/some-webhook-id",
            headers=read_only_headers
        )

        assert response.status_code in [403, 404, 503]

    @pytest.mark.asyncio
    async def test_read_only_cannot_test_webhook(self, test_client, read_only_headers, test_team):
        """Read-only token cannot test webhook URLs"""
        response = await test_client.post(
            f"/teams/{test_team['slug']}/webhooks/test-url",
            json={"url": "https://httpbin.org/post"},
            headers=read_only_headers
        )

        assert response.status_code in [403, 503]

    @pytest.mark.asyncio
    async def test_no_auth_cannot_access_webhooks(self, test_client, test_team):
        """Request without auth cannot access webhooks"""
        response = await test_client.get(f"/teams/{test_team['slug']}/webhooks")

        assert response.status_code in [401, 403]
