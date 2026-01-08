# Portal Architecture

## Overview

The Portal is the central management hub for the Kanban Platform. It handles user authentication, team management, workspace provisioning, and provides a unified interface for all platform operations.

## Components

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Portal Service                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────────────────────┐    ┌──────────────────────────────┐       │
│  │      Portal Frontend         │    │       Portal Backend         │       │
│  │        (React/Vite)          │    │        (FastAPI)             │       │
│  │                              │    │                              │       │
│  │  Port: 80 (via Traefik)      │    │  Port: 8000 (internal)       │       │
│  │  Route: /                    │    │  Route: /api                 │       │
│  └──────────────────────────────┘    └──────────────────────────────┘       │
│                                                    │                         │
│                                                    ▼                         │
│                              ┌──────────────────────────────┐               │
│                              │       Portal Worker          │               │
│                              │    (Background Tasks)        │               │
│                              │                              │               │
│                              │  - Task Processing           │               │
│                              │  - Status Listeners          │               │
│                              └──────────────────────────────┘               │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Portal Backend

### Technology Stack
- **Framework**: FastAPI (Python 3.11)
- **Database**: TinyDB (JSON-based)
- **Authentication**: Microsoft Entra ID (OIDC/OAuth 2.0)
- **Message Queue**: Redis
- **Secrets**: Azure Key Vault

### Directory Structure
```
portal/backend/
├── app/
│   ├── main.py              # FastAPI application entry
│   ├── config.py            # Configuration settings
│   ├── routes/
│   │   ├── auth.py          # Authentication endpoints
│   │   ├── users.py         # User management
│   │   ├── teams.py         # Team CRUD operations
│   │   ├── portal_api.py    # Portal-specific operations
│   │   ├── workspaces.py    # Workspace management
│   │   ├── sandboxes.py     # Sandbox management
│   │   └── tasks.py         # Task status tracking
│   ├── services/
│   │   ├── database_service.py   # TinyDB operations
│   │   ├── team_proxy.py         # Team API proxy
│   │   ├── email_service.py      # Email notifications
│   │   └── redis_service.py      # Redis operations
│   ├── models/              # Pydantic models
│   └── middleware/          # Request middleware
├── worker.py                # Background task processor
└── requirements.txt
```

### API Endpoints

#### Authentication (`/auth`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/auth/login` | Initiate Entra ID login |
| POST | `/auth/callback` | OAuth callback handler |
| GET | `/auth/user` | Get current user info |
| POST | `/auth/logout` | Logout user |

#### Users (`/users`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/users/me` | Get current user profile |
| PUT | `/users/me` | Update user profile |

#### Teams (`/teams`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/teams` | Create new team (triggers provisioning) |
| GET | `/teams` | List user's teams |
| GET | `/teams/{slug}` | Get team details |
| PUT | `/teams/{slug}` | Update team |
| DELETE | `/teams/{slug}` | Delete team (triggers cleanup) |
| POST | `/teams/{slug}/members` | Invite member |
| GET | `/teams/{slug}/members` | List team members |
| DELETE | `/teams/{slug}/members/{user}` | Remove member |

#### Workspaces (`/workspaces`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/workspaces` | Create workspace |
| GET | `/workspaces` | List user's workspaces |
| GET | `/workspaces/{slug}` | Get workspace details |
| DELETE | `/workspaces/{slug}` | Delete workspace |
| POST | `/workspaces/{slug}/members` | Invite to workspace |

#### Sandboxes (`/workspaces/{slug}/sandboxes`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/workspaces/{slug}/sandboxes` | Create sandbox |
| GET | `/workspaces/{slug}/sandboxes` | List sandboxes |
| DELETE | `/workspaces/{slug}/sandboxes/{sandbox}` | Delete sandbox |

#### Tasks (`/tasks`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/tasks` | List user's background tasks |
| GET | `/tasks/{task_id}` | Get task status and progress |

### Database Schema (TinyDB)

```json
{
  "users": {
    "id": "uuid",
    "email": "string",
    "display_name": "string",
    "avatar_url": "string",
    "provider": "entra_id",
    "created_at": "ISO8601"
  },
  "teams": {
    "id": "uuid",
    "slug": "string (unique)",
    "name": "string",
    "owner_id": "user_id",
    "status": "active|provisioning|suspended|deleted",
    "subdomain": "url",
    "created_at": "ISO8601"
  },
  "memberships": {
    "id": "uuid",
    "team_id": "uuid",
    "user_id": "uuid",
    "role": "owner|admin|member",
    "joined_at": "ISO8601"
  },
  "workspaces": {
    "id": "uuid",
    "slug": "string",
    "name": "string",
    "kanban_team_id": "uuid",
    "app_template_id": "uuid",
    "github_repo_url": "string",
    "azure_app_id": "string",
    "status": "pending|active|deleted",
    "created_at": "ISO8601"
  },
  "sandboxes": {
    "id": "uuid",
    "workspace_id": "uuid",
    "full_slug": "string",
    "git_branch": "string",
    "agent_webhook_secret": "string",
    "status": "pending|active|deleted",
    "created_at": "ISO8601"
  },
  "invites": {
    "id": "uuid",
    "team_id": "uuid",
    "email": "string",
    "role": "admin|member",
    "token": "string",
    "expires_at": "ISO8601"
  },
  "app_templates": {
    "id": "uuid",
    "name": "string",
    "github_template_repo": "string",
    "description": "string"
  }
}
```

### Authentication Flow

```
User                    Portal                   Entra ID
 │                        │                          │
 │  1. Click Login        │                          │
 ├───────────────────────►│                          │
 │                        │  2. Redirect to Entra    │
 │                        ├─────────────────────────►│
 │                        │                          │
 │  3. User authenticates │                          │
 │◄───────────────────────┼──────────────────────────┤
 │                        │                          │
 │  4. Callback with code │                          │
 ├───────────────────────►│                          │
 │                        │  5. Exchange code        │
 │                        ├─────────────────────────►│
 │                        │                          │
 │                        │  6. Access/ID tokens     │
 │                        │◄─────────────────────────┤
 │                        │                          │
 │  7. JWT + User info    │                          │
 │◄───────────────────────┤                          │
```

## Portal Frontend

### Technology Stack
- **Framework**: React 18 with TypeScript
- **Build Tool**: Vite
- **State Management**: Zustand
- **Styling**: Tailwind CSS
- **HTTP Client**: Axios

### Directory Structure
```
portal/frontend/
├── src/
│   ├── App.tsx              # Main application
│   ├── main.tsx             # Entry point
│   ├── pages/
│   │   ├── LoginPage.tsx    # Authentication
│   │   ├── DashboardPage.tsx # Main dashboard
│   │   ├── TeamsPage.tsx    # Team management
│   │   ├── WorkspacesPage.tsx # Workspace management
│   │   └── AcceptInvitePage.tsx # Invitation handling
│   ├── components/
│   │   ├── common/          # Shared components
│   │   ├── teams/           # Team-related components
│   │   └── workspaces/      # Workspace components
│   ├── stores/
│   │   └── authStore.ts     # Auth state (Zustand)
│   ├── services/
│   │   └── api.ts           # API client
│   └── types/               # TypeScript types
├── index.html
└── vite.config.ts
```

### Key Features
- Microsoft Entra ID login integration
- Real-time task progress display via WebSocket
- Team and workspace management dashboards
- Member invitation system
- Responsive design

## Portal Worker

### Purpose
Background task processor that:
1. Processes queued tasks (certificates, DNS, notifications)
2. Listens for status updates from orchestrator
3. Updates database with provisioning results

### Implementation
```python
# portal/backend/app/worker.py

async def main():
    # Initialize Redis connections
    redis = await get_redis_connection()
    pubsub = redis.pubsub()

    # Subscribe to status channels
    await pubsub.subscribe(
        "team:status",
        "workspace:status",
        "sandbox:status"
    )

    # Process messages
    async for message in pubsub.listen():
        await handle_status_update(message)

async def handle_status_update(message):
    channel = message["channel"]
    data = json.loads(message["data"])

    if channel == "team:status":
        await update_team_status(data)
    elif channel == "workspace:status":
        await update_workspace_status(data)
    elif channel == "sandbox:status":
        await update_sandbox_status(data)
```

### Status Update Flow
```
Orchestrator                  Redis                   Worker                  Database
     │                          │                        │                        │
     │  1. Publish status       │                        │                        │
     ├─────────────────────────►│                        │                        │
     │                          │  2. Deliver to sub     │                        │
     │                          ├───────────────────────►│                        │
     │                          │                        │  3. Update record      │
     │                          │                        ├───────────────────────►│
     │                          │                        │                        │
     │                          │  4. Notify user        │                        │
     │                          │◄───────────────────────┤                        │
     │                          │     (tasks:{user_id})  │                        │
```

## Configuration

### Environment Variables
```bash
# Server
PORT=8000
DOMAIN=kanban.amazing-ai.tools

# Database
PORTAL_DB_PATH=/data/portal/portal.json

# Redis
REDIS_URL=redis://redis:6379

# Azure Key Vault
AZURE_KEY_VAULT_URL=https://your-vault.vault.azure.net/

# Authentication (Entra ID)
ENTRA_CLIENT_ID=<client-id>
ENTRA_CLIENT_SECRET=<from-keyvault>
ENTRA_TENANT_ID=<tenant-id>

# Email
EMAIL_PROVIDER=sendgrid|office365
SENDGRID_API_KEY=<from-keyvault>

# Cross-domain
CROSS_DOMAIN_SECRET=<shared-secret>
```

### Azure Key Vault Integration
```python
# Credentials are loaded from Key Vault
from azure.keyvault.secrets import SecretClient

class Settings(BaseSettings):
    @cached_property
    def entra_client_secret(self) -> str:
        if self.azure_key_vault_url:
            client = SecretClient(vault_url=self.azure_key_vault_url)
            return client.get_secret("entra-client-secret").value
        return os.getenv("ENTRA_CLIENT_SECRET")
```

## Security

### Authentication
- Microsoft Entra ID exclusive authentication
- JWT tokens with 24-hour expiry
- HTTPS enforced via Traefik

### Authorization
- Role-based access: owner, admin, member
- Team-scoped permissions
- API token scopes: teams:read, teams:write, workspaces:read, workspaces:write

### Cross-Service Authentication
- CROSS_DOMAIN_SECRET for server-to-server calls
- Webhook secrets for agent communication

## Related Documentation
- [Overview](./overview.md)
- [Orchestrator Architecture](./orchestrator.md)
- [Message Queue Patterns](./message-queue.md)
