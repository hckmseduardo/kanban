We are focusing on create amazin tools.
the project should always use message queuen to order the tasks
all tasks should give feedback for the user during its process
we always display a feedback for the user when a task is completed
we don't touche anything on other stack docker running on the same server
we work a single configuration file and all necessary keys in an azure keyvault
we should keep an azure secret adding script as example using azure cli

always use the orchestrator to manipulate kanban-team and the apps

## Architecture Documentation

| Topic | Description | Documentation |
|-------|-------------|---------------|
| Orchestrator | Provisioning engine, Claude Code SSH setup | [orchestrator.md](docs/architecture/orchestrator.md) |
| Kanban Agents | On-demand AI agents via Claude Code | [kanban-agents.md](docs/architecture/kanban-agents.md) |
| Infrastructure | Docker, Traefik, Redis setup | [infrastructure.md](docs/architecture/infrastructure.md) |

### Claude Code SSH Configuration

The orchestrator runs Claude Code on the host machine via SSH. Required `.env` variables:

```bash
SSH_USER=myusername                           # Required: host machine username
SSH_HOST=host.docker.internal                 # Docker's way to reach host
SSH_CLAUDE_PATH=/usr/local/bin/claude-loggedin  # Path to Claude CLI wrapper
```

See [orchestrator.md](docs/architecture/orchestrator.md#claude-code-runner-service) for full setup instructions.

## Skills

Skills are documented in the `agent-skills/` folder. Each skill has its own `.md` file with usage instructions.

| Skill | Description | Documentation |
|-------|-------------|---------------|
| `/rebuild-workspace` | Rebuild and restart workspace containers via orchestrator | [rebuild-workspace.md](agent-skills/rebuild-workspace.md) |