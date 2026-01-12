# /run-e2e-tests

Run Playwright E2E tests to validate the workspace invitation flow.

## What It Tests

This test suite validates the complete user journey:

1. **Account authentication** - Owner logs in via JWT token
2. **Workspace creation** - Creates a "Kanban Only" workspace
3. **Member invitation** - Owner invites a new member via email
4. **Invitation viewing** - Invitee sees the invitation page (unauthenticated)
5. **Invitation acceptance** - Invitee accepts and joins the workspace
6. **Member verification** - Confirms the member appears in workspace

## Usage

```bash
./scripts/run-e2e-tests.sh [options]
```

## Options

| Option | Description |
|--------|-------------|
| `--filter <pattern>` | Run only tests matching the pattern |
| `--headed` | Run in headed mode (show browser) |
| `--debug` | Run in debug mode |
| `--cleanup-only` | Only cleanup test workspaces, don't run tests |

## Examples

```bash
# Run all E2E tests (generates token automatically)
./scripts/run-e2e-tests.sh

# Run only invitation flow tests
./scripts/run-e2e-tests.sh --filter "Invitation Flow"

# Run the full E2E flow test only
./scripts/run-e2e-tests.sh --filter "Full E2E"

# Just cleanup test workspaces
./scripts/run-e2e-tests.sh --cleanup-only
```

## Test Workspaces

The tests use fixed workspace names for consistent cleanup:

- `e2e-test-invitation` - Used by serial invitation flow tests
- `e2e-full-flow-test` - Used by the full E2E flow test

These workspaces are automatically deleted before and after tests run.

## Prerequisites

1. **Portal API running** - The `kanban-portal-api` container must be running
2. **Network access** - Tests connect to `https://kanban.amazing-ai.tools`
3. **Docker** - Tests run in a Playwright Docker container

## How It Works

1. Generates a fresh JWT token from the portal API container
2. Builds the Playwright Docker image (`kanban-e2e-tests`)
3. Runs tests against the live portal
4. Cleans up test workspaces before and after

## Test Results

Screenshots are saved to `e2e-tests/results/`:

```
e2e-tests/results/
├── 01-portal-accessible.png
├── 02-owner-authenticated.png
├── 03-create-workspace-page.png
├── ...
├── full-01-workspace-created.png
├── full-02-invite-sent.png
└── full-03-invite-page.png
```

## Related Files

- Test script: `scripts/run-e2e-tests.sh`
- Test spec: `e2e-tests/tests/workspace-invitation-flow.spec.ts`
- Docker runner: `e2e-tests/run-tests.sh`
- Dockerfile: `e2e-tests/Dockerfile`
