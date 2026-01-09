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

## After Modifying kanban-team Code

When you modify code in the `kanban-team` submodule, you MUST rebuild the Docker images for changes to take effect:

```bash
# After frontend changes (kanban-team/frontend/src/**)
./scripts/rebuild-images.sh --frontend --restart

# After backend changes (kanban-team/backend/**)
./scripts/rebuild-images.sh --backend --restart

# After both frontend and backend changes
./scripts/rebuild-images.sh --all --restart
```

**Important:** The `rebuild-workspace.sh` script does NOT rebuild images - it only restarts containers. Always use `rebuild-images.sh` after code changes.

## Skills

Skills are documented in the `agent-skills/` folder. Each skill has its own `.md` file with usage instructions.

| Skill | Description | Documentation |
|-------|-------------|---------------|
| `/rebuild-images` | Rebuild kanban-team Docker images after code changes | [rebuild-images.md](agent-skills/rebuild-images.md) |
| `/rebuild-workspace` | Restart workspace containers (does NOT rebuild images) | [rebuild-workspace.md](agent-skills/rebuild-workspace.md) |