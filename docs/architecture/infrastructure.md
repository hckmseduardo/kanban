# Infrastructure Architecture

## Overview

This document covers the infrastructure components that support the Kanban Platform: Traefik (reverse proxy), Redis (message queue), CoreDNS (DNS server), and Certbot (SSL certificates).

## Architecture Diagram

```
                                    Internet
                                        │
                                        ▼
                            ┌───────────────────────┐
                            │       Traefik         │
                            │   (Reverse Proxy)     │
                            │                       │
                            │   Ports: 80, 443      │
                            │   - TLS termination   │
                            │   - Dynamic routing   │
                            │   - Load balancing    │
                            └───────────────────────┘
                                        │
        ┌───────────────────────────────┼───────────────────────────────┐
        │               │               │               │               │
        ▼               ▼               ▼               ▼               ▼
   ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐
   │ Portal  │    │ Portal  │    │ Team A  │    │ Team B  │    │  Agents │
   │   Web   │    │   API   │    │         │    │         │    │         │
   └─────────┘    └─────────┘    └─────────┘    └─────────┘    └─────────┘
        │               │               │               │               │
        └───────────────┴───────────────┴───────────────┴───────────────┘
                                        │
                            ┌───────────────────────┐
                            │        Redis          │
                            │   (Message Queue)     │
                            │                       │
                            │   - Task Queues       │
                            │   - Pub/Sub           │
                            │   - Caching           │
                            └───────────────────────┘
                                        │
        ┌───────────────────────────────┴───────────────────────────────┐
        │                                                               │
        ▼                                                               ▼
┌───────────────────────┐                               ┌───────────────────────┐
│      Certbot          │                               │      CoreDNS          │
│  (SSL Certificates)   │                               │    (DNS Server)       │
│                       │                               │                       │
│  - Let's Encrypt      │                               │  - Dynamic subdomains │
│  - Auto renewal       │                               │  - Local development  │
└───────────────────────┘                               └───────────────────────┘
```

---

## Traefik (Reverse Proxy)

### Purpose
Traefik serves as the entry point for all HTTP/HTTPS traffic, providing:
- TLS termination with automatic certificate management
- Dynamic routing based on Docker labels
- Load balancing across service replicas
- Automatic service discovery

### Configuration

#### Directory Structure
```
traefik/
├── traefik.yml              # Static configuration
├── dynamic/
│   └── middlewares.yml      # Dynamic middleware config
└── acme.json                # Let's Encrypt certificates
```

#### Static Configuration
```yaml
# traefik/traefik.yml
api:
  dashboard: true
  insecure: false

entryPoints:
  web:
    address: ":80"
    http:
      redirections:
        entryPoint:
          to: websecure
          scheme: https

  websecure:
    address: ":443"
    http:
      tls:
        certResolver: letsencrypt

certificatesResolvers:
  letsencrypt:
    acme:
      email: admin@domain.com
      storage: /acme.json
      httpChallenge:
        entryPoint: web

providers:
  docker:
    endpoint: "unix:///var/run/docker.sock"
    exposedByDefault: false
    network: kanban-network

  file:
    directory: /dynamic
    watch: true

log:
  level: INFO

accessLog:
  filePath: /var/log/traefik/access.log
```

#### Dynamic Middleware
```yaml
# traefik/dynamic/middlewares.yml
http:
  middlewares:
    secure-headers:
      headers:
        frameDeny: true
        contentTypeNosniff: true
        browserXssFilter: true
        stsIncludeSubdomains: true
        stsSeconds: 31536000

    rate-limit:
      rateLimit:
        average: 100
        burst: 50

    compress:
      compress: {}
```

### Docker Labels

#### Portal Services
```yaml
# docker-compose.yml
services:
  portal-api:
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.portal-api.rule=Host(`kanban.domain`) && PathPrefix(`/api`)"
      - "traefik.http.routers.portal-api.entrypoints=websecure"
      - "traefik.http.routers.portal-api.tls.certresolver=letsencrypt"
      - "traefik.http.services.portal-api.loadbalancer.server.port=8000"

  portal-web:
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.portal-web.rule=Host(`kanban.domain`)"
      - "traefik.http.routers.portal-web.entrypoints=websecure"
      - "traefik.http.routers.portal-web.tls.certresolver=letsencrypt"
      - "traefik.http.services.portal-web.loadbalancer.server.port=80"
```

#### Dynamic Team Routing
```yaml
# Generated by orchestrator for each team
services:
  team-a-api:
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.team-a-api.rule=Host(`team-a.kanban.domain`) && PathPrefix(`/api`)"
      - "traefik.http.routers.team-a-api.entrypoints=websecure"
      - "traefik.http.routers.team-a-api.tls.certresolver=letsencrypt"
      - "traefik.http.services.team-a-api.loadbalancer.server.port=8000"

  team-a-web:
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.team-a-web.rule=Host(`team-a.kanban.domain`)"
      - "traefik.http.routers.team-a-web.entrypoints=websecure"
      - "traefik.http.routers.team-a-web.tls.certresolver=letsencrypt"
      - "traefik.http.services.team-a-web.loadbalancer.server.port=80"
```

### Routing Rules

| Pattern | Route | Service |
|---------|-------|---------|
| `kanban.domain/api/*` | Portal API | portal-api:8000 |
| `kanban.domain/*` | Portal Web | portal-web:80 |
| `{team}.kanban.domain/api/*` | Team API | team-{team}-api:8000 |
| `{team}.kanban.domain/*` | Team Web | team-{team}-web:80 |
| `{sandbox}.kanban.domain/api/*` | Sandbox API | sandbox-{sandbox}-api:8000 |

---

## Redis (Message Queue)

### Purpose
Redis provides:
- Message queues for async task processing
- Pub/Sub channels for real-time updates
- Session and cache storage
- Rate limiting counters

### Configuration

```yaml
# docker-compose.yml
services:
  redis:
    image: redis:7-alpine
    command: redis-server --appendonly yes --maxmemory 256mb --maxmemory-policy volatile-lru
    ports:
      - "6379:6379"
    volumes:
      - ./data/redis:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
```

### Queue Structure

```
Queue Hierarchy:
├── queue:provisioning:high      # High-priority provisioning
├── queue:provisioning:normal    # Standard provisioning
├── queue:certificates:high      # Urgent cert operations
├── queue:certificates:normal    # Standard cert operations
├── queue:dns:high               # DNS changes
├── queue:dns:normal             # Standard DNS
└── queue:notifications:normal   # Email/notifications
```

### Pub/Sub Channels

```
Channel Structure:
├── team:status                  # Team lifecycle events
├── workspace:status             # Workspace events
├── sandbox:status               # Sandbox events
└── tasks:{user_id}              # User-specific task updates
```

### Data Structures

```python
# Task metadata
task:{task_id} = {
    "id": "uuid",
    "type": "team.provision",
    "status": "processing",
    "step": 3,
    "total_steps": 10,
    "message": "Creating containers",
    "percentage": 30,
    "created_at": "timestamp",
    "updated_at": "timestamp"
}

# Rate limiting
ratelimit:{workspace}:{model} = <count>  # TTL: 60s

# Sessions
session:{token} = {
    "user_id": "uuid",
    "email": "user@example.com",
    "expires_at": "timestamp"
}

# Cache
cache:{key} = <value>  # TTL: varies
```

### Redis Commands Reference

```bash
# Queue operations
LPUSH queue:provisioning:high "{task_json}"  # Enqueue high priority
BRPOP queue:provisioning:high queue:provisioning:normal 5  # Blocking pop

# Pub/Sub
PUBLISH team:status "{status_json}"  # Publish update
SUBSCRIBE team:status workspace:status  # Subscribe to channels

# Task tracking
HSET task:uuid field value  # Update task field
HGETALL task:uuid  # Get task details
EXPIRE task:uuid 86400  # Set TTL (24h)
```

---

## CoreDNS (DNS Server)

### Purpose
CoreDNS provides dynamic DNS resolution for:
- Local development (*.localhost)
- Dynamic subdomain resolution
- Team and sandbox routing

### Configuration

#### Directory Structure
```
coredns/
├── Corefile              # Main configuration
└── zones/
    └── db.localhost      # Zone file
```

#### Corefile
```
# coredns/Corefile
.:53 {
    forward . 8.8.8.8 8.8.4.4
    log
    errors
}

localhost:53 {
    file /zones/db.localhost
    log
    errors
}
```

#### Zone File
```
; coredns/zones/db.localhost
$ORIGIN localhost.
@       IN      SOA     ns.localhost. admin.localhost. (
                        2024010101 ; serial
                        3600       ; refresh
                        600        ; retry
                        86400      ; expire
                        60         ; minimum
                        )

@               IN      NS      ns.localhost.
@               IN      A       127.0.0.1
ns              IN      A       127.0.0.1

; Wildcard for all subdomains
*               IN      A       127.0.0.1

; Specific entries (added dynamically)
team-a          IN      A       127.0.0.1
team-b          IN      A       127.0.0.1
```

### Docker Configuration

```yaml
# docker-compose.yml
services:
  coredns:
    image: coredns/coredns:latest
    command: -conf /Corefile
    ports:
      - "53:53/udp"
      - "53:53/tcp"
    volumes:
      - ./coredns/Corefile:/Corefile:ro
      - ./coredns/zones:/zones:ro
    profiles:
      - dns  # Optional, only start when needed
```

### Usage

```bash
# Start with DNS profile
docker compose --profile dns up -d

# Test DNS resolution
nslookup team-a.localhost 127.0.0.1
dig @127.0.0.1 team-a.localhost

# Configure system DNS (macOS)
sudo networksetup -setdnsservers Wi-Fi 127.0.0.1 8.8.8.8
```

---

## Certbot (SSL Certificates)

### Purpose
Certbot manages SSL certificates via Let's Encrypt:
- Automatic certificate issuance
- Wildcard certificate support
- Auto-renewal

### Configuration

#### Directory Structure
```
certbot/
├── conf/                 # Let's Encrypt configuration
│   └── renewal/          # Renewal configs
├── www/                  # HTTP challenge files
└── logs/                 # Certbot logs
```

#### Docker Configuration
```yaml
# docker-compose.yml
services:
  certbot:
    image: certbot/certbot
    volumes:
      - ./certbot/conf:/etc/letsencrypt
      - ./certbot/www:/var/www/certbot
      - ./certbot/logs:/var/log/letsencrypt
    entrypoint: /bin/sh -c "trap exit TERM; while :; do certbot renew; sleep 12h & wait $${!}; done"
```

### Certificate Operations

#### Initial Certificate Request
```bash
# HTTP challenge (single domain)
docker compose run --rm certbot certonly \
    --webroot \
    --webroot-path=/var/www/certbot \
    -d kanban.domain

# Wildcard certificate (DNS challenge)
docker compose run --rm certbot certonly \
    --manual \
    --preferred-challenges=dns \
    -d "*.kanban.domain" \
    -d kanban.domain
```

#### Certificate Renewal
```bash
# Manual renewal
docker compose run --rm certbot renew

# Check certificate status
docker compose run --rm certbot certificates
```

### Traefik Integration

Traefik can manage certificates directly via ACME:

```yaml
# traefik.yml
certificatesResolvers:
  letsencrypt:
    acme:
      email: admin@kanban.domain
      storage: /acme.json
      httpChallenge:
        entryPoint: web

  letsencrypt-dns:
    acme:
      email: admin@kanban.domain
      storage: /acme-dns.json
      dnsChallenge:
        provider: cloudflare
        delayBeforeCheck: 10
```

---

## Network Configuration

### Docker Network

```yaml
# docker-compose.yml
networks:
  kanban-network:
    driver: bridge
    ipam:
      config:
        - subnet: 172.20.0.0/16
```

### Service Discovery

Services communicate via Docker DNS:
- `redis` - Redis server
- `portal-api` - Portal backend
- `portal-web` - Portal frontend
- `orchestrator` - Provisioning service
- `team-{slug}-api` - Team API
- `team-{slug}-web` - Team frontend

### Port Mapping

| Service | Internal Port | External Port |
|---------|---------------|---------------|
| Traefik HTTP | 80 | 80 |
| Traefik HTTPS | 443 | 443 |
| Redis | 6379 | 6379 (optional) |
| CoreDNS | 53 | 53 (optional) |
| Portal API | 8000 | - |
| Portal Web | 80 | - |
| Team APIs | 8000 | - |
| Team Webs | 80 | - |

---

## Monitoring

### Traefik Dashboard

```yaml
# traefik.yml
api:
  dashboard: true
  insecure: true  # Only in development

# Access at http://traefik.localhost/dashboard/
```

### Redis Monitoring

```bash
# Connection info
redis-cli INFO

# Real-time commands
redis-cli MONITOR

# Memory usage
redis-cli INFO memory

# Queue lengths
redis-cli LLEN queue:provisioning:high
redis-cli LLEN queue:provisioning:normal
```

### Health Checks

```yaml
# docker-compose.yml
services:
  redis:
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

  traefik:
    healthcheck:
      test: ["CMD", "wget", "-q", "--spider", "http://localhost:8080/ping"]
      interval: 10s
      timeout: 5s
      retries: 5
```

---

## Security Considerations

### Traefik
- HTTPS redirect enforced
- Security headers middleware
- Rate limiting enabled
- Dashboard protected in production

### Redis
- No external port exposure in production
- Password authentication (optional)
- MaxMemory limits configured
- Append-only file for persistence

### Network
- Internal Docker network isolation
- Only Traefik exposed to internet
- Service-to-service via internal DNS

## Related Documentation
- [Overview](./overview.md)
- [Message Queue Patterns](./message-queue.md)
- [Orchestrator Architecture](./orchestrator.md)
