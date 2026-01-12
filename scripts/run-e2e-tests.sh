#!/bin/bash

# E2E Test Runner with Automatic Token Generation
# This script generates a JWT token and runs Playwright E2E tests

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
E2E_DIR="$PROJECT_DIR/e2e-tests"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Parse arguments
FILTER=""
HEADED=""
DEBUG=""
CLEANUP_ONLY=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --filter)
            FILTER="$2"
            shift 2
            ;;
        --headed)
            HEADED="--headed"
            shift
            ;;
        --debug)
            DEBUG="--debug"
            shift
            ;;
        --cleanup-only)
            CLEANUP_ONLY=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--filter <pattern>] [--headed] [--debug] [--cleanup-only]"
            exit 1
            ;;
    esac
done

echo -e "${GREEN}=== Kanban E2E Test Runner ===${NC}"
echo ""

# Check prerequisites
echo "Checking prerequisites..."

if ! docker ps | grep -q kanban-portal-api; then
    echo -e "${RED}Error: kanban-portal-api container is not running${NC}"
    echo "Start the portal first: docker-compose up -d"
    exit 1
fi

# Generate JWT token
echo ""
echo -e "${YELLOW}Generating JWT token...${NC}"

# Get the test user ID and email from the database or use defaults
TEST_USER_ID="${TEST_USER_ID:-c924f0bd-da75-4a71-9833-5f42fc25a896}"
TEST_USER_EMAIL="${TEST_USER_EMAIL:-hckmseduardo@gmail.com}"

OWNER_TEST_TOKEN=$(docker exec kanban-portal-api python -c "
from app.auth.jwt import create_access_token
from datetime import timedelta
token = create_access_token(
    data={'sub': '$TEST_USER_ID', 'email': '$TEST_USER_EMAIL'},
    expires_delta=timedelta(hours=24)
)
print(token)
" 2>/dev/null)

if [ -z "$OWNER_TEST_TOKEN" ]; then
    echo -e "${RED}Error: Failed to generate JWT token${NC}"
    exit 1
fi

echo -e "${GREEN}Token generated successfully${NC}"

# Export for the test runner
export OWNER_TEST_TOKEN
export INVITEE_EMAIL="${INVITEE_EMAIL:-e2e-test-invitee@example.com}"

# Cleanup only mode
if [ "$CLEANUP_ONLY" = true ]; then
    echo ""
    echo -e "${YELLOW}Cleaning up test workspaces...${NC}"

    for slug in "e2e-test-invitation" "e2e-full-flow-test"; do
        result=$(curl -sk -X DELETE "https://kanban.amazing-ai.tools/api/workspaces/$slug" \
            -H "Authorization: Bearer $OWNER_TEST_TOKEN" 2>/dev/null)

        if echo "$result" | grep -q "deletion started\|not found"; then
            echo -e "  ${GREEN}✓${NC} $slug"
        else
            echo -e "  ${YELLOW}?${NC} $slug: $result"
        fi
    done

    echo ""
    echo -e "${GREEN}Cleanup complete!${NC}"
    exit 0
fi

# Run the tests
echo ""
echo -e "${YELLOW}Running E2E tests...${NC}"
echo ""

cd "$E2E_DIR"

# Build filter argument if provided
FILTER_ARG=""
if [ -n "$FILTER" ]; then
    FILTER_ARG="--grep \"$FILTER\""
fi

# Run tests
./run-tests.sh

echo ""
echo -e "${GREEN}=== Tests Complete ===${NC}"
echo ""
echo "Screenshots saved to: $E2E_DIR/results/"
