#!/bin/bash
# Deploy sandbox app using the correct sandbox branch
# Usage: ./deploy-sandbox.sh <full_slug>
# Example: ./deploy-sandbox.sh finance-start

set -e

FULL_SLUG="${1:-}"
if [ -z "$FULL_SLUG" ]; then
    echo "Usage: $0 <full_slug>"
    echo "Example: $0 finance-start"
    exit 1
fi

# Paths
SANDBOX_DIR="/Volumes/dados/projects/kanban/data/sandboxes/${FULL_SLUG}"
REPO_DIR="${SANDBOX_DIR}/repo"
COMPOSE_FILE="${SANDBOX_DIR}/docker-compose.app.yml"

# Validate directories exist
if [ ! -d "$SANDBOX_DIR" ]; then
    echo "Error: Sandbox directory not found: $SANDBOX_DIR"
    exit 1
fi

if [ ! -d "$REPO_DIR" ]; then
    echo "Error: Repo directory not found: $REPO_DIR"
    exit 1
fi

if [ ! -f "$COMPOSE_FILE" ]; then
    echo "Error: Compose file not found: $COMPOSE_FILE"
    exit 1
fi

echo "=== Deploying Sandbox: $FULL_SLUG ==="

# Step 1: Ensure we're on the correct branch
echo ""
echo "[1/5] Checking out sandbox branch..."
cd "$REPO_DIR"
EXPECTED_BRANCH="sandbox/${FULL_SLUG}"
CURRENT_BRANCH=$(git branch --show-current)

if [ "$CURRENT_BRANCH" != "$EXPECTED_BRANCH" ]; then
    echo "Switching from '$CURRENT_BRANCH' to '$EXPECTED_BRANCH'"
    git fetch origin
    git checkout "$EXPECTED_BRANCH" || {
        echo "Error: Could not checkout branch $EXPECTED_BRANCH"
        exit 1
    }
fi

# Step 2: Pull latest changes
echo ""
echo "[2/5] Pulling latest changes..."
git pull origin "$EXPECTED_BRANCH" || {
    echo "Warning: Pull failed, continuing with local changes"
}

# Show latest commit
echo ""
echo "Latest commit:"
git log -1 --oneline

# Step 3: Stop existing containers
echo ""
echo "[3/5] Stopping existing containers..."
docker compose -f "$COMPOSE_FILE" -p "$FULL_SLUG" down --remove-orphans 2>/dev/null || true

# Step 4: Build and start containers
echo ""
echo "[4/5] Building and starting containers..."
docker compose -f "$COMPOSE_FILE" -p "$FULL_SLUG" up -d --build

# Step 5: Verify deployment
echo ""
echo "[5/5] Verifying deployment..."
sleep 5  # Give containers time to start

echo ""
echo "Container Status:"
docker ps --filter "name=${FULL_SLUG}" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

# Check if containers are running
RUNNING=$(docker ps --filter "name=${FULL_SLUG}" --filter "status=running" -q | wc -l | tr -d ' ')
if [ "$RUNNING" -lt 1 ]; then
    echo ""
    echo "Warning: No containers running for $FULL_SLUG"
    echo ""
    echo "Recent logs:"
    docker compose -f "$COMPOSE_FILE" -p "$FULL_SLUG" logs --tail 50
    exit 1
fi

echo ""
echo "=== Deployment Complete ==="
echo "Sandbox: $FULL_SLUG"
echo "Branch: $EXPECTED_BRANCH"
echo "Containers running: $RUNNING"
