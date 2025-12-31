"""Workflow Integration Tests

End-to-end tests simulating real kanban usage scenarios using Portal API tokens.
These tests verify the complete flow from team creation to card management.
"""

import pytest
import uuid
from datetime import datetime

from tests.factories import (
    create_user, create_team, create_board, create_column, create_card,
    create_portal_token, team_create_request, card_create_request,
    column_create_request, card_move_request
)


# =============================================================================
# WF-001: Complete Kanban Workflow
# =============================================================================

class TestCompleteKanbanWorkflow:
    """
    WF-001: Full cycle test
    team -> board -> columns -> cards -> move -> archive
    """

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_complete_kanban_workflow(
        self,
        test_client,
        mock_db,
        mock_task_service,
        mock_team_proxy,
        test_user
    ):
        """Complete workflow using Portal API token with full access"""
        # Setup: Create test data
        team = create_team(slug="workflow-team", owner_id=test_user["id"], status="active")
        board = create_board(name="Sprint Board", owner_id=test_user["id"])
        columns = [
            create_column(board_id=board["id"], name="Backlog", position=0),
            create_column(board_id=board["id"], name="Development", position=1),
            create_column(board_id=board["id"], name="Review", position=2),
            create_column(board_id=board["id"], name="Done", position=3)
        ]
        card = create_card(
            column_id=columns[0]["id"],
            title="Implement feature X",
            priority="high",
            created_by=test_user["id"]
        )

        # Setup mocks
        portal_token = create_portal_token(created_by=test_user["id"], scopes=["*"])
        mock_db.get_portal_api_token_by_hash.return_value = portal_token
        mock_db.get_user_by_id.return_value = test_user
        mock_db.get_team_by_slug.return_value = team
        mock_db.get_membership.return_value = {
            "user_id": test_user["id"],
            "team_id": team["id"],
            "role": "owner"
        }

        headers = {"Authorization": "Bearer pk_test_full_access_token"}

        # Step 1: List teams to verify access
        mock_db.get_user_teams.return_value = [team]
        response = await test_client.get("/teams", headers=headers)
        assert response.status_code == 200

        # Step 2: Get team details
        response = await test_client.get(f"/teams/{team['slug']}", headers=headers)
        assert response.status_code == 200

        # Step 3: List boards via team proxy
        mock_team_proxy.get.return_value = (200, [board])
        response = await test_client.get(f"/teams/{team['slug']}/boards", headers=headers)
        assert response.status_code == 200

        # Step 4: List columns
        mock_team_proxy.get.return_value = (200, columns)
        response = await test_client.get(f"/teams/{team['slug']}/columns", headers=headers)
        assert response.status_code == 200

        # Step 5: Create a card in Backlog
        new_card = create_card(column_id=columns[0]["id"], title="New Task")
        mock_team_proxy.post.return_value = (200, new_card)
        response = await test_client.post(
            f"/teams/{team['slug']}/cards",
            json=card_create_request(column_id=columns[0]["id"], title="New Task"),
            headers=headers
        )
        assert response.status_code == 200
        created_card_id = response.json()["id"]

        # Step 6: Move card to Development
        moved_card = {**new_card, "column_id": columns[1]["id"]}
        mock_team_proxy.post.return_value = (200, moved_card)
        response = await test_client.post(
            f"/teams/{team['slug']}/cards/{created_card_id}/move",
            json=card_move_request(column_id=columns[1]["id"]),
            headers=headers
        )
        assert response.status_code == 200

        # Step 7: Move card to Review
        moved_card = {**new_card, "column_id": columns[2]["id"]}
        mock_team_proxy.post.return_value = (200, moved_card)
        response = await test_client.post(
            f"/teams/{team['slug']}/cards/{created_card_id}/move",
            json=card_move_request(column_id=columns[2]["id"]),
            headers=headers
        )
        assert response.status_code == 200

        # Step 8: Move card to Done
        moved_card = {**new_card, "column_id": columns[3]["id"]}
        mock_team_proxy.post.return_value = (200, moved_card)
        response = await test_client.post(
            f"/teams/{team['slug']}/cards/{created_card_id}/move",
            json=card_move_request(column_id=columns[3]["id"]),
            headers=headers
        )
        assert response.status_code == 200

        # Step 9: Archive completed card
        archived_card = {**moved_card, "archived": True}
        mock_team_proxy.post.return_value = (200, archived_card)
        response = await test_client.post(
            f"/teams/{team['slug']}/cards/{created_card_id}/archive",
            headers=headers
        )
        assert response.status_code == 200
        assert response.json()["archived"] is True


# =============================================================================
# WF-003: Card Lifecycle
# =============================================================================

class TestCardLifecycle:
    """
    WF-003: Card lifecycle test
    create -> update -> move -> archive -> restore -> delete
    """

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_card_lifecycle(
        self,
        test_client,
        mock_db,
        mock_team_proxy,
        test_user
    ):
        """Test complete card lifecycle operations"""
        # Setup
        team = create_team(slug="card-test-team", owner_id=test_user["id"])
        board = create_board(owner_id=test_user["id"])
        columns = [
            create_column(board_id=board["id"], name="To Do", position=0),
            create_column(board_id=board["id"], name="Done", position=1)
        ]

        portal_token = create_portal_token(created_by=test_user["id"], scopes=["*"])
        mock_db.get_portal_api_token_by_hash.return_value = portal_token
        mock_db.get_user_by_id.return_value = test_user
        mock_db.get_team_by_slug.return_value = team
        mock_db.get_membership.return_value = {"role": "owner"}

        headers = {"Authorization": "Bearer pk_test_token"}

        # 1. Create card
        new_card = create_card(
            column_id=columns[0]["id"],
            title="Lifecycle Test Card",
            description="Initial description"
        )
        mock_team_proxy.post.return_value = (200, new_card)

        response = await test_client.post(
            f"/teams/{team['slug']}/cards",
            json=card_create_request(
                column_id=columns[0]["id"],
                title="Lifecycle Test Card",
                description="Initial description"
            ),
            headers=headers
        )
        assert response.status_code == 200
        card_id = response.json()["id"]

        # 2. Update card
        updated_card = {**new_card, "title": "Updated Title", "priority": "high"}
        mock_team_proxy.patch.return_value = (200, updated_card)

        response = await test_client.patch(
            f"/teams/{team['slug']}/cards/{card_id}",
            json={"title": "Updated Title", "priority": "high"},
            headers=headers
        )
        assert response.status_code == 200
        assert response.json()["title"] == "Updated Title"

        # 3. Move card to Done
        moved_card = {**updated_card, "column_id": columns[1]["id"]}
        mock_team_proxy.post.return_value = (200, moved_card)

        response = await test_client.post(
            f"/teams/{team['slug']}/cards/{card_id}/move",
            json=card_move_request(column_id=columns[1]["id"]),
            headers=headers
        )
        assert response.status_code == 200

        # 4. Archive card
        archived_card = {**moved_card, "archived": True}
        mock_team_proxy.post.return_value = (200, archived_card)

        response = await test_client.post(
            f"/teams/{team['slug']}/cards/{card_id}/archive",
            headers=headers
        )
        assert response.status_code == 200
        assert response.json()["archived"] is True

        # 5. Restore card
        restored_card = {**archived_card, "archived": False}
        mock_team_proxy.post.return_value = (200, restored_card)

        response = await test_client.post(
            f"/teams/{team['slug']}/cards/{card_id}/restore",
            headers=headers
        )
        assert response.status_code == 200
        assert response.json()["archived"] is False

        # 6. Delete card
        mock_team_proxy.delete.return_value = (200, {"deleted": True})

        response = await test_client.delete(
            f"/teams/{team['slug']}/cards/{card_id}",
            headers=headers
        )
        assert response.status_code == 200


# =============================================================================
# WF-005: WIP Limit Enforcement
# =============================================================================

class TestWipLimitEnforcement:
    """
    WF-005: WIP limit enforcement test
    Fill column to WIP limit, verify blocking
    """

    @pytest.mark.asyncio
    async def test_wip_limit_blocks_new_cards(
        self,
        test_client,
        mock_db,
        mock_team_proxy,
        test_user
    ):
        """Cannot create card when column is at WIP limit"""
        team = create_team(slug="wip-test", owner_id=test_user["id"])
        column_with_limit = create_column(
            name="In Progress",
            position=1,
            wip_limit=2  # Max 2 cards
        )

        portal_token = create_portal_token(created_by=test_user["id"], scopes=["*"])
        mock_db.get_portal_api_token_by_hash.return_value = portal_token
        mock_db.get_user_by_id.return_value = test_user
        mock_db.get_team_by_slug.return_value = team
        mock_db.get_membership.return_value = {"role": "owner"}

        headers = {"Authorization": "Bearer pk_test_token"}

        # Team proxy returns 400 when WIP limit exceeded
        mock_team_proxy.post.return_value = (400, {"detail": "WIP limit reached for column"})

        response = await test_client.post(
            f"/teams/{team['slug']}/cards",
            json=card_create_request(column_id=column_with_limit["id"], title="Third Card"),
            headers=headers
        )

        assert response.status_code == 400
        assert "WIP limit" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_wip_limit_blocks_move(
        self,
        test_client,
        mock_db,
        mock_team_proxy,
        test_user
    ):
        """Cannot move card to column at WIP limit"""
        team = create_team(slug="wip-move-test", owner_id=test_user["id"])
        source_column = create_column(name="To Do", position=0)
        target_column = create_column(name="In Progress", position=1, wip_limit=2)
        card = create_card(column_id=source_column["id"])

        portal_token = create_portal_token(created_by=test_user["id"], scopes=["*"])
        mock_db.get_portal_api_token_by_hash.return_value = portal_token
        mock_db.get_user_by_id.return_value = test_user
        mock_db.get_team_by_slug.return_value = team
        mock_db.get_membership.return_value = {"role": "owner"}

        headers = {"Authorization": "Bearer pk_test_token"}

        # Team proxy returns 400 when WIP limit exceeded
        mock_team_proxy.post.return_value = (400, {"detail": "WIP limit reached for target column"})

        response = await test_client.post(
            f"/teams/{team['slug']}/cards/{card['id']}/move",
            json=card_move_request(column_id=target_column["id"]),
            headers=headers
        )

        assert response.status_code == 400


# =============================================================================
# WF-002: Team Onboarding Workflow
# =============================================================================

class TestTeamOnboardingWorkflow:
    """
    WF-002: Team onboarding workflow
    Create team -> wait provisioning -> add members -> create first board
    """

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_team_onboarding(
        self,
        test_client,
        mock_db,
        mock_task_service,
        mock_team_proxy,
        test_user,
        another_user_data
    ):
        """Complete team onboarding workflow"""
        team_slug = f"onboard-{uuid.uuid4().hex[:8]}"
        team = create_team(slug=team_slug, owner_id=test_user["id"], status="pending")

        portal_token = create_portal_token(created_by=test_user["id"], scopes=["*"])
        mock_db.get_portal_api_token_by_hash.return_value = portal_token
        mock_db.get_user_by_id.return_value = test_user

        headers = {"Authorization": "Bearer pk_test_token"}

        # Step 1: Create team (returns task_id for provisioning)
        mock_db.get_team_by_slug.return_value = None  # Team doesn't exist yet
        mock_db.create_team.return_value = team
        mock_db.create_membership.return_value = True
        mock_task_service.create_team_provision_task.return_value = "task-123"

        response = await test_client.post(
            "/teams",
            json=team_create_request(name="Onboarding Team", slug=team_slug),
            headers=headers
        )

        assert response.status_code == 200
        data = response.json()
        assert "task_id" in data
        assert data["team"]["slug"] == team_slug

        # Step 2: Check team status (simulating polling)
        active_team = {**team, "status": "active"}
        mock_db.get_team_by_slug.return_value = active_team
        mock_db.get_membership.return_value = {"role": "owner"}

        response = await test_client.get(
            f"/teams/{team_slug}/status",
            headers=headers
        )

        assert response.status_code == 200
        assert response.json()["status"] == "active"

        # Step 3: Add a team member
        mock_db.get_user_by_email.return_value = another_user_data
        mock_db.get_membership.side_effect = [
            {"role": "owner"},  # For auth check
            None  # Member doesn't exist yet
        ]
        mock_db.create_membership.return_value = True
        mock_team_proxy.post.return_value = (200, {"message": "Member added"})

        response = await test_client.post(
            f"/teams/{team_slug}/members",
            json={"email": another_user_data["email"], "role": "member"},
            headers=headers
        )

        assert response.status_code == 200

        # Step 4: List team members
        mock_db.get_membership.return_value = {"role": "owner"}
        mock_db.get_team_members.return_value = [
            {"user_id": test_user["id"], "role": "owner"},
            {"user_id": another_user_data["id"], "role": "member"}
        ]

        response = await test_client.get(
            f"/teams/{team_slug}/members",
            headers=headers
        )

        assert response.status_code == 200
        assert len(response.json()) == 2


# =============================================================================
# WF-007: Sprint Planning Workflow
# =============================================================================

class TestSprintPlanningWorkflow:
    """
    WF-007: Sprint planning workflow
    Create backlog items -> prioritize -> move to sprint column
    """

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_sprint_planning(
        self,
        test_client,
        mock_db,
        mock_team_proxy,
        test_user
    ):
        """Sprint planning workflow with backlog prioritization"""
        team = create_team(slug="sprint-team", owner_id=test_user["id"])
        board = create_board(name="Sprint Board")
        backlog = create_column(board_id=board["id"], name="Backlog", position=0)
        sprint = create_column(board_id=board["id"], name="Sprint", position=1, wip_limit=5)

        portal_token = create_portal_token(created_by=test_user["id"], scopes=["*"])
        mock_db.get_portal_api_token_by_hash.return_value = portal_token
        mock_db.get_user_by_id.return_value = test_user
        mock_db.get_team_by_slug.return_value = team
        mock_db.get_membership.return_value = {"role": "owner"}

        headers = {"Authorization": "Bearer pk_test_token"}

        # Create backlog items with different priorities
        backlog_items = []
        priorities = ["low", "medium", "high", "high", "medium"]

        for i, priority in enumerate(priorities):
            card = create_card(
                column_id=backlog["id"],
                title=f"Task {i+1}",
                priority=priority,
                position=i
            )
            backlog_items.append(card)
            mock_team_proxy.post.return_value = (200, card)

            response = await test_client.post(
                f"/teams/{team['slug']}/cards",
                json=card_create_request(
                    column_id=backlog["id"],
                    title=f"Task {i+1}",
                    priority=priority
                ),
                headers=headers
            )
            assert response.status_code == 200

        # Move high priority items to sprint
        high_priority_cards = [c for c in backlog_items if c["priority"] == "high"]

        for card in high_priority_cards:
            moved_card = {**card, "column_id": sprint["id"]}
            mock_team_proxy.post.return_value = (200, moved_card)

            response = await test_client.post(
                f"/teams/{team['slug']}/cards/{card['id']}/move",
                json=card_move_request(column_id=sprint["id"]),
                headers=headers
            )
            assert response.status_code == 200

        # Verify sprint has the high priority items
        sprint_cards = [c for c in backlog_items if c["priority"] == "high"]
        mock_team_proxy.get.return_value = (200, sprint_cards)

        response = await test_client.get(
            f"/teams/{team['slug']}/cards",
            params={"column_id": sprint["id"]},
            headers=headers
        )
        assert response.status_code == 200


# =============================================================================
# Scope-Restricted Workflow Tests
# =============================================================================

class TestScopeRestrictedWorkflow:
    """Test workflows with limited scopes"""

    @pytest.mark.asyncio
    async def test_read_only_workflow(
        self,
        test_client,
        mock_db,
        mock_team_proxy,
        test_user
    ):
        """Read-only token can view but not modify"""
        team = create_team(slug="readonly-test", owner_id=test_user["id"])
        board = create_board()
        columns = [create_column(board_id=board["id"], name="To Do")]

        # Read-only token
        portal_token = create_portal_token(
            created_by=test_user["id"],
            scopes=["teams:read", "boards:read", "cards:read"]
        )
        mock_db.get_portal_api_token_by_hash.return_value = portal_token
        mock_db.get_user_by_id.return_value = test_user
        mock_db.get_team_by_slug.return_value = team
        mock_db.get_membership.return_value = {"role": "member"}
        mock_db.get_user_teams.return_value = [team]

        headers = {"Authorization": "Bearer pk_readonly_token"}

        # Can list teams
        response = await test_client.get("/teams", headers=headers)
        assert response.status_code == 200

        # Can list boards
        mock_team_proxy.get.return_value = (200, [board])
        response = await test_client.get(f"/teams/{team['slug']}/boards", headers=headers)
        assert response.status_code == 200

        # Cannot create cards (missing cards:write)
        response = await test_client.post(
            f"/teams/{team['slug']}/cards",
            json=card_create_request(column_id=columns[0]["id"]),
            headers=headers
        )
        assert response.status_code == 403
        assert "cards:write" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_cards_only_workflow(
        self,
        test_client,
        mock_db,
        mock_team_proxy,
        test_user
    ):
        """Cards-only token can manage cards but not teams/boards"""
        team = create_team(slug="cards-only-test", owner_id=test_user["id"])
        column = create_column(name="To Do")
        card = create_card(column_id=column["id"])

        # Cards-only token
        portal_token = create_portal_token(
            created_by=test_user["id"],
            scopes=["cards:read", "cards:write"]
        )
        mock_db.get_portal_api_token_by_hash.return_value = portal_token
        mock_db.get_user_by_id.return_value = test_user
        mock_db.get_team_by_slug.return_value = team
        mock_db.get_membership.return_value = {"role": "member"}

        headers = {"Authorization": "Bearer pk_cards_only_token"}

        # Can list cards
        mock_team_proxy.get.return_value = (200, [card])
        response = await test_client.get(f"/teams/{team['slug']}/cards", headers=headers)
        assert response.status_code == 200

        # Can create cards
        new_card = create_card(column_id=column["id"], title="New Card")
        mock_team_proxy.post.return_value = (200, new_card)
        response = await test_client.post(
            f"/teams/{team['slug']}/cards",
            json=card_create_request(column_id=column["id"], title="New Card"),
            headers=headers
        )
        assert response.status_code == 200

        # Cannot list boards (missing boards:read)
        response = await test_client.get(f"/teams/{team['slug']}/boards", headers=headers)
        assert response.status_code == 403
        assert "boards:read" in response.json()["detail"]
