#!/bin/bash
# =============================================================================
# Add Entra External ID secrets to Azure Key Vault via Docker
# =============================================================================
# This script runs Azure CLI in a Docker container to add the Entra External ID
# secrets required for email/password authentication.
#
# Usage:
#   ./scripts/add-entra-external-id-secrets.sh
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
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# Load .env file
if [ -f ".env" ]; then
    info "Loading .env file..."
    export $(grep -v '^#' .env | xargs)
else
    error ".env file not found. Please run from project root."
fi

# Validate required variables
[ -z "$AZURE_CLIENT_ID" ] && error "AZURE_CLIENT_ID not set in .env"
[ -z "$AZURE_CLIENT_SECRET" ] && error "AZURE_CLIENT_SECRET not set in .env"
[ -z "$AZURE_TENANT_ID" ] && error "AZURE_TENANT_ID not set in .env"
[ -z "$AZURE_KEY_VAULT_URL" ] && error "AZURE_KEY_VAULT_URL not set in .env"

# Extract vault name from URL
VAULT_NAME=$(echo "$AZURE_KEY_VAULT_URL" | sed 's|https://||' | sed 's|.vault.azure.net.*||')
info "Using Key Vault: $VAULT_NAME"

# Entra External ID configuration (from gtfseditor tenant)
ENTRA_AUTHORITY="https://gtfseditor.ciamlogin.com/5e9bc5a5-5537-483b-bccf-709d890bea87"
ENTRA_SCOPES="User.Read email"

echo -e "${BLUE}"
echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║     ADD ENTRA EXTERNAL ID SECRETS TO KEY VAULT                ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

info "Secrets to add:"
echo "  - entra-authority: $ENTRA_AUTHORITY"
echo "  - entra-scopes: $ENTRA_SCOPES"
echo ""

# Run Azure CLI in Docker
info "Running Azure CLI in Docker container..."

docker run --rm \
    -e AZURE_CLIENT_ID="$AZURE_CLIENT_ID" \
    -e AZURE_CLIENT_SECRET="$AZURE_CLIENT_SECRET" \
    -e AZURE_TENANT_ID="$AZURE_TENANT_ID" \
    mcr.microsoft.com/azure-cli:latest \
    bash -c "
        echo 'Logging in to Azure...'
        az login --service-principal \
            -u \$AZURE_CLIENT_ID \
            -p \$AZURE_CLIENT_SECRET \
            --tenant \$AZURE_TENANT_ID \
            --output none

        echo 'Setting entra-authority secret...'
        az keyvault secret set \
            --vault-name '$VAULT_NAME' \
            --name 'entra-authority' \
            --value '$ENTRA_AUTHORITY' \
            --output none

        echo 'Setting entra-scopes secret...'
        az keyvault secret set \
            --vault-name '$VAULT_NAME' \
            --name 'entra-scopes' \
            --value '$ENTRA_SCOPES' \
            --output none

        echo 'Verifying secrets...'
        az keyvault secret list --vault-name '$VAULT_NAME' --query \"[?name=='entra-authority' || name=='entra-scopes'].name\" -o tsv
    "

echo ""
success "Entra External ID secrets added to Key Vault!"
echo ""
echo "Now restart the backend to pick up the new config:"
echo "  docker compose restart portal-backend"
echo ""
