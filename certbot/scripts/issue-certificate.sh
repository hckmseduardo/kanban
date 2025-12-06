#!/bin/bash
# =============================================================================
# Issue Let's Encrypt Certificate
# =============================================================================
# Issues a certificate for a domain using HTTP-01 challenge via Traefik
#
# Usage:
#   ./issue-certificate.sh <domain> [--staging] [--wildcard]
#
# Examples:
#   ./issue-certificate.sh kanban.amazing-ai.tools
#   ./issue-certificate.sh kanban.amazing-ai.tools --staging
#   ./issue-certificate.sh kanban.amazing-ai.tools --wildcard
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

# Default values
DOMAIN=""
STAGING=""
WILDCARD=false
EMAIL="${CERTBOT_EMAIL:-admin@localhost}"
WEBROOT="/var/www/certbot"
CERT_DIR="/etc/letsencrypt"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --staging|-s)
            STAGING="--staging"
            shift
            ;;
        --wildcard|-w)
            WILDCARD=true
            shift
            ;;
        --email|-e)
            EMAIL="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: $0 <domain> [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --staging, -s    Use Let's Encrypt staging server (for testing)"
            echo "  --wildcard, -w   Issue wildcard certificate (requires DNS challenge)"
            echo "  --email, -e      Email for Let's Encrypt notifications"
            echo "  --help, -h       Show this help"
            exit 0
            ;;
        -*)
            error "Unknown option: $1"
            ;;
        *)
            DOMAIN="$1"
            shift
            ;;
    esac
done

# Validate domain
if [ -z "$DOMAIN" ]; then
    error "Domain is required. Usage: $0 <domain>"
fi

# Validate email
if [ "$EMAIL" = "admin@localhost" ]; then
    warn "Using default email. Set CERTBOT_EMAIL for production."
fi

info "Issuing certificate for: $DOMAIN"
info "Email: $EMAIL"
[ -n "$STAGING" ] && info "Mode: STAGING (test certificate)"

# Create webroot directory
mkdir -p "$WEBROOT"

if [ "$WILDCARD" = true ]; then
    # Wildcard certificates require DNS-01 challenge
    # This requires additional setup (DNS provider API credentials)
    info "Requesting wildcard certificate for *.$DOMAIN"
    warn "Wildcard certificates require DNS-01 challenge."
    warn "Make sure your DNS provider API credentials are configured."

    certbot certonly \
        $STAGING \
        --non-interactive \
        --agree-tos \
        --email "$EMAIL" \
        --preferred-challenges dns \
        --manual \
        --manual-public-ip-logging-ok \
        -d "$DOMAIN" \
        -d "*.$DOMAIN" \
        --cert-path "$CERT_DIR/live/$DOMAIN/fullchain.pem" \
        --key-path "$CERT_DIR/live/$DOMAIN/privkey.pem"
else
    # Standard HTTP-01 challenge via webroot
    info "Using HTTP-01 challenge (webroot: $WEBROOT)"

    certbot certonly \
        $STAGING \
        --non-interactive \
        --agree-tos \
        --email "$EMAIL" \
        --webroot \
        --webroot-path "$WEBROOT" \
        -d "$DOMAIN" \
        --cert-path "$CERT_DIR/live/$DOMAIN/fullchain.pem" \
        --key-path "$CERT_DIR/live/$DOMAIN/privkey.pem"
fi

# Verify certificate was created
if [ -f "$CERT_DIR/live/$DOMAIN/fullchain.pem" ]; then
    success "Certificate issued successfully!"

    # Show certificate info
    info "Certificate details:"
    openssl x509 -in "$CERT_DIR/live/$DOMAIN/fullchain.pem" -noout -text | grep -E "(Subject:|Issuer:|Not Before:|Not After:)"

    # Copy to Traefik-expected location if different
    TRAEFIK_CERT_DIR="/etc/letsencrypt"
    if [ "$CERT_DIR" != "$TRAEFIK_CERT_DIR" ]; then
        mkdir -p "$TRAEFIK_CERT_DIR/live/$DOMAIN"
        cp "$CERT_DIR/live/$DOMAIN/fullchain.pem" "$TRAEFIK_CERT_DIR/live/$DOMAIN/"
        cp "$CERT_DIR/live/$DOMAIN/privkey.pem" "$TRAEFIK_CERT_DIR/live/$DOMAIN/"
        info "Certificates copied to Traefik directory"
    fi
else
    error "Certificate issuance failed!"
fi
