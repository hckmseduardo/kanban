"""TinyDB database service"""

import os
import logging
from datetime import datetime
from typing import Optional, List
from pathlib import Path

from tinydb import TinyDB, Query

from app.config import settings

logger = logging.getLogger(__name__)


class DatabaseService:
    """TinyDB database service for portal data

    Note: TinyDB keeps data in memory. To ensure we always have fresh data
    (especially when the worker process modifies the database), we close
    and reopen the database on write operations.
    """

    def __init__(self):
        self.db: Optional[TinyDB] = None
        self._db_path: Optional[Path] = None
        self._ensure_db()

    def _ensure_db(self):
        """Ensure database exists and is connected"""
        if self.db is None:
            self._db_path = Path(settings.database_path)
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self.db = TinyDB(str(self._db_path))
            logger.info(f"Database connected: {self._db_path}")

    def refresh(self):
        """Force reload database from disk (call after external modifications)"""
        if self.db:
            # Clear TinyDB's internal cache by closing storage
            if hasattr(self.db, '_storage') and self.db._storage:
                self.db._storage.close()
            self.db.close()
            self.db = None
        # Force fresh read by creating new instance
        self._db_path = Path(settings.database_path)
        self.db = TinyDB(str(self._db_path))
        logger.debug(f"Database refreshed from disk: {self._db_path}")

    @property
    def users(self):
        """Users table"""
        self._ensure_db()
        return self.db.table("users")

    @property
    def teams(self):
        """Teams table"""
        self._ensure_db()
        return self.db.table("teams")

    @property
    def memberships(self):
        """Team memberships table"""
        self._ensure_db()
        return self.db.table("memberships")

    @property
    def invites(self):
        """Team invites table"""
        self._ensure_db()
        return self.db.table("invites")

    @property
    def api_tokens(self):
        """API tokens table (for team API tokens)"""
        self._ensure_db()
        return self.db.table("api_tokens")

    @property
    def portal_api_tokens(self):
        """Portal API tokens table (for portal-level API access)"""
        self._ensure_db()
        return self.db.table("portal_api_tokens")

    @property
    def app_templates(self):
        """App templates table (registry of available app templates)"""
        self._ensure_db()
        return self.db.table("app_templates")

    @property
    def workspaces(self):
        """Workspaces table (kanban team + optional app)"""
        self._ensure_db()
        return self.db.table("workspaces")

    @property
    def sandboxes(self):
        """Sandboxes table (isolated development environments for workspace apps)"""
        self._ensure_db()
        return self.db.table("sandboxes")

    @property
    def workspace_invitations(self):
        """Workspace invitations table"""
        self._ensure_db()
        return self.db.table("workspace_invitations")

    # =========================================================================
    # User Operations
    # =========================================================================

    def get_user_by_id(self, user_id: str) -> Optional[dict]:
        """Get user by ID"""
        User = Query()
        result = self.users.search(User.id == user_id)
        return result[0] if result else None

    def get_user_by_email(self, email: str) -> Optional[dict]:
        """Get user by email"""
        User = Query()
        result = self.users.search(User.email == email.lower())
        return result[0] if result else None

    def get_user_by_entra_oid(self, entra_oid: str) -> Optional[dict]:
        """Get user by Entra Object ID"""
        User = Query()
        result = self.users.search(User.entra_oid == entra_oid)
        return result[0] if result else None

    def create_user(self, user_data: dict) -> dict:
        """Create a new user"""
        user_data["created_at"] = datetime.utcnow().isoformat()
        user_data["updated_at"] = user_data["created_at"]
        user_data["email"] = user_data["email"].lower()
        self.users.insert(user_data)
        logger.info(f"User created: {user_data['id']}")
        return user_data

    def update_user(self, user_id: str, updates: dict) -> Optional[dict]:
        """Update user"""
        User = Query()
        updates["updated_at"] = datetime.utcnow().isoformat()
        self.users.update(updates, User.id == user_id)
        return self.get_user_by_id(user_id)

    def upsert_user_from_entra(self, entra_data: dict) -> dict:
        """Create or update user from Entra ID data"""
        existing = self.get_user_by_entra_oid(entra_data["oid"])

        # Get email from multiple possible fields (entra.authenticate returns 'email')
        email = (
            entra_data.get("email") or
            entra_data.get("preferred_username") or
            ""
        ).lower()

        if existing:
            # Update existing user
            updates = {
                "display_name": entra_data.get("name", existing["display_name"]),
                "email": email or existing.get("email", ""),
                "last_login_at": datetime.utcnow().isoformat()
            }
            return self.update_user(existing["id"], updates)
        else:
            # Create new user
            import uuid
            user_data = {
                "id": str(uuid.uuid4()),
                "entra_oid": entra_data["oid"],
                "email": email,
                "display_name": entra_data.get("name", "Unknown"),
                "avatar_url": None,
                "identity_provider": entra_data.get("idp", "microsoft"),
                "last_login_at": datetime.utcnow().isoformat()
            }
            return self.create_user(user_data)

    # =========================================================================
    # Team Operations
    # =========================================================================

    def get_team_by_id(self, team_id: str) -> Optional[dict]:
        """Get team by ID"""
        Team = Query()
        result = self.teams.search(Team.id == team_id)
        return result[0] if result else None

    def get_team_by_slug(self, slug: str) -> Optional[dict]:
        """Get team by slug

        Note: We refresh to pick up changes from worker process.
        """
        self.refresh()
        Team = Query()
        result = self.teams.search(Team.slug == slug.lower())
        return result[0] if result else None

    def create_team(self, team_data: dict) -> dict:
        """Create a new team"""
        team_data["slug"] = team_data["slug"].lower()
        team_data["created_at"] = datetime.utcnow().isoformat()
        team_data["updated_at"] = team_data["created_at"]
        team_data["status"] = "provisioning"
        self.teams.insert(team_data)
        logger.info(f"Team created: {team_data['id']} ({team_data['slug']})")
        return team_data

    def update_team(self, team_id: str, updates: dict) -> Optional[dict]:
        """Update team"""
        Team = Query()
        updates["updated_at"] = datetime.utcnow().isoformat()
        self.teams.update(updates, Team.id == team_id)
        return self.get_team_by_id(team_id)

    def get_user_teams(self, user_id: str) -> List[dict]:
        """Get all teams for a user

        Note: We refresh the database here because teams can be modified
        by the worker process running in a separate container.
        """
        # Refresh to pick up changes from worker process
        self.refresh()

        Membership = Query()
        memberships = self.memberships.search(Membership.user_id == user_id)

        teams = []
        for membership in memberships:
            team = self.get_team_by_id(membership["team_id"])
            if team:
                team["role"] = membership["role"]
                teams.append(team)

        return teams

    def delete_team(self, team_id: str):
        """Delete team and related data"""
        Team = Query()
        Membership = Query()

        self.teams.remove(Team.id == team_id)
        self.memberships.remove(Membership.team_id == team_id)
        logger.info(f"Team deleted: {team_id}")

    # =========================================================================
    # Membership Operations
    # =========================================================================

    def add_team_member(
        self,
        team_id: str,
        user_id: str,
        role: str = "member",
        invited_by: str = None
    ) -> dict:
        """Add user to team"""
        membership = {
            "team_id": team_id,
            "user_id": user_id,
            "role": role,
            "invited_by": invited_by,
            "joined_at": datetime.utcnow().isoformat()
        }
        self.memberships.insert(membership)
        logger.info(f"User {user_id} added to team {team_id} as {role}")
        return membership

    def get_team_members(self, team_id: str) -> List[dict]:
        """Get all members of a team"""
        Membership = Query()
        memberships = self.memberships.search(Membership.team_id == team_id)

        members = []
        for membership in memberships:
            user = self.get_user_by_id(membership["user_id"])
            if user:
                members.append({
                    **user,
                    "role": membership["role"],
                    "joined_at": membership["joined_at"]
                })

        return members

    def get_membership(self, team_id: str, user_id: str) -> Optional[dict]:
        """Get specific membership"""
        Membership = Query()
        result = self.memberships.search(
            (Membership.team_id == team_id) & (Membership.user_id == user_id)
        )
        return result[0] if result else None

    def update_membership(self, team_id: str, user_id: str, role: str):
        """Update member role"""
        Membership = Query()
        self.memberships.update(
            {"role": role},
            (Membership.team_id == team_id) & (Membership.user_id == user_id)
        )

    def remove_team_member(self, team_id: str, user_id: str):
        """Remove user from team"""
        Membership = Query()
        self.memberships.remove(
            (Membership.team_id == team_id) & (Membership.user_id == user_id)
        )
        logger.info(f"User {user_id} removed from team {team_id}")

    def get_team_owner(self, team_id: str) -> Optional[dict]:
        """Get the owner of a team from memberships"""
        Membership = Query()
        result = self.memberships.search(
            (Membership.team_id == team_id) & (Membership.role == "owner")
        )
        if result:
            # Return the first owner (there should only be one)
            return self.get_user_by_id(result[0]["user_id"])
        return None

    # =========================================================================
    # API Token Operations
    # =========================================================================

    def create_api_token(
        self,
        team_id: str,
        name: str,
        token_hash: str,
        created_by: str,
        scopes: List[str] = None,
        expires_at: str = None
    ) -> dict:
        """Create a new API token for a team"""
        import uuid
        token_data = {
            "id": str(uuid.uuid4()),
            "team_id": team_id,
            "name": name,
            "token_hash": token_hash,  # Store hashed token, not plaintext
            "scopes": scopes or ["read", "write", "webhook"],
            "created_by": created_by,
            "created_at": datetime.utcnow().isoformat(),
            "expires_at": expires_at,
            "last_used_at": None,
            "is_active": True
        }
        self.api_tokens.insert(token_data)
        logger.info(f"API token created for team {team_id}: {name}")
        return token_data

    def get_api_token_by_id(self, token_id: str) -> Optional[dict]:
        """Get API token by ID"""
        Token = Query()
        result = self.api_tokens.search(Token.id == token_id)
        return result[0] if result else None

    def get_api_token_by_hash(self, token_hash: str) -> Optional[dict]:
        """Get API token by hash (for validation)"""
        Token = Query()
        result = self.api_tokens.search(
            (Token.token_hash == token_hash) & (Token.is_active == True)
        )
        return result[0] if result else None

    def get_team_api_tokens(self, team_id: str) -> List[dict]:
        """Get all API tokens for a team"""
        Token = Query()
        tokens = self.api_tokens.search(Token.team_id == team_id)
        # Don't return token_hash in list
        return [{k: v for k, v in t.items() if k != "token_hash"} for t in tokens]

    def update_api_token_last_used(self, token_id: str):
        """Update last_used_at timestamp"""
        Token = Query()
        self.api_tokens.update(
            {"last_used_at": datetime.utcnow().isoformat()},
            Token.id == token_id
        )

    def revoke_api_token(self, token_id: str) -> bool:
        """Revoke (deactivate) an API token"""
        Token = Query()
        result = self.api_tokens.update(
            {"is_active": False, "revoked_at": datetime.utcnow().isoformat()},
            Token.id == token_id
        )
        if result:
            logger.info(f"API token revoked: {token_id}")
        return bool(result)

    def delete_api_token(self, token_id: str) -> bool:
        """Permanently delete an API token"""
        Token = Query()
        result = self.api_tokens.remove(Token.id == token_id)
        if result:
            logger.info(f"API token deleted: {token_id}")
        return bool(result)

    # =========================================================================
    # Portal API Token Operations
    # =========================================================================

    def create_portal_api_token(
        self,
        name: str,
        token_hash: str,
        created_by: str,
        scopes: List[str] = None,
        expires_at: str = None
    ) -> dict:
        """Create a new Portal API token"""
        import uuid
        token_data = {
            "id": str(uuid.uuid4()),
            "name": name,
            "token_hash": token_hash,  # Store hashed token, not plaintext
            "scopes": scopes or ["teams:read", "teams:write", "boards:read", "boards:write", "members:read", "members:write"],
            "created_by": created_by,
            "created_at": datetime.utcnow().isoformat(),
            "expires_at": expires_at,
            "last_used_at": None,
            "is_active": True
        }
        self.portal_api_tokens.insert(token_data)
        logger.info(f"Portal API token created: {name}")
        return token_data

    def get_portal_api_token_by_id(self, token_id: str) -> Optional[dict]:
        """Get Portal API token by ID"""
        Token = Query()
        result = self.portal_api_tokens.search(Token.id == token_id)
        return result[0] if result else None

    def get_portal_api_token_by_hash(self, token_hash: str) -> Optional[dict]:
        """Get Portal API token by hash (for validation)"""
        Token = Query()
        result = self.portal_api_tokens.search(
            (Token.token_hash == token_hash) & (Token.is_active == True)
        )
        return result[0] if result else None

    def get_all_portal_api_tokens(self, created_by: str = None) -> List[dict]:
        """Get all Portal API tokens, optionally filtered by creator"""
        Token = Query()
        if created_by:
            tokens = self.portal_api_tokens.search(Token.created_by == created_by)
        else:
            tokens = self.portal_api_tokens.all()
        # Don't return token_hash in list
        return [{k: v for k, v in t.items() if k != "token_hash"} for t in tokens]

    def update_portal_api_token_last_used(self, token_id: str):
        """Update last_used_at timestamp for portal token"""
        Token = Query()
        self.portal_api_tokens.update(
            {"last_used_at": datetime.utcnow().isoformat()},
            Token.id == token_id
        )

    def revoke_portal_api_token(self, token_id: str) -> bool:
        """Revoke (deactivate) a Portal API token"""
        Token = Query()
        result = self.portal_api_tokens.update(
            {"is_active": False, "revoked_at": datetime.utcnow().isoformat()},
            Token.id == token_id
        )
        if result:
            logger.info(f"Portal API token revoked: {token_id}")
        return bool(result)

    def delete_portal_api_token(self, token_id: str) -> bool:
        """Permanently delete a Portal API token"""
        Token = Query()
        result = self.portal_api_tokens.remove(Token.id == token_id)
        if result:
            logger.info(f"Portal API token deleted: {token_id}")
        return bool(result)

    # =========================================================================
    # App Template Operations
    # =========================================================================

    def get_app_template_by_id(self, template_id: str) -> Optional[dict]:
        """Get app template by ID"""
        Template = Query()
        result = self.app_templates.search(Template.id == template_id)
        return result[0] if result else None

    def get_app_template_by_slug(self, slug: str) -> Optional[dict]:
        """Get app template by slug"""
        Template = Query()
        result = self.app_templates.search(Template.slug == slug.lower())
        return result[0] if result else None

    def list_app_templates(self, active_only: bool = True) -> List[dict]:
        """List all app templates"""
        if active_only:
            Template = Query()
            return self.app_templates.search(Template.active == True)
        return self.app_templates.all()

    def create_app_template(self, template_data: dict) -> dict:
        """Create a new app template"""
        import uuid
        template_data["id"] = str(uuid.uuid4())
        template_data["slug"] = template_data["slug"].lower()
        template_data["created_at"] = datetime.utcnow().isoformat()
        template_data["active"] = template_data.get("active", True)
        self.app_templates.insert(template_data)
        logger.info(f"App template created: {template_data['id']} ({template_data['slug']})")
        return template_data

    def update_app_template(self, template_id: str, updates: dict) -> Optional[dict]:
        """Update app template"""
        Template = Query()
        updates["updated_at"] = datetime.utcnow().isoformat()
        self.app_templates.update(updates, Template.id == template_id)
        return self.get_app_template_by_id(template_id)

    def delete_app_template(self, template_id: str) -> bool:
        """Delete an app template"""
        Template = Query()
        result = self.app_templates.remove(Template.id == template_id)
        if result:
            logger.info(f"App template deleted: {template_id}")
        return bool(result)

    # =========================================================================
    # Workspace Operations
    # =========================================================================

    def get_workspace_by_id(self, workspace_id: str) -> Optional[dict]:
        """Get workspace by ID"""
        Workspace = Query()
        result = self.workspaces.search(Workspace.id == workspace_id)
        return result[0] if result else None

    def get_workspace_by_slug(self, slug: str) -> Optional[dict]:
        """Get workspace by slug

        Note: We refresh to pick up changes from worker process.
        """
        self.refresh()
        Workspace = Query()
        result = self.workspaces.search(Workspace.slug == slug.lower())
        return result[0] if result else None

    def get_user_workspaces(self, user_id: str) -> List[dict]:
        """Get all workspaces where user is a member (any role).

        Note: We refresh the database here because workspaces can be modified
        by the worker process running in a separate container.

        Access is now determined solely by membership - owners are members
        with role="owner". We also include workspaces in "provisioning" or
        "deleting" status where the user is the creator, so they can see
        progress immediately.
        """
        self.refresh()
        Membership = Query()
        Workspace = Query()

        workspaces = []
        seen_ids = set()

        # Include workspaces being provisioned/deleted by this user
        # These don't have a kanban_team_id yet so membership check won't find them
        provisioning_workspaces = self.workspaces.search(
            (Workspace.created_by == user_id) &
            (Workspace.status.one_of(["provisioning", "deleting"]))
        )
        for ws in provisioning_workspaces:
            if ws["id"] not in seen_ids:
                workspaces.append(ws)
                seen_ids.add(ws["id"])

        # Get all team memberships for this user
        memberships = self.memberships.search(Membership.user_id == user_id)

        if memberships:
            # Get team IDs
            team_ids = [m["team_id"] for m in memberships]

            # Find workspaces with these team IDs
            for team_id in team_ids:
                ws_list = self.workspaces.search(Workspace.kanban_team_id == team_id)
                for ws in ws_list:
                    if ws["id"] not in seen_ids:
                        workspaces.append(ws)
                        seen_ids.add(ws["id"])

        return workspaces

    def get_workspaces_by_team_member(self, user_id: str) -> List[dict]:
        """Get workspaces where user is a team member.

        This is now an alias for get_user_workspaces since all access
        is determined by membership.
        """
        return self.get_user_workspaces(user_id)

    def create_workspace(self, workspace_data: dict) -> dict:
        """Create a new workspace"""
        import uuid
        workspace_data["id"] = str(uuid.uuid4())
        workspace_data["slug"] = workspace_data["slug"].lower()
        workspace_data["created_at"] = datetime.utcnow().isoformat()
        workspace_data["updated_at"] = workspace_data["created_at"]
        workspace_data["status"] = "provisioning"
        self.workspaces.insert(workspace_data)
        logger.info(f"Workspace created: {workspace_data['id']} ({workspace_data['slug']})")
        return workspace_data

    def update_workspace(self, workspace_id: str, updates: dict) -> Optional[dict]:
        """Update workspace"""
        Workspace = Query()
        updates["updated_at"] = datetime.utcnow().isoformat()
        self.workspaces.update(updates, Workspace.id == workspace_id)
        return self.get_workspace_by_id(workspace_id)

    def delete_workspace(self, workspace_id: str):
        """Delete workspace and related sandboxes"""
        Workspace = Query()
        Sandbox = Query()

        # Delete all sandboxes for this workspace
        self.sandboxes.remove(Sandbox.workspace_id == workspace_id)

        # Delete the workspace
        self.workspaces.remove(Workspace.id == workspace_id)
        logger.info(f"Workspace deleted: {workspace_id}")

    # =========================================================================
    # Sandbox Operations
    # =========================================================================

    def get_sandbox_by_id(self, sandbox_id: str) -> Optional[dict]:
        """Get sandbox by ID"""
        Sandbox = Query()
        result = self.sandboxes.search(Sandbox.id == sandbox_id)
        return result[0] if result else None

    def get_sandbox_by_full_slug(self, full_slug: str) -> Optional[dict]:
        """Get sandbox by full slug ({workspace_slug}-{sandbox_slug})"""
        self.refresh()
        Sandbox = Query()
        result = self.sandboxes.search(Sandbox.full_slug == full_slug.lower())
        return result[0] if result else None

    def get_sandbox_by_workspace_and_slug(
        self,
        workspace_id: str,
        sandbox_slug: str
    ) -> Optional[dict]:
        """Get sandbox by workspace ID and sandbox slug"""
        self.refresh()
        Sandbox = Query()
        result = self.sandboxes.search(
            (Sandbox.workspace_id == workspace_id) &
            (Sandbox.slug == sandbox_slug.lower())
        )
        return result[0] if result else None

    def get_sandboxes_by_workspace(self, workspace_id: str) -> List[dict]:
        """Get all sandboxes for a workspace"""
        self.refresh()
        Sandbox = Query()
        return self.sandboxes.search(Sandbox.workspace_id == workspace_id)

    def create_sandbox(self, sandbox_data: dict) -> dict:
        """Create a new sandbox"""
        import uuid
        import secrets

        sandbox_data["id"] = str(uuid.uuid4())
        sandbox_data["slug"] = sandbox_data["slug"].lower()
        sandbox_data["full_slug"] = sandbox_data["full_slug"].lower()
        sandbox_data["created_at"] = datetime.utcnow().isoformat()
        sandbox_data["updated_at"] = sandbox_data["created_at"]
        sandbox_data["status"] = "provisioning"

        # Generate unique webhook secret for agent
        sandbox_data["agent_webhook_secret"] = secrets.token_urlsafe(32)

        self.sandboxes.insert(sandbox_data)
        logger.info(f"Sandbox created: {sandbox_data['id']} ({sandbox_data['full_slug']})")
        return sandbox_data

    def update_sandbox(self, sandbox_id: str, updates: dict) -> Optional[dict]:
        """Update sandbox"""
        Sandbox = Query()
        updates["updated_at"] = datetime.utcnow().isoformat()
        self.sandboxes.update(updates, Sandbox.id == sandbox_id)
        return self.get_sandbox_by_id(sandbox_id)

    def regenerate_sandbox_webhook_secret(self, sandbox_id: str) -> Optional[str]:
        """Regenerate webhook secret for a sandbox agent"""
        import secrets
        new_secret = secrets.token_urlsafe(32)
        Sandbox = Query()
        self.sandboxes.update(
            {
                "agent_webhook_secret": new_secret,
                "updated_at": datetime.utcnow().isoformat()
            },
            Sandbox.id == sandbox_id
        )
        logger.info(f"Sandbox webhook secret regenerated: {sandbox_id}")
        return new_secret

    def delete_sandbox(self, sandbox_id: str):
        """Delete a sandbox"""
        Sandbox = Query()
        self.sandboxes.remove(Sandbox.id == sandbox_id)
        logger.info(f"Sandbox deleted: {sandbox_id}")

    # =========================================================================
    # Workspace Invitation Operations
    # =========================================================================

    def create_workspace_invitation(
        self,
        workspace_id: str,
        email: str,
        role: str,
        invited_by: str,
        expires_days: int = 7
    ) -> dict:
        """Create a workspace invitation"""
        import uuid
        import secrets
        from datetime import timedelta

        # Generate unique invitation token
        token = secrets.token_urlsafe(32)

        invitation = {
            "id": str(uuid.uuid4()),
            "workspace_id": workspace_id,
            "email": email.lower(),
            "role": role,
            "token": token,
            "invited_by": invited_by,
            "status": "pending",  # pending, accepted, cancelled, expired
            "created_at": datetime.utcnow().isoformat(),
            "expires_at": (datetime.utcnow() + timedelta(days=expires_days)).isoformat(),
            "accepted_at": None,
            "accepted_by": None,
        }

        self.workspace_invitations.insert(invitation)
        logger.info(f"Workspace invitation created: {invitation['id']} for {email}")
        return invitation

    def get_workspace_invitation_by_id(self, invitation_id: str) -> Optional[dict]:
        """Get invitation by ID"""
        Invitation = Query()
        result = self.workspace_invitations.search(Invitation.id == invitation_id)
        return result[0] if result else None

    def get_workspace_invitation_by_token(self, token: str) -> Optional[dict]:
        """Get invitation by token"""
        self.refresh()
        Invitation = Query()
        result = self.workspace_invitations.search(Invitation.token == token)
        return result[0] if result else None

    def get_workspace_invitations(
        self,
        workspace_id: str,
        status: Optional[str] = None
    ) -> List[dict]:
        """Get all invitations for a workspace"""
        self.refresh()
        Invitation = Query()
        if status:
            return self.workspace_invitations.search(
                (Invitation.workspace_id == workspace_id) &
                (Invitation.status == status)
            )
        return self.workspace_invitations.search(
            Invitation.workspace_id == workspace_id
        )

    def get_pending_invitation_for_email(
        self,
        workspace_id: str,
        email: str
    ) -> Optional[dict]:
        """Check if there's already a pending invitation for this email"""
        Invitation = Query()
        result = self.workspace_invitations.search(
            (Invitation.workspace_id == workspace_id) &
            (Invitation.email == email.lower()) &
            (Invitation.status == "pending")
        )
        return result[0] if result else None

    def accept_workspace_invitation(
        self,
        invitation_id: str,
        user_id: str
    ) -> Optional[dict]:
        """Accept a workspace invitation"""
        Invitation = Query()
        updates = {
            "status": "accepted",
            "accepted_at": datetime.utcnow().isoformat(),
            "accepted_by": user_id,
        }
        self.workspace_invitations.update(updates, Invitation.id == invitation_id)
        logger.info(f"Workspace invitation accepted: {invitation_id} by {user_id}")
        return self.get_workspace_invitation_by_id(invitation_id)

    def cancel_workspace_invitation(self, invitation_id: str) -> Optional[dict]:
        """Cancel a workspace invitation"""
        Invitation = Query()
        updates = {
            "status": "cancelled",
        }
        self.workspace_invitations.update(updates, Invitation.id == invitation_id)
        logger.info(f"Workspace invitation cancelled: {invitation_id}")
        return self.get_workspace_invitation_by_id(invitation_id)

    def delete_workspace_invitation(self, invitation_id: str):
        """Delete a workspace invitation"""
        Invitation = Query()
        self.workspace_invitations.remove(Invitation.id == invitation_id)
        logger.info(f"Workspace invitation deleted: {invitation_id}")


# Singleton instance
db_service = DatabaseService()
