# Kanban API Test Plan

## Overview

This test plan covers the complete flow of the Kanban APIs using **Portal API tokens** (`pk_*` prefix) for programmatic authentication.

## Authentication Strategy

All tests use Portal API tokens with specific scopes:
- **Full Access Token**: `["*"]` - For complete workflow tests
- **Read-Only Token**: `["teams:read", "boards:read", "cards:read", "members:read"]`
- **Teams-Only Token**: `["teams:read", "teams:write"]`
- **Cards-Only Token**: `["cards:read", "cards:write"]`

## Test Structure

```
portal/backend/tests/
├── conftest.py                      # Shared fixtures
├── factories.py                     # Test data factories
├── test_portal_tokens.py            # Portal API token CRUD
├── test_team_management.py          # Team CRUD operations
├── test_team_members.py             # Member management
├── test_boards.py                   # Board operations
├── test_columns.py                  # Column CRUD
├── test_cards.py                    # Card operations
├── test_labels.py                   # Label listing
├── test_scope_authorization.py      # Scope-based access control
├── test_workflow_integration.py     # End-to-end workflows
└── test_error_handling.py           # Error cases
```

---

## 1. Portal Token Management Tests

**File**: `test_portal_tokens.py`

| Test ID | Test Name | Description | Expected Result |
|---------|-----------|-------------|-----------------|
| PT-001 | `test_create_token_with_jwt` | Create token using JWT auth | 200, returns `pk_*` token |
| PT-002 | `test_create_token_with_specific_scopes` | Create with `["teams:read", "boards:write"]` | Token has exact scopes |
| PT-003 | `test_create_token_with_wildcard` | Create with `["*"]` | Token has full access |
| PT-004 | `test_create_token_with_expiry` | Create with `expires_at` | Token expires at specified time |
| PT-005 | `test_create_token_without_auth` | No Authorization header | 401 Unauthorized |
| PT-006 | `test_create_token_with_invalid_jwt` | Malformed JWT | 401 Unauthorized |
| PT-007 | `test_list_tokens` | List user's tokens | 200, returns array |
| PT-008 | `test_list_tokens_only_shows_own` | User cannot see others' tokens | Returns only own tokens |
| PT-009 | `test_delete_token` | Delete token by ID | 200, token invalidated |
| PT-010 | `test_delete_token_not_owner` | Delete another user's token | 403 Forbidden |
| PT-011 | `test_delete_nonexistent_token` | Delete non-existent token | 404 Not Found |
| PT-012 | `test_validate_token_valid` | Validate valid `pk_*` token | `{"valid": true, ...}` |
| PT-013 | `test_validate_token_expired` | Validate expired token | `{"valid": false}` |
| PT-014 | `test_validate_token_revoked` | Validate deleted token | `{"valid": false}` |
| PT-015 | `test_validate_token_invalid_format` | Validate malformed token | `{"valid": false}` |

---

## 2. Team Management Tests

**File**: `test_team_management.py`

| Test ID | Test Name | Scope Required | Expected Result |
|---------|-----------|----------------|-----------------|
| TM-001 | `test_create_team` | `teams:write` | 200, team + task_id |
| TM-002 | `test_create_team_duplicate_slug` | `teams:write` | 409 Conflict |
| TM-003 | `test_create_team_invalid_slug` | `teams:write` | 422 Validation Error |
| TM-004 | `test_create_team_reserved_slug` | `teams:write` | 422 (admin, api, www) |
| TM-005 | `test_create_team_without_scope` | read-only | 403 Forbidden |
| TM-006 | `test_list_teams` | any auth | 200, teams array |
| TM-007 | `test_get_team_by_slug` | any auth | 200, team details |
| TM-008 | `test_get_team_not_member` | any auth | 403 Forbidden |
| TM-009 | `test_get_team_not_found` | any auth | 404 Not Found |
| TM-010 | `test_update_team` | `teams:write` | 200, updated team |
| TM-011 | `test_update_team_non_admin` | `teams:write` | 403 Forbidden |
| TM-012 | `test_delete_team` | `teams:write` | 200, task_id |
| TM-013 | `test_delete_team_non_owner` | `teams:write` | 403 Forbidden |
| TM-014 | `test_get_team_status` | any auth | 200, status object |
| TM-015 | `test_restart_team` | `teams:write` | 200, task_id |
| TM-016 | `test_restart_team_rebuild` | `teams:write` | 200, rebuild=true |

---

## 3. Team Members Tests

**File**: `test_team_members.py`

| Test ID | Test Name | Scope Required | Expected Result |
|---------|-----------|----------------|-----------------|
| MB-001 | `test_list_members` | any auth | 200, members array |
| MB-002 | `test_list_members_not_member` | any auth | 403 Forbidden |
| MB-003 | `test_add_member` | `members:write` | 200, success |
| MB-004 | `test_add_member_already_exists` | `members:write` | 409 Conflict |
| MB-005 | `test_add_member_user_not_found` | `members:write` | 404 Not Found |
| MB-006 | `test_add_member_without_scope` | read-only | 403 Forbidden |
| MB-007 | `test_remove_member` | `members:write` | 200, success |
| MB-008 | `test_remove_owner` | `members:write` | 400 Bad Request |
| MB-009 | `test_remove_self` | `members:write` | 200, success |
| MB-010 | `test_remove_member_non_admin` | `members:write` | 403 Forbidden |

---

## 4. Board Tests

**File**: `test_boards.py`

| Test ID | Test Name | Scope Required | Expected Result |
|---------|-----------|----------------|-----------------|
| BD-001 | `test_list_boards` | `boards:read` | 200, boards array |
| BD-002 | `test_list_boards_without_scope` | `cards:read` only | 403 Forbidden |
| BD-003 | `test_get_board` | `boards:read` | 200, board with columns/cards |
| BD-004 | `test_get_board_include_archived` | `boards:read` | 200, includes archived cards |
| BD-005 | `test_get_board_not_found` | `boards:read` | 404 Not Found |
| BD-006 | `test_list_board_labels` | `boards:read` | 200, labels array |

---

## 5. Column Tests

**File**: `test_columns.py`

| Test ID | Test Name | Scope Required | Expected Result |
|---------|-----------|----------------|-----------------|
| CL-001 | `test_list_columns` | `boards:read` | 200, columns array |
| CL-002 | `test_list_columns_by_board` | `boards:read` | 200, filtered columns |
| CL-003 | `test_create_column` | `boards:write` | 200, new column |
| CL-004 | `test_create_column_with_wip_limit` | `boards:write` | 200, wip_limit set |
| CL-005 | `test_create_column_without_scope` | `boards:read` only | 403 Forbidden |
| CL-006 | `test_update_column_name` | `boards:write` | 200, updated |
| CL-007 | `test_update_column_position` | `boards:write` | 200, reordered |
| CL-008 | `test_update_column_wip_limit` | `boards:write` | 200, wip_limit changed |
| CL-009 | `test_delete_column` | `boards:write` | 200, deleted |
| CL-010 | `test_delete_column_with_cards` | `boards:write` | Cards moved/deleted |

---

## 6. Card Tests

**File**: `test_cards.py`

| Test ID | Test Name | Scope Required | Expected Result |
|---------|-----------|----------------|-----------------|
| CD-001 | `test_list_cards` | `cards:read` | 200, cards array |
| CD-002 | `test_list_cards_by_column` | `cards:read` | 200, filtered cards |
| CD-003 | `test_list_cards_archived` | `cards:read` | 200, archived cards |
| CD-004 | `test_create_card` | `cards:write` | 200, new card |
| CD-005 | `test_create_card_full_fields` | `cards:write` | 200, all fields set |
| CD-006 | `test_create_card_wip_limit_exceeded` | `cards:write` | 400 WIP limit |
| CD-007 | `test_create_card_without_scope` | `cards:read` only | 403 Forbidden |
| CD-008 | `test_get_card` | `cards:read` | 200, card details |
| CD-009 | `test_get_card_not_found` | `cards:read` | 404 Not Found |
| CD-010 | `test_update_card_title` | `cards:write` | 200, updated |
| CD-011 | `test_update_card_description` | `cards:write` | 200, updated |
| CD-012 | `test_update_card_priority` | `cards:write` | 200, priority changed |
| CD-013 | `test_update_card_labels` | `cards:write` | 200, labels updated |
| CD-014 | `test_update_card_assignee` | `cards:write` | 200, assignee set |
| CD-015 | `test_update_card_due_date` | `cards:write` | 200, due_date set |
| CD-016 | `test_delete_card` | `cards:write` | 200, deleted |
| CD-017 | `test_move_card_to_column` | `cards:write` | 200, moved |
| CD-018 | `test_move_card_same_column` | `cards:write` | 200, reordered |
| CD-019 | `test_move_card_wip_limit` | `cards:write` | 400 WIP limit |
| CD-020 | `test_archive_card` | `cards:write` | 200, archived=true |
| CD-021 | `test_archive_already_archived` | `cards:write` | 400 Already archived |
| CD-022 | `test_restore_card` | `cards:write` | 200, restored |
| CD-023 | `test_restore_not_archived` | `cards:write` | 400 Not archived |

---

## 7. Scope Authorization Tests

**File**: `test_scope_authorization.py`

Systematic tests verifying scope-based access control.

### Scope Matrix

| Endpoint | Required Scope | Allowed Tokens |
|----------|----------------|----------------|
| `GET /teams` | any | all |
| `POST /teams` | `teams:write` | full, teams |
| `PUT /teams/{slug}` | `teams:write` | full, teams |
| `DELETE /teams/{slug}` | `teams:write` | full, teams |
| `GET /teams/{slug}/members` | any | all |
| `POST /teams/{slug}/members` | `members:write` | full, members |
| `DELETE /teams/{slug}/members/{id}` | `members:write` | full, members |
| `GET /teams/{slug}/boards` | `boards:read` | full, boards, read-only |
| `POST /teams/{slug}/columns` | `boards:write` | full, boards |
| `GET /teams/{slug}/cards` | `cards:read` | full, cards, read-only |
| `POST /teams/{slug}/cards` | `cards:write` | full, cards |
| `POST /teams/{slug}/cards/{id}/move` | `cards:write` | full, cards |
| `POST /teams/{slug}/cards/{id}/archive` | `cards:write` | full, cards |

### Test Cases

| Test ID | Test Name | Description |
|---------|-----------|-------------|
| SA-001 | `test_wildcard_grants_all_access` | Token with `["*"]` accesses all endpoints |
| SA-002 | `test_missing_scope_returns_403` | Clear error message on scope mismatch |
| SA-003 | `test_read_scope_blocks_write` | `cards:read` cannot POST cards |
| SA-004 | `test_write_scope_includes_read` | `cards:write` can GET cards |
| SA-005 | `test_cross_category_isolation` | `teams:*` cannot access boards |

---

## 8. Workflow Integration Tests

**File**: `test_workflow_integration.py`

End-to-end tests simulating real usage scenarios.

### Test Workflows

| Test ID | Test Name | Description |
|---------|-----------|-------------|
| WF-001 | `test_complete_kanban_workflow` | Full cycle: team → board → columns → cards → move → archive |
| WF-002 | `test_team_onboarding_workflow` | Create team → add members → create first board |
| WF-003 | `test_card_lifecycle` | Create → update → move → archive → restore → delete |
| WF-004 | `test_multi_board_organization` | Multiple boards, cards across boards |
| WF-005 | `test_wip_limit_enforcement` | Fill column to WIP limit, verify blocking |
| WF-006 | `test_auto_start_suspended_team` | Access suspended team, verify auto-start |
| WF-007 | `test_sprint_planning_workflow` | Create backlog → prioritize → move to sprint |

### WF-001: Complete Kanban Workflow

```
Step 1: Create Portal API token with full access
Step 2: Create team "test-workflow"
Step 3: Wait for team provisioning (poll status)
Step 4: List boards (default board created)
Step 5: Create columns: Backlog, Development, Review, Done
Step 6: Create 3 cards in Backlog
Step 7: Move card 1 to Development
Step 8: Move card 1 to Review
Step 9: Move card 1 to Done
Step 10: Archive card 1
Step 11: Verify archived card appears with include_archived=true
Step 12: Restore card 1
Step 13: Delete card 1
Step 14: Cleanup: delete team
```

---

## 9. Error Handling Tests

**File**: `test_error_handling.py`

| Test ID | Test Name | Expected Result |
|---------|-----------|-----------------|
| EH-001 | `test_invalid_token_format` | 401 Unauthorized |
| EH-002 | `test_expired_token` | 401 Unauthorized |
| EH-003 | `test_revoked_token` | 401 Unauthorized |
| EH-004 | `test_missing_auth_header` | 401 Unauthorized |
| EH-005 | `test_wrong_auth_scheme` | 401 (Basic vs Bearer) |
| EH-006 | `test_team_not_found` | 404 Not Found |
| EH-007 | `test_team_not_member` | 403 Forbidden |
| EH-008 | `test_card_not_found` | 404 Not Found |
| EH-009 | `test_column_not_found` | 404 Not Found |
| EH-010 | `test_invalid_json` | 422 Validation Error |
| EH-011 | `test_missing_required_fields` | 422 Validation Error |
| EH-012 | `test_invalid_field_types` | 422 Validation Error |
| EH-013 | `test_team_api_unavailable` | 503 Service Unavailable |
| EH-014 | `test_team_api_timeout` | 504 Gateway Timeout |

---

## 10. Message Queue & Async Task Tests

Per project requirements, async operations provide user feedback.

| Test ID | Test Name | Description |
|---------|-----------|-------------|
| MQ-001 | `test_team_provision_returns_task_id` | POST /teams returns task_id |
| MQ-002 | `test_team_delete_returns_task_id` | DELETE /teams/{slug} returns task_id |
| MQ-003 | `test_team_restart_returns_task_id` | POST /teams/{slug}/restart returns task_id |
| MQ-004 | `test_status_reflects_progress` | GET /teams/{slug}/status shows current state |
| MQ-005 | `test_task_completion_feedback` | Task completes with success message |
| MQ-006 | `test_task_failure_feedback` | Failed task returns error details |

---

## Test Fixtures

### conftest.py

```python
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from app.main import app

@pytest_asyncio.fixture
async def test_client():
    """Async HTTP client for testing"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

@pytest.fixture
def portal_token_full_access(test_client, jwt_token):
    """Portal API token with full access"""
    # Implementation: POST /portal/tokens with scopes=["*"]
    pass

@pytest.fixture
def portal_token_read_only(test_client, jwt_token):
    """Portal API token with read-only scopes"""
    # Implementation: POST /portal/tokens with read scopes
    pass

@pytest.fixture
def test_team(test_client, portal_token_full_access):
    """Pre-provisioned test team"""
    # Create and wait for team provisioning
    pass

@pytest.fixture
def test_board(test_team):
    """Test board in test team"""
    pass

@pytest.fixture
def test_columns(test_board):
    """Standard columns: To Do, In Progress, Done"""
    pass

@pytest.fixture
def test_card(test_columns):
    """Test card in first column"""
    pass
```

---

## Running Tests

### Docker (Recommended)

Tests run in an isolated Docker container with its own Redis instance:

```bash
cd portal/backend

# Run all tests with coverage (creates container, runs tests, cleans up)
./run-tests.sh

# Run specific test file
./run-tests.sh tests/test_portal_tokens.py

# Run tests matching pattern
./run-tests.sh -k "test_create"

# Run only workflow tests
./run-tests.sh tests/test_workflow_integration.py -v

# Run excluding slow tests
./run-tests.sh -m "not slow"
```

**Docker Compose directly:**

```bash
# Build and run all tests
docker-compose -f docker-compose.test.yml up --build --abort-on-container-exit

# Cleanup after tests
docker-compose -f docker-compose.test.yml down --volumes
```

**Test Reports:**
- Coverage HTML: `test-reports/coverage/index.html`
- JUnit XML: `test-reports/junit.xml`

### Local (Development)

```bash
# Install dependencies
pip install -r requirements-test.txt

# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=app --cov-report=html

# Run specific test file
pytest tests/test_cards.py -v

# Run by test ID pattern
pytest tests/ -k "CD-001"

# Run workflow tests only
pytest tests/test_workflow_integration.py -v

# Run excluding slow integration tests
pytest tests/ -m "not slow"
```

---

## Test Dependencies

Add to `requirements-dev.txt`:

```
pytest>=7.4.0
pytest-asyncio>=0.23.0
pytest-cov>=4.1.0
pytest-timeout>=2.2.0
httpx>=0.25.0
respx>=0.20.0
factory-boy>=3.3.0
freezegun>=1.4.0
```

---

## Coverage Goals

| Module | Target Coverage |
|--------|-----------------|
| `app/auth/unified.py` | 95% |
| `app/routes/portal_api.py` | 90% |
| `app/routes/teams.py` | 90% |
| `app/routes/team_api.py` | 85% |
| `app/services/team_proxy.py` | 80% |

---

## Test Priority

1. **P0 - Critical**: Authentication, authorization, team CRUD
2. **P1 - High**: Card operations, workflow integration
3. **P2 - Medium**: Column operations, labels, error handling
4. **P3 - Low**: Edge cases, performance tests
