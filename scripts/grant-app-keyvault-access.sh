#!/bin/bash
# =============================================================================
# Grant Application Access to Key Vault
# =============================================================================
# Grants the application's service principal permission to read secrets
# from Azure Key Vault.
#
# Usage:
#   ./scripts/grant-app-keyvault-access.sh
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
# Docker Fallback
# =============================================================================
if ! command -v az &> /dev/null; then
    if command -v docker &> /dev/null; then
        echo -e "${YELLOW}[INFO]${NC} Azure CLI not found locally. Running in Docker container..."

        exec docker run -it --rm \
            -v "$SCRIPT_DIR:/scripts:ro" \
            -v "$PROJECT_DIR/.env:/project/.env:ro" \
            -w /scripts \
            -e RUNNING_IN_DOCKER=1 \
            -e ENV_FILE=/project/.env \
            mcr.microsoft.com/azure-cli:latest \
            bash -c "az login --use-device-code && ./grant-app-keyvault-access.sh $*"
    else
        error "Azure CLI not found and Docker not available."
    fi
fi

# Configuration
VAULT_NAME="kanban"
RESOURCE_GROUP="kanban"

# Load .env file
ENV_FILE="${ENV_FILE:-$PROJECT_DIR/.env}"
if [ -f "$ENV_FILE" ]; then
    info "Loading configuration from $ENV_FILE"
    set -a
    source "$ENV_FILE"
    set +a
else
    error ".env file not found"
fi

echo -e "${BLUE}"
echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║       GRANT APPLICATION ACCESS TO KEY VAULT                   ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Check login
info "Checking Azure CLI login status..."
if ! az account show &> /dev/null; then
    error "Not logged in to Azure. Please run: az login"
fi

success "Logged in to Azure"

# Get Key Vault ID
info "Getting Key Vault information..."
VAULT_ID=$(az keyvault show --name "$VAULT_NAME" --resource-group "$RESOURCE_GROUP" --query id -o tsv)
success "Key Vault ID: $VAULT_ID"

# Get the service principal object ID from the app registration
APP_CLIENT_ID="${AZURE_CLIENT_ID}"
if [ -z "$APP_CLIENT_ID" ]; then
    error "AZURE_CLIENT_ID not set in .env"
fi

info "Looking up service principal for app: $APP_CLIENT_ID"
SP_OBJECT_ID=$(az ad sp show --id "$APP_CLIENT_ID" --query id -o tsv 2>/dev/null) || {
    warn "Service principal not found. Creating one..."
    az ad sp create --id "$APP_CLIENT_ID" --output none
    SP_OBJECT_ID=$(az ad sp show --id "$APP_CLIENT_ID" --query id -o tsv)
}
success "Service Principal Object ID: $SP_OBJECT_ID"

# Grant Key Vault Secrets User role (read-only access to secrets)
info "Granting 'Key Vault Secrets User' role to application..."
az role assignment create \
    --role "Key Vault Secrets User" \
    --assignee-object-id "$SP_OBJECT_ID" \
    --assignee-principal-type ServicePrincipal \
    --scope "$VAULT_ID" \
    --output none 2>/dev/null || {
        warn "RBAC assignment failed. Trying access policy..."

        az keyvault set-policy \
            --name "$VAULT_NAME" \
            --spn "$APP_CLIENT_ID" \
            --secret-permissions get list \
            --output none
    }

success "Application granted access to Key Vault secrets"

echo ""
echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}                    ACCESS GRANTED!                             ${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"
echo ""
echo "The application can now read secrets from Key Vault."
echo "Start the services with: ./start.sh"
