#!/bin/bash
# =============================================================================
# Kanban Platform - Start Script
# =============================================================================
# Usage:
#   ./start.sh              # Start with default port 3001
#   ./start.sh 8080         # Start with port 8080
#   ./start.sh --port 9000  # Start with port 9000
#   ./start.sh --dev        # Development mode (default)
#   ./start.sh --prod       # Production mode
# =============================================================================

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default values
PORT=3001
CERT_MODE="development"
BUILD=false

# Print banner
print_banner() {
    echo -e "${BLUE}"
    echo "╔═══════════════════════════════════════════════════════════════╗"
    echo "║                    KANBAN PLATFORM                            ║"
    echo "╚═══════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

# Print status message
info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --port|-p)
            PORT="$2"
            shift 2
            ;;
        --dev|--development)
            CERT_MODE="development"
            shift
            ;;
        --staging)
            CERT_MODE="staging"
            shift
            ;;
        --prod|--production)
            CERT_MODE="production"
            shift
            ;;
        --build|-b)
            BUILD=true
            shift
            ;;
        --help|-h)
            echo "Usage: ./start.sh [OPTIONS] [PORT]"
            echo ""
            echo "Options:"
            echo "  --port, -p PORT    Specify port (default: 3001)"
            echo "  --dev              Development mode with self-signed certs (default)"
            echo "  --staging          Staging mode with Let's Encrypt staging"
            echo "  --prod             Production mode with Let's Encrypt"
            echo "  --build, -b        Force rebuild of containers"
            echo "  --help, -h         Show this help message"
            echo ""
            echo "Examples:"
            echo "  ./start.sh                 # Start on port 3001 (dev mode)"
            echo "  ./start.sh 8080            # Start on port 8080"
            echo "  ./start.sh --port 9000     # Start on port 9000"
            echo "  ./start.sh --prod --build  # Production with rebuild"
            exit 0
            ;;
        [0-9]*)
            PORT="$1"
            shift
            ;;
        *)
            error "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

print_banner

# Check if .env exists
if [ ! -f .env ]; then
    warn ".env file not found. Creating from .env.example..."
    if [ -f .env.example ]; then
        cp .env.example .env
        success "Created .env file. Please edit it with your configuration."
    else
        error ".env.example not found!"
        exit 1
    fi
fi

# Load environment
set -a
source .env
set +a

# Override with command line values
export PORT=$PORT
export CERT_MODE=$CERT_MODE

info "Configuration:"
echo "  Port:      $PORT"
echo "  Mode:      $CERT_MODE"
echo "  Domain:    ${DOMAIN:-localhost}"
echo ""

# Generate certificates if needed
if [ "$CERT_MODE" == "development" ]; then
    info "Checking self-signed certificates..."

    CERT_DIR="./traefik/certs"
    if [ ! -f "$CERT_DIR/localhost.crt" ]; then
        info "Generating self-signed certificates..."
        mkdir -p "$CERT_DIR"

        # Generate CA
        openssl genrsa -out "$CERT_DIR/ca.key" 4096 2>/dev/null
        openssl req -new -x509 -days 3650 -key "$CERT_DIR/ca.key" \
            -out "$CERT_DIR/ca.crt" \
            -subj "/CN=Kanban Local CA" 2>/dev/null

        # Generate server certificate
        openssl genrsa -out "$CERT_DIR/localhost.key" 2048 2>/dev/null
        openssl req -new -key "$CERT_DIR/localhost.key" \
            -out "$CERT_DIR/localhost.csr" \
            -subj "/CN=localhost" 2>/dev/null

        # Create extension file for SAN
        cat > "$CERT_DIR/localhost.ext" << EOF
authorityKeyIdentifier=keyid,issuer
basicConstraints=CA:FALSE
keyUsage = digitalSignature, nonRepudiation, keyEncipherment, dataEncipherment
subjectAltName = @alt_names

[alt_names]
DNS.1 = localhost
DNS.2 = *.localhost
DNS.3 = app.localhost
DNS.4 = api.localhost
IP.1 = 127.0.0.1
EOF

        openssl x509 -req -in "$CERT_DIR/localhost.csr" \
            -CA "$CERT_DIR/ca.crt" -CAkey "$CERT_DIR/ca.key" \
            -CAcreateserial -out "$CERT_DIR/localhost.crt" \
            -days 365 -sha256 -extfile "$CERT_DIR/localhost.ext" 2>/dev/null

        rm -f "$CERT_DIR/localhost.csr" "$CERT_DIR/localhost.ext"

        success "Self-signed certificates generated!"
        echo ""
        warn "To trust the CA certificate (removes browser warnings):"
        echo "  macOS:   sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain $CERT_DIR/ca.crt"
        echo "  Linux:   sudo cp $CERT_DIR/ca.crt /usr/local/share/ca-certificates/ && sudo update-ca-certificates"
        echo ""
    else
        success "Certificates already exist"
    fi
fi

# Create required directories
mkdir -p data/portal data/teams

# Build if requested or first run
if [ "$BUILD" = true ]; then
    info "Building containers..."
    docker compose build
fi

# Start services
info "Starting Kanban platform..."
docker compose up -d

# Wait for services to be ready
info "Waiting for services to be ready..."
sleep 3

# Check service health
check_service() {
    local service=$1
    local status=$(docker inspect --format='{{.State.Status}}' "kanban-$service" 2>/dev/null)
    if [ "$status" == "running" ]; then
        echo -e "  ${GREEN}✓${NC} $service"
    else
        echo -e "  ${RED}✗${NC} $service ($status)"
    fi
}

echo ""
info "Service Status:"
check_service "traefik"
check_service "redis"
check_service "portal-api"
check_service "portal-web"
check_service "worker"
check_service "orchestrator"

echo ""
success "Kanban is running!"
echo ""
echo -e "${BLUE}Access URLs:${NC}"
echo "  Portal:     https://app.${DOMAIN:-localhost}:$PORT"
echo "  API:        https://api.${DOMAIN:-localhost}:$PORT"
echo "  API Docs:   https://api.${DOMAIN:-localhost}:$PORT/docs"
echo ""
echo -e "${YELLOW}Tip:${NC} Add to /etc/hosts if using localhost:"
echo "  127.0.0.1 app.localhost api.localhost"
echo ""
echo "To view logs:  docker compose logs -f"
echo "To stop:       docker compose down"
echo ""
