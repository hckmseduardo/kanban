"""Task management routes"""

import logging
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from app.auth.jwt import get_current_user
from app.services.task_service import task_service
from app.services.redis_service import redis_service

logger = logging.getLogger(__name__)
router = APIRouter()


# Response models
class TaskProgress(BaseModel):
    current_step: int
    total_steps: int
    step_name: str
    percentage: int
    message: Optional[str] = None


class TaskResponse(BaseModel):
    task_id: str
    type: str
    status: str
    progress: TaskProgress
    payload: dict
    result: Optional[dict] = None
    error: Optional[str] = None
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


@router.get("", response_model=List[TaskResponse])
async def list_tasks(
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user)
):
    """Get all tasks for current user"""
    tasks = await task_service.get_user_tasks(
        user_id=current_user["id"],
        status=status,
        limit=limit
    )

    return [
        TaskResponse(
            task_id=task["task_id"],
            type=task["type"],
            status=task["status"],
            progress=TaskProgress(**task.get("progress", {
                "current_step": 0,
                "total_steps": 0,
                "step_name": "Unknown",
                "percentage": 0
            })),
            payload=task.get("payload", {}),
            result=task.get("result"),
            error=task.get("error"),
            created_at=task["created_at"],
            started_at=task.get("started_at"),
            completed_at=task.get("completed_at")
        )
        for task in tasks
    ]


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get task by ID"""
    task = await task_service.get_task(task_id)

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Verify ownership
    if task.get("user_id") != current_user["id"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    return TaskResponse(
        task_id=task["task_id"],
        type=task["type"],
        status=task["status"],
        progress=TaskProgress(**task.get("progress", {
            "current_step": 0,
            "total_steps": 0,
            "step_name": "Unknown",
            "percentage": 0
        })),
        payload=task.get("payload", {}),
        result=task.get("result"),
        error=task.get("error"),
        created_at=task["created_at"],
        started_at=task.get("started_at"),
        completed_at=task.get("completed_at")
    )


@router.post("/{task_id}/retry")
async def retry_task(
    task_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Retry a failed task"""
    task = await task_service.get_task(task_id)

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.get("user_id") != current_user["id"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    if task.get("status") != "failed":
        raise HTTPException(status_code=400, detail="Only failed tasks can be retried")

    success = await task_service.retry_task(task_id)

    if not success:
        raise HTTPException(status_code=500, detail="Failed to retry task")

    return {"message": "Task queued for retry"}


@router.post("/{task_id}/cancel")
async def cancel_task(
    task_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Cancel a pending task"""
    task = await task_service.get_task(task_id)

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.get("user_id") != current_user["id"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    if task.get("status") != "pending":
        raise HTTPException(status_code=400, detail="Only pending tasks can be cancelled")

    success = await task_service.cancel_task(task_id)

    if not success:
        raise HTTPException(status_code=500, detail="Failed to cancel task")

    return {"message": "Task cancelled"}


@router.websocket("/ws")
async def task_websocket(websocket: WebSocket):
    """
    WebSocket endpoint for real-time task updates.
    Client must send user_id after connection to subscribe.
    """
    await websocket.accept()

    try:
        # Wait for user ID
        data = await websocket.receive_json()
        user_id = data.get("user_id")

        if not user_id:
            await websocket.close(code=4001, reason="user_id required")
            return

        # Subscribe to user's task channel
        channel = f"tasks:{user_id}"
        pubsub = await redis_service.subscribe(channel)

        logger.info(f"WebSocket subscribed to {channel}")

        # Send confirmation
        await websocket.send_json({
            "type": "subscribed",
            "channel": channel
        })

        # Listen for messages
        async for message in pubsub.listen():
            if message["type"] == "message":
                import json
                data = json.loads(message["data"])
                await websocket.send_json(data)

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await websocket.close(code=4000, reason=str(e))


@router.get("/stats/summary")
async def get_task_stats(
    current_user: dict = Depends(get_current_user)
):
    """Get task statistics for current user"""
    all_tasks = await task_service.get_user_tasks(
        user_id=current_user["id"],
        limit=100
    )

    stats = {
        "total": len(all_tasks),
        "pending": 0,
        "in_progress": 0,
        "completed": 0,
        "failed": 0
    }

    for task in all_tasks:
        status = task.get("status", "unknown")
        if status in stats:
            stats[status] += 1

    return stats
