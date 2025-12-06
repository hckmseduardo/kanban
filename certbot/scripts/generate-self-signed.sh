#!/bin/bash
# Generate self-signed certificate for development

set -e

DOMAIN=${1:-"localhost"}
CERT_DIR="/etc/letsencrypt/live/${DOMAIN}"

echo "Generating self-signed certificate for ${DOMAIN}..."

mkdir -p "$CERT_DIR"

# Generate private key
openssl genrsa -out "$CERT_DIR/privkey.pem" 2048

# Generate certificate
openssl req -new -x509 -days 365 \
    -key "$CERT_DIR/privkey.pem" \
    -out "$CERT_DIR/fullchain.pem" \
    -subj "/CN=${DOMAIN}" \
    -addext "subjectAltName=DNS:${DOMAIN},DNS:*.${DOMAIN}"

echo "Certificate generated at ${CERT_DIR}"
ls -la "$CERT_DIR"
