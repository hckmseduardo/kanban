#!/bin/bash
# =============================================================================
# Populate Existing Azure Key Vault with Secrets
# =============================================================================
# Adds all required secrets to an existing Key Vault for the Kanban platform.
# Reads values from .env file and generates secure secrets where needed.
#
# Usage:
#   ./scripts/populate-keyvault.sh
#   ./scripts/populate-keyvault.sh --vault-name kanban
#
# If Azure CLI is not installed, this script will automatically run in Docker.
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
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# Get script and project directories
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# =============================================================================
# Docker Fallback: Run in container if Azure CLI not installed
# =============================================================================
if ! command -v az &> /dev/null; then
    if command -v docker &> /dev/null; then
        echo -e "${YELLOW}[INFO]${NC} Azure CLI not found locally. Running in Docker container..."

        # Run this script inside a Docker container with Azure CLI
        exec docker run -it --rm \
            -v "$SCRIPT_DIR:/scripts:ro" \
            -v "$PROJECT_DIR/.env:/project/.env:ro" \
            -w /scripts \
            -e RUNNING_IN_DOCKER=1 \
            -e ENV_FILE=/project/.env \
            mcr.microsoft.com/azure-cli:latest \
            bash -c "az login --use-device-code && ./populate-keyvault.sh $*"
    else
        error "Azure CLI not found and Docker not available.\nPlease install Azure CLI or Docker."
    fi
fi

# =============================================================================
# Configuration
# =============================================================================

# Default vault name
VAULT_NAME="kanban"
RESOURCE_GROUP="kanban"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --vault-name|-v)
            VAULT_NAME="$2"
            shift 2
            ;;
        --resource-group|-g)
            RESOURCE_GROUP="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --vault-name, -v      Key Vault name (default: kanban)"
            echo "  --resource-group, -g  Resource group (default: kanban)"
            echo "  --help, -h            Show this help"
            exit 0
            ;;
        *)
            error "Unknown option: $1"
            ;;
    esac
done

# Load .env file
ENV_FILE="${ENV_FILE:-$PROJECT_DIR/.env}"
if [ -f "$ENV_FILE" ]; then
    info "Loading configuration from $ENV_FILE"
    set -a
    source "$ENV_FILE"
    set +a
else
    warn ".env file not found at $ENV_FILE"
fi

echo -e "${BLUE}"
echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║         POPULATE AZURE KEY VAULT WITH SECRETS                 ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

info "Vault Name: $VAULT_NAME"
info "Resource Group: $RESOURCE_GROUP"

# Show if running in Docker
if [ "$RUNNING_IN_DOCKER" = "1" ]; then
    info "Running inside Docker container"
fi

# Check login status
info "Checking Azure CLI login status..."
if ! az account show &> /dev/null; then
    error "Not logged in to Azure. Please run: az login"
fi

SUBSCRIPTION=$(az account show --query name -o tsv)
success "Logged in to subscription: $SUBSCRIPTION"

# Verify Key Vault exists
info "Verifying Key Vault exists..."
VAULT_INFO=$(az keyvault show --name "$VAULT_NAME" --resource-group "$RESOURCE_GROUP" 2>/dev/null) || {
    error "Key Vault '$VAULT_NAME' not found in resource group '$RESOURCE_GROUP'"
}
VAULT_ID=$(echo "$VAULT_INFO" | grep -o '"id": "[^"]*"' | head -1 | cut -d'"' -f4)
success "Key Vault '$VAULT_NAME' found"

# =============================================================================
# Check and Grant Permissions
# =============================================================================

info "Checking Key Vault permissions..."

# Get current user's object ID
USER_OBJECT_ID=$(az ad signed-in-user show --query id -o tsv 2>/dev/null) || {
    warn "Could not get current user ID - may be using service principal"
    USER_OBJECT_ID=""
}

# Test if we can set a secret (try to read first as a simpler test)
CAN_SET_SECRETS=false
if az keyvault secret list --vault-name "$VAULT_NAME" --max-results 1 &>/dev/null; then
    CAN_SET_SECRETS=true
fi

if [ "$CAN_SET_SECRETS" = false ] && [ -n "$USER_OBJECT_ID" ]; then
    warn "Insufficient permissions. Granting 'Key Vault Secrets Officer' role..."

    # Grant Key Vault Secrets Officer role
    az role assignment create \
        --role "Key Vault Secrets Officer" \
        --assignee-object-id "$USER_OBJECT_ID" \
        --assignee-principal-type User \
        --scope "$VAULT_ID" \
        --output none 2>/dev/null || {
            warn "Could not auto-grant permissions. Trying with Key Vault access policy..."

            # Fallback: Try access policy if RBAC fails
            az keyvault set-policy \
                --name "$VAULT_NAME" \
                --object-id "$USER_OBJECT_ID" \
                --secret-permissions get list set delete \
                --output none 2>/dev/null || {
                    error "Could not grant permissions. Please grant 'Key Vault Secrets Officer' role manually in Azure Portal."
                }
        }

    success "Permissions granted"

    # Wait for permissions to propagate
    info "Waiting for permissions to propagate (10 seconds)..."
    sleep 10
else
    success "Permissions verified"
fi

# =============================================================================
# Add Secrets
# =============================================================================

info "Adding secrets to Key Vault..."

# Function to set secret with retry
set_secret() {
    local name="$1"
    local value="$2"
    local description="$3"
    local retries=3

    if [ -z "$value" ] || [ "$value" = "CONFIGURE_ME" ]; then
        warn "Skipping $name - no value provided"
        return 0
    fi

    info "Setting $name..."

    for ((i=1; i<=retries; i++)); do
        if az keyvault secret set \
            --vault-name "$VAULT_NAME" \
            --name "$name" \
            --value "$value" \
            --output none 2>/dev/null; then
            success "  $name - $description"
            return 0
        fi

        if [ $i -lt $retries ]; then
            warn "  Retry $i/$retries for $name..."
            sleep 5
        fi
    done

    error "Failed to set secret $name after $retries attempts"
}

# Generate secure secrets if not already set
if [ "$PORTAL_SECRET_KEY" = "change-me-in-production" ] || [ -z "$PORTAL_SECRET_KEY" ]; then
    PORTAL_SECRET_KEY=$(openssl rand -base64 32)
    info "Generated new portal-secret-key"
fi

if [ "$CROSS_DOMAIN_SECRET" = "change-me-in-production" ] || [ -z "$CROSS_DOMAIN_SECRET" ]; then
    CROSS_DOMAIN_SECRET=$(openssl rand -base64 32)
    info "Generated new cross-domain-secret"
fi

echo ""
info "Adding secrets..."

# Security secrets
set_secret "portal-secret-key" "$PORTAL_SECRET_KEY" "JWT signing key"
set_secret "cross-domain-secret" "$CROSS_DOMAIN_SECRET" "Cross-domain SSO secret"

# Entra ID secrets
set_secret "entra-client-id" "$ENTRA_CLIENT_ID" "Entra ID client ID"
set_secret "entra-client-secret" "$ENTRA_CLIENT_SECRET" "Entra ID client secret"
set_secret "entra-tenant-id" "${ENTRA_TENANT_ID:-common}" "Entra ID tenant"

# Service configuration
set_secret "certbot-email" "$CERTBOT_EMAIL" "Let's Encrypt email"
set_secret "redis-url" "${REDIS_URL:-redis://redis:6379}" "Redis connection URL"

# =============================================================================
# Summary
# =============================================================================

echo ""
echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}                    SECRETS ADDED!                              ${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"
echo ""

# List all secrets
info "Secrets in Key Vault '$VAULT_NAME':"
az keyvault secret list --vault-name "$VAULT_NAME" --query "[].name" -o tsv | while read -r secret; do
    echo "  - $secret"
done

echo ""
success "Key Vault is ready for production use!"
echo ""
echo "Your .env already has the Key Vault URL configured."
echo "Secrets will be loaded automatically when CERT_MODE=production"
