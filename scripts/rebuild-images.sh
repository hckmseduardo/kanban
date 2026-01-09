#!/bin/bash
# Rebuild kanban-team Docker images (frontend/backend)
# Usage: ./rebuild-images.sh [--frontend] [--backend] [--all] [--restart]

set -e

# Default values
BUILD_FRONTEND=false
BUILD_BACKEND=false
RESTART_WORKSPACES=false

# Parse arguments
if [ $# -eq 0 ]; then
    # Default to --all if no arguments
    BUILD_FRONTEND=true
    BUILD_BACKEND=true
fi

while [[ $# -gt 0 ]]; do
    case $1 in
        --frontend)
            BUILD_FRONTEND=true
            shift
            ;;
        --backend)
            BUILD_BACKEND=true
            shift
            ;;
        --all)
            BUILD_FRONTEND=true
            BUILD_BACKEND=true
            shift
            ;;
        --restart)
            RESTART_WORKSPACES=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--frontend] [--backend] [--all] [--restart]"
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

# Get script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
KANBAN_TEAM_DIR="$PROJECT_ROOT/kanban-team"

echo -e "${BLUE}=== Kanban Team Image Builder ===${NC}"
echo -e "Build frontend: ${YELLOW}${BUILD_FRONTEND}${NC}"
echo -e "Build backend: ${YELLOW}${BUILD_BACKEND}${NC}"
echo -e "Restart workspaces: ${YELLOW}${RESTART_WORKSPACES}${NC}"
echo ""

# Build frontend image
if [ "$BUILD_FRONTEND" = true ]; then
    echo -e "${BLUE}Building frontend image...${NC}"

    FRONTEND_DIR="$KANBAN_TEAM_DIR/frontend"

    if [ ! -d "$FRONTEND_DIR" ]; then
        echo -e "${RED}Error: Frontend directory not found: $FRONTEND_DIR${NC}"
        exit 1
    fi

    # Build the Docker image
    if docker build --no-cache -t kanban-team-web:latest "$FRONTEND_DIR"; then
        echo -e "${GREEN}Frontend image built successfully!${NC}"
        docker images kanban-team-web --format "  Image: {{.ID}} Created: {{.CreatedAt}}"
    else
        echo -e "${RED}Frontend build failed!${NC}"
        exit 1
    fi
    echo ""
fi

# Build backend image
if [ "$BUILD_BACKEND" = true ]; then
    echo -e "${BLUE}Building backend image...${NC}"

    BACKEND_DIR="$KANBAN_TEAM_DIR/backend"

    if [ ! -d "$BACKEND_DIR" ]; then
        echo -e "${RED}Error: Backend directory not found: $BACKEND_DIR${NC}"
        exit 1
    fi

    # Build the Docker image
    if docker build --no-cache -t kanban-team-api:latest "$BACKEND_DIR"; then
        echo -e "${GREEN}Backend image built successfully!${NC}"
        docker images kanban-team-api --format "  Image: {{.ID}} Created: {{.CreatedAt}}"
    else
        echo -e "${RED}Backend build failed!${NC}"
        exit 1
    fi
    echo ""
fi

# Restart workspaces if requested
if [ "$RESTART_WORKSPACES" = true ]; then
    echo -e "${BLUE}Restarting workspaces to use new images...${NC}"

    # Find all running workspace containers
    WORKSPACES=$(docker ps --filter "name=-kanban-web-" --format "{{.Names}}" | sed 's/-kanban-web-1//' | sort -u)

    if [ -z "$WORKSPACES" ]; then
        echo -e "${YELLOW}No running workspaces found${NC}"
    else
        for workspace in $WORKSPACES; do
            echo -e "  Restarting workspace: ${YELLOW}${workspace}${NC}"
            "$SCRIPT_DIR/rebuild-workspace.sh" "$workspace" --restart-only
        done
    fi
    echo ""
fi

echo -e "${GREEN}Done!${NC}"
