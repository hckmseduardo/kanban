#!/bin/bash
# Issue Let's Encrypt certificate for a domain

set -e

DOMAIN=$1
EMAIL=${CERTBOT_EMAIL:-"admin@localhost"}
WEBROOT="/var/www/certbot"

if [ -z "$DOMAIN" ]; then
    echo "Usage: $0 <domain>"
    exit 1
fi

echo "Issuing certificate for ${DOMAIN}..."

# Check if we're in development mode
if [ "$CERT_MODE" == "development" ]; then
    echo "Development mode - generating self-signed certificate"
    /scripts/generate-self-signed.sh "$DOMAIN"
    exit 0
fi

# Check DNS
echo "Checking DNS for ${DOMAIN}..."
if ! host "$DOMAIN" > /dev/null 2>&1; then
    echo "WARNING: DNS for ${DOMAIN} not resolvable yet"
fi

# Issue certificate
certbot certonly \
    --webroot \
    -w "$WEBROOT" \
    -d "$DOMAIN" \
    --email "$EMAIL" \
    --agree-tos \
    --non-interactive \
    --expand

echo "Certificate issued successfully for ${DOMAIN}"
