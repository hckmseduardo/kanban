#!/bin/bash
# =============================================================================
# Kanban Platform - Start Script
# =============================================================================
# This script starts the portal infrastructure only.
# Workspace containers are managed by the orchestrator based on database state.
#
# Usage:
#   ./start.sh              # Start portal (default port 443)
#   ./start.sh --build      # Rebuild and start portal
#   ./start.sh --stop       # Stop portal
# =============================================================================

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default values
BUILD=false
STOP=false

# Print banner
print_banner() {
    echo -e "${BLUE}"
    echo "╔═══════════════════════════════════════════════════════════════╗"
    echo "║                    KANBAN PLATFORM                            ║"
    echo "╚═══════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

# Print status message
info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check service health
check_service() {
    local service=$1
    local status=$(docker inspect --format='{{.State.Status}}' "kanban-$service" 2>/dev/null)
    if [ "$status" == "running" ]; then
        echo -e "  ${GREEN}✓${NC} $service"
        return 0
    else
        echo -e "  ${RED}✗${NC} $service ($status)"
        return 1
    fi
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --build|-b)
            BUILD=true
            shift
            ;;
        --stop)
            STOP=true
            shift
            ;;
        --help|-h)
            echo "Usage: ./start.sh [OPTIONS]"
            echo ""
            echo "This script starts the Kanban portal infrastructure."
            echo "Workspace containers are managed by the orchestrator."
            echo ""
            echo "Options:"
            echo "  --build, -b    Force rebuild of portal containers"
            echo "  --stop         Stop the portal"
            echo "  --help, -h     Show this help message"
            echo ""
            echo "Examples:"
            echo "  ./start.sh           # Start portal"
            echo "  ./start.sh --build   # Rebuild and start portal"
            echo "  ./start.sh --stop    # Stop portal"
            echo ""
            echo "Note: Workspace containers are started automatically by the"
            echo "      orchestrator based on database state."
            exit 0
            ;;
        *)
            error "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

print_banner

# Check if .env exists
if [ ! -f .env ]; then
    warn ".env file not found. Creating from .env.example..."
    if [ -f .env.example ]; then
        cp .env.example .env
        success "Created .env file. Please edit it with your configuration."
    else
        error ".env.example not found!"
        exit 1
    fi
fi

# Load environment
set -a
source .env
set +a

# Handle stop
if [ "$STOP" = true ]; then
    info "Stopping Kanban portal..."
    docker compose down
    success "Portal stopped"
    exit 0
fi

info "Configuration:"
echo "  Domain:    ${DOMAIN:-localhost}"
echo "  Port:      ${PORT:-443}"
echo ""

# Create required directories
mkdir -p data/portal data/workspaces data/workspaces/.archived

# Build if requested
if [ "$BUILD" = true ]; then
    info "Building portal containers..."
    docker compose build --no-cache
fi

# Start services
info "Starting Kanban portal..."
docker compose up -d

# Wait for services to be ready
info "Waiting for services to be ready..."
sleep 5

echo ""
info "Service Status:"
check_service "traefik"
check_service "redis"
check_service "portal-api"
check_service "portal-web"
check_service "worker"
check_service "orchestrator"

echo ""
success "Kanban portal is running!"
echo ""
echo -e "${BLUE}Access URLs:${NC}"
echo "  Portal:     https://kanban.${DOMAIN:-localhost}"
echo "  API:        https://kanban.${DOMAIN:-localhost}/api"
echo "  API Docs:   https://kanban.${DOMAIN:-localhost}/api/docs"
echo ""
echo -e "${YELLOW}Note:${NC} Workspace containers are managed by the orchestrator."
echo "      The orchestrator will start workspaces based on database state."
echo ""
echo "To view logs:  docker compose logs -f"
echo "To stop:       ./start.sh --stop"
echo ""
