# Kanban Platform - Architecture Overview

## Introduction

The Kanban Platform is a multi-tenant SaaS application that provides isolated team workspaces with integrated Kanban boards and AI-powered automation agents. The platform enables teams to manage projects, automate development tasks, and provision isolated sandbox environments for development.

## System Architecture

```
                                    ┌─────────────────────────────────────────────────────────────┐
                                    │                        Internet                              │
                                    └─────────────────────────────────────────────────────────────┘
                                                              │
                                                              ▼
                                    ┌─────────────────────────────────────────────────────────────┐
                                    │                    Traefik (Reverse Proxy)                   │
                                    │              Ports: 80/443 - TLS Termination                │
                                    └─────────────────────────────────────────────────────────────┘
                                                              │
                        ┌─────────────────────────────────────┼─────────────────────────────────────┐
                        │                                     │                                     │
                        ▼                                     ▼                                     ▼
          ┌─────────────────────────┐       ┌─────────────────────────┐       ┌─────────────────────────┐
          │     Portal Frontend     │       │      Portal API         │       │    Team Instances       │
          │     (React/Vite)        │       │      (FastAPI)          │       │    (Dynamic)            │
          │                         │       │                         │       │                         │
          │  - User Dashboard       │       │  - Authentication       │       │  - {team}.domain        │
          │  - Team Management      │       │  - Team CRUD            │       │  - Per-team Kanban      │
          │  - Workspace UI         │       │  - Task Tracking        │       │  - Isolated Database    │
          └─────────────────────────┘       └─────────────────────────┘       └─────────────────────────┘
                                                              │
                                                              │
                              ┌────────────────────────────────┴────────────────────────────────┐
                              │                                                                 │
                              ▼                                                                 ▼
          ┌─────────────────────────────────────────┐             ┌─────────────────────────────────────────┐
          │              Redis                       │             │            Portal Worker               │
          │                                          │             │                                         │
          │  - Message Queues (High/Normal)          │◄───────────►│  - Background Task Processing           │
          │  - Pub/Sub Channels                      │             │  - Status Update Listener               │
          │  - Session/Cache Storage                 │             │  - Database Updates                     │
          └─────────────────────────────────────────┘             └─────────────────────────────────────────┘
                              │
                              │
                              ▼
          ┌─────────────────────────────────────────┐
          │            Orchestrator                  │
          │                                          │
          │  - Team Provisioning                     │
          │  - Workspace Lifecycle                   │
          │  - Sandbox Management                    │
          │  - Resource Cleanup                      │
          └─────────────────────────────────────────┘
                              │
          ┌───────────────────┼───────────────────┐
          │                   │                   │
          ▼                   ▼                   ▼
    ┌───────────┐      ┌───────────┐      ┌───────────┐
    │  GitHub   │      │  Azure    │      │  Docker   │
    │  Service  │      │  Service  │      │  Engine   │
    └───────────┘      └───────────┘      └───────────┘
```

## Core Components

| Component | Technology | Purpose |
|-----------|------------|---------|
| **Portal** | FastAPI + React | Central management for users, teams, workspaces |
| **Orchestrator** | Python asyncio | Provisioning and lifecycle management |
| **Kanban Team** | FastAPI + React | Individual team Kanban boards |
| **Kanban Agents** | Python + LLM APIs | AI-powered task automation |
| **LLM Proxy** | Python | LLM API routing and management |
| **Traefik** | Go | Reverse proxy and load balancing |
| **Redis** | Redis 7 | Message queue and pub/sub |
| **CoreDNS** | Go | Dynamic DNS resolution (dev) |
| **Certbot** | Python | SSL certificate management |

## Technology Stack

| Layer | Technology |
|-------|-----------|
| Reverse Proxy | Traefik v3.0 |
| Message Queue | Redis 7-Alpine |
| DNS | CoreDNS |
| Certificates | Let's Encrypt via Certbot |
| Backend APIs | FastAPI + Python 3.11 |
| Frontend | React + TypeScript + Vite |
| Database | TinyDB (JSON-based) |
| Authentication | Microsoft Entra ID (MSAL) |
| Secrets | Azure Key Vault |
| LLM Integration | Claude (Anthropic), OpenAI, Ollama |
| Containerization | Docker + Docker Compose |

## Multi-Tenancy Model

```
Portal (Central)
    │
    ├── Team A ─────► team-a.domain ─────► Kanban Board + Database
    │                                            │
    │                                            └── Sandbox A1 ─────► Branch + Agent
    │
    ├── Team B ─────► team-b.domain ─────► Kanban Board + Database
    │
    └── Team C ─────► Workspace C ─────► App + Kanban + GitHub Repo
                            │
                            ├── Sandbox C1 ─────► Feature Branch + Agent
                            └── Sandbox C2 ─────► Bugfix Branch + Agent
```

## Key Architectural Patterns

### 1. Message Queue Pattern
All long-running tasks use Redis queues with priority levels:
- **High Priority**: Team provisioning, urgent operations
- **Normal Priority**: Standard provisioning, cleanup tasks

### 2. Pub/Sub for Real-time Updates
Status updates flow through Redis pub/sub channels:
- `team:status` - Team lifecycle events
- `workspace:status` - Workspace provisioning
- `sandbox:status` - Sandbox provisioning
- `tasks:{user_id}` - User-specific task progress

### 3. Async Provisioning
```
User Request → API → Queue Task → Return Task ID
                         │
                         ▼
              Orchestrator Processes
                         │
                         ▼
              Pub/Sub Status Updates
                         │
                         ▼
              Frontend Real-time Display
```

### 4. Isolation Pattern
Each tenant (team/sandbox) receives:
- Dedicated Docker containers
- Isolated TinyDB database
- Unique subdomain routing
- Separate agent instances (sandboxes)

## Configuration Management

The platform follows a single configuration file pattern:
- Environment variables for runtime configuration
- Azure Key Vault for production secrets
- Pydantic BaseSettings for validation

Key configuration areas:
- `DOMAIN` - Base domain for the platform
- `REDIS_URL` - Message queue connection
- `AZURE_KEY_VAULT_URL` - Secrets management
- `ENTRA_CLIENT_ID/SECRET` - Authentication
- `LLM_PROVIDER` - AI model selection

## Directory Structure

```
kanban/
├── portal/                 # Central management portal
│   ├── backend/           # FastAPI API
│   └── frontend/          # React SPA
├── orchestrator/           # Provisioning engine
├── kanban-team/            # Team instance template
│   ├── backend/           # Team API
│   └── frontend/          # Team UI
├── kanban-agents/          # AI automation
├── llm-proxy/              # LLM routing
├── traefik/                # Reverse proxy config
├── certbot/                # SSL management
├── coredns/                # DNS server
├── data/                   # Persistent storage
├── scripts/                # Utility scripts
└── docker-compose.yml      # Service orchestration
```

## Related Documentation

- [Portal Architecture](./portal.md)
- [Orchestrator Architecture](./orchestrator.md)
- [Kanban Team Architecture](./kanban-team.md)
- [Kanban Agents Architecture](./kanban-agents.md)
- [LLM Proxy Architecture](./llm-proxy.md)
- [Infrastructure Architecture](./infrastructure.md)
- [Message Queue Patterns](./message-queue.md)
- [Data Flow Diagrams](./data-flow.md)
