#!/bin/bash
# =============================================================================
# Update Azure Key Vault Secret
# =============================================================================
# Helper script to update individual secrets in Azure Key Vault
#
# Usage:
#   ./update-keyvault-secret.sh <secret-name> <secret-value>
#   ./update-keyvault-secret.sh --vault-name myvault <secret-name> <secret-value>
#
# Examples:
#   ./update-keyvault-secret.sh certbot-email admin@example.com
#   ./update-keyvault-secret.sh entra-client-id "your-client-id"
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

# =============================================================================
# Docker Fallback: Run in container if Azure CLI not installed
# =============================================================================
if ! command -v az &> /dev/null; then
    if command -v docker &> /dev/null; then
        echo -e "${YELLOW}[INFO]${NC} Azure CLI not found locally. Running in Docker container..."

        # Get the script directory
        SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

        # Run this script inside a Docker container with Azure CLI
        exec docker run -it --rm \
            -v "$SCRIPT_DIR:/scripts:ro" \
            -w /scripts \
            -e RUNNING_IN_DOCKER=1 \
            -e AZURE_KEY_VAULT_NAME="$AZURE_KEY_VAULT_NAME" \
            -e AZURE_KEY_VAULT_URL="$AZURE_KEY_VAULT_URL" \
            mcr.microsoft.com/azure-cli:latest \
            bash -c "az login --use-device-code && ./update-keyvault-secret.sh $*"
    else
        error "Azure CLI not found and Docker not available.\nPlease install Azure CLI or Docker."
    fi
fi

# Default vault name (can be overridden)
VAULT_NAME=""
SECRET_NAME=""
SECRET_VALUE=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --vault-name|-v)
            VAULT_NAME="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: $0 [--vault-name <vault>] <secret-name> <secret-value>"
            echo ""
            echo "Options:"
            echo "  --vault-name, -v   Azure Key Vault name (or set AZURE_KEY_VAULT_NAME env var)"
            echo "  --help, -h         Show this help"
            echo ""
            echo "Available secrets:"
            echo "  portal-secret-key     JWT signing key for portal"
            echo "  cross-domain-secret   Secret for cross-domain SSO tokens"
            echo "  entra-client-id       Microsoft Entra ID application client ID"
            echo "  entra-client-secret   Microsoft Entra ID application client secret"
            echo "  entra-tenant-id       Microsoft Entra ID tenant ID"
            echo "  redis-url             Redis connection URL"
            echo "  certbot-email         Email for Let's Encrypt certificates"
            exit 0
            ;;
        -*)
            error "Unknown option: $1"
            ;;
        *)
            if [ -z "$SECRET_NAME" ]; then
                SECRET_NAME="$1"
            elif [ -z "$SECRET_VALUE" ]; then
                SECRET_VALUE="$1"
            else
                error "Too many arguments"
            fi
            shift
            ;;
    esac
done

# Try to get vault name from environment if not provided
if [ -z "$VAULT_NAME" ]; then
    VAULT_NAME="${AZURE_KEY_VAULT_NAME:-}"
fi

# Try to extract from AZURE_KEY_VAULT_URL
if [ -z "$VAULT_NAME" ] && [ -n "$AZURE_KEY_VAULT_URL" ]; then
    VAULT_NAME=$(echo "$AZURE_KEY_VAULT_URL" | sed -E 's|https://([^.]+)\.vault\.azure\.net.*|\1|')
fi

# Validate inputs
if [ -z "$VAULT_NAME" ]; then
    error "Vault name is required. Use --vault-name or set AZURE_KEY_VAULT_NAME"
fi

if [ -z "$SECRET_NAME" ]; then
    error "Secret name is required"
fi

if [ -z "$SECRET_VALUE" ]; then
    error "Secret value is required"
fi

# Check Azure CLI
if ! command -v az &> /dev/null; then
    error "Azure CLI not found. Please install it."
fi

# Check login
if ! az account show &> /dev/null; then
    error "Not logged in to Azure. Please run: az login"
fi

info "Updating secret '$SECRET_NAME' in vault '$VAULT_NAME'..."

# Update the secret
az keyvault secret set \
    --vault-name "$VAULT_NAME" \
    --name "$SECRET_NAME" \
    --value "$SECRET_VALUE" \
    --output none

success "Secret '$SECRET_NAME' updated successfully"

# Show secret info (not the value)
info "Secret details:"
az keyvault secret show \
    --vault-name "$VAULT_NAME" \
    --name "$SECRET_NAME" \
    --query "{name:name, enabled:attributes.enabled, created:attributes.created, updated:attributes.updated}" \
    -o table
