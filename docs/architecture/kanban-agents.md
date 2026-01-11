# On-Demand AI Agents Architecture

## Overview

AI agents in the Kanban system are spawned on-demand when cards are moved between columns. Instead of running persistent agent containers, the orchestrator spawns Claude Code CLI (default) or Codex CLI (optional) subprocesses for each task, providing:

- **Cost efficiency**: No idle containers
- **Full agentic capabilities**: Claude Code CLI or Codex CLI with tools
- **Pro subscription usage**: No per-call API costs
- **Sandbox isolation**: Each agent runs in its sandbox's git branch

## Architecture

```
┌─────────────────┐     Webhook      ┌─────────────────┐
│  Kanban Team    │ ───────────────► │  Portal Backend │
│  (card.moved)   │                  │  (queue task)   │
└─────────────────┘                  └────────┬────────┘
                                              │
                                              ▼
┌─────────────────────────────────────────────────────────┐
│                     Redis Queue                          │
│  queue:agents:high / queue:agents:normal                │
└────────────────────────────┬────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────┐
│                    Orchestrator                          │
│  ┌─────────────────────────────────────────────────────┐│
│  │  AgentTaskProcessor                                 ││
│  │  - Listen to queue:agents:*                         ││
│  │  - For each task:                                   ││
│  │    1. Checkout sandbox git branch                   ││
│  │    2. Prepare environment                           ││
│  │    3. Spawn agent CLI subprocess                    ││
│  │    4. Stream progress to card comments              ││
│  │    5. Commit changes on success                     ││
│  │    6. Update card status                            ││
│  └─────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────┘
```

## Data Flow

1. **Card moves to a column** in Kanban Team
2. **Webhook fires** to Portal Backend `/agents/webhook`
3. **Task queued** in Redis (`queue:agents:high` or `queue:agents:normal`)
4. **Orchestrator picks up task** and spawns the configured agent CLI subprocess
5. **Agent CLI executes** with agent persona and tools
6. **Results committed** to sandbox git branch
7. **Card updated** with agent completion status

## Agent Types & Column Mapping

| Column | Agent Type | Tools | Description |
|--------|------------|-------|-------------|
| Backlog | `product_owner` | Read, Glob, Grep | Refines requirements, adds acceptance criteria |
| To Do | `architect` | Read, Glob, Grep, Bash, Task | Designs technical solution |
| Development | `developer` | Read, Write, Edit, Glob, Grep, Bash, Task | Implements features and fixes |
| Code Review | `reviewer` | Read, Glob, Grep, Bash | Reviews code quality |
| Testing | `qa` | Read, Glob, Grep, Bash | Runs tests, validates implementation |
| Done | `release` | Read, Glob, Grep, Bash | Updates changelog, release notes |

## Key Components

### Webhook Endpoint

Located in `portal/backend/app/routes/agents.py`:

```python
@router.post("/webhook")
async def receive_card_event(
    request: Request,
    payload: CardEventPayload,
    x_webhook_signature: Optional[str] = Header(None),
):
    # Verify signature
    # Determine agent type from column
    # Queue agent task
```

### Task Service

Located in `portal/backend/app/services/task_service.py`:

```python
async def create_agent_task(
    card_id: str,
    card_title: str,
    card_description: str,
    column_name: str,
    agent_type: str,
    sandbox_id: str,
    workspace_slug: str,
    git_branch: str,
    ...
) -> str:
    """Queue an on-demand agent task."""
```

### Agent CLI Runners

Located in `orchestrator/app/services/claude_code_runner.py` (Claude CLI) and
`orchestrator/app/services/codex_cli_runner.py` (Codex CLI):

```python
class ClaudeCodeRunner:
    async def run(
        self,
        prompt: str,
        working_dir: str,
        agent_type: str,
        allowed_tools: list = None,
        timeout: int = None,
    ) -> AgentResult:
        """Spawn Claude Code CLI subprocess."""
```

### Agent Task Processor

Located in `orchestrator/app/main.py`:

```python
async def process_agent_task(self, task: dict):
    """Process an AI agent task using an agent CLI subprocess."""
    # 1. Prepare sandbox context
    # 2. Build agent prompt
    # 3. Run agent CLI
    # 4. Process results (commit changes)
    # 5. Update card
```

## Agent Prompts

Each agent type has a specific prompt that defines its persona:

```python
AGENT_PROMPTS = {
    "developer": """You are an expert software developer.
Your task is to implement the feature or fix described in the card.

Instructions:
1. Read the existing codebase to understand patterns
2. Implement the changes described in the card
3. Write clean, maintainable code
4. Add or update tests as needed
5. Ensure the code compiles/runs without errors""",

    "architect": """You are a software architect.
Your task is to design the technical solution for this card.

Instructions:
1. Analyze the requirements
2. Explore the existing codebase architecture
3. Design a technical approach
4. Document the design decisions
5. Break down into implementation tasks""",

    # ... other agents
}
```

## Sandbox Isolation

Each agent task runs in an isolated context:

```
Workspace: my-project
├── main branch (production)
├── Sandbox: feature-auth
│   └── Git branch: sandbox/my-project-feature-auth
│       └── Agent runs HERE with isolated context
└── Sandbox: bugfix-login
    └── Git branch: sandbox/my-project-bugfix-login
        └── Different agent runs HERE
```

### Isolation Mechanisms

1. **Git branch checkout**: Agent works on sandbox-specific branch
2. **Working directory**: Agent CLI runs in sandbox project path
3. **Database**: Each sandbox has isolated database
4. **Webhook secret**: Per-sandbox authentication

## Configuration

### Environment Variables (Orchestrator)

```bash
# Claude Code CLI must be installed (default)
# Codex CLI is optional when using llm_provider=codex-cli

# Project paths
HOST_PROJECT_PATH=/path/to/kanban
```

Per-column agent overrides can set `llm_provider` to `codex-cli` to switch the
agent CLI for that column (defaults to `claude-cli`).

### Agent Timeouts

```python
AGENT_TIMEOUTS = {
    "developer": 900,   # 15 minutes
    "architect": 600,   # 10 minutes
    "reviewer": 300,    # 5 minutes
    "qa": 600,          # 10 minutes
    "product_owner": 300,
    "release": 300,
}
```

## Error Handling

### Task Failure

When an agent task fails:
1. Error is logged
2. Card is updated with failure comment
3. Task marked as failed in Redis
4. Can be retried via task service

### Timeout Handling

```python
try:
    await asyncio.wait_for(
        asyncio.gather(stdout_task, stderr_task),
        timeout=timeout
    )
except asyncio.TimeoutError:
    proc.terminate()
    return AgentResult(success=False, error="Agent timed out")
```

## Security

### Webhook Authentication
- HMAC-SHA256 signature verification
- Per-sandbox webhook secrets
- Request validation

### Tool Permissions
- Claude Code runs with `--dangerouslySkipPermissions` in sandbox
- Codex CLI runs with `--approval-mode` mapped from tool_profile
- Tools restricted to sandbox directory
- No access to other sandboxes

### Secret Management
- Webhook secrets stored in database
- No secrets in card comments or logs

## Comparison: Old vs New Architecture

| Aspect | Old (Container per sandbox) | New (On-demand subprocess) |
|--------|----------------------------|---------------------------|
| Resource usage | Always running | Only when processing |
| Cost | Container overhead | Zero idle cost |
| Startup time | Instant (always ready) | ~2-3s (spawn subprocess) |
| Isolation | Docker container | Git branch + directory |
| LLM | API calls (pay per use) | Pro subscription (included) |
| Tools | Custom Python tools | Claude Code built-in tools |
| Complexity | Container management | Subprocess management |

## Related Documentation

- [Overview](./overview.md)
- [Orchestrator Architecture](./orchestrator.md)
- [Kanban Team Architecture](./kanban-team.md)
