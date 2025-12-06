#!/bin/bash
# =============================================================================
# Production Deployment Script
# =============================================================================
# Validates configuration and deploys the Kanban platform in production mode
#
# Usage:
#   ./scripts/deploy-production.sh [--skip-validation] [--dry-run]
#
# Prerequisites:
#   1. Azure CLI installed and logged in
#   2. Docker and Docker Compose installed
#   3. .env file configured with production values
#   4. DNS configured to point to this server
# =============================================================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info() { echo -e "${BLUE}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# Parse arguments
SKIP_VALIDATION=false
DRY_RUN=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-validation)
            SKIP_VALIDATION=true
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --skip-validation   Skip configuration validation"
            echo "  --dry-run           Show what would be done without executing"
            echo "  --help, -h          Show this help"
            exit 0
            ;;
        *)
            error "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo ""
echo -e "${BLUE}╔═══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║           KANBAN PLATFORM - PRODUCTION DEPLOYMENT             ║${NC}"
echo -e "${BLUE}╚═══════════════════════════════════════════════════════════════╝${NC}"
echo ""

# =============================================================================
# Pre-flight Checks
# =============================================================================

info "Running pre-flight checks..."

# Check .env file
if [ ! -f ".env" ]; then
    error ".env file not found. Copy .env.example to .env and configure it."
    exit 1
fi

# Load environment variables
set -a
source .env
set +a

# Validate required variables
ERRORS=()

if [ "$CERT_MODE" != "production" ]; then
    ERRORS+=("CERT_MODE must be 'production' (current: $CERT_MODE)")
fi

if [ -z "$DOMAIN" ] || [ "$DOMAIN" = "localhost" ] || [ "$DOMAIN" = "kanban.your-domain.com" ]; then
    ERRORS+=("DOMAIN must be set to your actual domain")
fi

if [ -z "$AZURE_KEY_VAULT_URL" ]; then
    warn "AZURE_KEY_VAULT_URL not set - using environment variables for secrets"

    if [ "$PORTAL_SECRET_KEY" = "change-me-in-production" ] || [ "$PORTAL_SECRET_KEY" = "dev-secret-change-me" ]; then
        ERRORS+=("PORTAL_SECRET_KEY must be changed from default value")
    fi

    if [ "$CROSS_DOMAIN_SECRET" = "change-me-in-production" ] || [ "$CROSS_DOMAIN_SECRET" = "dev-cross-domain-secret" ]; then
        ERRORS+=("CROSS_DOMAIN_SECRET must be changed from default value")
    fi
fi

if [ -z "$ENTRA_CLIENT_ID" ]; then
    ERRORS+=("ENTRA_CLIENT_ID is required for authentication")
fi

if [ "$CERTBOT_EMAIL" = "admin@localhost" ] || [ "$CERTBOT_EMAIL" = "admin@yourdomain.com" ]; then
    ERRORS+=("CERTBOT_EMAIL must be set to a valid email")
fi

# Check for validation errors
if [ ${#ERRORS[@]} -gt 0 ] && [ "$SKIP_VALIDATION" = false ]; then
    error "Configuration validation failed:"
    for err in "${ERRORS[@]}"; do
        echo -e "  ${RED}✗${NC} $err"
    done
    echo ""
    echo "Fix the errors above or use --skip-validation to proceed anyway."
    exit 1
fi

success "Configuration validated"

# =============================================================================
# DNS Check
# =============================================================================

if [ "$SKIP_VALIDATION" = false ]; then
    info "Checking DNS resolution for $DOMAIN..."

    RESOLVED_IP=$(dig +short "$DOMAIN" | head -1)
    if [ -z "$RESOLVED_IP" ]; then
        warn "Could not resolve $DOMAIN - make sure DNS is configured"
    else
        info "$DOMAIN resolves to $RESOLVED_IP"

        # Check if it matches HOST_IP
        if [ "$RESOLVED_IP" != "$HOST_IP" ] && [ -n "$HOST_IP" ]; then
            warn "DNS ($RESOLVED_IP) doesn't match HOST_IP ($HOST_IP)"
        fi
    fi
fi

# =============================================================================
# Azure Key Vault Check
# =============================================================================

if [ -n "$AZURE_KEY_VAULT_URL" ]; then
    info "Checking Azure Key Vault access..."

    if command -v az &> /dev/null; then
        VAULT_NAME=$(echo "$AZURE_KEY_VAULT_URL" | sed -E 's|https://([^.]+)\.vault\.azure\.net.*|\1|')

        if az keyvault secret list --vault-name "$VAULT_NAME" &>/dev/null; then
            success "Azure Key Vault accessible"
        else
            warn "Cannot access Key Vault $VAULT_NAME - check permissions"
        fi
    else
        warn "Azure CLI not installed - skipping Key Vault check"
    fi
fi

# =============================================================================
# Docker Check
# =============================================================================

info "Checking Docker..."

if ! command -v docker &> /dev/null; then
    error "Docker not installed"
    exit 1
fi

if ! docker info &>/dev/null; then
    error "Docker daemon not running"
    exit 1
fi

if ! command -v docker compose &> /dev/null && ! docker compose version &>/dev/null; then
    error "Docker Compose not installed"
    exit 1
fi

success "Docker is ready"

# =============================================================================
# Dry Run
# =============================================================================

if [ "$DRY_RUN" = true ]; then
    info "DRY RUN - Would execute the following:"
    echo ""
    echo "  1. Stop existing containers: docker compose down"
    echo "  2. Build images: docker compose build"
    echo "  3. Start services: docker compose up -d"
    echo "  4. Wait for services to be healthy"
    echo "  5. Show service status"
    echo ""
    echo "Environment:"
    echo "  DOMAIN=$DOMAIN"
    echo "  PORT=$PORT"
    echo "  CERT_MODE=$CERT_MODE"
    echo "  CERTBOT_EMAIL=$CERTBOT_EMAIL"
    echo ""
    exit 0
fi

# =============================================================================
# Deployment
# =============================================================================

info "Starting production deployment..."

# Create required directories
mkdir -p data/portal data/teams traefik/certs

# Stop existing containers
info "Stopping existing containers..."
docker compose down --remove-orphans || true

# Build images
info "Building Docker images..."
docker compose build --no-cache

# Start services
info "Starting services..."
docker compose up -d

# Wait for services to be healthy
info "Waiting for services to be healthy..."
sleep 10

# Check service status
info "Checking service status..."
docker compose ps

# Check health endpoints
info "Checking health endpoints..."
sleep 5

HEALTH_URL="https://${DOMAIN}/api/health"
if [ "$PORT" != "443" ]; then
    HEALTH_URL="https://${DOMAIN}:${PORT}/api/health"
fi

if curl -sf -k "$HEALTH_URL" &>/dev/null; then
    success "API health check passed"
else
    warn "API health check failed - service may still be starting"
fi

# =============================================================================
# Summary
# =============================================================================

echo ""
echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}                    DEPLOYMENT COMPLETE!                        ${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"
echo ""
echo "Your Kanban platform is now running at:"
echo ""
if [ "$PORT" = "443" ]; then
    echo -e "  ${BLUE}Portal:${NC} https://${DOMAIN}"
    echo -e "  ${BLUE}API:${NC}    https://${DOMAIN}/api"
else
    echo -e "  ${BLUE}Portal:${NC} https://${DOMAIN}:${PORT}"
    echo -e "  ${BLUE}API:${NC}    https://${DOMAIN}:${PORT}/api"
fi
echo ""
echo "Useful commands:"
echo "  docker compose logs -f          # View logs"
echo "  docker compose ps               # Check status"
echo "  docker compose down             # Stop services"
echo "  docker compose restart traefik  # Reload Traefik"
echo ""

# Check certificate status
CERT_FILE="traefik/certs/live/${DOMAIN}/fullchain.pem"
if [ -f "$CERT_FILE" ]; then
    CERT_EXPIRY=$(openssl x509 -in "$CERT_FILE" -noout -enddate 2>/dev/null | cut -d= -f2)
    if [ -n "$CERT_EXPIRY" ]; then
        info "SSL certificate expires: $CERT_EXPIRY"
    fi
fi
