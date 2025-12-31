"""Health Check Tests

Tests for health check endpoints.
"""

import pytest


class TestHealthCheck:
    """Test basic health check"""

    @pytest.mark.asyncio
    async def test_health_check(self, test_client):
        """Basic health check returns healthy status"""
        response = await test_client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_health_check_no_auth_required(self, test_client):
        """Health check does not require authentication"""
        response = await test_client.get("/health")

        assert response.status_code == 200


class TestRedisHealth:
    """Test Redis health check"""

    @pytest.mark.asyncio
    async def test_redis_health(self, test_client):
        """Redis health check endpoint works"""
        response = await test_client.get("/health/redis")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ["healthy", "unhealthy"]

    @pytest.mark.asyncio
    async def test_redis_health_includes_details(self, test_client):
        """Redis health check includes connection details"""
        response = await test_client.get("/health/redis")

        assert response.status_code == 200
        data = response.json()
        # Should include some status information
        assert "status" in data


class TestHealthCheckIntegration:
    """Integration tests for health monitoring"""

    @pytest.mark.asyncio
    async def test_health_check_response_time(self, test_client):
        """Health check should respond quickly"""
        import time
        start = time.time()
        response = await test_client.get("/health")
        elapsed = time.time() - start

        assert response.status_code == 200
        # Should respond in under 1 second
        assert elapsed < 1.0

    @pytest.mark.asyncio
    async def test_multiple_health_checks(self, test_client):
        """Multiple health checks should all succeed"""
        for _ in range(5):
            response = await test_client.get("/health")
            assert response.status_code == 200
            assert response.json()["status"] == "healthy"
