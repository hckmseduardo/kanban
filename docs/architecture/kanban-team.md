# Kanban Team Architecture

## Overview

Kanban Team is the individual team instance component that provides isolated Kanban boards for each tenant. Each team instance runs as a separate set of containers with dedicated storage, accessible via a unique subdomain.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          Team Instance (per team)                            │
│                          https://{team-slug}.domain                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────────────────────┐    ┌──────────────────────────────┐       │
│  │      Team Frontend           │    │       Team Backend            │       │
│  │        (React/Vite)          │    │        (FastAPI)              │       │
│  │                              │    │                              │       │
│  │  - Drag-drop boards          │    │  Port: 8000                  │       │
│  │  - Real-time updates         │    │  - REST API                  │       │
│  │  - Markdown support          │    │  - WebSocket server          │       │
│  │  - Link previews             │    │  - Webhook triggers          │       │
│  └──────────────────────────────┘    └──────────────────────────────┘       │
│                                                    │                         │
│                                                    ▼                         │
│                              ┌──────────────────────────────┐               │
│                              │        TinyDB Database        │               │
│                              │     (Isolated per team)       │               │
│                              │                              │               │
│                              │  /data/{team-slug}/db.json   │               │
│                              └──────────────────────────────┘               │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Directory Structure

```
kanban-team/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI application
│   │   ├── config.py            # Configuration
│   │   ├── routes/
│   │   │   ├── boards.py        # Board CRUD
│   │   │   ├── columns.py       # Column management
│   │   │   ├── cards.py         # Card operations
│   │   │   ├── members.py       # Team members
│   │   │   ├── webhooks.py      # Webhook management
│   │   │   ├── comments.py      # Card comments
│   │   │   ├── attachments.py   # File attachments
│   │   │   ├── labels.py        # Label management
│   │   │   ├── activity.py      # Activity logs
│   │   │   ├── export.py        # Data export
│   │   │   ├── templates.py     # Card templates
│   │   │   ├── reminders.py     # Due date reminders
│   │   │   ├── notifications.py # Notification system
│   │   │   ├── automations.py   # Automated workflows
│   │   │   ├── analytics.py     # Board metrics
│   │   │   ├── agents.py        # Agent integration
│   │   │   └── websocket.py     # Real-time updates
│   │   ├── services/
│   │   │   ├── database.py      # TinyDB operations
│   │   │   ├── webhook_service.py # Webhook dispatcher
│   │   │   └── notification_service.py
│   │   └── models/              # Pydantic models
│   ├── Dockerfile
│   └── requirements.txt
│
└── frontend/
    ├── src/
    │   ├── App.tsx              # Main application
    │   ├── pages/
    │   │   ├── BoardPage.tsx    # Kanban board view
    │   │   ├── BoardsListPage.tsx
    │   │   └── SettingsPage.tsx
    │   ├── components/
    │   │   ├── Board/           # Board components
    │   │   ├── Column/          # Column components
    │   │   ├── Card/            # Card components
    │   │   └── common/          # Shared components
    │   ├── services/
    │   │   ├── api.ts           # API client
    │   │   └── websocket.ts     # WebSocket client
    │   └── stores/              # Zustand stores
    ├── index.html
    └── vite.config.ts
```

## Backend API

### Board Endpoints (`/boards`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/boards` | Create new board |
| GET | `/boards` | List all boards |
| GET | `/boards/{id}` | Get board with columns and cards |
| PUT | `/boards/{id}` | Update board settings |
| DELETE | `/boards/{id}` | Delete board |

### Column Endpoints (`/columns`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/columns` | Create column |
| PUT | `/columns/{id}` | Update column (name, WIP limit) |
| DELETE | `/columns/{id}` | Delete column |
| PUT | `/columns/reorder` | Reorder columns |

### Card Endpoints (`/cards`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/cards` | Create card |
| GET | `/cards/{id}` | Get card details |
| PUT | `/cards/{id}` | Update card |
| DELETE | `/cards/{id}` | Delete card |
| PUT | `/cards/{id}/move` | Move card between columns |
| POST | `/cards/{id}/archive` | Archive card |

### Member Endpoints (`/members`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/members` | List team members |
| POST | `/members` | Add member |
| PUT | `/members/{id}` | Update member role |
| DELETE | `/members/{id}` | Remove member |

### Webhook Endpoints (`/webhooks`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/webhooks` | Register webhook |
| GET | `/webhooks` | List webhooks |
| PUT | `/webhooks/{id}` | Update webhook |
| DELETE | `/webhooks/{id}` | Delete webhook |

### Agent Endpoints (`/agents`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/agents/definitions` | Get agent definitions |
| POST | `/agents/subscribe` | Subscribe to agent updates |
| PUT | `/agents/definitions/{id}` | Update agent config |

### Other Endpoints
| Group | Endpoints |
|-------|-----------|
| Comments | `/cards/{id}/comments` - CRUD |
| Attachments | `/cards/{id}/attachments` - Upload/Download |
| Labels | `/labels` - CRUD, `/cards/{id}/labels` - Assign |
| Activity | `/activity`, `/boards/{id}/activity` |
| Export | `/boards/{id}/export` - CSV, JSON |
| Templates | `/templates` - Card templates |
| Analytics | `/boards/{id}/analytics` - Metrics |
| Notifications | `/notifications` - User notifications |
| Automations | `/automations` - Workflow rules |

## Database Schema (TinyDB)

```json
{
  "boards": {
    "id": "uuid",
    "name": "string",
    "description": "string",
    "visibility": "private|team|public",
    "owner_id": "uuid",
    "created_at": "ISO8601",
    "updated_at": "ISO8601"
  },
  "columns": {
    "id": "uuid",
    "board_id": "uuid",
    "name": "string",
    "wip_limit": "int (0 = no limit)",
    "position": "int",
    "color": "hex string"
  },
  "cards": {
    "id": "uuid",
    "column_id": "uuid",
    "title": "string",
    "description": "markdown",
    "assignee_id": "uuid",
    "labels": ["label_id"],
    "due_date": "ISO8601",
    "position": "int",
    "status": "active|archived",
    "sandbox_id": "uuid (optional)",
    "created_at": "ISO8601",
    "updated_at": "ISO8601"
  },
  "members": {
    "id": "uuid",
    "user_id": "uuid",
    "email": "string",
    "display_name": "string",
    "role": "owner|admin|member",
    "joined_at": "ISO8601"
  },
  "labels": {
    "id": "uuid",
    "board_id": "uuid",
    "name": "string",
    "color": "hex string"
  },
  "comments": {
    "id": "uuid",
    "card_id": "uuid",
    "author_id": "uuid",
    "content": "markdown",
    "created_at": "ISO8601"
  },
  "attachments": {
    "id": "uuid",
    "card_id": "uuid",
    "filename": "string",
    "file_path": "string",
    "mime_type": "string",
    "size": "int",
    "uploaded_by": "uuid",
    "created_at": "ISO8601"
  },
  "webhooks": {
    "id": "uuid",
    "url": "string",
    "secret": "string",
    "events": ["card.created", "card.moved", ...],
    "active": "bool",
    "created_at": "ISO8601"
  },
  "activity": {
    "id": "uuid",
    "entity_type": "board|column|card",
    "entity_id": "uuid",
    "action": "create|update|delete|move",
    "actor_id": "uuid",
    "changes": "json",
    "created_at": "ISO8601"
  },
  "agent_definitions": {
    "id": "uuid",
    "name": "string",
    "persona": "string",
    "tools": ["string"],
    "llm_config": {
      "model": "string",
      "temperature": "float"
    }
  },
  "column_agent_configs": {
    "id": "uuid",
    "column_id": "uuid",
    "agent_id": "uuid",
    "enabled": "bool",
    "trigger_on": "card_enter|card_create"
  },
  "automations": {
    "id": "uuid",
    "board_id": "uuid",
    "name": "string",
    "trigger": {
      "type": "card_moved|card_created|due_date",
      "conditions": {}
    },
    "actions": [{
      "type": "move_card|assign_member|add_label|notify",
      "params": {}
    }],
    "enabled": "bool"
  }
}
```

## Real-time Updates

### WebSocket Connection
```typescript
// frontend/src/services/websocket.ts
class WebSocketService {
  private ws: WebSocket;

  connect(boardId: string) {
    this.ws = new WebSocket(
      `wss://${window.location.host}/ws/boards/${boardId}`
    );

    this.ws.onmessage = (event) => {
      const message = JSON.parse(event.data);
      this.handleMessage(message);
    };
  }

  handleMessage(message: WSMessage) {
    switch (message.type) {
      case 'card.created':
        boardStore.addCard(message.data);
        break;
      case 'card.updated':
        boardStore.updateCard(message.data);
        break;
      case 'card.moved':
        boardStore.moveCard(message.data);
        break;
      case 'column.updated':
        boardStore.updateColumn(message.data);
        break;
    }
  }
}
```

### Server-side Broadcasting
```python
# backend/app/routes/websocket.py
from fastapi import WebSocket

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, board_id: str):
        await websocket.accept()
        if board_id not in self.active_connections:
            self.active_connections[board_id] = []
        self.active_connections[board_id].append(websocket)

    async def broadcast(self, board_id: str, message: dict):
        for connection in self.active_connections.get(board_id, []):
            await connection.send_json(message)

manager = ConnectionManager()

@app.websocket("/ws/boards/{board_id}")
async def websocket_endpoint(websocket: WebSocket, board_id: str):
    await manager.connect(websocket, board_id)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, board_id)
```

## Webhook System

### Webhook Events
| Event | Description | Payload |
|-------|-------------|---------|
| `card.created` | New card created | Card object |
| `card.updated` | Card modified | Card object + changes |
| `card.moved` | Card moved between columns | Card, from_column, to_column |
| `card.deleted` | Card removed | Card ID |
| `card.assigned` | Assignee changed | Card, assignee |
| `card.labeled` | Labels changed | Card, labels |
| `column.created` | New column | Column object |
| `column.updated` | Column modified | Column object |
| `board.updated` | Board settings changed | Board object |

### Webhook Dispatch
```python
async def trigger_webhook(event: str, payload: dict):
    webhooks = await db.get_webhooks(events_contains=event)

    for webhook in webhooks:
        if not webhook.active:
            continue

        # Sign payload
        signature = hmac.new(
            webhook.secret.encode(),
            json.dumps(payload).encode(),
            hashlib.sha256
        ).hexdigest()

        headers = {
            "X-Webhook-Event": event,
            "X-Webhook-Signature": signature,
            "Content-Type": "application/json"
        }

        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    webhook.url,
                    json=payload,
                    headers=headers,
                    timeout=30
                )
        except Exception as e:
            logger.error(f"Webhook failed: {e}")
```

## Agent Integration

### Agent Configuration per Column
```python
# Column can have assigned agents that trigger on card entry
{
  "column_id": "in-progress",
  "agent_id": "developer-agent",
  "enabled": true,
  "trigger_on": "card_enter"
}
```

### Agent Trigger Flow
```
Card moved to "In Progress" column
           │
           ▼
Column has agent configured?
           │
    Yes    │    No
     ▼     │     ▼
Trigger    │   Done
webhook    │
           │
           ▼
Kanban Agent receives webhook
           │
           ▼
Agent processes card (reads, writes code, etc.)
           │
           ▼
Agent updates card (comments, moves to next column)
```

## Frontend Features

### Drag and Drop
- React DnD for card movement
- Column reordering
- Cross-column card moves
- Optimistic updates with rollback

### Markdown Support
- Full markdown rendering in card descriptions
- Syntax highlighting for code blocks
- Checkbox lists (task lists)
- Tables support

### Link Previews
- Twitter/X embeds
- GitHub issue/PR previews
- YouTube video thumbnails
- OpenGraph metadata for generic links

### Responsive Design
- Mobile-friendly board view
- Touch gestures for card movement
- Collapsible columns on small screens

## Configuration

### Environment Variables
```bash
# Server
PORT=8000
TEAM_SLUG=my-team

# Database
DATABASE_PATH=/data/my-team/db.json

# Portal Integration
PORTAL_API_URL=https://kanban.domain/api
PORTAL_API_TOKEN=<team-token>

# WebSocket
WS_HEARTBEAT_INTERVAL=30

# Uploads
MAX_ATTACHMENT_SIZE=10485760  # 10MB
UPLOAD_DIR=/data/my-team/attachments
```

## Isolation Model

Each team instance is completely isolated:

```
Team A                          Team B
   │                               │
   ▼                               ▼
┌─────────────────┐        ┌─────────────────┐
│ team-a-api      │        │ team-b-api      │
│ team-a-web      │        │ team-b-web      │
│                 │        │                 │
│ /data/team-a/   │        │ /data/team-b/   │
│   └── db.json   │        │   └── db.json   │
│   └── uploads/  │        │   └── uploads/  │
└─────────────────┘        └─────────────────┘
        │                          │
        └────────────┬─────────────┘
                     │
              Traefik routes by subdomain
                     │
        team-a.domain    team-b.domain
```

## Related Documentation
- [Overview](./overview.md)
- [Kanban Agents Architecture](./kanban-agents.md)
- [Portal Architecture](./portal.md)
