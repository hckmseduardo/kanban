#!/bin/bash
# =============================================================================
# Azure Key Vault Setup Script
# =============================================================================
# This script creates and configures an Azure Key Vault for the Kanban platform.
#
# Prerequisites:
#   - Azure CLI installed and logged in (az login)
#     OR Docker installed (will run Azure CLI in container)
#   - Appropriate Azure subscription permissions
#
# Usage:
#   ./scripts/setup-azure-keyvault.sh
#   ./scripts/setup-azure-keyvault.sh --resource-group mygroup --vault-name myvault
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

# =============================================================================
# Docker Fallback: Run in container if Azure CLI not installed
# =============================================================================
if ! command -v az &> /dev/null; then
    if command -v docker &> /dev/null; then
        echo -e "${YELLOW}[INFO]${NC} Azure CLI not found locally. Running in Docker container..."

        # Get the script directory
        SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
        PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

        # Run this script inside a Docker container with Azure CLI
        exec docker run -it --rm \
            -v "$SCRIPT_DIR:/scripts:ro" \
            -v "$PROJECT_DIR:/project" \
            -w /scripts \
            -e RUNNING_IN_DOCKER=1 \
            mcr.microsoft.com/azure-cli:latest \
            bash -c "az login --use-device-code && ./setup-azure-keyvault.sh $*"
    else
        error "Azure CLI not found and Docker not available.\nPlease install Azure CLI: https://docs.microsoft.com/en-us/cli/azure/install-azure-cli\nOr install Docker to run Azure CLI in a container."
    fi
fi

# =============================================================================
# Configuration
# =============================================================================

# Default values
RESOURCE_GROUP="kanban-rg"
LOCATION="eastus"
VAULT_NAME="kanban-kv-$(openssl rand -hex 4)"
APP_NAME="kanban-app"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --resource-group|-g)
            RESOURCE_GROUP="$2"
            shift 2
            ;;
        --location|-l)
            LOCATION="$2"
            shift 2
            ;;
        --vault-name|-v)
            VAULT_NAME="$2"
            shift 2
            ;;
        --app-name|-a)
            APP_NAME="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --resource-group, -g   Azure resource group name (default: kanban-rg)"
            echo "  --location, -l         Azure region (default: eastus)"
            echo "  --vault-name, -v       Key Vault name (default: kanban-kv-<random>)"
            echo "  --app-name, -a         App registration name (default: kanban-app)"
            echo "  --help, -h             Show this help"
            echo ""
            echo "If Azure CLI is not installed, this script will automatically"
            echo "run inside a Docker container with Azure CLI."
            exit 0
            ;;
        *)
            error "Unknown option: $1"
            ;;
    esac
done

echo -e "${BLUE}"
echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║           AZURE KEY VAULT SETUP FOR KANBAN                    ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

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
TENANT_ID=$(az account show --query tenantId -o tsv)
success "Logged in to subscription: $SUBSCRIPTION"

# Create Resource Group
info "Creating resource group: $RESOURCE_GROUP..."
az group create \
    --name "$RESOURCE_GROUP" \
    --location "$LOCATION" \
    --output none
success "Resource group created"

# Create Key Vault
info "Creating Key Vault: $VAULT_NAME..."
az keyvault create \
    --name "$VAULT_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --location "$LOCATION" \
    --enable-rbac-authorization false \
    --output none
success "Key Vault created"

# Create App Registration for Kanban
info "Creating App Registration: $APP_NAME..."
APP_ID=$(az ad app create \
    --display-name "$APP_NAME" \
    --sign-in-audience AzureADandPersonalMicrosoftAccount \
    --query appId -o tsv)

# Create Service Principal
info "Creating Service Principal..."
SP_INFO=$(az ad sp create --id "$APP_ID" 2>/dev/null || true)
SP_OBJECT_ID=$(az ad sp show --id "$APP_ID" --query id -o tsv)

# Create client secret
info "Creating client secret..."
CLIENT_SECRET=$(az ad app credential reset \
    --id "$APP_ID" \
    --display-name "kanban-secret" \
    --years 2 \
    --query password -o tsv)

# Grant Key Vault access to the Service Principal
info "Granting Key Vault access..."
az keyvault set-policy \
    --name "$VAULT_NAME" \
    --spn "$APP_ID" \
    --secret-permissions get list set delete \
    --output none
success "Key Vault access granted"

# Create initial secrets
info "Creating initial secrets..."

# Generate random secrets
PORTAL_SECRET=$(openssl rand -base64 32)
CROSS_DOMAIN_SECRET=$(openssl rand -base64 32)

# Store secrets in Key Vault
info "Storing portal-secret-key..."
az keyvault secret set --vault-name "$VAULT_NAME" --name "portal-secret-key" --value "$PORTAL_SECRET" --output none

info "Storing cross-domain-secret..."
az keyvault secret set --vault-name "$VAULT_NAME" --name "cross-domain-secret" --value "$CROSS_DOMAIN_SECRET" --output none

# Placeholder secrets (to be configured later)
info "Creating placeholder secrets (configure these manually)..."

# These need to be set manually after Entra ID app registration
az keyvault secret set --vault-name "$VAULT_NAME" --name "entra-client-id" --value "CONFIGURE_ME" --output none
az keyvault secret set --vault-name "$VAULT_NAME" --name "entra-client-secret" --value "CONFIGURE_ME" --output none
az keyvault secret set --vault-name "$VAULT_NAME" --name "entra-tenant-id" --value "$TENANT_ID" --output none

# Redis URL (defaults to internal Docker service)
az keyvault secret set --vault-name "$VAULT_NAME" --name "redis-url" --value "redis://redis:6379" --output none

# Certbot email for Let's Encrypt
az keyvault secret set --vault-name "$VAULT_NAME" --name "certbot-email" --value "CONFIGURE_ME" --output none

success "Initial secrets created"

# List all secrets
info "Secrets in Key Vault:"
az keyvault secret list --vault-name "$VAULT_NAME" --query "[].name" -o tsv | while read -r secret; do
    echo "  - $secret"
done

# Create Entra ID App for authentication (External Identities)
info "Setting up Entra ID authentication..."

# Add redirect URIs
az ad app update \
    --id "$APP_ID" \
    --web-redirect-uris \
        "https://localhost:3001/auth/callback" \
        "https://app.localhost:3001/auth/callback" \
        "http://localhost:3001/auth/callback"

# Enable ID tokens
az ad app update \
    --id "$APP_ID" \
    --enable-id-token-issuance true

success "Entra ID authentication configured"

# Output configuration
echo ""
echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}                    SETUP COMPLETE!                            ${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"
echo ""
echo "Add these values to your .env file:"
echo ""
echo -e "${YELLOW}# Azure Configuration${NC}"
echo "AZURE_KEY_VAULT_URL=https://${VAULT_NAME}.vault.azure.net/"
echo "AZURE_CLIENT_ID=${APP_ID}"
echo "AZURE_CLIENT_SECRET=${CLIENT_SECRET}"
echo "AZURE_TENANT_ID=${TENANT_ID}"
echo ""
echo -e "${YELLOW}# Entra ID (same as above for single-tenant)${NC}"
echo "ENTRA_CLIENT_ID=${APP_ID}"
echo "ENTRA_CLIENT_SECRET=${CLIENT_SECRET}"
echo "ENTRA_TENANT_ID=${TENANT_ID}"
echo ""
echo -e "${BLUE}Key Vault URL:${NC} https://${VAULT_NAME}.vault.azure.net/"
echo -e "${BLUE}Resource Group:${NC} $RESOURCE_GROUP"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo "1. Copy the values above to your .env file"
echo "2. Configure External Identities in Azure Portal for social logins:"
echo "   Azure Portal > Entra ID > External Identities > All identity providers"
echo "3. Add additional secrets to Key Vault as needed:"
echo "   az keyvault secret set --vault-name $VAULT_NAME --name <name> --value <value>"
echo ""

# Save config to file
CONFIG_FILE="./azure-config.txt"
cat > "$CONFIG_FILE" << EOF
# Azure Configuration for Kanban Platform
# Generated: $(date)

AZURE_KEY_VAULT_URL=https://${VAULT_NAME}.vault.azure.net/
AZURE_CLIENT_ID=${APP_ID}
AZURE_CLIENT_SECRET=${CLIENT_SECRET}
AZURE_TENANT_ID=${TENANT_ID}

ENTRA_CLIENT_ID=${APP_ID}
ENTRA_CLIENT_SECRET=${CLIENT_SECRET}
ENTRA_TENANT_ID=${TENANT_ID}

# Resources
Resource Group: $RESOURCE_GROUP
Key Vault: $VAULT_NAME
App Registration: $APP_NAME
EOF

success "Configuration saved to $CONFIG_FILE"
warn "Keep this file secure and do not commit to version control!"
