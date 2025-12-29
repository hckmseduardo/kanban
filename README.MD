# Kanban

A multi-tenant Kanban board platform for teams of any kind. Features a centralized user management portal with Microsoft Entra ID authentication, isolated team environments with dedicated containers and databases, built-in DNS server for dynamic subdomain generation, per-subdomain Let's Encrypt certificates via Certbot, and rich Markdown support with link previews.

Designed for marketing teams, operations, HR, project management, personal productivity, or any workflow that benefits from visual task organization.

## Table of Contents

- [Features](#features)
- [Pricing Plans](#pricing-plans)
- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Directory Structure](#directory-structure)
- [Components](#components)
- [Provisioning Flow](#provisioning-flow)
- [API Reference](#api-reference)
- [Data Models](#data-models)
- [Commands](#commands)
- [Development](#development)
- [Troubleshooting](#troubleshooting)

---

## Features

### Portal (Central)

- **Exclusive authentication via Microsoft Entra ID** (no local accounts)
  - Supports Microsoft accounts (work, school, personal)
  - Social identity providers: Google, Facebook, Apple, etc.
  - Enterprise SSO via federated identity
- Create new teams (provisions isolated environment)
- Join existing teams via invite
- Manage team memberships across all teams
- User profile and settings
- Team billing and quotas (optional)

### Team Instance (Isolated)

- Dedicated containers per team
- Separate TinyDB database per team
- Full Kanban functionality
- Markdown support with syntax highlighting
- Link previews (Twitter/X, GitHub, YouTube, generic OpenGraph)
- Real-time updates via WebSocket
- Accessible via `{team-slug}.devkanban.io`

### Board Management

- Create, edit, and archive Kanban boards
- Customizable columns (Backlog, To Do, In Progress, Review, Done)
- Drag-and-drop card movement
- WIP limits per column
- Board visibility: team-wide or specific members

### Card/Task Management

- Title, description, due dates
- Markdown support in descriptions and comments
- Link previews for external resources
- Assignees (from team members)
- Labels and tags
- Checklists and subtasks
- Comments and activity history
- File attachments

### Team Management

- Create a new team with name, description, and optional avatar
- Generate invite links or codes to join a team
- Request to join existing teams (with approval workflow)
- Leave a team
- Team roles: Owner, Admin, Member
- Transfer team ownership
- Delete team (owner only)

---

## Pricing Plans

### Free Plan

- Full access to all Kanban features
- Unlimited boards and cards
- Team collaboration
- Markdown support with link previews
- Real-time updates
- **Includes non-intrusive ad banners** to support the platform

### Paid Plan

- Everything in Free Plan
- **No advertisements** for a clean, distraction-free experience
- Priority support
- Advanced analytics and reporting
- Extended storage for attachments

---

## Architecture

### High-Level Overview

```
                              Internet
                                 │
                                 ▼
                    ┌────────────────────────┐
                    │   External DNS         │
                    │   NS → our server      │
                    └───────────┬────────────┘
                                │
                                ▼
┌───────────────────────────────────────────────────────────────────────┐
│                          Docker Host                                  │
│                                                                       │
│  ┌─────────────────────────────────────────────────────────────────┐  │
│  │                    CoreDNS (Built-in DNS)                       │  │
│  │                         :53 UDP/TCP                             │  │
│  │  Resolves: *.devkanban.io → Host IP                             │  │
│  └─────────────────────────────────────────────────────────────────┘  │
│                                                                       │
│  ┌─────────────────────────────────────────────────────────────────┐  │
│  │                    Traefik (Edge Router)                        │  │
│  │                        :80 / :443                               │  │
│  └──────────────────────────┬──────────────────────────────────────┘  │
│                             │                                         │
│  ┌──────────────────────────┴──────────────────────────────────────┐  │
│  │                         Certbot                                 │  │
│  │              (Per-subdomain Let's Encrypt certs)                │  │
│  └─────────────────────────────────────────────────────────────────┘  │
│                                                                       │
│         ┌───────────────────┼───────────────────┐                     │
│         │                   │                   │                     │
│         ▼                   ▼                   ▼                     │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐               │
│  │   Portal    │    │  Team: acme │    │ Team: globex│               │
│  │             │    │             │    │             │       ...     │
│  │ ┌─────────┐ │    │ ┌─────────┐ │    │ ┌─────────┐ │               │
│  │ │ TinyDB  │ │    │ │ TinyDB  │ │    │ │ TinyDB  │ │               │
│  │ │(portal) │ │    │ │ (acme)  │ │    │ │(globex) │ │               │
│  │ └─────────┘ │    │ └─────────┘ │    │ └─────────┘ │               │
│  └─────────────┘    └─────────────┘    └─────────────┘               │
│                                                                       │
└───────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
                  ┌──────────────────────────┐
                  │       Azure Cloud        │
                  │  ┌────────────────────┐  │
                  │  │    Key Vault       │  │
                  │  └────────────────────┘  │
                  │  ┌────────────────────┐  │
                  │  │    Entra ID        │  │
                  │  └────────────────────┘  │
                  └──────────────────────────┘
```

### Subdomain Routing

| Subdomain | Target | Purpose |
|-----------|--------|---------|
| `app.devkanban.io` | Portal | Central user/team management |
| `api.devkanban.io` | Portal API | Auth, team provisioning |
| `{slug}.devkanban.io` | Team instance | Isolated Kanban for team |

### Container Layout

#### Per Team Instance

```
Team: acme
├── Network: devkanban-acme
├── Volumes:
│   └── ./teams/acme/data/
│       ├── db/team.json    (TinyDB database)
│       ├── uploads/        (attachments)
│       └── cache/          (link previews)
└── Containers:
    ├── devkanban-acme-nginx    (team gateway)
    ├── devkanban-acme-api      (FastAPI)
    ├── devkanban-acme-frontend (static files)
    └── devkanban-acme-worker   (background jobs)
```

#### Global Infrastructure

```
Global
├── Network: devkanban-global
├── Volumes:
│   └── portal_data
└── Containers:
    ├── devkanban-dns           (CoreDNS)
    ├── devkanban-traefik       (edge router)
    ├── devkanban-certbot       (certificate manager)
    ├── devkanban-portal-api    (central API)
    ├── devkanban-portal-web    (portal frontend)
    └── devkanban-orchestrator  (provisions teams)
```

---

## Prerequisites

- Docker Engine 24.0+
- Docker Compose v2.20+
- A domain with configurable NS records
- Azure subscription (for Key Vault and Entra ID)
- Public IP address for your server

### External DNS Setup (Domain Registrar)

Configure your domain registrar with these records:

```
devkanban.io.       NS      ns1.devkanban.io.
devkanban.io.       NS      ns2.devkanban.io.
ns1.devkanban.io.   A       <your-server-ip>
ns2.devkanban.io.   A       <your-server-ip>
devkanban.io.       A       <your-server-ip>
```

---

## Quick Start

### 1. Clone the Repository

```bash
git clone https://github.com/yourorg/devkanban.git
cd devkanban
```

### 2. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` with your settings:

```bash
DOMAIN=devkanban.io
HOST_IP=203.0.113.50
CERTBOT_EMAIL=admin@devkanban.io

AZURE_KEY_VAULT_URL=https://devkanban-kv.vault.azure.net/
AZURE_CLIENT_ID=your-service-principal-id
AZURE_CLIENT_SECRET=your-service-principal-secret
AZURE_TENANT_ID=your-tenant-id
```

### 3. Initialize DNS Zone File

```bash
# Replace HOST_IP in the zone file
sed -i "s/\${HOST_IP}/$HOST_IP/g" coredns/zones/devkanban.io.db
```

### 4. Start Infrastructure

```bash
# Start with default port (3001)
docker compose up -d

# Or specify a custom port
PORT=8080 docker compose up -d
```

**Using the start script:**

```bash
./start.sh              # Uses default port 3001
./start.sh 8080         # Uses port 8080
./start.sh --port 9000  # Uses port 9000
```

<details>
<summary>start.sh script</summary>

```bash
#!/bin/bash
# start.sh - Start the Kanban platform

set -e

# Default port
PORT=3001

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --port|-p)
            PORT="$2"
            shift 2
            ;;
        [0-9]*)
            PORT="$1"
            shift
            ;;
        *)
            echo "Usage: ./start.sh [PORT] or ./start.sh --port PORT"
            echo "  Default port: 3001"
            exit 1
            ;;
    esac
done

echo "Starting Kanban on port $PORT..."
export PORT=$PORT

# Start containers
docker compose up -d

echo ""
echo "✓ Kanban is running!"
echo ""
echo "  Portal:  https://localhost:$PORT"
echo "  API:     https://localhost:$PORT/api"
echo ""
```
</details>

### 5. Issue Initial Certificates

```bash
# Wait for DNS to propagate, then issue portal certificates
docker exec devkanban-certbot certbot certonly \
  --webroot -w /var/www/certbot \
  -d app.devkanban.io -d api.devkanban.io \
  --email admin@devkanban.io --agree-tos --non-interactive
```

### 6. Restart Traefik to Load Certificates

```bash
docker compose restart traefik
```

### 7. Access the Portal

Open `https://app.devkanban.io` in your browser.

---

## Configuration

### Environment Variables

| Variable | Description | Default | Example |
|----------|-------------|---------|---------|
| `PORT` | Port to run the platform on | `3001` | `8080` |
| `CERT_MODE` | Certificate mode | `development` | `production` |
| `DOMAIN` | Base domain for the platform | `localhost` | `kanban.io` |
| `HOST_IP` | Public IP of the server | - | `203.0.113.50` |
| `CERTBOT_EMAIL` | Email for Let's Encrypt | - | `admin@kanban.io` |
| `AZURE_KEY_VAULT_URL` | Azure Key Vault URL | - | `https://kv.vault.azure.net/` |
| `AZURE_CLIENT_ID` | Service Principal client ID | - | `xxxxxxxx-xxxx-...` |
| `AZURE_CLIENT_SECRET` | Service Principal secret | - | `your-secret` |
| `AZURE_TENANT_ID` | Azure tenant ID | - | `xxxxxxxx-xxxx-...` |

### Azure Key Vault Secrets

| Secret Name | Scope | Description |
|-------------|-------|-------------|
| `entra-client-id` | Portal | Entra ID app client ID |
| `entra-client-secret` | Portal | Entra ID app client secret |
| `entra-tenant-id` | Portal | Entra ID tenant ID |
| `portal-secret-key` | Portal | JWT signing key |
| `cross-domain-secret` | Global | Signs cross-domain tokens |
| `twitter-bearer-token` | Teams | Twitter API |
| `github-access-token` | Teams | GitHub API |
| `youtube-api-key` | Teams | YouTube API |

---

## Directory Structure

```
devkanban/
├── docker-compose.yml              # Global infrastructure
├── .env                            # Environment configuration
├── .env.example                    # Environment template
│
├── coredns/
│   ├── Corefile                    # CoreDNS configuration
│   └── zones/
│       └── devkanban.io.db         # Dynamic zone file
│
├── traefik/
│   ├── traefik.yml                 # Traefik configuration
│   ├── dynamic/
│   │   ├── middlewares.yml         # HTTP middlewares
│   │   └── tls.yml                 # TLS certificates config
│   └── certs/                      # Let's Encrypt certificates
│       ├── live/
│       │   ├── app.devkanban.io/
│       │   ├── api.devkanban.io/
│       │   └── {team}.devkanban.io/
│       └── ...
│
├── certbot/
│   ├── Dockerfile
│   ├── scripts/
│   │   ├── issue-cert.sh           # Issue new certificate
│   │   └── renew-certs.sh          # Renew all certificates
│   └── webroot/                    # HTTP-01 challenge files
│
├── portal/
│   ├── frontend/
│   │   ├── Dockerfile
│   │   ├── package.json
│   │   └── src/
│   │       ├── components/
│   │       ├── pages/
│   │       ├── services/
│   │       └── App.jsx
│   └── backend/
│       ├── Dockerfile
│       ├── requirements.txt
│       └── app/
│           ├── main.py
│           ├── config.py
│           ├── auth/
│           │   └── entra.py
│           ├── models/
│           │   ├── user.py
│           │   └── team.py
│           ├── routes/
│           │   ├── auth.py
│           │   ├── users.py
│           │   └── teams.py
│           ├── services/
│           │   ├── team_provisioner.py
│           │   ├── dns_manager.py
│           │   └── cert_manager.py
│           └── db/
│               └── portal.json
│
├── orchestrator/
│   ├── Dockerfile
│   └── app/
│       ├── main.py
│       ├── provisioner.py
│       ├── dns_manager.py
│       ├── cert_manager.py
│       └── templates/
│           └── docker-compose.team.yml.j2
│
├── kanban-team/                      # Git submodule
│   ├── docker-compose.yml.j2       # Jinja2 template
│   ├── nginx/
│   │   └── nginx.conf
│   ├── frontend/
│   │   ├── Dockerfile
│   │   └── src/
│   │       ├── components/
│   │       │   ├── Board.jsx
│   │       │   ├── Card.jsx
│   │       │   ├── MarkdownRenderer.jsx
│   │       │   ├── LinkPreview.jsx
│   │       │   ├── TwitterPreview.jsx
│   │       │   ├── GitHubPreview.jsx
│   │       │   └── YouTubePreview.jsx
│   │       └── ...
│   └── backend/
│       ├── Dockerfile
│       ├── requirements.txt
│       └── app/
│           ├── main.py
│           ├── config.py
│           ├── models/
│           │   ├── board.py
│           │   ├── card.py
│           │   ├── comment.py
│           │   ├── attachment.py
│           │   └── link_preview.py
│           ├── routes/
│           │   ├── auth.py
│           │   ├── boards.py
│           │   ├── cards.py
│           │   └── previews.py
│           ├── services/
│           │   ├── markdown_service.py
│           │   └── preview_service.py
│           ├── providers/
│           │   ├── base.py
│           │   ├── twitter.py
│           │   ├── github.py
│           │   ├── youtube.py
│           │   └── opengraph.py
│           └── db/
│               └── team.json
│
└── teams/                          # Generated per team
    ├── acme/
    │   ├── docker-compose.yml
    │   ├── nginx/
    │   │   └── nginx.conf
    │   └── data/
    │       ├── db/
    │       │   └── team.json       # Isolated TinyDB
    │       ├── uploads/
    │       └── cache/
    ├── globex/
    │   └── ...
    └── ...
```

---

## Components

### CoreDNS

Built-in DNS server that handles all `*.devkanban.io` resolution dynamically.

**Corefile:**

```
devkanban.io:53 {
    file /etc/coredns/zones/devkanban.io.db
    log
    errors
    reload 10s
}

.:53 {
    forward . 8.8.8.8 1.1.1.1
    log
    errors
    cache 30
}
```

**Zone File Example:**

```
$ORIGIN devkanban.io.
$TTL 300

@       IN  SOA     ns1.devkanban.io. admin.devkanban.io. (
                    2024010101  ; Serial
                    3600        ; Refresh
                    600         ; Retry
                    86400       ; Expire
                    300         ; Minimum TTL
                    )

@       IN  NS      ns1.devkanban.io.
@       IN  NS      ns2.devkanban.io.

ns1     IN  A       203.0.113.50
ns2     IN  A       203.0.113.50

@       IN  A       203.0.113.50
app     IN  A       203.0.113.50
api     IN  A       203.0.113.50

; Team subdomains (auto-generated)
acme    IN  A       203.0.113.50
globex  IN  A       203.0.113.50
```

### Traefik

Edge router that handles:
- HTTP to HTTPS redirection
- TLS termination with per-subdomain certificates
- Routing to portal and team instances
- Security headers

### Certbot / Certificate Manager

Manages SSL certificates with support for both development and production environments.

#### Certificate Modes

| Mode | Use Case | Certificate Type |
|------|----------|------------------|
| **Development** | Local development, testing | Self-signed certificates |
| **Staging** | Pre-production testing | Let's Encrypt Staging |
| **Production** | Live deployment | Let's Encrypt Production |

#### Development Mode (Self-Signed)

For local development, self-signed certificates are auto-generated:

```bash
# Start in development mode
CERT_MODE=development docker compose up -d
```

```yaml
# docker-compose.override.yml (development)
services:
  certbot:
    environment:
      - CERT_MODE=development
    command: /scripts/generate-self-signed.sh
```

Self-signed certificate generation:

```bash
#!/bin/bash
# scripts/generate-self-signed.sh

DOMAIN=${1:-"localhost"}
CERT_DIR="/etc/letsencrypt/live/${DOMAIN}"

mkdir -p "$CERT_DIR"

openssl req -x509 -nodes -days 365 \
  -newkey rsa:2048 \
  -keyout "$CERT_DIR/privkey.pem" \
  -out "$CERT_DIR/fullchain.pem" \
  -subj "/CN=${DOMAIN}" \
  -addext "subjectAltName=DNS:${DOMAIN},DNS:*.${DOMAIN}"

echo "Self-signed certificate generated for ${DOMAIN}"
```

#### Production Mode (Let's Encrypt)

For production, real certificates are issued via Let's Encrypt:

```bash
# Start in production mode
CERT_MODE=production docker compose up -d
```

```yaml
# docker-compose.yml (production)
services:
  certbot:
    environment:
      - CERT_MODE=production
      - CERTBOT_EMAIL=${CERTBOT_EMAIL}
    volumes:
      - ./traefik/certs:/etc/letsencrypt
      - ./certbot/webroot:/var/www/certbot
```

Features:
- Per-subdomain certificates (no wildcards)
- HTTP-01 challenge via webroot
- Automatic renewal via cron

#### Environment Configuration

```bash
# .env
CERT_MODE=development      # development | staging | production

# Development settings
DEV_DOMAIN=localhost
DEV_CERT_VALIDITY_DAYS=365

# Production settings
DOMAIN=kanban.io
CERTBOT_EMAIL=admin@kanban.io
LETSENCRYPT_SERVER=https://acme-v02.api.letsencrypt.org/directory

# Staging settings (for testing Let's Encrypt without rate limits)
LETSENCRYPT_STAGING_SERVER=https://acme-staging-v02.api.letsencrypt.org/directory
```

#### Certificate Issuance Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Certificate Mode Decision Flow                            │
└─────────────────────────────────────────────────────────────────────────────┘

                           CERT_MODE?
                               │
           ┌───────────────────┼───────────────────┐
           │                   │                   │
           ▼                   ▼                   ▼
      development          staging            production
           │                   │                   │
           ▼                   ▼                   ▼
    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
    │ Self-Signed │    │ LE Staging  │    │ LE Prod     │
    │ Certificate │    │ Certificate │    │ Certificate │
    └─────────────┘    └─────────────┘    └─────────────┘
           │                   │                   │
           ▼                   ▼                   ▼
    Instant (local)    Test rate limits    Real certificate
    Browser warning    Browser warning     Trusted by all
```

#### Team Certificate Strategy

| Environment | New Team Certificate |
|-------------|---------------------|
| Development | Generate self-signed immediately |
| Staging | Request from LE Staging |
| Production | Request from LE Production (with DNS check) |

```python
# cert_manager.py
async def issue_certificate(team_slug: str) -> Certificate:
    domain = f"{team_slug}.{DOMAIN}"

    if CERT_MODE == "development":
        return await generate_self_signed(domain)

    elif CERT_MODE == "staging":
        return await request_letsencrypt(
            domain,
            server=LETSENCRYPT_STAGING_SERVER
        )

    else:  # production
        # Wait for DNS propagation first
        await wait_for_dns(domain)
        return await request_letsencrypt(
            domain,
            server=LETSENCRYPT_SERVER
        )
```

#### Local Development with HTTPS

For local development with self-signed certificates:

```bash
# 1. Add to /etc/hosts
127.0.0.1 app.kanban.local
127.0.0.1 api.kanban.local
127.0.0.1 acme.kanban.local

# 2. Start with development mode
CERT_MODE=development DOMAIN=kanban.local docker compose up -d

# 3. Trust the root CA (optional, removes browser warning)
# macOS:
sudo security add-trusted-cert -d -r trustRoot \
  -k /Library/Keychains/System.keychain \
  ./traefik/certs/ca.pem

# 4. Access https://app.kanban.local
```

### Portal

Central hub for:
- User authentication via Entra ID (exclusive method)
- Team creation and management
- Cross-domain SSO token generation

### Authentication (Microsoft Entra ID)

**No local accounts** - All authentication flows through Microsoft Entra ID External Identities.

#### Supported Identity Providers

| Provider | Type | Configuration |
|----------|------|---------------|
| Microsoft | Built-in | Work, school, and personal accounts |
| Google | Social | OAuth 2.0 via Entra External Identities |
| Facebook | Social | OAuth 2.0 via Entra External Identities |
| Apple | Social | Sign in with Apple via Entra |
| Enterprise | Federated | SAML/OIDC for corporate SSO |

#### Authentication Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Authentication Flow                                  │
└─────────────────────────────────────────────────────────────────────────────┘

  User                    Portal                Entra ID              Provider
   │                        │                      │                      │
   │  Click "Sign In"       │                      │                      │
   ├───────────────────────►│                      │                      │
   │                        │  Redirect to Entra   │                      │
   │◄───────────────────────┤                      │                      │
   │                        │                      │                      │
   │  ─────────────────────────────────────────────►                      │
   │                        │   Show login options │                      │
   │                        │   ┌────────────────┐ │                      │
   │                        │   │ Sign in with:  │ │                      │
   │                        │   │ ○ Microsoft    │ │                      │
   │                        │   │ ○ Google       │ │                      │
   │                        │   │ ○ Facebook     │ │                      │
   │                        │   │ ○ Apple        │ │                      │
   │                        │   └────────────────┘ │                      │
   │                        │                      │                      │
   │  Select Google         │                      │                      │
   │  ─────────────────────────────────────────────►                      │
   │                        │                      │  Redirect to Google  │
   │  ◄─────────────────────────────────────────────────────────────────────
   │                        │                      │                      │
   │  Authenticate with Google account             │                      │
   │  ─────────────────────────────────────────────────────────────────────►
   │                        │                      │                      │
   │  ◄─────────────────────────────────────────────────────────────────────
   │                        │                      │  Return to Entra     │
   │  ─────────────────────────────────────────────►                      │
   │                        │                      │                      │
   │                        │  ID Token + Claims   │                      │
   │  ◄────────────────────────────────────────────┤                      │
   │                        │                      │                      │
   │  Redirect to Portal    │                      │                      │
   │  ──────────────────────►                      │                      │
   │                        │  Validate token      │                      │
   │                        │  Create/update user  │                      │
   │                        │  Issue session JWT   │                      │
   │  Session established   │                      │                      │
   │◄───────────────────────┤                      │                      │
```

#### User Identity Mapping

Users from different providers are unified under a single profile:

```json
{
  "id": "uuid",
  "entra_oid": "entra-object-id",
  "email": "user@example.com",
  "display_name": "John Doe",
  "avatar_url": "https://...",
  "identity_provider": "google.com",
  "linked_identities": [
    {"provider": "google.com", "sub": "google-user-id"},
    {"provider": "microsoft.com", "sub": "ms-user-id"}
  ],
  "created_at": "2024-01-01T00:00:00Z"
}
```

#### Entra ID Configuration

Required Azure setup:

1. **App Registration** in Entra ID
2. **External Identities** configuration for social providers
3. **API Permissions**: `openid`, `profile`, `email`
4. **Token Configuration**: Include `oid`, `email`, `name` claims

```
Azure Portal → Entra ID → External Identities → All identity providers
├── Google (OAuth 2.0)
├── Facebook (OAuth 2.0)
├── Apple (Sign in with Apple)
└── SAML/OIDC (Enterprise federation)
```

#### Cross-Domain SSO

When users access team instances, a secure token exchange occurs:

```
Portal (app.kanban.io) ──► Team Instance (acme.kanban.io)

1. Portal generates one-time token signed with cross-domain secret
2. User redirected to team instance with token
3. Team instance validates token with Portal API
4. Team instance creates local session
```

### Orchestrator

Provisions and manages team instances:
- Creates team directories and configs
- Manages DNS records
- Issues SSL certificates
- Starts/stops team containers

### Team Instance

Isolated environment per team:
- Dedicated containers (nginx, api, frontend, worker)
- Separate TinyDB database
- Independent data volumes

### Data Isolation

Each team's data is stored in a dedicated folder, ensuring complete isolation.

#### Folder Structure

```
/data/teams/
├── acme/
│   ├── db/
│   │   └── team.json          # TinyDB database
│   ├── uploads/
│   │   ├── cards/             # Card attachments
│   │   │   └── {card-id}/
│   │   │       └── {file-uuid}.{ext}
│   │   └── avatars/           # User/team avatars
│   ├── cache/
│   │   └── previews/          # Link preview cache
│   │       └── {url-hash}.json
│   ├── backups/
│   │   └── 2024-01-15_100000.json.gz
│   └── logs/
│       ├── api.log
│       └── worker.log
│
├── globex/
│   ├── db/
│   ├── uploads/
│   ├── cache/
│   ├── backups/
│   └── logs/
│
└── marketing/
    └── ...
```

#### Data Ownership

| Data Type | Location | Retention | Backup |
|-----------|----------|-----------|--------|
| **Database** | `{team}/db/team.json` | Permanent | Daily |
| **Attachments** | `{team}/uploads/cards/` | Permanent | Daily |
| **Avatars** | `{team}/uploads/avatars/` | Permanent | Daily |
| **Link Previews** | `{team}/cache/previews/` | 7 days TTL | No |
| **Backups** | `{team}/backups/` | 30 days | N/A |
| **Logs** | `{team}/logs/` | 14 days | No |

#### Volume Mounting

```yaml
# Team docker-compose.yml
services:
  api:
    volumes:
      - /data/teams/${TEAM_SLUG}/db:/app/data/db
      - /data/teams/${TEAM_SLUG}/uploads:/app/data/uploads
      - /data/teams/${TEAM_SLUG}/cache:/app/data/cache
      - /data/teams/${TEAM_SLUG}/logs:/app/logs

  worker:
    volumes:
      - /data/teams/${TEAM_SLUG}/db:/app/data/db
      - /data/teams/${TEAM_SLUG}/uploads:/app/data/uploads
      - /data/teams/${TEAM_SLUG}/cache:/app/data/cache
      - /data/teams/${TEAM_SLUG}/backups:/app/data/backups
```

#### Data Isolation Guarantees

| Guarantee | Implementation |
|-----------|----------------|
| **Network Isolation** | Each team runs in its own Docker network |
| **Storage Isolation** | Separate volume mounts per team |
| **Process Isolation** | Dedicated containers per team |
| **Database Isolation** | Individual TinyDB file per team |
| **No Cross-Team Access** | Containers cannot access other team folders |

#### Backup Strategy

```json
{
  "team_slug": "acme",
  "backup_config": {
    "enabled": true,
    "schedule": "0 2 * * *",
    "retention_days": 30,
    "include": ["db", "uploads"],
    "exclude": ["cache", "logs"],
    "compression": "gzip",
    "storage": {
      "local": "/data/teams/acme/backups/",
      "remote": "s3://kanban-backups/teams/acme/"
    }
  }
}
```

#### Team Deletion

When a team is deleted, data handling follows this policy:

```
1. Mark team as "pending_deletion"
2. Create final backup (retained 90 days)
3. Stop all team containers
4. Remove DNS record
5. Revoke SSL certificate
6. Archive data folder → /data/archived/{team_slug}/
7. After 30 days: permanently delete archived data
```

---

## Provisioning Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                     Team Creation Flow                              │
└─────────────────────────────────────────────────────────────────────┘

User clicks "Create Team" in Portal
              │
              ▼
┌──────────────────────────┐
│  1. Validate team slug   │
│     (unique, valid chars)│
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│  2. Create team record   │
│     status: provisioning │
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│  3. Create team directory│
│     and docker-compose   │
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│  4. Initialize TinyDB    │
│     database             │
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│  5. Add DNS record       │
│     to zone file         │
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│  6. Wait for DNS         │
│     propagation          │
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│  7. Issue Let's Encrypt  │
│     certificate          │
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│  8. Update Traefik       │
│     TLS config           │
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│  9. Start team           │
│     containers           │
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│  10. Health check        │
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│  11. Update status:      │
│      active              │
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│  12. Redirect user to    │
│      {slug}.devkanban.io │
└──────────────────────────┘
```

### Provisioning Summary

| Step | Component | Action |
|------|-----------|--------|
| 1 | Portal | User creates team, validates slug |
| 2 | Portal | Creates team record (status: provisioning) |
| 3 | Orchestrator | Creates team directory and files |
| 4 | Orchestrator | Initializes empty TinyDB database |
| 5 | DNS Manager | Adds A record to zone file |
| 6 | CoreDNS | Reloads zone (10s interval) |
| 7 | Cert Manager | Waits for DNS, issues Let's Encrypt cert |
| 8 | Orchestrator | Updates Traefik TLS config |
| 9 | Orchestrator | Starts team containers |
| 10 | Orchestrator | Health check |
| 11 | Portal | Updates team status to active |

---

## API Reference

### Portal API (`api.devkanban.io`)

#### Authentication

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/auth/login` | Initiate Entra ID login |
| `GET` | `/auth/callback` | OAuth callback |
| `POST` | `/auth/logout` | Logout user |
| `GET` | `/auth/me` | Get current user |
| `POST` | `/auth/exchange` | Exchange one-time token for JWT |

#### Users

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/users/me` | Get profile |
| `PUT` | `/users/me` | Update profile |
| `GET` | `/users/me/teams` | List user's teams |

#### Teams

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/teams` | Create team (triggers provisioning) |
| `GET` | `/teams` | List user's teams |
| `GET` | `/teams/{slug}` | Get team details |
| `PUT` | `/teams/{slug}` | Update team |
| `DELETE` | `/teams/{slug}` | Delete team (deprovision) |
| `GET` | `/teams/{slug}/status` | Provisioning status |

#### Memberships

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/teams/{slug}/members` | List members |
| `POST` | `/teams/{slug}/members` | Add member |
| `PUT` | `/teams/{slug}/members/{id}` | Update role |
| `DELETE` | `/teams/{slug}/members/{id}` | Remove member |

#### Invites

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/teams/{slug}/invites` | Create invite |
| `GET` | `/teams/{slug}/invites` | List invites |
| `DELETE` | `/teams/{slug}/invites/{id}` | Revoke invite |
| `POST` | `/invites/{code}/accept` | Accept invite |

#### Portal API Tokens

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/tokens` | Create Portal API token |
| `GET` | `/api/tokens` | List your tokens |
| `DELETE` | `/api/tokens/{id}` | Delete token |

#### Programmatic Team Management (requires Portal API Token)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/teams` | List all teams |
| `POST` | `/api/teams` | Create team |
| `GET` | `/api/teams/{slug}` | Get team details |
| `DELETE` | `/api/teams/{slug}` | Delete team |
| `GET` | `/api/teams/{slug}/members` | List team members |
| `POST` | `/api/teams/{slug}/members` | Add team member |
| `DELETE` | `/api/teams/{slug}/members/{id}` | Remove team member |

**Available Scopes:**
- `teams:read` - List and view teams
- `teams:write` - Create and delete teams
- `members:read` - List team members
- `members:write` - Add/remove team members
- `boards:read` - List team boards
- `boards:write` - Create team boards

**Example Usage:**
```bash
# Create a Portal API token via the UI at Settings
# Token format: pk_xxxx...

# List all teams
curl -H "Authorization: Bearer pk_your_token" https://api.kanban.example.com/api/teams

# Create a team
curl -X POST https://api.kanban.example.com/api/teams \
  -H "Authorization: Bearer pk_your_token" \
  -H "Content-Type: application/json" \
  -d '{"name": "My Team", "slug": "my-team"}&owner_id=user-uuid'

# Add a member
curl -X POST https://api.kanban.example.com/api/teams/my-team/members \
  -H "Authorization: Bearer pk_your_token" \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "role": "member"}'
```

### Team Instance API (`{slug}.devkanban.io/api`)

#### Authentication

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/auth/verify` | Verify session with Portal |
| `GET` | `/auth/callback` | Receive cross-domain token |

#### Boards

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/boards` | Create board |
| `GET` | `/boards` | List boards |
| `GET` | `/boards/{id}` | Get board with cards |
| `PUT` | `/boards/{id}` | Update board |
| `DELETE` | `/boards/{id}` | Delete board |

#### Cards

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/boards/{id}/cards` | Create card |
| `GET` | `/cards/{id}` | Get card with previews |
| `PUT` | `/cards/{id}` | Update card |
| `PUT` | `/cards/{id}/move` | Move card |
| `DELETE` | `/cards/{id}` | Delete card |

#### Comments

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/cards/{id}/comments` | Add comment |
| `PUT` | `/comments/{id}` | Edit comment |
| `DELETE` | `/comments/{id}` | Delete comment |

#### Attachments

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/cards/{id}/attachments` | Upload file |
| `GET` | `/attachments/{id}` | Download file |
| `DELETE` | `/attachments/{id}` | Delete file |

#### Previews

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/previews?url={url}` | Get link preview |

#### WebSocket

| Protocol | Endpoint | Description |
|----------|----------|-------------|
| `WS` | `/ws/boards/{id}` | Real-time updates |

---

## Data Models

### Portal Database

#### User

```json
{
  "id": "entra-user-id",
  "email": "user@example.com",
  "display_name": "John Doe",
  "avatar_url": "https://...",
  "created_at": "2024-01-01T00:00:00Z",
  "last_login_at": "2024-01-15T12:00:00Z"
}
```

#### Team

```json
{
  "id": "uuid",
  "slug": "acme",
  "name": "Acme Corp",
  "description": "Acme development team",
  "avatar_url": "https://...",
  "owner_id": "user-id",
  "status": "active",
  "subdomain": "https://acme.devkanban.io",
  "created_at": "2024-01-01T00:00:00Z",
  "provisioned_at": "2024-01-01T00:01:00Z",
  "config": {}
}
```

#### TeamMembership

```json
{
  "team_id": "team-uuid",
  "user_id": "user-id",
  "role": "admin",
  "joined_at": "2024-01-01T00:00:00Z",
  "invited_by": "owner-user-id"
}
```

### Team Instance Database

#### Board

```json
{
  "id": "uuid",
  "name": "Sprint 1",
  "description": "Current sprint board",
  "columns": [
    {"id": "col-1", "name": "Backlog", "position": 0, "wip_limit": null},
    {"id": "col-2", "name": "In Progress", "position": 1, "wip_limit": 3},
    {"id": "col-3", "name": "Done", "position": 2, "wip_limit": null}
  ],
  "created_by": "user-id",
  "created_at": "2024-01-01T00:00:00Z"
}
```

#### Card

```json
{
  "id": "uuid",
  "board_id": "board-uuid",
  "column_id": "col-2",
  "position": 0,
  "title": "Implement OAuth flow",
  "description_md": "Check out https://github.com/authlib/authlib",
  "description_html": "<p>Check out <a href=\"...\">...</a></p>",
  "extracted_links": ["https://github.com/authlib/authlib"],
  "assignees": ["user-1", "user-2"],
  "labels": ["backend", "auth"],
  "due_date": "2024-02-15T00:00:00Z",
  "created_by": "user-id",
  "created_at": "2024-01-01T00:00:00Z",
  "updated_at": "2024-01-10T00:00:00Z"
}
```

#### LinkPreview

```json
{
  "id": "uuid",
  "url": "https://github.com/authlib/authlib",
  "provider": "github",
  "title": "authlib/authlib",
  "description": "The ultimate Python library for OAuth",
  "image_url": "https://opengraph.githubassets.com/...",
  "author_name": null,
  "author_avatar": null,
  "metadata": {
    "type": "repo",
    "stars_count": 4200,
    "forks_count": 380,
    "language": "Python"
  },
  "fetched_at": "2024-01-01T00:00:00Z",
  "expires_at": "2024-01-02T00:00:00Z"
}
```

---

## Commands

### Infrastructure Management

```bash
# Start all global services
docker compose up -d

# View logs
docker compose logs -f

# Stop everything
docker compose down

# Restart specific service
docker compose restart traefik
```

### Certificate Management

```bash
# Issue initial portal certificates
docker exec devkanban-certbot certbot certonly \
  --webroot -w /var/www/certbot \
  -d app.devkanban.io -d api.devkanban.io \
  --email admin@devkanban.io --agree-tos --non-interactive

# Renew all certificates
docker exec devkanban-certbot certbot renew

# List certificates
docker exec devkanban-certbot certbot certificates

# Manually issue certificate for a team
docker exec devkanban-certbot /scripts/issue-cert.sh acme.devkanban.io
```

### DNS Management

```bash
# View current zone file
cat coredns/zones/devkanban.io.db

# Check DNS resolution
dig @localhost acme.devkanban.io

# Force CoreDNS reload
docker exec devkanban-dns kill -SIGUSR1 1
```

### Team Management

```bash
# View all team containers
docker ps --filter "name=devkanban-*-api"

# View specific team logs
docker compose -f teams/acme/docker-compose.yml logs -f

# Restart team
docker compose -f teams/acme/docker-compose.yml restart

# Stop team
docker compose -f teams/acme/docker-compose.yml down

# Remove team completely (with data)
docker compose -f teams/acme/docker-compose.yml down -v
rm -rf teams/acme

# Manually provision a team (for testing)
docker exec devkanban-orchestrator python -m app.cli provision \
  --slug=testteam --name="Test Team" --owner-id=user-123
```

### Debugging

```bash
# Access portal API shell
docker exec -it devkanban-portal-api bash

# Access team API shell
docker exec -it devkanban-acme-api bash

# Check Traefik dashboard
open http://localhost:8080

# Test team health endpoint
curl https://acme.devkanban.io/api/health
```

---

## Development

### Local Development Setup

1. Install dependencies:

```bash
# Portal backend
cd portal/backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Portal frontend
cd portal/frontend
npm install
```

2. Start with docker compose for dependencies:

```bash
docker compose up -d coredns traefik certbot
```

3. Run portal locally:

```bash
# Backend
cd portal/backend
uvicorn app.main:app --reload --port 8000

# Frontend
cd portal/frontend
npm run dev
```

### Building Images

```bash
# Build all images
docker compose build

# Build team template images
docker build -t devkanban/team-api:latest kanban-team/backend
docker build -t devkanban/team-frontend:latest kanban-team/frontend
```

### Running Tests

```bash
# Portal tests
cd portal/backend
pytest

# Team instance tests
cd kanban-team/backend
pytest
```

---

## Troubleshooting

### DNS Issues

**Problem:** Subdomain not resolving

```bash
# Check if CoreDNS is running
docker ps | grep coredns

# Check zone file syntax
docker exec devkanban-dns cat /etc/coredns/zones/devkanban.io.db

# Test resolution
dig @localhost acme.devkanban.io
```

### Certificate Issues

**Problem:** Certificate issuance fails

```bash
# Check DNS propagation first
host acme.devkanban.io

# Check certbot logs
docker logs devkanban-certbot

# Verify webroot is accessible
curl http://acme.devkanban.io/.well-known/acme-challenge/test
```

### Team Provisioning Issues

**Problem:** Team stuck in "provisioning" status

```bash
# Check orchestrator logs
docker logs devkanban-orchestrator

# Check if containers started
docker ps --filter "name=devkanban-{slug}-*"

# Check team compose logs
docker compose -f teams/{slug}/docker-compose.yml logs
```

### Container Networking

**Problem:** Team can't reach portal API

```bash
# Verify network connectivity
docker exec devkanban-acme-api ping devkanban-portal-api

# Check network membership
docker network inspect devkanban-global
```

---

## Asynchronous Task Processing

Long-running tasks are executed asynchronously with real-time user feedback via a message queue system.

### Architecture

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                        Async Task Processing Flow                            │
└──────────────────────────────────────────────────────────────────────────────┘

  User Action           API                Queue              Worker           User
      │                  │                   │                  │                │
      │  POST /teams     │                   │                  │                │
      ├─────────────────►│                   │                  │                │
      │                  │  Publish Task     │                  │                │
      │                  ├──────────────────►│                  │                │
      │  202 Accepted    │                   │                  │                │
      │  + task_id       │                   │                  │                │
      │◄─────────────────┤                   │                  │                │
      │                  │                   │  Consume Task    │                │
      │                  │                   ├─────────────────►│                │
      │                  │                   │                  │                │
      │  WS: Subscribe   │                   │                  │                │
      ├─────────────────►│                   │                  │                │
      │                  │                   │                  │  Step 1        │
      │                  │                   │◄─────────────────┤  Progress      │
      │                  │  Broadcast        │                  │                │
      │◄─────────────────┼───────────────────┤                  │                │
      │  "Creating dirs" │                   │                  │                │
      │                  │                   │                  │  Step 2        │
      │                  │                   │◄─────────────────┤  Progress      │
      │◄─────────────────┼───────────────────┤                  │                │
      │  "Issuing cert"  │                   │                  │                │
      │                  │                   │                  │                │
      │                  │                   │                  │  Complete      │
      │                  │                   │◄─────────────────┤                │
      │◄─────────────────┼───────────────────┤                  │                │
      │  "Team ready!"   │                   │                  │                │
      │                  │                   │                  │                │
```

### Message Queue (Redis)

All long-running tasks are published to Redis queues and processed by dedicated workers.

**Queue Structure:**

| Queue Name | Purpose | Priority |
|------------|---------|----------|
| `tasks:provisioning` | Team creation/deletion | High |
| `tasks:certificates` | SSL cert issuance/renewal | High |
| `tasks:dns` | DNS record updates | High |
| `tasks:previews` | Link preview fetching | Low |
| `tasks:notifications` | Email/push notifications | Medium |

### Task Schema

```json
{
  "task_id": "uuid",
  "type": "team.provision",
  "status": "pending|in_progress|completed|failed",
  "payload": {
    "team_slug": "acme",
    "owner_id": "user-123"
  },
  "progress": {
    "current_step": 3,
    "total_steps": 11,
    "step_name": "Issuing SSL certificate",
    "percentage": 27
  },
  "result": null,
  "error": null,
  "created_at": "2024-01-01T00:00:00Z",
  "started_at": "2024-01-01T00:00:01Z",
  "completed_at": null,
  "user_id": "user-123"
}
```

### Real-time Feedback (WebSocket)

Users receive live progress updates via WebSocket connections.

**WebSocket Endpoints:**

| Endpoint | Purpose |
|----------|---------|
| `/ws/tasks/{task_id}` | Subscribe to specific task updates |
| `/ws/user/tasks` | Subscribe to all user's task updates |

**WebSocket Message Types:**

```json
// Task Progress Update
{
  "type": "task.progress",
  "task_id": "uuid",
  "step": 3,
  "total_steps": 11,
  "step_name": "Issuing SSL certificate",
  "percentage": 27,
  "message": "Requesting certificate from Let's Encrypt..."
}

// Task Completed
{
  "type": "task.completed",
  "task_id": "uuid",
  "result": {
    "team_url": "https://acme.devkanban.io"
  },
  "message": "Team 'acme' is ready!"
}

// Task Failed
{
  "type": "task.failed",
  "task_id": "uuid",
  "error": "Certificate issuance failed: DNS not propagated",
  "retry_available": true
}
```

### Long-Running Tasks

| Task Type | Estimated Duration | Steps |
|-----------|-------------------|-------|
| `team.provision` | 30-90 seconds | 11 steps |
| `team.delete` | 10-30 seconds | 5 steps |
| `cert.issue` | 10-60 seconds | 4 steps |
| `cert.renew` | 5-30 seconds | 3 steps |
| `preview.fetch` | 1-5 seconds | 2 steps |
| `data.export` | Variable | 3 steps |
| `data.import` | Variable | 4 steps |

### Task API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/tasks` | List user's tasks |
| `GET` | `/tasks/{id}` | Get task details |
| `POST` | `/tasks/{id}/retry` | Retry failed task |
| `POST` | `/tasks/{id}/cancel` | Cancel pending task |

### Worker Implementation

Workers consume tasks from queues and publish progress updates:

```python
# Pseudo-code for task worker
class TaskWorker:
    async def process_task(self, task: Task):
        try:
            await self.update_status(task, "in_progress")

            for i, step in enumerate(task.steps):
                # Publish progress to user
                await self.publish_progress(task, {
                    "current_step": i + 1,
                    "total_steps": len(task.steps),
                    "step_name": step.name,
                    "message": step.description
                })

                # Execute step
                result = await step.execute()

            # Task completed
            await self.update_status(task, "completed", result=result)
            await self.publish_completed(task, result)

        except Exception as e:
            await self.update_status(task, "failed", error=str(e))
            await self.publish_failed(task, error=e)
```

### UI Feedback Components

The frontend displays task progress via:

1. **Toast Notifications** - Brief updates for quick tasks
2. **Progress Modal** - Detailed step-by-step for long tasks
3. **Task History Panel** - View past and ongoing tasks
4. **Status Badges** - Visual indicators on affected resources

```
┌─────────────────────────────────────────────────────────┐
│  Creating Team "acme"                              [X]  │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ✓ Validating team slug                                 │
│  ✓ Creating team record                                 │
│  ✓ Generating configuration                             │
│  ● Issuing SSL certificate...                           │
│  ○ Starting containers                                  │
│  ○ Running health checks                                │
│                                                         │
│  ████████████░░░░░░░░░░░░░░░░░░  45%                   │
│                                                         │
│  Requesting certificate from Let's Encrypt...           │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### Task Manager

A dedicated interface for users to monitor and manage all their background tasks.

#### Task Manager UI

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Task Manager                                           [Refresh] [Settings]│
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Filter: [All ▼]  [In Progress ▼]  [Last 24 hours ▼]      🔍 Search...     │
│                                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ● IN PROGRESS                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ 🔄 Creating Team "marketing"                          Started 2m ago │   │
│  │    Step 4/11: Issuing SSL certificate                                │   │
│  │    ████████████████░░░░░░░░░░░░░░  36%                              │   │
│  │                                                     [View] [Cancel]  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ✓ COMPLETED TODAY                                                          │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ ✓ Team "sales" created successfully                   Completed 1h ago│   │
│  │   Result: https://sales.kanban.io                      [View] [Hide] │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ ✓ SSL certificate renewed for "acme"                  Completed 3h ago│   │
│  │   Valid until: 2025-03-15                              [View] [Hide] │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ✗ FAILED                                                                   │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ ✗ Data export failed                                  Failed 5h ago  │   │
│  │   Error: Connection timeout to storage service                       │   │
│  │                                                    [Retry] [Details] │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### Task Manager Features

| Feature | Description |
|---------|-------------|
| **Real-time Updates** | Live progress via WebSocket, no manual refresh needed |
| **Filtering** | By status, type, date range, or search query |
| **Task Details** | Expandable view with step-by-step logs |
| **Retry Failed** | One-click retry for recoverable failures |
| **Cancel Pending** | Abort tasks before they complete |
| **Notifications** | Browser/email alerts on completion or failure |
| **Task History** | Searchable log of past tasks with retention policy |
| **Bulk Actions** | Cancel all pending, clear completed, retry all failed |

#### Task Manager Data Model

```json
{
  "id": "uuid",
  "user_id": "user-123",
  "type": "team.provision",
  "title": "Creating Team \"marketing\"",
  "status": "in_progress",
  "priority": "high",
  "payload": { ... },
  "progress": {
    "current_step": 4,
    "total_steps": 11,
    "step_name": "Issuing SSL certificate",
    "percentage": 36,
    "logs": [
      {"timestamp": "...", "level": "info", "message": "Validating team slug..."},
      {"timestamp": "...", "level": "info", "message": "Team slug 'marketing' is available"},
      {"timestamp": "...", "level": "info", "message": "Creating team record..."},
      {"timestamp": "...", "level": "info", "message": "Requesting SSL certificate..."}
    ]
  },
  "result": null,
  "error": null,
  "retries": 0,
  "max_retries": 3,
  "created_at": "2024-01-15T10:00:00Z",
  "started_at": "2024-01-15T10:00:01Z",
  "completed_at": null,
  "expires_at": "2024-01-22T10:00:00Z"
}
```

#### Task Manager API

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/tasks` | List tasks (paginated, filterable) |
| `GET` | `/tasks/{id}` | Get task with full logs |
| `GET` | `/tasks/{id}/logs` | Stream task logs |
| `POST` | `/tasks/{id}/retry` | Retry failed task |
| `POST` | `/tasks/{id}/cancel` | Cancel pending/in-progress task |
| `DELETE` | `/tasks/{id}` | Remove task from history |
| `DELETE` | `/tasks` | Bulk delete (with filters) |
| `GET` | `/tasks/stats` | Task statistics (counts by status) |

#### Query Parameters

```
GET /tasks?status=failed&type=team.provision&from=2024-01-01&limit=20&offset=0
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `status` | string | Filter by status: pending, in_progress, completed, failed |
| `type` | string | Filter by task type |
| `from` | datetime | Tasks created after this date |
| `to` | datetime | Tasks created before this date |
| `limit` | int | Page size (default: 20, max: 100) |
| `offset` | int | Pagination offset |
| `search` | string | Search in title and logs |

#### Notification Preferences

Users can configure how they receive task updates:

```json
{
  "user_id": "user-123",
  "task_notifications": {
    "in_app": true,
    "browser_push": true,
    "email": {
      "on_complete": false,
      "on_failure": true,
      "digest": "daily"
    },
    "notify_on_types": ["team.provision", "team.delete", "data.export"],
    "quiet_hours": {
      "enabled": true,
      "start": "22:00",
      "end": "08:00",
      "timezone": "America/New_York"
    }
  }
}
```

### Platform Updates & Rollouts

When the platform is updated, all team environments must be updated in a controlled, queued manner with full visibility.

#### Rollout Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Platform Rollout Flow                                 │
└─────────────────────────────────────────────────────────────────────────────┘

  Admin                  Portal API            Queue               Workers
    │                        │                   │                    │
    │  Trigger Rollout       │                   │                    │
    │  v2.3.0 → v2.4.0       │                   │                    │
    ├───────────────────────►│                   │                    │
    │                        │                   │                    │
    │                        │  Get all teams    │                    │
    │                        ├──────────────────►│                    │
    │                        │                   │                    │
    │                        │  Create rollout   │                    │
    │                        │  batch tasks      │                    │
    │                        ├──────────────────►│                    │
    │                        │                   │                    │
    │  Rollout ID            │                   │                    │
    │◄───────────────────────┤                   │                    │
    │                        │                   │                    │
    │                        │                   │  Worker 1: acme    │
    │                        │                   ├───────────────────►│
    │                        │                   │  Worker 2: globex  │
    │                        │                   ├───────────────────►│
    │                        │                   │  Worker 3: sales   │
    │                        │                   ├───────────────────►│
    │                        │                   │       ...          │
    │                        │                   │                    │
    │                        │  Progress updates │                    │
    │◄───────────────────────┼──────────────────┼────────────────────┤
    │                        │                   │                    │
    │  WS: 12/50 complete    │                   │                    │
    │  WS: 25/50 complete    │                   │                    │
    │  WS: 50/50 complete ✓  │                   │                    │
```

#### Rollout Strategies

| Strategy | Description | Use Case |
|----------|-------------|----------|
| **All at once** | Update all teams simultaneously | Minor updates, low risk |
| **Batched** | Update in batches of N teams | Medium risk, controlled |
| **Canary** | Update 5% first, wait, then rest | Major updates, high risk |
| **Blue-Green** | Spin up new, switch traffic, teardown old | Zero-downtime critical |
| **Manual** | Admin approves each batch | Maximum control |

#### Rollout Data Model

```json
{
  "id": "rollout-uuid",
  "type": "platform_update",
  "strategy": "batched",
  "config": {
    "batch_size": 10,
    "delay_between_batches_seconds": 60,
    "pause_on_failure": true,
    "max_failures": 3,
    "rollback_on_threshold": true
  },
  "source_version": "2.3.0",
  "target_version": "2.4.0",
  "status": "in_progress",
  "teams": {
    "total": 50,
    "pending": 25,
    "updating": 10,
    "completed": 13,
    "failed": 2,
    "skipped": 0
  },
  "started_by": "admin-user-id",
  "started_at": "2024-01-15T10:00:00Z",
  "estimated_completion": "2024-01-15T10:30:00Z",
  "completed_at": null
}
```

#### Team Update Task

```json
{
  "task_id": "uuid",
  "type": "team.update",
  "rollout_id": "rollout-uuid",
  "team_slug": "acme",
  "payload": {
    "source_version": "2.3.0",
    "target_version": "2.4.0",
    "update_components": ["api", "frontend", "worker"],
    "run_migrations": true
  },
  "status": "in_progress",
  "progress": {
    "current_step": 3,
    "total_steps": 6,
    "step_name": "Running database migrations",
    "logs": [
      {"timestamp": "...", "message": "Pulling new images..."},
      {"timestamp": "...", "message": "Stopping current containers..."},
      {"timestamp": "...", "message": "Running migrations..."}
    ]
  }
}
```

#### Update Steps Per Team

| Step | Action | Rollback Action |
|------|--------|-----------------|
| 1 | Pull new container images | - |
| 2 | Create database backup | - |
| 3 | Stop current containers | - |
| 4 | Run database migrations | Restore backup |
| 5 | Start new containers | Start old containers |
| 6 | Health check | Rollback if failed |

#### Rollout Admin Dashboard

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  🚀 Platform Rollout: v2.3.0 → v2.4.0                              [Pause]  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Strategy: Batched (10 per batch)          Started: 10:00 AM               │
│  Status: IN PROGRESS                        ETA: 10:30 AM                   │
│                                                                             │
│  Progress                                                                   │
│  ████████████████████░░░░░░░░░░░░░░░░░░░░  26/50 teams (52%)              │
│                                                                             │
│  ┌────────────────┐ ┌────────────────┐ ┌────────────────┐ ┌────────────────┐│
│  │  Completed     │ │  In Progress   │ │  Pending       │ │  Failed        ││
│  │      23        │ │      3         │ │      22        │ │      2         ││
│  └────────────────┘ └────────────────┘ └────────────────┘ └────────────────┘│
│                                                                             │
│  Current Batch (3/3)                                                        │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ Team         │ Status       │ Step              │ Duration │ Action │   │
│  ├──────────────┼──────────────┼───────────────────┼──────────┼────────┤   │
│  │ marketing    │ 🔄 Updating  │ 4/6 Migrations    │ 45s      │ [View] │   │
│  │ engineering  │ 🔄 Updating  │ 5/6 Starting      │ 52s      │ [View] │   │
│  │ sales        │ 🔄 Updating  │ 3/6 Stopping      │ 30s      │ [View] │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  Failed Teams                                                    [Retry All]│
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ Team         │ Failed At    │ Error                      │ Action  │   │
│  ├──────────────┼──────────────┼────────────────────────────┼─────────┤   │
│  │ legacy-corp  │ Migrations   │ Migration 023 failed       │ [Retry] │   │
│  │ test-team    │ Health check │ API not responding         │ [Retry] │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  Actions: [Pause Rollout] [Skip Failed] [Rollback All] [Cancel]            │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### Rollout API

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/admin/rollouts` | Start new rollout |
| `GET` | `/admin/rollouts` | List rollouts |
| `GET` | `/admin/rollouts/{id}` | Get rollout status |
| `POST` | `/admin/rollouts/{id}/pause` | Pause rollout |
| `POST` | `/admin/rollouts/{id}/resume` | Resume rollout |
| `POST` | `/admin/rollouts/{id}/cancel` | Cancel rollout |
| `POST` | `/admin/rollouts/{id}/rollback` | Rollback all updated teams |
| `POST` | `/admin/rollouts/{id}/teams/{slug}/retry` | Retry failed team |
| `POST` | `/admin/rollouts/{id}/teams/{slug}/skip` | Skip team |
| `WS` | `/ws/admin/rollouts/{id}` | Real-time rollout updates |

#### Rollout Notifications

Admins receive notifications at key points:

```json
{
  "type": "rollout.batch_completed",
  "rollout_id": "uuid",
  "batch": 3,
  "total_batches": 5,
  "completed": 30,
  "failed": 1,
  "message": "Batch 3 completed with 1 failure"
}
```

| Event | Notification |
|-------|--------------|
| `rollout.started` | "Rollout v2.4.0 started for 50 teams" |
| `rollout.batch_completed` | "Batch 3/5 completed" |
| `rollout.team_failed` | "Team 'legacy-corp' failed: Migration error" |
| `rollout.paused` | "Rollout paused after 3 failures" |
| `rollout.completed` | "Rollout completed: 48 success, 2 failed" |
| `rollout.rolled_back` | "Rollout rolled back to v2.3.0" |

### Container Updates

The worker container handles async processing:

```yaml
# docker-compose.yml addition
devkanban-worker:
  image: devkanban/worker:latest
  environment:
    - REDIS_URL=redis://redis:6379
  depends_on:
    - redis
  volumes:
    - /var/run/docker.sock:/var/run/docker.sock
  networks:
    - devkanban-global

devkanban-redis:
  image: redis:7-alpine
  volumes:
    - redis_data:/data
  networks:
    - devkanban-global
```

---

## Statistics Dashboard

A real-time dashboard providing instant visibility into team and project metrics.

### Dashboard Overview

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│  📊 Dashboard                                    Team: Marketing     [Last 30 days ▼]  │
├─────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                         │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐│
│  │  Total Cards     │  │  Completed       │  │  In Progress     │  │  Overdue         ││
│  │      127         │  │      89          │  │      18          │  │       4          ││
│  │   ▲ 12% vs last  │  │   ▲ 8% vs last   │  │   ▼ 3% vs last   │  │   ▼ 2 vs last    ││
│  └──────────────────┘  └──────────────────┘  └──────────────────┘  └──────────────────┘│
│                                                                                         │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐│
│  │  Avg Cycle Time  │  │  Throughput      │  │  On-Time Rate    │  │  Active Members  ││
│  │    2.4 days      │  │   3.2 cards/day  │  │      87%         │  │       8          ││
│  │   ▼ 0.3d better  │  │   ▲ 0.5 vs last  │  │   ▲ 5% vs last   │  │   ── same        ││
│  └──────────────────┘  └──────────────────┘  └──────────────────┘  └──────────────────┘│
│                                                                                         │
│  ┌─────────────────────────────────────────┐  ┌─────────────────────────────────────┐  │
│  │  Throughput (Last 30 Days)              │  │  Work Distribution                  │  │
│  │                                         │  │                                     │  │
│  │    5│    ·  ·                           │  │  @alice    ████████████   28        │  │
│  │    4│  · ·· ·· ·   ·                    │  │  @bob      █████████      22        │  │
│  │    3│ ··········· ····                  │  │  @carol    ██████████     24        │  │
│  │    2│·····················              │  │  @dave     ███████        17        │  │
│  │    1│                                   │  │  Unassigned ██            5         │  │
│  │     └─────────────────────              │  │                                     │  │
│  │      Week 1  Week 2  Week 3  Week 4     │  │                                     │  │
│  └─────────────────────────────────────────┘  └─────────────────────────────────────┘  │
│                                                                                         │
│  ┌─────────────────────────────────────────┐  ┌─────────────────────────────────────┐  │
│  │  Board Status                           │  │  Recent Activity                    │  │
│  │                                         │  │                                     │  │
│  │  Q1 Campaign    ████████░░  78%         │  │  • @alice moved "Email blast"       │  │
│  │  Product Launch ██████████  100% ✓      │  │    to Done (2m ago)                 │  │
│  │  Website Redo   █████░░░░░  52%         │  │  • @bob commented on "Social        │  │
│  │  HR Onboarding  ███░░░░░░░  32%         │  │    campaign" (15m ago)              │  │
│  │                                         │  │  • @carol created "Press release"  │  │
│  │  ▶ View all boards                      │  │    (1h ago)                         │  │
│  └─────────────────────────────────────────┘  └─────────────────────────────────────┘  │
│                                                                                         │
│  ┌──────────────────────────────────────────────────────────────────────────────────┐  │
│  │  ⚠️ Needs Attention                                                               │  │
│  │                                                                                    │  │
│  │  🔴 4 cards overdue    🟡 3 cards aging    🔵 2 WIP limit exceeded               │  │
│  │                                                                                    │  │
│  │  │ Card                     │ Board       │ Issue        │ Days │ Assignee │     │  │
│  │  ├──────────────────────────┼─────────────┼──────────────┼──────┼──────────┤     │  │
│  │  │ Newsletter copy          │ Q1 Campaign │ Overdue      │  3   │ @alice   │     │  │
│  │  │ Banner designs           │ Q1 Campaign │ Overdue      │  2   │ @bob     │     │  │
│  │  │ Competitor analysis      │ Website     │ Aging        │  8   │ @carol   │     │  │
│  │  │ SEO audit                │ Website     │ WIP exceeded │  -   │ Team     │     │  │
│  └──────────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                         │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

### Dashboard Widgets

| Widget | Description | Update Frequency |
|--------|-------------|------------------|
| **Card Counts** | Total, completed, in progress, overdue | Real-time |
| **Cycle Time** | Average time to complete cards | Hourly |
| **Throughput** | Cards completed per time period | Hourly |
| **On-Time Rate** | % of cards completed by due date | Hourly |
| **Work Distribution** | Cards per team member | Real-time |
| **Board Progress** | Completion % per board | Real-time |
| **Throughput Chart** | Line/bar chart over time | Hourly |
| **Recent Activity** | Live feed of actions | Real-time |
| **Needs Attention** | Overdue, aging, WIP violations | Real-time |
| **Labels Breakdown** | Cards by label/category | Real-time |

### Dashboard API

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/dashboard` | Get all dashboard widgets |
| `GET` | `/dashboard/summary` | Key metrics only |
| `GET` | `/dashboard/throughput` | Throughput chart data |
| `GET` | `/dashboard/distribution` | Work distribution data |
| `GET` | `/dashboard/attention` | Items needing attention |
| `GET` | `/dashboard/activity` | Recent activity feed |
| `WS` | `/ws/dashboard` | Real-time updates |

### Dashboard Data Models

#### Summary Metrics

```json
{
  "period": {
    "from": "2024-01-01T00:00:00Z",
    "to": "2024-01-31T23:59:59Z"
  },
  "cards": {
    "total": 127,
    "completed": 89,
    "in_progress": 18,
    "overdue": 4,
    "blocked": 2
  },
  "metrics": {
    "avg_cycle_time_hours": 57.6,
    "median_cycle_time_hours": 48.0,
    "throughput_per_day": 3.2,
    "on_time_rate": 0.87
  },
  "trends": {
    "cards_total": {"current": 127, "previous": 113, "change_pct": 12.4},
    "completed": {"current": 89, "previous": 82, "change_pct": 8.5},
    "cycle_time": {"current": 57.6, "previous": 64.8, "change_pct": -11.1}
  }
}
```

#### Activity Feed

```json
{
  "activities": [
    {
      "id": "uuid",
      "type": "card.moved",
      "actor": {"id": "user-1", "name": "Alice", "avatar": "..."},
      "target": {"type": "card", "id": "card-1", "title": "Email blast"},
      "details": {"from_column": "Review", "to_column": "Done"},
      "board": {"id": "board-1", "name": "Q1 Campaign"},
      "timestamp": "2024-01-15T14:30:00Z"
    }
  ],
  "cursor": "next-page-token"
}
```

### Dashboard Customization

Users can customize their dashboard layout:

```json
{
  "user_id": "user-123",
  "dashboard_config": {
    "layout": "grid",
    "widgets": [
      {"type": "summary", "position": {"row": 1, "col": 1, "width": 4}},
      {"type": "throughput_chart", "position": {"row": 2, "col": 1, "width": 2}},
      {"type": "distribution", "position": {"row": 2, "col": 3, "width": 2}},
      {"type": "attention", "position": {"row": 3, "col": 1, "width": 4}}
    ],
    "default_period": "30d",
    "boards_filter": ["board-1", "board-2"],
    "auto_refresh": true,
    "refresh_interval_seconds": 60
  }
}
```

### Personal vs Team Dashboard

| Dashboard | Scope | Typical User |
|-----------|-------|--------------|
| **Personal** | Only cards assigned to current user | Individual contributor |
| **Team** | All cards across team boards | Manager, team lead |
| **Board** | Single board focus | Project-specific view |
| **Executive** | High-level KPIs across all boards | Leadership |

---

## Reports & Analytics

Comprehensive reporting tools for project management, team productivity, and workflow analysis.

### Available Reports

| Report | Description | Audience |
|--------|-------------|----------|
| **Board Summary** | Overview of cards by column, labels, assignees | Team |
| **Cycle Time** | Time cards spend in each column | Managers |
| **Lead Time** | Total time from creation to completion | Managers |
| **Throughput** | Cards completed per day/week/month | Managers |
| **Cumulative Flow** | Visual stacked area chart of work states over time | Managers |
| **Aging Work** | Cards sitting too long in a column | Team |
| **WIP Analysis** | Work-in-progress trends and limit violations | Team |
| **Team Workload** | Cards per assignee, balance analysis | Managers |
| **Blockers Report** | Blocked cards, duration, resolution time | Team |
| **Due Date Tracking** | Upcoming, overdue, and on-time completion rates | All |
| **Activity Log** | Timeline of all actions on a board | All |
| **Label Distribution** | Breakdown by labels/tags | All |

### Report Dashboards

#### Board Summary Dashboard

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  📊 Sprint 1 - Board Summary                    [Export ▼] [Date Range ▼]  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Total Cards: 47        Completed: 23 (49%)      Blocked: 2                │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Backlog    │  To Do     │  In Progress  │  Review   │  Done       │   │
│  │     12      │     8      │      6/5 ⚠    │     3     │    18       │   │
│  │   ████      │   ███      │    ██████     │   ██      │  ████████   │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  By Assignee                          By Label                              │
│  ┌────────────────────────┐          ┌────────────────────────┐            │
│  │ @alice    ████████  12 │          │ 🔴 Bug      ████    8  │            │
│  │ @bob      █████      8 │          │ 🟢 Feature  ██████ 12  │            │
│  │ @carol    ███████   10 │          │ 🔵 Task     ████████16 │            │
│  │ Unassigned ████      6 │          │ 🟡 Urgent   ██      4  │            │
│  └────────────────────────┘          └────────────────────────┘            │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### Cycle Time Report

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  ⏱️ Cycle Time Analysis                         Last 30 days    [Export]    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Average Cycle Time: 3.2 days     Median: 2.5 days     P85: 5.8 days       │
│                                                                             │
│  Time in Each Column (avg)                                                  │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ To Do        ████████████████████████  1.8 days                     │   │
│  │ In Progress  █████████████████         1.2 days                     │   │
│  │ Review       ████████                  0.6 days                     │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  Cycle Time Trend                                                           │
│    5d │          ·                                                         │
│    4d │    ·    · ·   ·                                                    │
│    3d │   ···  ·····  ····  ──────────── avg                              │
│    2d │  ···· ······ ······                                                │
│    1d │ ···············································                    │
│       └──────────────────────────────────────────────────                  │
│         Week 1   Week 2   Week 3   Week 4                                  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### Cumulative Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  📈 Cumulative Flow Diagram                     Last 30 days    [Export]    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Cards                                                                      │
│   50 │                                          ████████████  Done         │
│      │                                   ███████████████████               │
│   40 │                           ████████████████████████████              │
│      │                    ███████▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓  Review       │
│   30 │            ████████▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓               │
│      │     ███████▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒  In Progress  │
│   20 │████▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒               │
│      │░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  To Do        │
│   10 │░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░               │
│      │                                                        Backlog      │
│    0 └──────────────────────────────────────────────────────               │
│       Day 1      Day 10       Day 20        Day 30                         │
│                                                                             │
│  Insights:                                                                  │
│  • WIP stable around 6-8 cards                                             │
│  • Review queue cleared efficiently                                         │
│  • Steady throughput of ~3 cards/day                                       │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### Aging Work Report

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  ⏳ Aging Work Items                                            [Export]    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ⚠️ Cards exceeding column time thresholds                                  │
│                                                                             │
│  │ Card                      │ Column       │ Days │ Threshold │ Status   │ │
│  ├───────────────────────────┼──────────────┼──────┼───────────┼──────────┤ │
│  │ API Rate Limiting         │ In Progress  │  8   │    5      │ 🔴 Aging │ │
│  │ Database Migration        │ Review       │  4   │    2      │ 🟡 At Risk│ │
│  │ User Dashboard Redesign   │ In Progress  │  6   │    5      │ 🔴 Aging │ │
│  │ Email Templates           │ To Do        │ 12   │    7      │ 🔴 Aging │ │
│                                                                             │
│  Aging Distribution                                                         │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Healthy (< threshold)     ██████████████████████████████████  78%  │   │
│  │  At Risk (near threshold)  ██████                              12%  │   │
│  │  Aging (> threshold)       █████                               10%  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Report Data Models

#### Report Configuration

```json
{
  "id": "uuid",
  "board_id": "board-uuid",
  "type": "cycle_time",
  "name": "Sprint Cycle Time",
  "config": {
    "date_range": {
      "type": "rolling",
      "days": 30
    },
    "columns": ["To Do", "In Progress", "Review"],
    "exclude_labels": ["blocked"],
    "group_by": "week"
  },
  "schedule": {
    "enabled": true,
    "frequency": "weekly",
    "day": "monday",
    "time": "09:00",
    "timezone": "America/New_York",
    "recipients": ["user-1", "user-2"],
    "format": "pdf"
  },
  "created_by": "user-123",
  "created_at": "2024-01-01T00:00:00Z"
}
```

#### Report Snapshot

```json
{
  "id": "uuid",
  "report_id": "report-uuid",
  "generated_at": "2024-01-15T09:00:00Z",
  "date_range": {
    "from": "2023-12-16T00:00:00Z",
    "to": "2024-01-15T00:00:00Z"
  },
  "data": {
    "summary": {
      "total_cards": 47,
      "completed": 23,
      "avg_cycle_time_hours": 76.8,
      "median_cycle_time_hours": 60.0,
      "p85_cycle_time_hours": 139.2
    },
    "by_column": {
      "To Do": {"avg_hours": 43.2, "card_count": 8},
      "In Progress": {"avg_hours": 28.8, "card_count": 6},
      "Review": {"avg_hours": 14.4, "card_count": 3}
    },
    "trend": [
      {"date": "2024-01-08", "avg_cycle_time": 72.0},
      {"date": "2024-01-15", "avg_cycle_time": 76.8}
    ]
  }
}
```

### Reports API

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/boards/{id}/reports` | List available reports |
| `GET` | `/boards/{id}/reports/{type}` | Get report data |
| `POST` | `/boards/{id}/reports` | Create scheduled report |
| `PUT` | `/reports/{id}` | Update report config |
| `DELETE` | `/reports/{id}` | Delete scheduled report |
| `GET` | `/reports/{id}/snapshots` | List historical snapshots |
| `POST` | `/reports/{id}/export` | Export report (PDF/CSV/JSON) |

### Report Types Detail

#### Cycle Time
Measures time from when work starts (enters first active column) to completion.

```
GET /boards/{id}/reports/cycle-time?from=2024-01-01&to=2024-01-31&group_by=week
```

#### Lead Time
Measures time from card creation to completion (includes backlog time).

```
GET /boards/{id}/reports/lead-time?from=2024-01-01&to=2024-01-31
```

#### Throughput
Counts cards completed per time period.

```
GET /boards/{id}/reports/throughput?from=2024-01-01&to=2024-01-31&group_by=day
```

#### Team Workload
Analyzes work distribution across team members.

```
GET /boards/{id}/reports/workload?as_of=2024-01-15
```

Response:
```json
{
  "as_of": "2024-01-15T00:00:00Z",
  "team": [
    {
      "user_id": "user-1",
      "name": "Alice",
      "assigned_cards": 12,
      "in_progress": 3,
      "completed_last_30d": 18,
      "avg_cycle_time_hours": 48.0,
      "overdue_cards": 1
    }
  ],
  "unassigned_cards": 6,
  "balance_score": 0.82
}
```

### Export Formats

| Format | Use Case |
|--------|----------|
| **PDF** | Printable reports, stakeholder presentations |
| **CSV** | Data analysis in spreadsheets |
| **JSON** | Integration with external tools |
| **PNG** | Charts for embedding in documents |

### Scheduled Reports

Reports can be scheduled to run automatically and sent via email:

```json
{
  "schedule": {
    "enabled": true,
    "frequency": "weekly",
    "day": "monday",
    "time": "09:00",
    "timezone": "America/New_York",
    "recipients": [
      {"user_id": "user-1", "format": "pdf"},
      {"email": "manager@example.com", "format": "pdf"}
    ]
  }
}
```

---

## Integrations

The platform supports integrations for external tools, automation, and AI agents.

### Integration Types

| Type | Description | Use Case |
|------|-------------|----------|
| **Webhooks** | Push events to external URLs | Notifications, sync, automation |
| **API Keys** | Programmatic access to the API | Scripts, bots, integrations |
| **AI Agents** | Autonomous agents with scoped permissions | Task automation, assistants |
| **OAuth Apps** | Third-party app authorization | External tools, dashboards |
| **MCP Servers** | Model Context Protocol for AI | Claude, GPT, local LLMs |

### Webhooks

Receive real-time events when actions occur on your boards.

#### Webhook Configuration

```json
{
  "id": "webhook-uuid",
  "team_id": "team-uuid",
  "name": "Slack Notifications",
  "url": "https://hooks.slack.com/services/...",
  "secret": "whsec_...",
  "events": [
    "card.created",
    "card.moved",
    "card.completed",
    "comment.added"
  ],
  "filters": {
    "boards": ["board-1", "board-2"],
    "labels": ["urgent", "bug"]
  },
  "enabled": true,
  "created_at": "2024-01-01T00:00:00Z"
}
```

#### Webhook Events

| Event | Trigger | Payload |
|-------|---------|---------|
| `card.created` | New card added | Card object |
| `card.updated` | Card details changed | Card object, changes |
| `card.moved` | Card moved to column | Card, from_column, to_column |
| `card.completed` | Card moved to Done | Card object |
| `card.deleted` | Card removed | Card ID |
| `card.assigned` | Assignee added | Card, user |
| `card.due_soon` | Due date approaching | Card, due_date |
| `card.overdue` | Past due date | Card, due_date |
| `comment.added` | New comment | Comment, card |
| `board.created` | New board | Board object |
| `member.joined` | User joined team | User, team |

#### Webhook Payload

```json
{
  "id": "event-uuid",
  "type": "card.moved",
  "timestamp": "2024-01-15T14:30:00Z",
  "team": {
    "id": "team-uuid",
    "slug": "marketing"
  },
  "actor": {
    "id": "user-uuid",
    "name": "Alice",
    "email": "alice@example.com"
  },
  "data": {
    "card": {
      "id": "card-uuid",
      "title": "Launch campaign",
      "board_id": "board-uuid"
    },
    "from_column": "In Progress",
    "to_column": "Review"
  }
}
```

### API Keys

Generate API keys for programmatic access.

#### API Key Scopes

| Scope | Permissions |
|-------|-------------|
| `read:boards` | View boards and cards |
| `write:boards` | Create/update boards |
| `read:cards` | View cards and comments |
| `write:cards` | Create/update/move cards |
| `read:members` | View team members |
| `admin` | Full access (team admins only) |

#### API Key Model

```json
{
  "id": "key-uuid",
  "name": "CI/CD Integration",
  "prefix": "kb_live_",
  "key_hash": "sha256:...",
  "scopes": ["read:boards", "write:cards"],
  "team_id": "team-uuid",
  "created_by": "user-uuid",
  "last_used_at": "2024-01-15T10:00:00Z",
  "expires_at": "2025-01-01T00:00:00Z",
  "rate_limit": {
    "requests_per_minute": 60,
    "requests_per_day": 10000
  }
}
```

#### API Authentication

```bash
# Using API key in header
curl -H "Authorization: Bearer kb_live_xxxxx" \
  https://api.kanban.io/v1/boards

# Using API key as query param (not recommended)
curl "https://api.kanban.io/v1/boards?api_key=kb_live_xxxxx"
```

---

### AI Agents

AI agents can autonomously interact with the Kanban platform to automate workflows, provide assistance, and manage tasks.

#### Agent Types

| Agent Type | Description | Example Use Cases |
|------------|-------------|-------------------|
| **Task Manager** | Creates, updates, and organizes cards | Auto-create cards from emails, Slack |
| **Reviewer** | Reviews and validates work | Approval workflows, checklist validation |
| **Reporter** | Generates reports and insights | Daily standups, weekly summaries |
| **Planner** | Helps plan and prioritize work | Sprint planning, backlog grooming |
| **Assistant** | Answers questions about boards | "What's blocking the release?" |
| **Automator** | Executes rules and workflows | Auto-assign, auto-label, auto-move |

#### Agent Configuration

```json
{
  "id": "agent-uuid",
  "name": "Project Assistant",
  "type": "assistant",
  "description": "Helps team members with project questions",
  "team_id": "team-uuid",
  "status": "active",
  "permissions": {
    "scopes": ["read:boards", "read:cards", "write:cards", "write:comments"],
    "boards": ["board-1", "board-2"],
    "actions": {
      "can_create_cards": true,
      "can_move_cards": true,
      "can_assign_cards": false,
      "can_delete_cards": false,
      "can_comment": true
    }
  },
  "authentication": {
    "type": "api_key",
    "key_id": "key-uuid"
  },
  "settings": {
    "model": "claude-sonnet-4-20250514",
    "temperature": 0.7,
    "max_actions_per_minute": 10,
    "require_approval_for": ["delete", "bulk_move"]
  },
  "created_by": "user-uuid",
  "created_at": "2024-01-01T00:00:00Z"
}
```

#### Agent Actions

| Action | Description | Requires Approval |
|--------|-------------|-------------------|
| `card.create` | Create a new card | No |
| `card.update` | Update card details | No |
| `card.move` | Move card to column | No |
| `card.assign` | Assign user to card | Configurable |
| `card.delete` | Delete a card | Yes |
| `card.bulk_move` | Move multiple cards | Yes |
| `comment.add` | Add a comment | No |
| `label.apply` | Apply label to card | No |
| `report.generate` | Generate a report | No |

#### Agent Activity Log

All agent actions are logged for audit:

```json
{
  "id": "activity-uuid",
  "agent_id": "agent-uuid",
  "action": "card.create",
  "target": {
    "type": "card",
    "id": "card-uuid",
    "title": "Follow up with client"
  },
  "reason": "Created from Slack message by @alice",
  "context": {
    "source": "slack",
    "message_id": "slack-msg-123",
    "triggered_by": "user mention"
  },
  "status": "completed",
  "timestamp": "2024-01-15T14:30:00Z"
}
```

#### Agent API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/agents` | Create agent |
| `GET` | `/agents` | List agents |
| `GET` | `/agents/{id}` | Get agent details |
| `PUT` | `/agents/{id}` | Update agent |
| `DELETE` | `/agents/{id}` | Delete agent |
| `POST` | `/agents/{id}/pause` | Pause agent |
| `POST` | `/agents/{id}/resume` | Resume agent |
| `GET` | `/agents/{id}/activity` | Get activity log |
| `GET` | `/agents/{id}/stats` | Get usage statistics |

---

### MCP Server (Model Context Protocol)

Expose Kanban data and actions to AI models via MCP.

#### MCP Server Configuration

```json
{
  "name": "kanban-mcp",
  "version": "1.0.0",
  "description": "MCP server for Kanban platform",
  "transport": {
    "type": "sse",
    "url": "https://api.kanban.io/mcp"
  },
  "authentication": {
    "type": "bearer",
    "token_env": "KANBAN_API_KEY"
  }
}
```

#### MCP Tools

```json
{
  "tools": [
    {
      "name": "list_boards",
      "description": "List all boards in the team",
      "parameters": {
        "type": "object",
        "properties": {
          "status": {
            "type": "string",
            "enum": ["active", "archived", "all"]
          }
        }
      }
    },
    {
      "name": "get_board",
      "description": "Get a board with all its cards",
      "parameters": {
        "type": "object",
        "properties": {
          "board_id": {"type": "string"},
          "include_archived": {"type": "boolean"}
        },
        "required": ["board_id"]
      }
    },
    {
      "name": "create_card",
      "description": "Create a new card on a board",
      "parameters": {
        "type": "object",
        "properties": {
          "board_id": {"type": "string"},
          "title": {"type": "string"},
          "description": {"type": "string"},
          "column": {"type": "string"},
          "assignees": {"type": "array", "items": {"type": "string"}},
          "labels": {"type": "array", "items": {"type": "string"}},
          "due_date": {"type": "string", "format": "date"}
        },
        "required": ["board_id", "title"]
      }
    },
    {
      "name": "move_card",
      "description": "Move a card to a different column",
      "parameters": {
        "type": "object",
        "properties": {
          "card_id": {"type": "string"},
          "to_column": {"type": "string"}
        },
        "required": ["card_id", "to_column"]
      }
    },
    {
      "name": "search_cards",
      "description": "Search for cards across boards",
      "parameters": {
        "type": "object",
        "properties": {
          "query": {"type": "string"},
          "board_id": {"type": "string"},
          "assignee": {"type": "string"},
          "label": {"type": "string"},
          "status": {"type": "string"}
        }
      }
    },
    {
      "name": "add_comment",
      "description": "Add a comment to a card",
      "parameters": {
        "type": "object",
        "properties": {
          "card_id": {"type": "string"},
          "content": {"type": "string"}
        },
        "required": ["card_id", "content"]
      }
    },
    {
      "name": "get_report",
      "description": "Generate a report for a board",
      "parameters": {
        "type": "object",
        "properties": {
          "board_id": {"type": "string"},
          "report_type": {
            "type": "string",
            "enum": ["summary", "cycle_time", "throughput", "workload"]
          },
          "period": {"type": "string", "enum": ["7d", "30d", "90d"]}
        },
        "required": ["board_id", "report_type"]
      }
    }
  ]
}
```

#### MCP Resources

```json
{
  "resources": [
    {
      "name": "board",
      "uri_template": "kanban://boards/{board_id}",
      "description": "A Kanban board with columns and cards"
    },
    {
      "name": "card",
      "uri_template": "kanban://cards/{card_id}",
      "description": "A card with details, comments, and attachments"
    },
    {
      "name": "dashboard",
      "uri_template": "kanban://dashboard",
      "description": "Team dashboard with metrics and activity"
    }
  ]
}
```

#### Using with Claude Desktop

```json
// claude_desktop_config.json
{
  "mcpServers": {
    "kanban": {
      "command": "npx",
      "args": ["-y", "@kanban/mcp-server"],
      "env": {
        "KANBAN_API_KEY": "kb_live_xxxxx",
        "KANBAN_TEAM": "marketing"
      }
    }
  }
}
```

---

### Pre-built Integrations

| Integration | Type | Description |
|-------------|------|-------------|
| **Slack** | Webhook + Bot | Notifications, create cards from messages |
| **Microsoft Teams** | Webhook + Bot | Notifications, card previews |
| **GitHub** | Webhook | Link PRs to cards, auto-move on merge |
| **GitLab** | Webhook | Link MRs to cards, auto-move on merge |
| **Jira** | Sync | Two-way sync with Jira issues |
| **Email** | Inbound | Create cards from emails |
| **Zapier** | OAuth | Connect to 5000+ apps |
| **n8n** | API | Self-hosted automation workflows |
| **Calendar** | Sync | Sync due dates with Google/Outlook |
| **Notion** | Sync | Two-way sync with Notion databases |

### Integration API

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/integrations` | List available integrations |
| `GET` | `/integrations/installed` | List installed integrations |
| `POST` | `/integrations/{type}/install` | Install integration |
| `DELETE` | `/integrations/{type}` | Uninstall integration |
| `GET` | `/integrations/{type}/config` | Get configuration |
| `PUT` | `/integrations/{type}/config` | Update configuration |
| `GET` | `/webhooks` | List webhooks |
| `POST` | `/webhooks` | Create webhook |
| `DELETE` | `/webhooks/{id}` | Delete webhook |
| `GET` | `/api-keys` | List API keys |
| `POST` | `/api-keys` | Create API key |
| `DELETE` | `/api-keys/{id}` | Revoke API key |

---

## Markdown Support

Cards and comments support full Markdown with the following features:

| Element | Syntax | Supported |
|---------|--------|-----------|
| Headers | `# H1` `## H2` | ✓ |
| Bold | `**text**` | ✓ |
| Italic | `*text*` | ✓ |
| Strikethrough | `~~text~~` | ✓ |
| Code inline | `` `code` `` | ✓ |
| Code blocks | ` ```lang ``` ` | ✓ (syntax highlighting) |
| Links | `[text](url)` | ✓ |
| Images | `![alt](url)` | ✓ |
| Lists | `- item` `1. item` | ✓ |
| Blockquotes | `> quote` | ✓ |
| Tables | `| a | b |` | ✓ |
| Task lists | `- [ ] task` | ✓ |
| @mentions | `@username` | ✓ (linked to user) |

---

## Link Preview Support

Automatically detects and enriches links with metadata previews:

| Platform | Preview Content |
|----------|-----------------|
| **Twitter/X** | Tweet text, author, avatar, timestamp, media |
| **GitHub** | Repo/issue/PR title, description, stars, status |
| **YouTube** | Video title, thumbnail, channel, duration |
| **LinkedIn** | Post content, author |
| **Generic URLs** | OpenGraph/meta title, description, image |

---

## License

MIT License - see [LICENSE](LICENSE) for details.

---

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## Support

- Documentation: https://docs.devkanban.io
- Issues: https://github.com/yourorg/devkanban/issues
- Discussions: https://github.com/yourorg/devkanban/discussions
