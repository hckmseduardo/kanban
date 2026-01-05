#!/bin/bash
# =============================================================================
# Issue Certificate for Workspace App Subdomain
# =============================================================================
# Called by the orchestrator when provisioning a workspace with an app.
# Issues certificates for:
#   - {workspace}.app.{domain} (app frontend/API)
#
# Usage:
#   ./issue-workspace-certificate.sh <workspace-slug>
#
# Environment variables:
#   DOMAIN          - Base domain (e.g., kanban.amazing-ai.tools)
#   CERTBOT_EMAIL   - Email for Let's Encrypt
#   CERT_MODE       - "development" or "production"
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

# Configuration
WORKSPACE_SLUG="$1"
BASE_DOMAIN="${DOMAIN:-localhost}"
EMAIL="${CERTBOT_EMAIL:-admin@localhost}"
CERT_MODE="${CERT_MODE:-development}"
STAGING="${LETSENCRYPT_STAGING:-false}"
WEBROOT="/var/www/certbot"

# Validate input
if [ -z "$WORKSPACE_SLUG" ]; then
    error "Workspace slug is required. Usage: $0 <workspace-slug>"
fi

# Construct workspace app domain
APP_DOMAIN="${WORKSPACE_SLUG}.app.${BASE_DOMAIN}"
CERT_DIR="/etc/letsencrypt/live/${APP_DOMAIN}"

info "Issuing certificate for workspace app: $WORKSPACE_SLUG"
info "Domain: $APP_DOMAIN"
info "Mode: $CERT_MODE"

# Create directories
mkdir -p "$WEBROOT"
mkdir -p "$CERT_DIR"

if [ "$CERT_MODE" = "development" ]; then
    # =========================================================================
    # Development: Generate self-signed certificate
    # =========================================================================
    info "Generating self-signed certificate for $APP_DOMAIN"

    # Generate private key
    openssl genrsa -out "$CERT_DIR/privkey.pem" 2048

    # Generate certificate with SAN
    openssl req -new -x509 -days 365 \
        -key "$CERT_DIR/privkey.pem" \
        -out "$CERT_DIR/fullchain.pem" \
        -subj "/CN=${APP_DOMAIN}" \
        -addext "subjectAltName=DNS:${APP_DOMAIN}"

    success "Self-signed certificate generated for $APP_DOMAIN"

elif [ "$CERT_MODE" = "production" ]; then
    # =========================================================================
    # Production: Request Let's Encrypt certificate
    # =========================================================================
    info "Requesting Let's Encrypt certificate for $APP_DOMAIN"

    # Validate email
    if [ "$EMAIL" = "admin@localhost" ]; then
        error "CERTBOT_EMAIL must be set in production mode"
    fi

    # Staging flag
    STAGING_FLAG=""
    if [ "$STAGING" = "true" ]; then
        warn "Using Let's Encrypt STAGING server"
        STAGING_FLAG="--staging"
    fi

    # Check if certificate already exists
    if [ -f "$CERT_DIR/fullchain.pem" ]; then
        if openssl x509 -checkend 2592000 -noout -in "$CERT_DIR/fullchain.pem" 2>/dev/null; then
            info "Valid certificate already exists for $APP_DOMAIN"
            exit 0
        fi
    fi

    # Request certificate using HTTP-01 challenge
    certbot certonly \
        $STAGING_FLAG \
        --non-interactive \
        --agree-tos \
        --email "$EMAIL" \
        --webroot \
        --webroot-path "$WEBROOT" \
        -d "$APP_DOMAIN" \
        --cert-name "$APP_DOMAIN" \
        || {
            error "Failed to obtain certificate for $APP_DOMAIN"
        }

    success "Let's Encrypt certificate issued for $APP_DOMAIN"
else
    error "Invalid CERT_MODE: $CERT_MODE"
fi

# Output certificate info
if [ -f "$CERT_DIR/fullchain.pem" ]; then
    info "Certificate details:"
    openssl x509 -in "$CERT_DIR/fullchain.pem" -noout -subject -dates

    # Output JSON for orchestrator to parse
    echo ""
    echo "---CERT_INFO_START---"
    cat << EOF
{
    "workspace_slug": "$WORKSPACE_SLUG",
    "domain": "$APP_DOMAIN",
    "cert_path": "$CERT_DIR/fullchain.pem",
    "key_path": "$CERT_DIR/privkey.pem",
    "mode": "$CERT_MODE",
    "issued_at": "$(date -Iseconds)"
}
EOF
    echo "---CERT_INFO_END---"
fi
