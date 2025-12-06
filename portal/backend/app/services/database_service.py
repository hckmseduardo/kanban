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
    """TinyDB database service for portal data"""

    def __init__(self):
        self.db: Optional[TinyDB] = None
        self._ensure_db()

    def _ensure_db(self):
        """Ensure database exists and is connected"""
        if self.db is None:
            db_path = Path(settings.database_path)
            db_path.parent.mkdir(parents=True, exist_ok=True)
            self.db = TinyDB(str(db_path))
            logger.info(f"Database connected: {db_path}")

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
        """Get team by slug"""
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
        """Get all teams for a user"""
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


# Singleton instance
db_service = DatabaseService()
