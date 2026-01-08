#!/bin/bash
# =============================================================================
# Certbot Container Entrypoint
# =============================================================================
# Handles both development (self-signed) and production (Let's Encrypt) modes
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

# Configuration from environment
CERT_MODE="${CERT_MODE:-development}"
DOMAIN="${DOMAIN:-localhost}"
STAGING="${LETSENCRYPT_STAGING:-false}"

# =============================================================================
# Fetch CERTBOT_EMAIL from Azure Key Vault if credentials are available
# =============================================================================
fetch_keyvault_secret() {
    local secret_name="$1"
    local vault_url="$2"

    # Get access token from Azure AD
    local token_response=$(curl -s -X POST \
        "https://login.microsoftonline.com/${AZURE_TENANT_ID}/oauth2/v2.0/token" \
        -H "Content-Type: application/x-www-form-urlencoded" \
        -d "client_id=${AZURE_CLIENT_ID}" \
        -d "client_secret=${AZURE_CLIENT_SECRET}" \
        -d "scope=https://vault.azure.net/.default" \
        -d "grant_type=client_credentials")

    local access_token=$(echo "$token_response" | jq -r '.access_token')

    if [ -z "$access_token" ] || [ "$access_token" = "null" ]; then
        return 1
    fi

    # Fetch secret from Key Vault
    local secret_response=$(curl -s \
        "${vault_url}secrets/${secret_name}?api-version=7.4" \
        -H "Authorization: Bearer ${access_token}")

    echo "$secret_response" | jq -r '.value'
}

# Try to fetch CERTBOT_EMAIL from Key Vault
EMAIL="${CERTBOT_EMAIL:-admin@localhost}"
if [ -n "$AZURE_KEY_VAULT_URL" ] && [ -n "$AZURE_CLIENT_ID" ] && [ -n "$AZURE_CLIENT_SECRET" ] && [ -n "$AZURE_TENANT_ID" ]; then
    info "Fetching certbot-email from Azure Key Vault..."
    KV_EMAIL=$(fetch_keyvault_secret "certbot-email" "$AZURE_KEY_VAULT_URL")
    if [ -n "$KV_EMAIL" ] && [ "$KV_EMAIL" != "null" ]; then
        EMAIL="$KV_EMAIL"
        success "Loaded certbot-email from Key Vault"
    else
        warn "Could not fetch certbot-email from Key Vault, using default"
    fi
fi

echo ""
echo -e "${BLUE}╔═══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║              CERTBOT CERTIFICATE MANAGER                      ║${NC}"
echo -e "${BLUE}╚═══════════════════════════════════════════════════════════════╝${NC}"
echo ""

info "Mode: $CERT_MODE"
info "Domain: $DOMAIN"
info "Email: $EMAIL"

# Create required directories
mkdir -p /var/www/certbot
mkdir -p /var/log/certbot
mkdir -p /etc/letsencrypt/live/$DOMAIN

if [ "$CERT_MODE" = "development" ]; then
    # =========================================================================
    # Development Mode: Generate self-signed certificate
    # =========================================================================
    info "Running in DEVELOPMENT mode - generating self-signed certificate"

    CERT_FILE="/etc/letsencrypt/live/$DOMAIN/fullchain.pem"
    KEY_FILE="/etc/letsencrypt/live/$DOMAIN/privkey.pem"

    # Check if certificate already exists and is valid
    if [ -f "$CERT_FILE" ] && [ -f "$KEY_FILE" ]; then
        # Check if certificate is still valid (not expired)
        if openssl x509 -checkend 86400 -noout -in "$CERT_FILE" 2>/dev/null; then
            info "Valid self-signed certificate already exists"
        else
            warn "Certificate expired or expiring soon, regenerating..."
            /scripts/generate-self-signed.sh "$DOMAIN"
        fi
    else
        info "Generating new self-signed certificate..."
        /scripts/generate-self-signed.sh "$DOMAIN"
    fi

    success "Development certificate ready"

    # Keep container running (no renewal needed in dev)
    info "Container will stay running. Self-signed certs don't need renewal."
    exec tail -f /dev/null

elif [ "$CERT_MODE" = "production" ]; then
    # =========================================================================
    # Production Mode: Use Let's Encrypt
    # =========================================================================
    info "Running in PRODUCTION mode - using Let's Encrypt"

    CERT_FILE="/etc/letsencrypt/live/$DOMAIN/fullchain.pem"
    KEY_FILE="/etc/letsencrypt/live/$DOMAIN/privkey.pem"

    # Validate email
    if [ "$EMAIL" = "admin@localhost" ]; then
        error "CERTBOT_EMAIL must be set to a valid email in production mode"
        exit 1
    fi

    # Staging flag
    STAGING_FLAG=""
    if [ "$STAGING" = "true" ]; then
        warn "Using Let's Encrypt STAGING server (certificates won't be trusted)"
        STAGING_FLAG="--staging"
    fi

    # Check if certificate already exists
    if [ -f "$CERT_FILE" ] && [ -f "$KEY_FILE" ]; then
        # Check if certificate is valid and not near expiration (30 days)
        if openssl x509 -checkend 2592000 -noout -in "$CERT_FILE" 2>/dev/null; then
            info "Valid Let's Encrypt certificate already exists"
        else
            warn "Certificate expiring soon, will renew..."
        fi
    else
        info "No certificate found, requesting new one from Let's Encrypt..."

        # Wait for Traefik to be ready (it handles HTTP challenges)
        info "Waiting for Traefik to be ready..."
        sleep 10

        # Request initial certificate
        certbot certonly \
            $STAGING_FLAG \
            --non-interactive \
            --agree-tos \
            --email "$EMAIL" \
            --webroot \
            --webroot-path /var/www/certbot \
            -d "$DOMAIN" \
            || {
                error "Failed to obtain certificate. Check DNS and firewall settings."
                # Fall back to self-signed for graceful degradation
                warn "Falling back to self-signed certificate..."
                /scripts/generate-self-signed.sh "$DOMAIN"
            }
    fi

    # Set up cron for automatic renewal
    info "Setting up automatic renewal (runs twice daily at 00:00 and 12:00)..."

    # Create cron job
    cat > /etc/crontabs/root << EOF
# Certbot renewal - runs twice daily
0 0 * * * /scripts/renew-certificates.sh >> /var/log/certbot/cron.log 2>&1
0 12 * * * /scripts/renew-certificates.sh >> /var/log/certbot/cron.log 2>&1
EOF

    # Start cron daemon
    crond -b -l 8

    success "Production mode initialized with automatic renewal"
    info "Renewal cron job scheduled"

    # Keep container running and monitor logs
    exec tail -f /var/log/certbot/cron.log 2>/dev/null || tail -f /dev/null

else
    error "Invalid CERT_MODE: $CERT_MODE (must be 'development' or 'production')"
    exit 1
fi
