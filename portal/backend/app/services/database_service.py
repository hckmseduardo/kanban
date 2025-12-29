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

        if existing:
            # Update existing user
            updates = {
                "display_name": entra_data.get("name", existing["display_name"]),
                "email": entra_data.get("preferred_username", existing["email"]).lower(),
                "last_login_at": datetime.utcnow().isoformat()
            }
            return self.update_user(existing["id"], updates)
        else:
            # Create new user
            import uuid
            user_data = {
                "id": str(uuid.uuid4()),
                "entra_oid": entra_data["oid"],
                "email": entra_data.get("preferred_username", "").lower(),
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


# Singleton instance
db_service = DatabaseService()
