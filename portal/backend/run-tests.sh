#!/bin/bash
# Script to run Kanban Portal API tests in Docker
# Usage: ./run-tests.sh [pytest-args]
# Examples:
#   ./run-tests.sh                          # Run all tests
#   ./run-tests.sh -k "test_create"         # Run tests matching pattern
#   ./run-tests.sh tests/test_portal_tokens.py  # Run specific file
#   ./run-tests.sh --cov                    # Run with coverage

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}========================================${NC}"
echo -e "${YELLOW}  Kanban Portal API - Test Runner${NC}"
echo -e "${YELLOW}========================================${NC}"

# Create test-reports directory
mkdir -p test-reports

# Check if custom pytest args provided
if [ $# -gt 0 ]; then
    PYTEST_ARGS="$@"
    echo -e "${GREEN}Running tests with args: ${PYTEST_ARGS}${NC}"

    docker-compose -f docker-compose.test.yml run --rm test \
        pytest tests/portal/ -v --tb=short \
        --junitxml=/app/test-reports/junit.xml \
        $PYTEST_ARGS
else
    echo -e "${GREEN}Running all tests with coverage...${NC}"

    docker-compose -f docker-compose.test.yml up \
        --build \
        --abort-on-container-exit \
        --exit-code-from test
fi

EXIT_CODE=$?

# Cleanup containers
echo -e "${YELLOW}Cleaning up containers...${NC}"
docker-compose -f docker-compose.test.yml down --volumes

if [ $EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}  All tests passed!${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo -e "Coverage report: ${SCRIPT_DIR}/test-reports/coverage/index.html"
    echo -e "JUnit report: ${SCRIPT_DIR}/test-reports/junit.xml"
else
    echo -e "${RED}========================================${NC}"
    echo -e "${RED}  Tests failed with exit code: $EXIT_CODE${NC}"
    echo -e "${RED}========================================${NC}"
fi

exit $EXIT_CODE
