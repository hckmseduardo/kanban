#!/bin/bash
# =============================================================================
# Renew Let's Encrypt Certificates
# =============================================================================
# Renews all certificates that are near expiration
# Designed to be run as a cron job or scheduled task
#
# Usage:
#   ./renew-certificates.sh [--dry-run] [--force]
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

# Log file
LOG_DIR="/var/log/certbot"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/renewal-$(date +%Y%m%d-%H%M%S).log"

# Parse arguments
DRY_RUN=""
FORCE=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run|-n)
            DRY_RUN="--dry-run"
            shift
            ;;
        --force|-f)
            FORCE="--force-renewal"
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --dry-run, -n   Test renewal without making changes"
            echo "  --force, -f     Force renewal even if not near expiration"
            echo "  --help, -h      Show this help"
            exit 0
            ;;
        *)
            error "Unknown option: $1"
            exit 1
            ;;
    esac
done

info "Starting certificate renewal check..."
echo "Renewal started at $(date)" >> "$LOG_FILE"

# Check if there are any certificates to renew
CERT_COUNT=$(find /etc/letsencrypt/live -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l)
if [ "$CERT_COUNT" -eq 0 ]; then
    warn "No certificates found to renew"
    exit 0
fi

info "Found $CERT_COUNT certificate(s) to check"

# Run certbot renew
certbot renew \
    $DRY_RUN \
    $FORCE \
    --non-interactive \
    --quiet \
    --deploy-hook "/scripts/post-renewal.sh" \
    2>&1 | tee -a "$LOG_FILE"

RESULT=${PIPESTATUS[0]}

if [ $RESULT -eq 0 ]; then
    success "Renewal check completed successfully"
    echo "Renewal completed successfully at $(date)" >> "$LOG_FILE"
else
    error "Renewal check failed with exit code $RESULT"
    echo "Renewal FAILED at $(date)" >> "$LOG_FILE"
fi

# List certificates and their expiration
info "Certificate status:"
for cert_dir in /etc/letsencrypt/live/*/; do
    if [ -d "$cert_dir" ]; then
        domain=$(basename "$cert_dir")
        if [ -f "$cert_dir/fullchain.pem" ]; then
            expiry=$(openssl x509 -in "$cert_dir/fullchain.pem" -noout -enddate | cut -d= -f2)
            expiry_epoch=$(date -d "$expiry" +%s 2>/dev/null || date -j -f "%b %d %T %Y %Z" "$expiry" +%s 2>/dev/null)
            now_epoch=$(date +%s)
            days_left=$(( (expiry_epoch - now_epoch) / 86400 ))

            if [ $days_left -lt 7 ]; then
                warn "$domain: expires in $days_left days ($expiry)"
            elif [ $days_left -lt 30 ]; then
                info "$domain: expires in $days_left days ($expiry)"
            else
                success "$domain: expires in $days_left days"
            fi
        fi
    fi
done

# Clean up old log files (keep last 30 days)
find "$LOG_DIR" -name "renewal-*.log" -mtime +30 -delete 2>/dev/null || true

exit $RESULT
