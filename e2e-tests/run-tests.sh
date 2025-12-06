#!/bin/bash

# E2E Test Runner Script
# This script builds and runs the Playwright tests in Docker

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Get test token from argument or use default
TEST_TOKEN="${1:-}"

echo "=== Building E2E Test Container ==="
docker build -t kanban-e2e-tests "$SCRIPT_DIR"

echo ""
echo "=== Running E2E Tests ==="

# Create results directory
mkdir -p "$SCRIPT_DIR/results"

# Run the container
docker run --rm \
  --network kanban-global \
  --add-host=localhost:host-gateway \
  --add-host=app.localhost:host-gateway \
  --add-host=api.localhost:host-gateway \
  --add-host=teste.localhost:host-gateway \
  -e PORTAL_URL=https://app.localhost:4443 \
  -e PORTAL_API_URL=https://api.localhost:4443 \
  -e TEST_TOKEN="$TEST_TOKEN" \
  -e NODE_TLS_REJECT_UNAUTHORIZED=0 \
  -v "$SCRIPT_DIR/results:/app/results" \
  kanban-e2e-tests

echo ""
echo "=== Test Results ==="
echo "Screenshots saved to: $SCRIPT_DIR/results/"
ls -la "$SCRIPT_DIR/results/" 2>/dev/null || echo "No results yet"
