"""Redis service for message queue and caching"""

import json
import logging
from typing import Any, Optional
from datetime import datetime
import uuid

import redis.asyncio as redis

from app.config import settings

logger = logging.getLogger(__name__)


class RedisService:
    """Redis service for pub/sub, queues, and caching"""

    def __init__(self):
        self.client: Optional[redis.Redis] = None
        self.pubsub: Optional[redis.client.PubSub] = None

    async def connect(self):
        """Connect to Redis"""
        self.client = redis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True
        )
        logger.info("Redis connection established")

    async def disconnect(self):
        """Disconnect from Redis"""
        if self.client:
            await self.client.close()
            logger.info("Redis connection closed")

    async def ping(self) -> bool:
        """Check Redis connection"""
        try:
            if self.client:
                await self.client.ping()
                return True
        except Exception as e:
            logger.error(f"Redis ping failed: {e}")
        return False

    # =========================================================================
    # Queue Operations (Task Processing)
    # =========================================================================

    async def enqueue_task(
        self,
        queue_name: str,
        task_type: str,
        payload: dict,
        user_id: str,
        priority: str = "normal"
    ) -> str:
        """Add a task to the queue"""
        task_id = str(uuid.uuid4())
        task = {
            "task_id": task_id,
            "type": task_type,
            "status": "pending",
            "payload": payload,
            "user_id": user_id,
            "priority": priority,
            "progress": {
                "current_step": 0,
                "total_steps": 0,
                "step_name": "Queued",
                "percentage": 0
            },
            "created_at": datetime.utcnow().isoformat() + "Z",
            "started_at": None,
            "completed_at": None
        }

        # Store task data
        await self.client.hset(f"task:{task_id}", mapping={
            "data": json.dumps(task)
        })

        # Add to queue based on priority
        queue_key = f"queue:{queue_name}:{priority}"
        await self.client.lpush(queue_key, task_id)

        # Publish task created event
        await self.publish(f"tasks:{user_id}", {
            "type": "task.created",
            "task_id": task_id,
            "task_type": task_type
        })

        logger.info(f"Task {task_id} enqueued to {queue_name}")
        return task_id

    async def get_task(self, task_id: str) -> Optional[dict]:
        """Get task by ID"""
        data = await self.client.hget(f"task:{task_id}", "data")
        if data:
            return json.loads(data)
        return None

    async def update_task_progress(
        self,
        task_id: str,
        current_step: int,
        total_steps: int,
        step_name: str,
        message: str = ""
    ):
        """Update task progress and notify subscribers"""
        task = await self.get_task(task_id)
        if not task:
            return

        percentage = int((current_step / total_steps) * 100) if total_steps > 0 else 0

        task["status"] = "in_progress"
        task["progress"] = {
            "current_step": current_step,
            "total_steps": total_steps,
            "step_name": step_name,
            "percentage": percentage,
            "message": message
        }

        if current_step == 1 and not task.get("started_at"):
            task["started_at"] = datetime.utcnow().isoformat() + "Z"

        await self.client.hset(f"task:{task_id}", mapping={
            "data": json.dumps(task)
        })

        # Publish progress update
        await self.publish(f"tasks:{task['user_id']}", {
            "type": "task.progress",
            "task_id": task_id,
            "step": current_step,
            "total_steps": total_steps,
            "step_name": step_name,
            "percentage": percentage,
            "message": message
        })

    async def complete_task(self, task_id: str, result: dict = None):
        """Mark task as completed"""
        task = await self.get_task(task_id)
        if not task:
            return

        task["status"] = "completed"
        task["completed_at"] = datetime.utcnow().isoformat() + "Z"
        task["result"] = result
        task["progress"]["percentage"] = 100
        task["progress"]["step_name"] = "Completed"

        await self.client.hset(f"task:{task_id}", mapping={
            "data": json.dumps(task)
        })

        # Publish completion
        await self.publish(f"tasks:{task['user_id']}", {
            "type": "task.completed",
            "task_id": task_id,
            "result": result,
            "message": f"Task completed successfully"
        })

        logger.info(f"Task {task_id} completed")

    async def fail_task(self, task_id: str, error: str):
        """Mark task as failed"""
        task = await self.get_task(task_id)
        if not task:
            return

        task["status"] = "failed"
        task["completed_at"] = datetime.utcnow().isoformat() + "Z"
        task["error"] = error

        await self.client.hset(f"task:{task_id}", mapping={
            "data": json.dumps(task)
        })

        # Publish failure
        await self.publish(f"tasks:{task['user_id']}", {
            "type": "task.failed",
            "task_id": task_id,
            "error": error,
            "retry_available": True
        })

        logger.error(f"Task {task_id} failed: {error}")

    async def get_user_tasks(
        self,
        user_id: str,
        status: str = None,
        limit: int = 20
    ) -> list:
        """Get tasks for a user"""
        # In a production system, you'd want an index for this
        # For now, we'll use a simple scan
        tasks = []
        cursor = 0

        while True:
            cursor, keys = await self.client.scan(
                cursor=cursor,
                match="task:*",
                count=100
            )

            for key in keys:
                data = await self.client.hget(key, "data")
                if data:
                    task = json.loads(data)
                    if task.get("user_id") == user_id:
                        if status is None or task.get("status") == status:
                            tasks.append(task)

            if cursor == 0:
                break

        # Sort by created_at descending
        tasks.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return tasks[:limit]

    # =========================================================================
    # Pub/Sub Operations
    # =========================================================================

    async def publish(self, channel: str, message: dict):
        """Publish message to channel"""
        await self.client.publish(channel, json.dumps(message))

    async def subscribe(self, channel: str):
        """Subscribe to channel - creates dedicated pubsub for each caller"""
        # Create new pubsub for each WebSocket to avoid conflicts
        pubsub = self.client.pubsub()
        await pubsub.subscribe(channel)
        return pubsub

    # =========================================================================
    # Cache Operations
    # =========================================================================

    async def cache_set(self, key: str, value: Any, expire: int = 3600):
        """Set cache value with expiration"""
        await self.client.setex(
            f"cache:{key}",
            expire,
            json.dumps(value)
        )

    async def cache_get(self, key: str) -> Optional[Any]:
        """Get cached value"""
        data = await self.client.get(f"cache:{key}")
        if data:
            return json.loads(data)
        return None

    async def cache_delete(self, key: str):
        """Delete cached value"""
        await self.client.delete(f"cache:{key}")


# Singleton instance
redis_service = RedisService()
