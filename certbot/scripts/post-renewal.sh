#!/bin/bash
# =============================================================================
# Post-Renewal Hook
# =============================================================================
# Called by certbot after successful certificate renewal
# Notifies Traefik to reload certificates
# =============================================================================

set -e

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

info() { echo -e "${BLUE}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }

RENEWED_DOMAIN="${RENEWED_LINEAGE##*/}"

info "Certificate renewed for: $RENEWED_DOMAIN"
info "Certificate path: $RENEWED_LINEAGE"

# Notify via Redis (if available)
if command -v redis-cli &> /dev/null; then
    REDIS_URL="${REDIS_URL:-redis://redis:6379}"
    REDIS_HOST=$(echo "$REDIS_URL" | sed -E 's|redis://([^:]+):.*|\1|')
    REDIS_PORT=$(echo "$REDIS_URL" | sed -E 's|redis://[^:]+:([0-9]+).*|\1|')

    info "Publishing renewal notification to Redis..."
    redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" PUBLISH "cert:renewed" "$RENEWED_DOMAIN" 2>/dev/null || true
fi

# Touch a file to signal Traefik to reload (if using file provider)
RELOAD_FILE="/etc/traefik/certs/.reload"
touch "$RELOAD_FILE" 2>/dev/null || true

# Log the renewal
echo "$(date): Certificate renewed for $RENEWED_DOMAIN" >> /var/log/certbot/renewals.log

success "Post-renewal hook completed for $RENEWED_DOMAIN"
