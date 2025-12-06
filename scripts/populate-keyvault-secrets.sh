#!/bin/bash
# =============================================================================
# Populate Azure Key Vault with Kanban Platform Secrets
# =============================================================================
# This script adds the required secrets to your Azure Key Vault.
#
# Prerequisites:
#   - Azure CLI installed and logged in (az login)
#   - Key Vault already created (run setup-azure-keyvault.sh first)
#   - .env file with AZURE_KEY_VAULT_URL configured
#
# Usage:
#   ./scripts/populate-keyvault-secrets.sh
#   ./scripts/populate-keyvault-secrets.sh --vault-name your-vault-name
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

# Load .env file if it exists
if [ -f ".env" ]; then
    info "Loading .env file..."
    export $(grep -v '^#' .env | xargs)
fi

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --vault-name|-v)
            VAULT_NAME="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --vault-name, -v   Key Vault name (or set AZURE_KEY_VAULT_URL in .env)"
            echo "  --help, -h         Show this help"
            exit 0
            ;;
        *)
            error "Unknown option: $1"
            ;;
    esac
done

# Extract vault name from URL if not provided
if [ -z "$VAULT_NAME" ]; then
    if [ -n "$AZURE_KEY_VAULT_URL" ]; then
        VAULT_NAME=$(echo "$AZURE_KEY_VAULT_URL" | sed 's|https://||' | sed 's|.vault.azure.net/||')
        info "Using vault name from AZURE_KEY_VAULT_URL: $VAULT_NAME"
    else
        error "No vault name provided. Use --vault-name or set AZURE_KEY_VAULT_URL in .env"
    fi
fi

echo -e "${BLUE}"
echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║         POPULATE KEY VAULT SECRETS FOR KANBAN                 ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Check Azure CLI
if ! command -v az &> /dev/null; then
    error "Azure CLI not found. Please install it: https://docs.microsoft.com/en-us/cli/azure/install-azure-cli"
fi

# Check login status
info "Checking Azure CLI login status..."
if ! az account show &> /dev/null; then
    error "Not logged in to Azure. Please run: az login"
fi

success "Logged in to Azure"

# Function to set a secret
set_secret() {
    local name=$1
    local value=$2
    local description=$3

    if [ -z "$value" ]; then
        warn "Skipping $name - no value provided"
        return
    fi

    info "Setting secret: $name"
    az keyvault secret set \
        --vault-name "$VAULT_NAME" \
        --name "$name" \
        --value "$value" \
        --output none 2>/dev/null || {
            warn "Failed to set $name (might already exist or permission issue)"
            return
        }
    success "Set: $name"
}

echo ""
info "Populating secrets in Key Vault: $VAULT_NAME"
echo ""

# =============================================================================
# Portal Secrets
# =============================================================================
info "Setting Portal secrets..."

# Generate random secrets if not set
if [ "$PORTAL_SECRET_KEY" = "change-me-in-production" ] || [ -z "$PORTAL_SECRET_KEY" ]; then
    PORTAL_SECRET_KEY=$(openssl rand -base64 32)
    info "Generated new PORTAL_SECRET_KEY"
fi

if [ "$CROSS_DOMAIN_SECRET" = "change-me-in-production" ] || [ -z "$CROSS_DOMAIN_SECRET" ]; then
    CROSS_DOMAIN_SECRET=$(openssl rand -base64 32)
    info "Generated new CROSS_DOMAIN_SECRET"
fi

set_secret "portal-secret-key" "$PORTAL_SECRET_KEY" "JWT signing key for portal"
set_secret "cross-domain-secret" "$CROSS_DOMAIN_SECRET" "Secret for cross-domain token exchange"

# =============================================================================
# Entra ID / Authentication Secrets
# =============================================================================
info "Setting Entra ID secrets..."

set_secret "entra-client-id" "$ENTRA_CLIENT_ID" "Entra ID application client ID"
set_secret "entra-client-secret" "$ENTRA_CLIENT_SECRET" "Entra ID application client secret"
set_secret "entra-tenant-id" "$ENTRA_TENANT_ID" "Entra ID tenant ID"

# =============================================================================
# Optional: Social Provider API Keys
# =============================================================================
info "Setting optional social provider secrets..."

set_secret "twitter-bearer-token" "${TWITTER_BEARER_TOKEN:-}" "Twitter API bearer token for link previews"
set_secret "github-access-token" "${GITHUB_ACCESS_TOKEN:-}" "GitHub access token for link previews"
set_secret "youtube-api-key" "${YOUTUBE_API_KEY:-}" "YouTube API key for link previews"

# =============================================================================
# Database & Redis
# =============================================================================
info "Setting infrastructure secrets..."

set_secret "redis-url" "${REDIS_URL:-redis://redis:6379}" "Redis connection URL"

# =============================================================================
# Summary
# =============================================================================
echo ""
echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}                    SECRETS CONFIGURED!                        ${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"
echo ""
echo "Secrets have been added to Key Vault: $VAULT_NAME"
echo ""
echo "To list all secrets:"
echo "  az keyvault secret list --vault-name $VAULT_NAME --output table"
echo ""
echo "To get a secret value:"
echo "  az keyvault secret show --vault-name $VAULT_NAME --name <secret-name> --query value -o tsv"
echo ""

# Show current secrets
info "Current secrets in Key Vault:"
az keyvault secret list --vault-name "$VAULT_NAME" --output table 2>/dev/null || warn "Could not list secrets"
