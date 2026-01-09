# Orchestrator Architecture

## Overview

The Orchestrator is the provisioning engine responsible for creating, managing, and cleaning up infrastructure resources. It handles team instances, workspaces, sandboxes, and coordinates with external services like GitHub and Azure.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            Orchestrator Service                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────┐     │
│  │                        Main Process                                 │     │
│  │                                                                     │     │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                 │     │
│  │  │   Queue     │  │   Task      │  │   Status    │                 │     │
│  │  │   Listener  │  │   Router    │  │   Publisher │                 │     │
│  │  └─────────────┘  └─────────────┘  └─────────────┘                 │     │
│  └────────────────────────────────────────────────────────────────────┘     │
│                                    │                                         │
│        ┌───────────────────────────┼───────────────────────────┐            │
│        │                           │                           │            │
│        ▼                           ▼                           ▼            │
│  ┌───────────────┐         ┌───────────────┐         ┌───────────────┐     │
│  │    GitHub     │         │    Azure      │         │   Agent       │     │
│  │    Service    │         │    Service    │         │   Factory     │     │
│  │               │         │               │         │               │     │
│  │ - Create repo │         │ - App reg     │         │ - Provision   │     │
│  │ - Branches    │         │ - Redirect    │         │ - Configure   │     │
│  │ - Templates   │         │   URIs        │         │ - Restart     │     │
│  └───────────────┘         └───────────────┘         └───────────────┘     │
│        │                           │                           │            │
│        ▼                           ▼                           ▼            │
│  ┌───────────────┐         ┌───────────────┐         ┌───────────────┐     │
│  │  Certificate  │         │   Database    │         │    Docker     │     │
│  │    Service    │         │    Cloner     │         │    Service    │     │
│  │               │         │               │         │               │     │
│  │ - SSL certs   │         │ - Clone DB    │         │ - Containers  │     │
│  │ - Renewal     │         │ - Isolation   │         │ - Networks    │     │
│  └───────────────┘         └───────────────┘         └───────────────┘     │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Directory Structure

```
orchestrator/
├── app/
│   ├── main.py                  # Main entry point
│   ├── config.py                # Configuration settings
│   ├── services/
│   │   ├── claude_code_runner.py # On-demand agent subprocess
│   │   ├── azure_service.py     # Azure AD integration
│   │   ├── certificate_service.py # SSL certificates
│   │   ├── database_cloner.py   # Database operations
│   │   └── github_service.py    # GitHub operations
│   ├── tasks/
│   │   ├── team_tasks.py        # Team provisioning
│   │   ├── workspace_tasks.py   # Workspace provisioning
│   │   └── sandbox_tasks.py     # Sandbox provisioning
│   └── templates/               # Docker compose templates
├── Dockerfile
└── requirements.txt
```

## Task Types

### Team Tasks
| Task Type | Description | Priority |
|-----------|-------------|----------|
| `team.provision` | Create new team instance | High |
| `team.delete` | Remove team and cleanup | Normal |
| `team.restart` | Restart team containers | High |
| `team.suspend` | Suspend idle team | Normal |

### Workspace Tasks
| Task Type | Description | Priority |
|-----------|-------------|----------|
| `workspace.provision` | Create workspace with app | High |
| `workspace.delete` | Remove workspace | Normal |

### Sandbox Tasks
| Task Type | Description | Priority |
|-----------|-------------|----------|
| `sandbox.provision` | Create development sandbox | High |
| `sandbox.delete` | Remove sandbox | Normal |
| `sandbox.agent.restart` | Restart agent container | High |

## Queue Processing

### Queue Configuration
```python
QUEUES = [
    "queue:provisioning:high",    # Priority queue
    "queue:provisioning:normal"   # Standard queue
]
```

### Task Processing Loop
```python
async def process_tasks():
    redis = await get_redis_connection()

    while True:
        # BRPOP blocks until task available
        # High priority checked first
        result = await redis.brpop(
            "queue:provisioning:high",
            "queue:provisioning:normal",
            timeout=5
        )

        if result:
            queue_name, task_data = result
            task = json.loads(task_data)
            await route_task(task)
```

### Task Routing
```python
async def route_task(task: dict):
    task_type = task["type"]

    handlers = {
        "team.provision": handle_team_provision,
        "team.delete": handle_team_delete,
        "team.restart": handle_team_restart,
        "workspace.provision": handle_workspace_provision,
        "workspace.delete": handle_workspace_delete,
        "sandbox.provision": handle_sandbox_provision,
        "sandbox.delete": handle_sandbox_delete,
        "sandbox.agent.restart": handle_agent_restart,
    }

    handler = handlers.get(task_type)
    if handler:
        await handler(task)
```

## Services

### Claude Code Runner Service

Executes Claude Code CLI on the host machine via SSH for on-demand AI agent tasks.
This allows using the Claude Pro subscription for reduced costs instead of API calls.

#### SSH Configuration

The orchestrator runs inside Docker and connects to the host machine via SSH to execute
Claude Code. This requires the following environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `SSH_USER` | Username on the host machine | **Required** |
| `SSH_HOST` | Host to SSH into | `host.docker.internal` |
| `SSH_CLAUDE_PATH` | Path to Claude CLI on host | `~/.local/bin/claude` |

**Example `.env` configuration:**
```bash
# SSH Configuration for Claude Code (AI Enhancement)
SSH_USER=myusername
SSH_HOST=host.docker.internal
SSH_CLAUDE_PATH=/usr/local/bin/claude-loggedin
```

#### Authentication Wrapper

If Claude CLI requires authentication (login), you may need to create a wrapper script
that runs Claude with the correct environment. For example:

```bash
#!/bin/bash
# /usr/local/bin/claude-loggedin
# Wrapper to run Claude with proper authentication context

export HOME=/Users/myusername
export CLAUDE_CONFIG_DIR=$HOME/.claude
exec /Users/myusername/.local/bin/claude "$@"
```

Make the wrapper executable and set `SSH_CLAUDE_PATH` to point to it.

#### Prerequisites

1. **SSH access from Docker to host**: The orchestrator mounts `~/.ssh:/root/.ssh:ro`
   to access SSH keys. Ensure passwordless SSH works:
   ```bash
   ssh myusername@host.docker.internal echo "SSH works"
   ```

2. **Claude CLI installed on host**: Install via `npm install -g @anthropic-ai/claude-code`

3. **Claude CLI authenticated**: Run `claude login` on the host to authenticate

#### API

```python
class ClaudeCodeRunner:
    async def run(
        self,
        prompt: str,
        working_dir: str,
        agent_type: str = "developer",
        tool_profile: str = None,
        allowed_tools: list = None,
        timeout: int = None
    ) -> AgentResult:
        """
        Executes Claude Code CLI on host via SSH.

        Steps:
        1. Build SSH command with prompt and tools
        2. Execute via SSH to host machine
        3. Stream output for progress updates
        4. Return result with success/error status
        """

    def get_tools_for_profile(self, tool_profile: str) -> list:
        """Get allowed tools for a tool profile (readonly, developer, full-access)."""

    def get_tools_for_agent(self, agent_type: str) -> list:
        """Legacy: Get allowed tools for an agent type."""

    def get_timeout_for_agent(self, agent_type: str) -> int:
        """Get timeout in seconds for an agent type."""
```

#### Tool Profiles

| Profile | Tools | Use Case |
|---------|-------|----------|
| `readonly` | Read, Glob, Grep | Analysis, enhancement suggestions |
| `developer` | Read, Write, Edit, Glob, Grep, Bash | Code modifications |
| `full-access` | All tools + Task, WebFetch | Complex multi-step tasks |

Note: AI agents are now on-demand via Claude Code subprocess.
No dedicated agent containers - see [On-Demand Agents](./kanban-agents.md).

### GitHub Service

Manages repository operations for workspaces.

```python
class GitHubService:
    async def create_repo_from_template(
        self,
        template_repo: str,
        new_repo_name: str,
        private: bool = True
    ) -> str:
        """Create a new repository from a template."""

    async def create_branch(
        self,
        repo: str,
        branch_name: str,
        source_branch: str = "main"
    ) -> None:
        """Create a new branch for sandbox development."""

    async def delete_branch(self, repo: str, branch_name: str) -> None:
        """Delete a branch when sandbox is removed."""
```

### Azure Service

Handles Azure AD app registration for workspace authentication.

```python
class AzureService:
    async def create_app_registration(
        self,
        display_name: str,
        redirect_uris: List[str]
    ) -> AzureApp:
        """
        Creates an Azure AD app registration.

        Returns:
        - client_id
        - client_secret (generated)
        - tenant_id
        """

    async def add_redirect_uri(
        self,
        app_id: str,
        redirect_uri: str
    ) -> None:
        """Add redirect URI for sandbox."""

    async def remove_redirect_uri(
        self,
        app_id: str,
        redirect_uri: str
    ) -> None:
        """Remove redirect URI when sandbox deleted."""

    async def delete_app_registration(self, app_id: str) -> None:
        """Delete app registration when workspace deleted."""
```

### Certificate Service

Manages SSL certificates via Let's Encrypt.

```python
class CertificateService:
    async def request_certificate(self, domain: str) -> bool:
        """Request a new SSL certificate."""

    async def renew_certificate(self, domain: str) -> bool:
        """Renew an existing certificate."""

    async def check_certificate_status(self, domain: str) -> CertStatus:
        """Check certificate validity and expiry."""
```

### Database Cloner Service

Handles database operations for isolation.

```python
class DatabaseCloner:
    async def clone_database(
        self,
        source_path: str,
        target_path: str
    ) -> None:
        """Clone a TinyDB database for sandbox isolation."""

    async def delete_database(self, path: str) -> None:
        """Remove database when resource deleted."""
```

## Provisioning Flows

### Team Provisioning Flow

```
Portal API                    Orchestrator                    Docker
     │                              │                            │
     │  1. Queue team.provision     │                            │
     ├─────────────────────────────►│                            │
     │                              │                            │
     │                              │  2. Create team directory  │
     │                              ├───────────────────────────►│
     │                              │                            │
     │                              │  3. Generate docker-compose│
     │                              ├───────────────────────────►│
     │                              │                            │
     │                              │  4. Create TinyDB instance │
     │                              ├───────────────────────────►│
     │                              │                            │
     │                              │  5. Start containers       │
     │                              ├───────────────────────────►│
     │                              │                            │
     │  6. Publish team:status      │                            │
     │◄─────────────────────────────┤                            │
```

### Workspace Provisioning Flow

```
Portal API                Orchestrator               GitHub            Azure
     │                         │                        │                 │
     │  1. Queue workspace.    │                        │                 │
     │     provision           │                        │                 │
     ├────────────────────────►│                        │                 │
     │                         │                        │                 │
     │                         │  2. Create team        │                 │
     │                         ├───────────────────────►│                 │
     │                         │                        │                 │
     │                         │  3. Create repo from   │                 │
     │                         │     template           │                 │
     │                         ├───────────────────────►│                 │
     │                         │                        │                 │
     │                         │  4. Create app         │                 │
     │                         │     registration       │                 │
     │                         ├───────────────────────────────────────────►
     │                         │                        │                 │
     │                         │  5. Deploy app         │                 │
     │                         │     containers         │                 │
     │                         ├───────────────────────►│                 │
     │                         │                        │                 │
     │  6. Publish workspace:  │                        │                 │
     │     status              │                        │                 │
     │◄────────────────────────┤                        │                 │
```

### Sandbox Provisioning Flow

```
Portal API                Orchestrator              Git              Docker
     │                         │                      │                  │
     │  1. Queue sandbox.      │                      │                  │
     │     provision           │                      │                  │
     ├────────────────────────►│                      │                  │
     │                         │                      │                  │
     │                         │  2. Create git       │                  │
     │                         │     branch           │                  │
     │                         ├─────────────────────►│                  │
     │                         │                      │                  │
     │                         │  3. Clone database   │                  │
     │                         ├─────────────────────────────────────────►
     │                         │                      │                  │
     │                         │  4. Deploy sandbox   │                  │
     │                         │     app containers   │                  │
     │                         ├─────────────────────────────────────────►
     │                         │                      │                  │
     │                         │  5. Add Azure        │                  │
     │                         │     redirect URI     │                  │
     │                         ├─────────────────────►│                  │
     │                         │                      │                  │
     │  6. Publish sandbox:    │                      │                  │
     │     status              │                      │                  │
     │◄────────────────────────┤                      │                  │

Note: No dedicated agent containers are provisioned.
AI agents are spawned on-demand when cards are moved.
```

## Status Publishing

### Status Channels
```python
CHANNELS = {
    "team": "team:status",
    "workspace": "workspace:status",
    "sandbox": "sandbox:status"
}
```

### Status Message Format
```python
{
    "type": "provision|delete|restart",
    "resource_type": "team|workspace|sandbox",
    "resource_id": "uuid",
    "status": "active|deleted|failed",
    "error": "optional error message",
    "metadata": {
        # Resource-specific data
        "subdomain": "team-slug.domain",
        "agent_webhook_secret": "secret",
        "github_repo_url": "url"
    }
}
```

### Publishing Updates
```python
async def publish_status(
    resource_type: str,
    resource_id: str,
    status: str,
    metadata: dict = None
):
    redis = await get_redis_connection()
    channel = CHANNELS[resource_type]

    message = {
        "resource_id": resource_id,
        "status": status,
        "metadata": metadata or {},
        "timestamp": datetime.utcnow().isoformat()
    }

    await redis.publish(channel, json.dumps(message))
```

## Progress Tracking

### Task Progress Updates
```python
async def update_task_progress(
    task_id: str,
    user_id: str,
    step: int,
    total_steps: int,
    message: str
):
    redis = await get_redis_connection()

    # Update task hash
    await redis.hset(f"task:{task_id}", mapping={
        "step": step,
        "total_steps": total_steps,
        "message": message,
        "percentage": int((step / total_steps) * 100)
    })

    # Publish to user channel
    await redis.publish(f"tasks:{user_id}", json.dumps({
        "type": "task.progress",
        "task_id": task_id,
        "step": step,
        "total_steps": total_steps,
        "percentage": int((step / total_steps) * 100),
        "message": message
    }))
```

## Docker Compose Templates

### Team Instance Template
```yaml
# templates/team-compose.yml.j2
version: '3.8'

services:
  {{ team_slug }}-api:
    image: kanban-team-api:latest
    environment:
      - TEAM_SLUG={{ team_slug }}
      - DATABASE_PATH=/data/{{ team_slug }}/db.json
      - PORTAL_API_URL={{ portal_api_url }}
    volumes:
      - ./data/{{ team_slug }}:/data/{{ team_slug }}
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.{{ team_slug }}-api.rule=Host(`{{ team_slug }}.{{ domain }}`)"

  {{ team_slug }}-web:
    image: kanban-team-web:latest
    environment:
      - API_URL=https://{{ team_slug }}.{{ domain }}/api
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.{{ team_slug }}-web.rule=Host(`{{ team_slug }}.{{ domain }}`)"
```

### Agent Container Template
```yaml
# templates/agent-compose.yml.j2
version: '3.8'

services:
  {{ workspace_slug }}-agent-{{ branch }}:
    image: kanban-agents:latest
    environment:
      - WORKSPACE_SLUG={{ workspace_slug }}
      - GIT_BRANCH={{ branch }}
      - WEBHOOK_SECRET={{ webhook_secret }}
      - KANBAN_API_URL={{ kanban_api_url }}
      - LLM_PROVIDER={{ llm_provider }}
    volumes:
      - ./repos/{{ workspace_slug }}:/app/repo
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.{{ agent_name }}.rule=Host(`{{ agent_subdomain }}.{{ domain }}`)"
```

## Configuration

### Environment Variables
```bash
# Redis
REDIS_URL=redis://redis:6379

# Docker
DOCKER_HOST=unix:///var/run/docker.sock

# GitHub
GITHUB_TOKEN=<from-keyvault>
GITHUB_ORG=<organization>

# Azure
AZURE_KEY_VAULT_URL=https://vault.vault.azure.net/
AZURE_CLIENT_ID=<client-id>
AZURE_CLIENT_SECRET=<from-keyvault>
AZURE_TENANT_ID=<tenant-id>

# Domain
DOMAIN=kanban.amazing-ai.tools
PORTAL_API_URL=https://kanban.amazing-ai.tools/api

# SSH - Claude Code execution on host (required for AI enhancement)
SSH_USER=myusername              # Required: username on host machine
SSH_HOST=host.docker.internal    # Docker's way to reach host
SSH_CLAUDE_PATH=/usr/local/bin/claude-loggedin  # Path to Claude CLI (or wrapper)
```

## Error Handling

### Retry Strategy
```python
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=60)
)
async def provision_with_retry(task: dict):
    try:
        await handle_provisioning(task)
    except Exception as e:
        logger.error(f"Provisioning failed: {e}")
        await publish_failure(task, str(e))
        raise
```

### Cleanup on Failure
```python
async def handle_workspace_provision(task: dict):
    created_resources = []
    try:
        # Track resources as they're created
        team = await create_team(task)
        created_resources.append(("team", team.id))

        repo = await create_repo(task)
        created_resources.append(("repo", repo.url))

        app = await create_azure_app(task)
        created_resources.append(("azure_app", app.id))

        await deploy_containers(task)

    except Exception as e:
        # Rollback created resources
        for resource_type, resource_id in reversed(created_resources):
            await cleanup_resource(resource_type, resource_id)
        raise
```

## Related Documentation
- [Overview](./overview.md)
- [Portal Architecture](./portal.md)
- [Message Queue Patterns](./message-queue.md)
- [Data Flow Diagrams](./data-flow.md)
