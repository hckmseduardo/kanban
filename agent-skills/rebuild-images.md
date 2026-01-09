# /rebuild-images

Rebuild kanban-team Docker images (frontend and/or backend) after making code changes.

## When to Use

Use this script **after modifying code** in the `kanban-team` submodule:

- **Frontend changes** (`kanban-team/frontend/src/**`): Run with `--frontend`
- **Backend changes** (`kanban-team/backend/**`): Run with `--backend`
- **Both**: Run with `--all` (default)

**Important:** The `rebuild-workspace.sh` script does NOT rebuild images - it only restarts containers using existing images. You MUST use this script to rebuild images when code changes.

## Usage

```bash
./scripts/rebuild-images.sh [options]
```

## Options

| Option | Description |
|--------|-------------|
| `--frontend` | Rebuild only the frontend image (kanban-team-web) |
| `--backend` | Rebuild only the backend image (kanban-team-api) |
| `--all` | Rebuild both frontend and backend images (default if no options) |
| `--restart` | Also restart all running workspaces after building |

## Examples

```bash
# Rebuild both images (default)
./scripts/rebuild-images.sh

# Rebuild only frontend after UI changes
./scripts/rebuild-images.sh --frontend

# Rebuild only backend after API changes
./scripts/rebuild-images.sh --backend

# Rebuild frontend and restart all workspaces
./scripts/rebuild-images.sh --frontend --restart

# Full rebuild with restart
./scripts/rebuild-images.sh --all --restart
```

## Workflow

After making changes to `kanban-team`:

1. **Build the code** (if frontend):
   ```bash
   cd kanban-team/frontend && npm run build
   ```

2. **Rebuild the Docker image(s)**:
   ```bash
   ./scripts/rebuild-images.sh --frontend  # or --backend or --all
   ```

3. **Restart workspaces** to use the new image:
   ```bash
   ./scripts/rebuild-workspace.sh finance --restart-only
   ```

   Or combine steps 2-3:
   ```bash
   ./scripts/rebuild-images.sh --frontend --restart
   ```

## How It Works

1. Runs `docker build --no-cache` on the appropriate Dockerfile(s)
2. Tags the image as `kanban-team-web:latest` or `kanban-team-api:latest`
3. Optionally restarts all running workspace containers

## Image Architecture

The kanban-team uses **shared images**:

- `kanban-team-web:latest` - Nginx serving the built React frontend
- `kanban-team-api:latest` - Python FastAPI backend

All workspace instances (finance, marketing, etc.) use these same images. Rebuilding an image updates it for all workspaces (after restart).

## Related Files

- Script: `scripts/rebuild-images.sh`
- Frontend Dockerfile: `kanban-team/frontend/Dockerfile`
- Backend Dockerfile: `kanban-team/backend/Dockerfile`
- Workspace compose: `kanban-team/docker-compose.yml` (uses pre-built images)
