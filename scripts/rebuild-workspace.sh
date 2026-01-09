#!/bin/bash
# Rebuild and restart workspace containers via the orchestrator
# Usage: ./rebuild-workspace.sh [workspace_slug] [--rebuild|--restart-only] [--with-app]

set -e

# Default values
WORKSPACE_SLUG="${1:-finance}"
REBUILD=true
RESTART_APP=false

# Parse arguments
shift 2>/dev/null || true
while [[ $# -gt 0 ]]; do
    case $1 in
        --rebuild)
            REBUILD=true
            shift
            ;;
        --restart-only)
            REBUILD=false
            shift
            ;;
        --with-app)
            RESTART_APP=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [workspace_slug] [--rebuild|--restart-only] [--with-app]"
            exit 1
            ;;
    esac
done

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}=== Workspace Rebuild Tool ===${NC}"
echo -e "Workspace: ${YELLOW}${WORKSPACE_SLUG}${NC}"
echo -e "Rebuild images: ${YELLOW}${REBUILD}${NC}"
echo -e "Restart app: ${YELLOW}${RESTART_APP}${NC}"
echo ""

# Check if redis container is running
if ! docker ps --format '{{.Names}}' | grep -q 'kanban-redis'; then
    echo -e "${RED}Error: kanban-redis container is not running${NC}"
    exit 1
fi

# Check if orchestrator is running
if ! docker ps --format '{{.Names}}' | grep -q 'kanban-orchestrator'; then
    echo -e "${RED}Error: kanban-orchestrator container is not running${NC}"
    exit 1
fi

# Generate task ID
TASK_ID="rebuild-${WORKSPACE_SLUG}-$(date +%s)"
TASK_DATA="{\"type\": \"workspace.restart\", \"task_id\": \"${TASK_ID}\", \"user_id\": \"cli\", \"payload\": {\"workspace_id\": \"${WORKSPACE_SLUG}\", \"workspace_slug\": \"${WORKSPACE_SLUG}\", \"rebuild\": ${REBUILD}, \"restart_app\": ${RESTART_APP}}}"

echo -e "${BLUE}Creating task: ${TASK_ID}${NC}"

# Create task in Redis
docker exec kanban-redis redis-cli HSET "task:${TASK_ID}" \
    "type" "workspace.restart" \
    "created_at" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    "id" "${TASK_ID}" \
    "status" "pending" \
    "data" "${TASK_DATA}" > /dev/null

# Push to queue
docker exec kanban-redis redis-cli LPUSH "queue:provisioning:high" "${TASK_ID}" > /dev/null

echo -e "${GREEN}Task queued successfully${NC}"
echo ""
echo -e "${BLUE}Monitoring progress...${NC}"

# Monitor progress
MAX_WAIT=120  # 2 minutes max
WAIT_TIME=0
LAST_STEP=""

while [ $WAIT_TIME -lt $MAX_WAIT ]; do
    DATA=$(docker exec kanban-redis redis-cli HGET "task:${TASK_ID}" data 2>/dev/null)

    if [ -n "$DATA" ]; then
        STATUS=$(echo "$DATA" | python3 -c "import sys,json; d=json.loads(sys.stdin.read()); print(d.get('status', 'pending'))" 2>/dev/null || echo "pending")
        STEP=$(echo "$DATA" | python3 -c "import sys,json; d=json.loads(sys.stdin.read()); print(d.get('progress', {}).get('step_name', 'Waiting...'))" 2>/dev/null || echo "Waiting...")
        PERCENT=$(echo "$DATA" | python3 -c "import sys,json; d=json.loads(sys.stdin.read()); print(d.get('progress', {}).get('percentage', 0))" 2>/dev/null || echo "0")

        # Only print if step changed
        if [ "$STEP" != "$LAST_STEP" ]; then
            echo -e "[${PERCENT}%] ${STEP}"
            LAST_STEP="$STEP"
        fi

        if [ "$STATUS" = "completed" ]; then
            echo ""
            echo -e "${GREEN}Workspace ${WORKSPACE_SLUG} rebuilt successfully!${NC}"

            # Show container status
            echo ""
            echo -e "${BLUE}Container Status:${NC}"
            docker ps --filter "name=${WORKSPACE_SLUG}-kanban" --format "table {{.Names}}\t{{.Status}}\t{{.CreatedAt}}"
            exit 0
        fi

        if [ "$STATUS" = "failed" ]; then
            ERROR=$(echo "$DATA" | python3 -c "import sys,json; d=json.loads(sys.stdin.read()); print(d.get('error', 'Unknown error'))" 2>/dev/null || echo "Unknown error")
            echo ""
            echo -e "${RED}Rebuild failed: ${ERROR}${NC}"
            exit 1
        fi
    fi

    sleep 2
    WAIT_TIME=$((WAIT_TIME + 2))
done

echo -e "${YELLOW}Warning: Task is still running after ${MAX_WAIT}s. Check orchestrator logs.${NC}"
exit 0
