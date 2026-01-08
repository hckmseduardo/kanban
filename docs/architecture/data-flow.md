# Data Flow Architecture

## Overview

This document illustrates the data flows between components in the Kanban Platform, showing how requests, tasks, and events move through the system.

---

## Flow 1: User Authentication

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│    User      │     │   Portal     │     │  Portal API  │     │  Entra ID    │
│  (Browser)   │     │  Frontend    │     │  (FastAPI)   │     │  (Microsoft) │
└──────────────┘     └──────────────┘     └──────────────┘     └──────────────┘
       │                    │                    │                    │
       │  1. Click Login    │                    │                    │
       ├───────────────────►│                    │                    │
       │                    │                    │                    │
       │                    │  2. GET /auth/login│                    │
       │                    ├───────────────────►│                    │
       │                    │                    │                    │
       │                    │  3. Auth URL       │                    │
       │                    │◄───────────────────┤                    │
       │                    │                    │                    │
       │  4. Redirect to Entra ID               │                    │
       │◄───────────────────┤                    │                    │
       │                    │                    │                    │
       │  5. User authenticates with Microsoft  │                    │
       ├────────────────────────────────────────────────────────────►│
       │                    │                    │                    │
       │  6. Callback with authorization code   │                    │
       │◄───────────────────────────────────────────────────────────┤
       │                    │                    │                    │
       │  7. POST /auth/callback (code)         │                    │
       ├────────────────────────────────────────►│                    │
       │                    │                    │                    │
       │                    │                    │  8. Exchange code  │
       │                    │                    ├───────────────────►│
       │                    │                    │                    │
       │                    │                    │  9. Access token   │
       │                    │                    │◄───────────────────┤
       │                    │                    │                    │
       │                    │  10. Create/update user, generate JWT  │
       │                    │                    │                    │
       │  11. JWT + User info                   │                    │
       │◄────────────────────────────────────────┤                    │
       │                    │                    │                    │
       │  12. Store token   │                    │                    │
       ├───────────────────►│                    │                    │
       │                    │                    │                    │
```

---

## Flow 2: Team Creation & Provisioning

```
┌────────┐   ┌────────┐   ┌────────┐   ┌────────┐   ┌────────┐   ┌────────┐
│  User  │   │Frontend│   │Portal  │   │ Redis  │   │Orchest-│   │ Docker │
│        │   │        │   │  API   │   │        │   │ rator  │   │        │
└────────┘   └────────┘   └────────┘   └────────┘   └────────┘   └────────┘
     │            │            │            │            │            │
     │ 1. Create  │            │            │            │            │
     │    Team    │            │            │            │            │
     ├───────────►│            │            │            │            │
     │            │            │            │            │            │
     │            │ 2. POST    │            │            │            │
     │            │   /teams   │            │            │            │
     │            ├───────────►│            │            │            │
     │            │            │            │            │            │
     │            │            │ 3. Create team record  │            │
     │            │            │    (status: pending)   │            │
     │            │            │            │            │            │
     │            │            │ 4. Enqueue │            │            │
     │            │            │    task    │            │            │
     │            │            ├───────────►│            │            │
     │            │            │            │            │            │
     │            │ 5. Return  │            │            │            │
     │            │   task_id  │            │            │            │
     │            │◄───────────┤            │            │            │
     │            │            │            │            │            │
     │ 6. Show    │            │            │            │            │
     │   progress │            │            │            │            │
     │◄───────────┤            │            │            │            │
     │            │            │            │            │            │
     │            │            │            │ 7. BRPOP   │            │
     │            │            │            │    task    │            │
     │            │            │            ├───────────►│            │
     │            │            │            │            │            │
     │            │            │            │            │ 8. Create  │
     │            │            │            │            │   compose  │
     │            │            │            │            ├───────────►│
     │            │            │            │            │            │
     │            │            │            │            │ 9. Start   │
     │            │            │            │            │   containers│
     │            │            │            │            ├───────────►│
     │            │            │            │            │            │
     │            │            │            │10. Publish │            │
     │            │            │            │   progress │            │
     │            │            │            │◄───────────┤            │
     │            │            │            │            │            │
     │ 11. Progress updates via WebSocket   │            │            │
     │◄───────────────────────────────────────────────────            │
     │            │            │            │            │            │
     │            │            │            │12. Publish │            │
     │            │            │            │   complete │            │
     │            │            │            │◄───────────┤            │
     │            │            │            │            │            │
     │            │            │13. Worker  │            │            │
     │            │            │   updates  │            │            │
     │            │            │   database │            │            │
     │            │            │◄───────────┤            │            │
     │            │            │            │            │            │
     │ 14. Task completed notification      │            │            │
     │◄───────────────────────────────────────────────────            │
```

---

## Flow 3: Card Processing by AI Agent

```
┌────────┐   ┌────────┐   ┌────────┐   ┌────────┐   ┌────────┐   ┌────────┐
│  User  │   │ Team   │   │ Team   │   │ Agent  │   │  LLM   │   │Codebase│
│        │   │Frontend│   │  API   │   │        │   │Provider│   │        │
└────────┘   └────────┘   └────────┘   └────────┘   └────────┘   └────────┘
     │            │            │            │            │            │
     │ 1. Move card to        │            │            │            │
     │   "In Progress"        │            │            │            │
     ├───────────►│            │            │            │            │
     │            │            │            │            │            │
     │            │ 2. PUT     │            │            │            │
     │            │   /cards   │            │            │            │
     │            ├───────────►│            │            │            │
     │            │            │            │            │            │
     │            │            │ 3. Trigger │            │            │
     │            │            │   webhook  │            │            │
     │            │            ├───────────►│            │            │
     │            │            │            │            │            │
     │            │            │            │ 4. Verify  │            │
     │            │            │            │   signature│            │
     │            │            │            │            │            │
     │            │            │            │ 5. Route to│            │
     │            │            │            │   agent    │            │
     │            │            │            │            │            │
     │            │            │            │ 6. Build   │            │
     │            │            │            │   context  │            │
     │            │            │            │            │            │
     │            │            │            │ 7. LLM     │            │
     │            │            │            │   request  │            │
     │            │            │            ├───────────►│            │
     │            │            │            │            │            │
     │            │            │            │ 8. Tool    │            │
     │            │            │            │   calls    │            │
     │            │            │            │◄───────────┤            │
     │            │            │            │            │            │
     │            │            │            │ 9. Execute │            │
     │            │            │            │   tools    │            │
     │            │            │            ├─────────────────────────►│
     │            │            │            │            │            │
     │            │            │            │10. Read/   │            │
     │            │            │            │   write    │            │
     │            │            │            │   files    │            │
     │            │            │            │◄─────────────────────────┤
     │            │            │            │            │            │
     │            │            │            │11. Git     │            │
     │            │            │            │   commit   │            │
     │            │            │            ├─────────────────────────►│
     │            │            │            │            │            │
     │            │            │            │12. Continue│            │
     │            │            │            │   with LLM │            │
     │            │            │            ├───────────►│            │
     │            │            │            │            │            │
     │            │            │            │13. Final   │            │
     │            │            │            │   response │            │
     │            │            │            │◄───────────┤            │
     │            │            │            │            │            │
     │            │            │14. Update  │            │            │
     │            │            │   card     │            │            │
     │            │            │◄───────────┤            │            │
     │            │            │            │            │            │
     │ 15. Card updated via WebSocket       │            │            │
     │◄────────────────────────┤            │            │            │
```

---

## Flow 4: Workspace with App Provisioning

```
┌────────┐   ┌────────┐   ┌────────┐   ┌────────┐   ┌────────┐   ┌────────┐
│  User  │   │Portal  │   │Orchest-│   │ GitHub │   │ Azure  │   │ Docker │
│        │   │  API   │   │ rator  │   │        │   │        │   │        │
└────────┘   └────────┘   └────────┘   └────────┘   └────────┘   └────────┘
     │            │            │            │            │            │
     │ 1. POST    │            │            │            │            │
     │  /workspaces│           │            │            │            │
     ├───────────►│            │            │            │            │
     │            │            │            │            │            │
     │            │ 2. Validate│            │            │            │
     │            │   request  │            │            │            │
     │            │            │            │            │            │
     │            │ 3. Create  │            │            │            │
     │            │   record   │            │            │            │
     │            │            │            │            │            │
     │            │ 4. Queue   │            │            │            │
     │            │   task     │            │            │            │
     │            ├───────────►│            │            │            │
     │            │            │            │            │            │
     │ 5. Task ID │            │            │            │            │
     │◄───────────┤            │            │            │            │
     │            │            │            │            │            │
     │            │            │ 6. Create  │            │            │
     │            │            │   kanban   │            │            │
     │            │            │   team     │            │            │
     │            │            ├────────────────────────────────────►│
     │            │            │            │            │            │
     │ 7. Progress: Creating team           │            │            │
     │◄──────────────────────────────────────            │            │
     │            │            │            │            │            │
     │            │            │ 8. Create  │            │            │
     │            │            │   repo     │            │            │
     │            │            ├───────────►│            │            │
     │            │            │            │            │            │
     │            │            │ 9. Repo URL│            │            │
     │            │            │◄───────────┤            │            │
     │            │            │            │            │            │
     │ 10. Progress: Creating repo          │            │            │
     │◄──────────────────────────────────────            │            │
     │            │            │            │            │            │
     │            │            │11. Create  │            │            │
     │            │            │   app reg  │            │            │
     │            │            ├─────────────────────────►│            │
     │            │            │            │            │            │
     │            │            │12. App ID  │            │            │
     │            │            │◄─────────────────────────┤            │
     │            │            │            │            │            │
     │ 13. Progress: Creating Azure app     │            │            │
     │◄──────────────────────────────────────            │            │
     │            │            │            │            │            │
     │            │            │14. Deploy  │            │            │
     │            │            │   app      │            │            │
     │            │            ├────────────────────────────────────►│
     │            │            │            │            │            │
     │ 15. Progress: Deploying app          │            │            │
     │◄──────────────────────────────────────            │            │
     │            │            │            │            │            │
     │            │            │16. Publish │            │            │
     │            │            │   complete │            │            │
     │            │            │            │            │            │
     │ 17. Workspace ready                  │            │            │
     │◄──────────────────────────────────────            │            │
```

---

## Flow 5: Sandbox Creation

```
┌────────┐   ┌────────┐   ┌────────┐   ┌────────┐   ┌────────┐   ┌────────┐
│  User  │   │Portal  │   │Orchest-│   │  Git   │   │ Agent  │   │ Azure  │
│        │   │  API   │   │ rator  │   │        │   │Factory │   │        │
└────────┘   └────────┘   └────────┘   └────────┘   └────────┘   └────────┘
     │            │            │            │            │            │
     │ 1. POST    │            │            │            │            │
     │  /sandboxes│            │            │            │            │
     ├───────────►│            │            │            │            │
     │            │            │            │            │            │
     │            │ 2. Queue   │            │            │            │
     │            │   sandbox  │            │            │            │
     │            │   provision│            │            │            │
     │            ├───────────►│            │            │            │
     │            │            │            │            │            │
     │ 3. Task ID │            │            │            │            │
     │◄───────────┤            │            │            │            │
     │            │            │            │            │            │
     │            │            │ 4. Create  │            │            │
     │            │            │   branch   │            │            │
     │            │            ├───────────►│            │            │
     │            │            │            │            │            │
     │ 5. Progress: Creating branch         │            │            │
     │◄──────────────────────────────────────            │            │
     │            │            │            │            │            │
     │            │            │ 6. Clone   │            │            │
     │            │            │   database │            │            │
     │            │            │            │            │            │
     │ 7. Progress: Cloning database        │            │            │
     │◄──────────────────────────────────────            │            │
     │            │            │            │            │            │
     │            │            │ 8. Provision            │            │
     │            │            │   agent    │            │            │
     │            │            ├─────────────────────────►│            │
     │            │            │            │            │            │
     │            │            │ 9. Generate│            │            │
     │            │            │   webhook  │            │            │
     │            │            │   secret   │            │            │
     │            │            │◄─────────────────────────┤            │
     │            │            │            │            │            │
     │ 10. Progress: Provisioning agent     │            │            │
     │◄──────────────────────────────────────            │            │
     │            │            │            │            │            │
     │            │            │11. Add     │            │            │
     │            │            │   redirect │            │            │
     │            │            │   URI      │            │            │
     │            │            ├─────────────────────────────────────►│
     │            │            │            │            │            │
     │ 12. Progress: Configuring Azure      │            │            │
     │◄──────────────────────────────────────            │            │
     │            │            │            │            │            │
     │            │            │13. Deploy  │            │            │
     │            │            │   sandbox  │            │            │
     │            │            │   containers            │            │
     │            │            │            │            │            │
     │ 14. Sandbox ready                    │            │            │
     │◄──────────────────────────────────────            │            │
```

---

## Flow 6: Real-time Task Progress

```
┌────────────────────────────────────────────────────────────────────────────┐
│                           Real-time Progress Flow                           │
├────────────────────────────────────────────────────────────────────────────┤

Portal Frontend                Redis                  Orchestrator
      │                          │                          │
      │ 1. Connect WebSocket     │                          │
      │     /ws/tasks/{user_id}  │                          │
      ├─────────────────────────►│                          │
      │                          │                          │
      │                          │ 2. Subscribe to          │
      │                          │    tasks:{user_id}       │
      │                          │                          │
      │                          │                          │ 3. Process task
      │                          │                          │    step 1
      │                          │                          │
      │                          │ 4. Publish progress      │
      │                          │◄─────────────────────────┤
      │                          │                          │
      │ 5. Receive progress      │                          │
      │◄─────────────────────────┤                          │
      │                          │                          │
      │ 6. Update UI             │                          │
      │    (progress bar)        │                          │
      │                          │                          │
      │                          │                          │ 7. Process task
      │                          │                          │    step 2
      │                          │                          │
      │                          │ 8. Publish progress      │
      │                          │◄─────────────────────────┤
      │                          │                          │
      │ 9. Receive progress      │                          │
      │◄─────────────────────────┤                          │
      │                          │                          │
      │ 10. Update UI            │                          │
      │                          │                          │
      │                          │                          │...repeat...
      │                          │                          │
      │                          │ N. Publish complete      │
      │                          │◄─────────────────────────┤
      │                          │                          │
      │ N+1. Receive complete    │                          │
      │◄─────────────────────────┤                          │
      │                          │                          │
      │ N+2. Show success        │                          │
      │      notification        │                          │

```

---

## Flow 7: LLM Request Routing

```
┌────────┐     ┌────────┐     ┌────────┐     ┌────────┐
│ Agent  │     │  LLM   │     │Provider│     │  LLM   │
│        │     │ Proxy  │     │ Router │     │  API   │
└────────┘     └────────┘     └────────┘     └────────┘
     │              │              │              │
     │ 1. POST      │              │              │
     │  /v1/messages│              │              │
     │  model: claude-sonnet       │              │
     ├─────────────►│              │              │
     │              │              │              │
     │              │ 2. Validate  │              │
     │              │    API key   │              │
     │              │              │              │
     │              │ 3. Check     │              │
     │              │    rate limit│              │
     │              │              │              │
     │              │ 4. Route     │              │
     │              │    request   │              │
     │              ├─────────────►│              │
     │              │              │              │
     │              │              │ 5. Map model │
     │              │              │    to provider│
     │              │              │    (Anthropic)│
     │              │              │              │
     │              │              │ 6. Forward   │
     │              │              │    request   │
     │              │              ├─────────────►│
     │              │              │              │
     │              │              │ 7. LLM       │
     │              │              │    response  │
     │              │              │◄─────────────┤
     │              │              │              │
     │              │ 8. Response  │              │
     │              │◄─────────────┤              │
     │              │              │              │
     │              │ 9. Track     │              │
     │              │    usage     │              │
     │              │              │              │
     │ 10. Response │              │              │
     │◄─────────────┤              │              │
```

---

## Data Storage Layout

```
/data/
├── portal/
│   └── portal.json              # Portal TinyDB
│
├── teams/
│   ├── team-a/
│   │   ├── db.json              # Team TinyDB
│   │   └── attachments/         # File uploads
│   │
│   └── team-b/
│       ├── db.json
│       └── attachments/
│
├── workspaces/
│   ├── workspace-1/
│   │   ├── kanban/
│   │   │   └── db.json          # Workspace kanban DB
│   │   ├── app/                 # App source code
│   │   └── sandboxes/
│   │       ├── feature-auth/
│   │       │   └── db.json      # Sandbox DB (cloned)
│   │       └── bugfix-login/
│   │           └── db.json
│   │
│   └── workspace-2/
│       └── ...
│
├── redis/
│   └── dump.rdb                 # Redis persistence
│
└── certbot/
    └── acme.json                # SSL certificates
```

---

## Event Types Summary

| Event Category | Events |
|----------------|--------|
| **Task Lifecycle** | task.created, task.progress, task.completed, task.failed |
| **Team Events** | team.provisioned, team.deleted, team.suspended |
| **Workspace Events** | workspace.provisioned, workspace.deleted |
| **Sandbox Events** | sandbox.provisioned, sandbox.deleted |
| **Card Events** | card.created, card.updated, card.moved, card.deleted |
| **Agent Events** | agent.started, agent.completed, agent.failed |

## Related Documentation
- [Overview](./overview.md)
- [Message Queue Patterns](./message-queue.md)
- [Portal Architecture](./portal.md)
- [Orchestrator Architecture](./orchestrator.md)
- [Kanban Agents Architecture](./kanban-agents.md)
