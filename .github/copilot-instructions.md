# Copilot / AI agent instructions for this repository

This file gives concise, repository-specific guidance so AI coding agents can be immediately productive.

**Big Picture**
- **Platform:** multi-tenant Kanban where a central Portal provisions isolated per-team Docker stacks. See `README.MD` Architecture diagrams.
- **Major components:** `portal/` (central UI + backend), `orchestrator/` (provisions team instances), `team-template/` (Jinja2 templates for per-team Docker stacks), global infra (`coredns/`, `traefik/`, `certbot/`).
- **Routing & isolation:** each team is served at `{slug}.devkanban.io` (CoreDNS → Traefik → team gateway). Team state is stored in per-team TinyDB JSON files under `teams/<slug>/data/`.

**Key files to inspect before coding**
- `docker-compose.yml` (root) — global infra layout.
- `coredns/ zones/devkanban.io.db` — DNS zone template and examples of how host IP is injected.
- `traefik/` and `certbot/scripts/` — TLS and certificate lifecycle.
- `portal/backend/app/` — central API: `main.py`, `auth/entra.py`, `services/team_provisioner.py`.
- `orchestrator/app/provisioner.py` and `orchestrator/templates/docker-compose.team.yml.j2` — how team stacks are generated.
- `team-template/` — canonical per-team service layout (nginx, frontend, backend, worker) and `docker-compose.yml.j2` template.

**Project-specific conventions and patterns**
- Per-team isolation: when adding a new per-team capability, update the `team-template/` and the Jinja templates in `orchestrator/templates/`.
- TinyDB usage: each team uses a small JSON DB file (examples in README). Look for `db/*.json` and update migration code in `portal/backend/app/db/` when schema changes.
- Naming: services, networks and volumes follow the `devkanban-<team>-*` pattern. Keep names predictable to allow `orchestrator` to manage them.
- Certificates: certs are issued per-subdomain using Certbot; certificate files live under `traefik/certs/live/` — changes to TLS routing should consider Traefik dynamic config files.
- Feedback/queueing: repository notes (e.g., `Claude.MD`) mention message queue order and user feedback during tasks — prefer enqueueing long-running operations (provisioning, cert issuance, link preview jobs) into the worker queue and send status updates to the Portal.

**Developer workflows & important commands**
- Start infra (local server): `docker compose up -d` from repo root.
- Edit zone file: `sed -i "s/\${HOST_IP}/$HOST_IP/g" coredns/zones/devkanban.io.db` (see README for exact usage).
- Issue initial certs (example): `docker exec devkanban-certbot certbot certonly --webroot -w /var/www/certbot -d app.devkanban.io -d api.devkanban.io --email admin@devkanban.io --agree-tos --non-interactive` then `docker compose restart traefik`.
- Provision a team: code paths to review: `portal/backend/app/services/team_provisioner.py` and `orchestrator/app/provisioner.py`. Use the Jinja templates in `orchestrator/templates/` for changes.

**Integration points & external dependencies**
- Azure: Key Vault (`AZURE_KEY_VAULT_URL`) and Microsoft Entra ID (see `portal/backend/app/auth/entra.py`) for auth and secrets.
- DNS: external registrar must point NS records to this host (see README sample records).
- External APIs: Twitter, GitHub, YouTube used for link previews — tokens stored in Key Vault.

**What to change vs. where to change it**
- UI/UX changes: update `portal/frontend/` or `team-template/frontend/src/components/`.
- API/Provisioning logic: change `portal/backend/app/services/team_provisioner.py` and `orchestrator/app/provisioner.py` together to keep templates and provisioner in sync.
- Template changes: modify `orchestrator/templates/docker-compose.team.yml.j2` and `team-template/docker-compose.yml.j2` — tests of template rendering should be done in a disposable environment.

**Quick pointers for AI edits**
- Keep patches minimal and targeted to the component you change; update corresponding Jinja templates when adding services.
- When modifying infra (DNS/Traefik/Certbot), include an explicit restart step and mention any manual cert issuance steps in the PR description.
- If you add background jobs, ensure they are queued (worker) and instrumented to emit user-facing progress messages (see `Claude.MD` guidance).

If anything here is unclear or you want more examples (unit tests, local run scripts, or a checklist for provisioning), tell me which area to expand and I will update this file.
