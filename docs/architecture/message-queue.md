# Message Queue Architecture

## Overview

The Kanban Platform uses Redis as its message queue system for asynchronous task processing and real-time communication. This document details the queue patterns, message formats, and best practices used throughout the platform.

## Core Principles

Per the project guidelines (CLAUDE.md):
1. **All tasks use message queues** - Tasks are ordered through queues, not executed synchronously
2. **Continuous feedback** - Every task provides progress updates during execution
3. **Completion notifications** - Users are notified when tasks complete
4. **Priority support** - High-priority and normal queues for task ordering

## Queue Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Redis Server                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                           Task Queues                                  │  │
│  │                                                                        │  │
│  │   ┌──────────────────────┐    ┌──────────────────────┐                │  │
│  │   │ provisioning:high    │    │ provisioning:normal  │                │  │
│  │   │                      │    │                      │                │  │
│  │   │ • team.provision     │    │ • team.delete        │                │  │
│  │   │ • workspace.provision│    │ • workspace.delete   │                │  │
│  │   │ • sandbox.provision  │    │ • sandbox.delete     │                │  │
│  │   └──────────────────────┘    └──────────────────────┘                │  │
│  │                                                                        │  │
│  │   ┌──────────────────────┐    ┌──────────────────────┐                │  │
│  │   │ certificates:high    │    │ certificates:normal  │                │  │
│  │   └──────────────────────┘    └──────────────────────┘                │  │
│  │                                                                        │  │
│  │   ┌──────────────────────┐    ┌──────────────────────┐                │  │
│  │   │ dns:high             │    │ dns:normal           │                │  │
│  │   └──────────────────────┘    └──────────────────────┘                │  │
│  │                                                                        │  │
│  │   ┌──────────────────────┐                                            │  │
│  │   │ notifications:normal │                                            │  │
│  │   └──────────────────────┘                                            │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                         Pub/Sub Channels                               │  │
│  │                                                                        │  │
│  │   ┌──────────────────────┐    ┌──────────────────────┐                │  │
│  │   │ team:status          │    │ workspace:status     │                │  │
│  │   └──────────────────────┘    └──────────────────────┘                │  │
│  │                                                                        │  │
│  │   ┌──────────────────────┐    ┌──────────────────────┐                │  │
│  │   │ sandbox:status       │    │ tasks:{user_id}      │                │  │
│  │   └──────────────────────┘    └──────────────────────┘                │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                         Task Metadata                                  │  │
│  │                                                                        │  │
│  │   task:{task_id} → Hash with progress, status, timestamps             │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Task Queue Pattern

### Enqueue Task

```python
from redis import asyncio as aioredis
import json
from uuid import uuid4
from datetime import datetime

async def enqueue_task(
    redis: aioredis.Redis,
    task_type: str,
    payload: dict,
    user_id: str,
    priority: str = "normal"  # "high" or "normal"
) -> str:
    """
    Enqueue a task for async processing.

    Args:
        redis: Redis connection
        task_type: Type of task (e.g., "team.provision")
        payload: Task-specific data
        user_id: ID of user who initiated task
        priority: Queue priority level

    Returns:
        task_id: Unique identifier for tracking
    """
    task_id = str(uuid4())

    task = {
        "id": task_id,
        "type": task_type,
        "payload": payload,
        "user_id": user_id,
        "status": "pending",
        "created_at": datetime.utcnow().isoformat(),
    }

    # Determine queue based on task type and priority
    queue_category = get_queue_category(task_type)  # e.g., "provisioning"
    queue_name = f"queue:{queue_category}:{priority}"

    # Store task metadata
    await redis.hset(f"task:{task_id}", mapping={
        "id": task_id,
        "type": task_type,
        "status": "pending",
        "user_id": user_id,
        "step": 0,
        "total_steps": 0,
        "message": "Queued",
        "percentage": 0,
        "created_at": task["created_at"],
    })
    await redis.expire(f"task:{task_id}", 86400)  # 24h TTL

    # Enqueue task
    await redis.lpush(queue_name, json.dumps(task))

    # Notify user of task creation
    await redis.publish(f"tasks:{user_id}", json.dumps({
        "type": "task.created",
        "task_id": task_id,
        "task_type": task_type,
        "message": "Task queued for processing"
    }))

    return task_id
```

### Process Tasks

```python
async def process_tasks(redis: aioredis.Redis, queues: List[str]):
    """
    Main task processing loop.

    Processes high-priority queue first, then normal.
    """
    while True:
        # BRPOP blocks until a task is available
        # First queue (high) is checked before second (normal)
        result = await redis.brpop(queues, timeout=5)

        if result:
            queue_name, task_data = result
            task = json.loads(task_data)

            try:
                await process_single_task(redis, task)
            except Exception as e:
                await handle_task_failure(redis, task, str(e))

async def process_single_task(redis: aioredis.Redis, task: dict):
    """Process a single task with progress updates."""
    task_id = task["id"]
    user_id = task["user_id"]

    # Update status to processing
    await update_task_status(redis, task_id, user_id, "processing", "Starting...")

    # Route to appropriate handler
    handler = get_task_handler(task["type"])
    if handler:
        await handler(redis, task)
    else:
        raise ValueError(f"Unknown task type: {task['type']}")
```

### Progress Updates

```python
async def update_task_progress(
    redis: aioredis.Redis,
    task_id: str,
    user_id: str,
    step: int,
    total_steps: int,
    message: str
):
    """
    Update task progress and notify user.

    This is called during task execution to provide real-time feedback.
    """
    percentage = int((step / total_steps) * 100) if total_steps > 0 else 0

    # Update task metadata
    await redis.hset(f"task:{task_id}", mapping={
        "status": "processing",
        "step": step,
        "total_steps": total_steps,
        "message": message,
        "percentage": percentage,
        "updated_at": datetime.utcnow().isoformat(),
    })

    # Publish progress to user channel
    await redis.publish(f"tasks:{user_id}", json.dumps({
        "type": "task.progress",
        "task_id": task_id,
        "step": step,
        "total_steps": total_steps,
        "percentage": percentage,
        "message": message,
    }))
```

### Task Completion

```python
async def complete_task(
    redis: aioredis.Redis,
    task_id: str,
    user_id: str,
    result: dict = None
):
    """
    Mark task as completed and notify user.
    """
    await redis.hset(f"task:{task_id}", mapping={
        "status": "completed",
        "percentage": 100,
        "message": "Completed successfully",
        "result": json.dumps(result) if result else "{}",
        "completed_at": datetime.utcnow().isoformat(),
    })

    # Notify user
    await redis.publish(f"tasks:{user_id}", json.dumps({
        "type": "task.completed",
        "task_id": task_id,
        "message": "Task completed successfully",
        "result": result,
    }))

async def fail_task(
    redis: aioredis.Redis,
    task_id: str,
    user_id: str,
    error: str
):
    """
    Mark task as failed and notify user.
    """
    await redis.hset(f"task:{task_id}", mapping={
        "status": "failed",
        "message": f"Failed: {error}",
        "error": error,
        "failed_at": datetime.utcnow().isoformat(),
    })

    await redis.publish(f"tasks:{user_id}", json.dumps({
        "type": "task.failed",
        "task_id": task_id,
        "error": error,
    }))
```

## Pub/Sub Pattern

### Status Channels

```python
# Channel definitions
CHANNELS = {
    "team:status": "Team lifecycle events",
    "workspace:status": "Workspace provisioning events",
    "sandbox:status": "Sandbox provisioning events",
    "tasks:{user_id}": "User-specific task updates",
}
```

### Publishing Status

```python
async def publish_resource_status(
    redis: aioredis.Redis,
    resource_type: str,  # "team", "workspace", "sandbox"
    resource_id: str,
    status: str,  # "active", "deleted", "failed"
    metadata: dict = None,
    error: str = None
):
    """
    Publish resource status update.

    This is called by orchestrator after resource operations complete.
    """
    channel = f"{resource_type}:status"

    message = {
        "resource_type": resource_type,
        "resource_id": resource_id,
        "status": status,
        "metadata": metadata or {},
        "timestamp": datetime.utcnow().isoformat(),
    }

    if error:
        message["error"] = error

    await redis.publish(channel, json.dumps(message))
```

### Subscribing to Status

```python
async def listen_for_status_updates(redis: aioredis.Redis):
    """
    Listen for status updates and process them.

    This runs in the Portal Worker.
    """
    pubsub = redis.pubsub()
    await pubsub.subscribe(
        "team:status",
        "workspace:status",
        "sandbox:status"
    )

    async for message in pubsub.listen():
        if message["type"] == "message":
            channel = message["channel"].decode()
            data = json.loads(message["data"])

            if channel == "team:status":
                await handle_team_status(data)
            elif channel == "workspace:status":
                await handle_workspace_status(data)
            elif channel == "sandbox:status":
                await handle_sandbox_status(data)
```

## Message Formats

### Task Message

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "type": "team.provision",
  "payload": {
    "team_id": "team-uuid",
    "slug": "my-team",
    "name": "My Team",
    "owner_id": "user-uuid"
  },
  "user_id": "user-uuid",
  "status": "pending",
  "created_at": "2024-01-15T10:30:00Z"
}
```

### Progress Message

```json
{
  "type": "task.progress",
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "step": 3,
  "total_steps": 10,
  "percentage": 30,
  "message": "Step 3/10: Creating containers"
}
```

### Completion Message

```json
{
  "type": "task.completed",
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "message": "Task completed successfully",
  "result": {
    "subdomain": "my-team.kanban.domain",
    "api_url": "https://my-team.kanban.domain/api"
  }
}
```

### Failure Message

```json
{
  "type": "task.failed",
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "error": "Docker container failed to start: port already in use"
}
```

### Status Update Message

```json
{
  "resource_type": "team",
  "resource_id": "team-uuid",
  "status": "active",
  "metadata": {
    "subdomain": "my-team.kanban.domain",
    "container_ids": ["abc123", "def456"]
  },
  "timestamp": "2024-01-15T10:35:00Z"
}
```

## Queue Categories

| Category | High Priority | Normal Priority | Tasks |
|----------|---------------|-----------------|-------|
| Provisioning | `queue:provisioning:high` | `queue:provisioning:normal` | team.*, workspace.*, sandbox.* |
| Certificates | `queue:certificates:high` | `queue:certificates:normal` | cert.issue, cert.renew |
| DNS | `queue:dns:high` | `queue:dns:normal` | dns.add, dns.remove |
| Notifications | - | `queue:notifications:normal` | email.*, notification.* |

## Frontend Integration

### WebSocket Listener

```typescript
// portal/frontend/src/services/taskSocket.ts
class TaskSocketService {
  private ws: WebSocket | null = null;

  connect(userId: string) {
    this.ws = new WebSocket(
      `wss://${window.location.host}/ws/tasks/${userId}`
    );

    this.ws.onmessage = (event) => {
      const message = JSON.parse(event.data);
      this.handleMessage(message);
    };
  }

  private handleMessage(message: TaskMessage) {
    switch (message.type) {
      case 'task.created':
        taskStore.addTask(message);
        toast.info('Task started');
        break;

      case 'task.progress':
        taskStore.updateProgress(message.task_id, {
          step: message.step,
          totalSteps: message.total_steps,
          percentage: message.percentage,
          message: message.message,
        });
        break;

      case 'task.completed':
        taskStore.markCompleted(message.task_id, message.result);
        toast.success('Task completed successfully');
        break;

      case 'task.failed':
        taskStore.markFailed(message.task_id, message.error);
        toast.error(`Task failed: ${message.error}`);
        break;
    }
  }
}
```

### Task Progress Component

```tsx
// portal/frontend/src/components/TaskProgress.tsx
function TaskProgress({ task }: { task: Task }) {
  return (
    <div className="task-progress">
      <div className="task-header">
        <span className="task-type">{task.type}</span>
        <span className="task-status">{task.status}</span>
      </div>

      {task.status === 'processing' && (
        <>
          <div className="progress-bar">
            <div
              className="progress-fill"
              style={{ width: `${task.percentage}%` }}
            />
          </div>
          <div className="progress-message">
            {task.message} ({task.percentage}%)
          </div>
        </>
      )}

      {task.status === 'completed' && (
        <div className="success-message">
          Completed successfully
        </div>
      )}

      {task.status === 'failed' && (
        <div className="error-message">
          {task.error}
        </div>
      )}
    </div>
  );
}
```

## Best Practices

### 1. Always Use Queues for Long Operations

```python
# Good: Queue the task
async def create_team(request: CreateTeamRequest):
    team = await db.create_team(request)
    task_id = await enqueue_task(
        redis, "team.provision", {"team_id": team.id}, request.user_id, "high"
    )
    return {"team": team, "task_id": task_id}

# Bad: Synchronous provisioning
async def create_team(request: CreateTeamRequest):
    team = await db.create_team(request)
    await provision_team_containers(team)  # Blocks request
    return {"team": team}
```

### 2. Provide Granular Progress Updates

```python
async def provision_team(redis, task):
    task_id = task["id"]
    user_id = task["user_id"]

    steps = [
        "Creating directory structure",
        "Generating configuration",
        "Creating database",
        "Building containers",
        "Starting services",
        "Configuring routing",
        "Running health checks",
        "Finalizing setup",
    ]

    for i, step in enumerate(steps, 1):
        await update_task_progress(redis, task_id, user_id, i, len(steps), step)
        await execute_step(step, task)

    await complete_task(redis, task_id, user_id)
```

### 3. Handle Failures Gracefully

```python
async def process_with_recovery(redis, task):
    try:
        await process_task(redis, task)
    except RetryableError as e:
        # Requeue with backoff
        await asyncio.sleep(2 ** task.get("retry_count", 0))
        task["retry_count"] = task.get("retry_count", 0) + 1
        if task["retry_count"] < 3:
            await redis.lpush("queue:provisioning:normal", json.dumps(task))
        else:
            await fail_task(redis, task["id"], task["user_id"], str(e))
    except Exception as e:
        await fail_task(redis, task["id"], task["user_id"], str(e))
```

### 4. Use Priority Appropriately

| Priority | Use Case |
|----------|----------|
| High | User-initiated actions requiring immediate feedback |
| Normal | Background operations, cleanup tasks, bulk operations |

### 5. Set Appropriate TTLs

```python
# Task metadata: 24 hours (sufficient for viewing history)
await redis.expire(f"task:{task_id}", 86400)

# Rate limits: 60 seconds
await redis.expire(f"ratelimit:{key}", 60)

# Cache: varies by use case
await redis.expire(f"cache:{key}", 300)  # 5 minutes
```

## Monitoring

### Queue Depth

```bash
# Check queue lengths
redis-cli LLEN queue:provisioning:high
redis-cli LLEN queue:provisioning:normal

# Monitor in real-time
watch -n 1 'redis-cli LLEN queue:provisioning:high && redis-cli LLEN queue:provisioning:normal'
```

### Active Tasks

```bash
# Find all active tasks
redis-cli KEYS "task:*" | xargs -I {} redis-cli HGET {} status
```

### Pub/Sub Activity

```bash
# Monitor all pub/sub messages
redis-cli PSUBSCRIBE "*:status" "tasks:*"
```

## Related Documentation
- [Overview](./overview.md)
- [Infrastructure Architecture](./infrastructure.md)
- [Orchestrator Architecture](./orchestrator.md)
- [Portal Architecture](./portal.md)
