# /rebuild-workspace

Rebuild and restart workspace containers via the orchestrator.

## Usage

```bash
./scripts/rebuild-workspace.sh [workspace_slug] [options]
```

## Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `workspace_slug` | The workspace to rebuild | `finance` |

## Options

| Option | Description |
|--------|-------------|
| `--rebuild` | Rebuild images before restarting (default behavior) |
| `--restart-only` | Only restart containers without rebuilding images |
| `--with-app` | Also restart the app containers |

## Examples

```bash
# Rebuild finance workspace (default)
./scripts/rebuild-workspace.sh

# Rebuild specific workspace
./scripts/rebuild-workspace.sh myworkspace

# Restart without rebuilding
./scripts/rebuild-workspace.sh finance --restart-only

# Rebuild with app containers
./scripts/rebuild-workspace.sh finance --rebuild --with-app
```

## How It Works

1. Validates that `kanban-redis` and `kanban-orchestrator` containers are running
2. Creates a task with a unique ID and pushes it to the Redis queue `queue:provisioning:high`
3. The orchestrator picks up the task and executes the rebuild/restart
4. Script monitors progress and displays real-time status updates
5. Shows final container status on completion

## Task Flow

```
Script → Redis Queue → Orchestrator → Docker Compose → Containers
```

## Related Files

- Script: `scripts/rebuild-workspace.sh`
- Orchestrator: `orchestrator/app/main.py` (handles `workspace.restart` tasks)
- Docker Compose: `kanban-team/docker-compose.yml`
