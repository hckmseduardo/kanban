#!/bin/bash

# E2E Test Runner Script
# This script builds and runs the Playwright tests in Docker

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Get test credentials from arguments or environment
OWNER_TEST_TOKEN="${OWNER_TEST_TOKEN:-$1}"
INVITEE_TEST_TOKEN="${INVITEE_TEST_TOKEN:-}"
INVITEE_EMAIL="${INVITEE_EMAIL:-}"
TEST_TOKEN="${TEST_TOKEN:-$OWNER_TEST_TOKEN}"
TEST_USER_EMAIL="${TEST_USER_EMAIL:-}"
TEST_USER_PASSWORD="${TEST_USER_PASSWORD:-}"

echo "=== Building E2E Test Container ==="
docker build -t kanban-e2e-tests "$SCRIPT_DIR"

echo ""
echo "=== Running E2E Tests ==="

# Create results directory
mkdir -p "$SCRIPT_DIR/results"

# Run the container
docker run --rm \
  --network kanban-global \
  --add-host=kanban.amazing-ai.tools:host-gateway \
  -e PORTAL_URL=https://kanban.amazing-ai.tools \
  -e PORTAL_API_URL=https://kanban.amazing-ai.tools/api \
  -e TEST_TOKEN="$TEST_TOKEN" \
  -e OWNER_TEST_TOKEN="$OWNER_TEST_TOKEN" \
  -e INVITEE_TEST_TOKEN="$INVITEE_TEST_TOKEN" \
  -e INVITEE_EMAIL="$INVITEE_EMAIL" \
  -e TEST_USER_EMAIL="$TEST_USER_EMAIL" \
  -e TEST_USER_PASSWORD="$TEST_USER_PASSWORD" \
  -e NODE_TLS_REJECT_UNAUTHORIZED=0 \
  -v "$SCRIPT_DIR/results:/app/results" \
  kanban-e2e-tests

echo ""
echo "=== Test Results ==="
echo "Screenshots saved to: $SCRIPT_DIR/results/"
ls -la "$SCRIPT_DIR/results/" 2>/dev/null || echo "No results yet"
