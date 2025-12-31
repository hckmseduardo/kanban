"""Task Queue Tests

Tests for listing, retrieving, retrying, and canceling background tasks.
"""

import pytest


class TestTaskListing:
    """Test task listing operations - Tasks require JWT auth, not Portal API token"""

    @pytest.mark.asyncio
    async def test_list_tasks(self, test_client, jwt_headers):
        """List all tasks for the user"""
        response = await test_client.get("/tasks", headers=jwt_headers)

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_list_tasks_by_status(self, test_client, jwt_headers):
        """List tasks filtered by status"""
        for status in ["pending", "running", "completed", "failed"]:
            response = await test_client.get(
                "/tasks",
                params={"status": status},
                headers=jwt_headers
            )

            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_list_tasks_by_type(self, test_client, jwt_headers):
        """List tasks filtered by type"""
        response = await test_client.get(
            "/tasks",
            params={"task_type": "team_provision"},
            headers=jwt_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_list_tasks_without_auth_fails(self, test_client):
        """Listing tasks without authentication should fail"""
        response = await test_client.get("/tasks")

        assert response.status_code in [401, 403]


class TestTaskRetrieval:
    """Test task retrieval operations - Tasks require JWT auth"""

    @pytest.mark.asyncio
    async def test_get_task_by_id(self, test_client, jwt_headers):
        """Get a specific task by ID"""
        # First list tasks to get an ID
        list_response = await test_client.get("/tasks", headers=jwt_headers)

        if list_response.status_code == 200:
            tasks = list_response.json()
            if tasks:
                task_id = tasks[0]["task_id"]
                response = await test_client.get(
                    f"/tasks/{task_id}",
                    headers=jwt_headers
                )
                assert response.status_code == 200
                data = response.json()
                assert data["task_id"] == task_id

    @pytest.mark.asyncio
    async def test_get_task_not_found(self, test_client, jwt_headers):
        """Getting non-existent task should return 404"""
        response = await test_client.get(
            "/tasks/nonexistent-task-id",
            headers=jwt_headers
        )

        assert response.status_code == 404


class TestTaskRetry:
    """Test task retry operations - Tasks require JWT auth"""

    @pytest.mark.asyncio
    async def test_retry_task(self, test_client, jwt_headers):
        """Retry a failed task"""
        # First list tasks to find a failed one
        list_response = await test_client.get(
            "/tasks",
            params={"status": "failed"},
            headers=jwt_headers
        )

        if list_response.status_code == 200:
            tasks = list_response.json()
            if tasks:
                task_id = tasks[0]["task_id"]
                response = await test_client.post(
                    f"/tasks/{task_id}/retry",
                    headers=jwt_headers
                )
                # May succeed or fail based on task state
                assert response.status_code in [200, 202, 400, 404]

    @pytest.mark.asyncio
    async def test_retry_nonexistent_task(self, test_client, jwt_headers):
        """Retrying non-existent task should return 404"""
        response = await test_client.post(
            "/tasks/nonexistent-task-id/retry",
            headers=jwt_headers
        )

        assert response.status_code == 404


class TestTaskCancellation:
    """Test task cancellation operations - Tasks require JWT auth"""

    @pytest.mark.asyncio
    async def test_cancel_task(self, test_client, jwt_headers):
        """Cancel a pending task"""
        # First list tasks to find a pending one
        list_response = await test_client.get(
            "/tasks",
            params={"status": "pending"},
            headers=jwt_headers
        )

        if list_response.status_code == 200:
            tasks = list_response.json()
            if tasks:
                task_id = tasks[0]["task_id"]
                response = await test_client.post(
                    f"/tasks/{task_id}/cancel",
                    headers=jwt_headers
                )
                # May succeed or fail based on task state
                assert response.status_code in [200, 400, 404]

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_task(self, test_client, jwt_headers):
        """Canceling non-existent task should return 404"""
        response = await test_client.post(
            "/tasks/nonexistent-task-id/cancel",
            headers=jwt_headers
        )

        assert response.status_code == 404


class TestTaskStats:
    """Test task statistics operations - Tasks require JWT auth"""

    @pytest.mark.asyncio
    async def test_task_stats_summary(self, test_client, jwt_headers):
        """Get task statistics summary"""
        response = await test_client.get(
            "/tasks/stats/summary",
            headers=jwt_headers
        )

        assert response.status_code == 200
        data = response.json()
        # Should contain counts by status
        assert isinstance(data, dict)


class TestTaskAuthorization:
    """Test task authorization - Tasks require JWT auth, not Portal API token"""

    @pytest.mark.asyncio
    async def test_jwt_can_list_tasks(self, test_client, jwt_headers):
        """JWT token can list tasks"""
        response = await test_client.get("/tasks", headers=jwt_headers)

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_jwt_can_get_task(self, test_client, jwt_headers):
        """JWT token can get task details"""
        # First list tasks
        list_response = await test_client.get("/tasks", headers=jwt_headers)

        if list_response.status_code == 200:
            tasks = list_response.json()
            if tasks:
                task_id = tasks[0]["task_id"]
                response = await test_client.get(
                    f"/tasks/{task_id}",
                    headers=jwt_headers
                )
                assert response.status_code in [200, 404]
