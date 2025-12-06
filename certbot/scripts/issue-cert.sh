#!/bin/bash
# Issue Let's Encrypt certificate for a domain

set -e

DOMAIN=${1:-$DOMAIN}
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

# For wildcard certificates, we need DNS-01 challenge
# For single domain, we use webroot (HTTP-01) challenge
if [[ "$DOMAIN" == *"*"* ]]; then
    echo "Wildcard domain detected - DNS-01 challenge required"
    echo "Please use manual DNS validation or configure DNS plugin"

    # Manual mode for wildcard
    certbot certonly \
        --manual \
        --preferred-challenges dns \
        -d "$DOMAIN" \
        -d "*.${DOMAIN}" \
        --email "$EMAIL" \
        --agree-tos \
        --non-interactive \
        --manual-public-ip-logging-ok
else
    # Issue certificate with HTTP-01 challenge
    # Request both base domain and wildcard for flexibility
    certbot certonly \
        --webroot \
        -w "$WEBROOT" \
        -d "$DOMAIN" \
        -d "app.${DOMAIN}" \
        -d "api.${DOMAIN}" \
        --email "$EMAIL" \
        --agree-tos \
        --non-interactive \
        --expand
fi

echo "Certificate issued successfully for ${DOMAIN}"
