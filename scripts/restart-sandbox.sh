#!/bin/bash
# Restart sandbox via the orchestrator
# Usage: ./restart-sandbox.sh <full_slug>
# Example: ./restart-sandbox.sh finance-start
#
# This script triggers the orchestrator to:
# 1. Pull latest code from the sandbox branch
# 2. Stop existing containers
# 3. Rebuild and start containers
# 4. Run health check

set -e

FULL_SLUG="${1:-}"
if [ -z "$FULL_SLUG" ]; then
    echo "Usage: $0 <full_slug>"
    echo "Example: $0 finance-start"
    exit 1
fi

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}=== Sandbox Restart Tool ===${NC}"
echo -e "Sandbox: ${YELLOW}${FULL_SLUG}${NC}"
echo ""

# Extract workspace slug from full_slug (everything before the last dash)
WORKSPACE_SLUG="${FULL_SLUG%-*}"

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
TASK_ID="restart-sandbox-${FULL_SLUG}-$(date +%s)"
TASK_DATA="{\"type\": \"sandbox.restart\", \"task_id\": \"${TASK_ID}\", \"user_id\": \"cli\", \"payload\": {\"sandbox_id\": \"${FULL_SLUG}\", \"full_slug\": \"${FULL_SLUG}\", \"workspace_slug\": \"${WORKSPACE_SLUG}\"}}"

echo -e "${BLUE}Creating task: ${TASK_ID}${NC}"

# Create task in Redis
docker exec kanban-redis redis-cli HSET "task:${TASK_ID}" \
    "type" "sandbox.restart" \
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
MAX_WAIT=180  # 3 minutes max for sandbox restart
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
            echo -e "${GREEN}Sandbox ${FULL_SLUG} restarted successfully!${NC}"

            # Show container status
            echo ""
            echo -e "${BLUE}Container Status:${NC}"
            docker ps --filter "name=${FULL_SLUG}" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

            echo ""
            # Show recent API logs
            echo -e "${BLUE}API Container Logs (last 10 lines):${NC}"
            docker logs "${FULL_SLUG}-api" --tail 10 2>&1 || echo "Could not fetch API logs"

            # Health check - verify API is actually responding
            echo ""
            echo -e "${BLUE}Running health check...${NC}"

            # Wait a moment for API to fully start
            sleep 3

            # Check if container is running (not restarting)
            API_STATUS=$(docker inspect "${FULL_SLUG}-api" --format "{{.State.Status}}" 2>/dev/null || echo "not_found")
            RESTART_COUNT=$(docker inspect "${FULL_SLUG}-api" --format "{{.RestartCount}}" 2>/dev/null || echo "0")

            if [ "$API_STATUS" != "running" ]; then
                echo -e "${RED}HEALTH CHECK FAILED: API container is not running (status: ${API_STATUS})${NC}"
                echo ""
                echo -e "${YELLOW}Container logs:${NC}"
                docker logs "${FULL_SLUG}-api" --tail 50 2>&1 || true
                exit 1
            fi

            if [ "$RESTART_COUNT" -gt 2 ]; then
                echo -e "${RED}HEALTH CHECK FAILED: API container has restarted ${RESTART_COUNT} times (crash loop detected)${NC}"
                echo ""
                echo -e "${YELLOW}Container logs:${NC}"
                docker logs "${FULL_SLUG}-api" --tail 50 2>&1 || true
                exit 1
            fi

            # Check for Python errors in logs
            if docker logs "${FULL_SLUG}-api" --tail 50 2>&1 | grep -qE "(ImportError|ModuleNotFoundError|SyntaxError|IndentationError|Traceback)"; then
                echo -e "${RED}HEALTH CHECK FAILED: Python errors detected in logs${NC}"
                echo ""
                echo -e "${YELLOW}Error logs:${NC}"
                docker logs "${FULL_SLUG}-api" --tail 50 2>&1 | grep -A5 -E "(ImportError|ModuleNotFoundError|SyntaxError|IndentationError|Traceback)"
                exit 1
            fi

            echo -e "${GREEN}Health check passed: Container running, no crash loops, no Python errors${NC}"
            exit 0
        fi

        if [ "$STATUS" = "failed" ]; then
            ERROR=$(echo "$DATA" | python3 -c "import sys,json; d=json.loads(sys.stdin.read()); print(d.get('error', 'Unknown error'))" 2>/dev/null || echo "Unknown error")
            echo ""
            echo -e "${RED}Restart failed: ${ERROR}${NC}"

            # Show container logs for debugging
            echo ""
            echo -e "${YELLOW}API Container Logs:${NC}"
            docker logs "${FULL_SLUG}-api" --tail 50 2>&1 || echo "Could not fetch API logs"
            exit 1
        fi
    fi

    sleep 2
    WAIT_TIME=$((WAIT_TIME + 2))
done

echo -e "${YELLOW}Warning: Task is still running after ${MAX_WAIT}s. Check orchestrator logs.${NC}"
exit 0
