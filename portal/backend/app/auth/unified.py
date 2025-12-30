"""Unified authentication - supports both JWT and Portal API tokens"""

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.auth.jwt import verify_token
from app.services.database_service import db_service

logger = logging.getLogger(__name__)

# Security scheme - optional to allow both JWT and API tokens
security = HTTPBearer(auto_error=False)


@dataclass
class AuthContext:
    """Unified authentication context for both JWT and API token auth"""
    user: dict                          # Full user dict from database
    auth_type: str                      # "jwt" or "api_token"
    scopes: List[str]                   # Explicit scopes (API token) or ["*"] (JWT)
    token_id: Optional[str] = None      # API token ID (if api_token auth)
    token_name: Optional[str] = None    # API token name (if api_token auth)

    def has_scope(self, required_scope: str) -> bool:
        """Check if this auth context has the required scope"""
        # Wildcard = full access
        if "*" in self.scopes:
            return True
        # Exact match
        if required_scope in self.scopes:
            return True
        # Category wildcard (e.g., teams:* covers teams:read)
        category = required_scope.split(":")[0]
        if f"{category}:*" in self.scopes:
            return True
        return False


def _verify_portal_api_token(token: str) -> Optional[dict]:
    """Verify a portal API token and return token data"""
    if not token.startswith("pk_"):
        return None

    # Strip pk_ prefix before hashing (token is stored without prefix)
    raw_token = token[3:]  # Remove "pk_" prefix
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    token_data = db_service.get_portal_api_token_by_hash(token_hash)

    if not token_data:
        return None

    # Check if active
    if not token_data.get("is_active", True):
        return None

    # Check expiration
    if token_data.get("expires_at"):
        expires = datetime.fromisoformat(token_data["expires_at"])
        if datetime.utcnow() > expires:
            return None

    # Update last used
    db_service.update_portal_api_token_last_used(token_data["id"])

    return token_data


async def get_auth_context(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> AuthContext:
    """
    Get unified authentication context from either JWT or Portal API token.

    JWT tokens: User gets implicit full access ["*"]
    API tokens: User gets explicit scopes from token, acting as token creator
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials

    # Try Portal API token first (has pk_ prefix)
    if token.startswith("pk_"):
        token_data = _verify_portal_api_token(token)
        if not token_data:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired API token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Get the user who created this token
        user = db_service.get_user_by_id(token_data["created_by"])
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token creator user not found",
                headers={"WWW-Authenticate": "Bearer"},
            )

        logger.debug(f"API token auth: {token_data['name']} (user: {user['email']})")

        return AuthContext(
            user=user,
            auth_type="api_token",
            scopes=token_data.get("scopes", []),
            token_id=token_data["id"],
            token_name=token_data["name"]
        )

    # Try JWT token
    payload = verify_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid JWT token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db_service.get_user_by_id(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    logger.debug(f"JWT auth: {user['email']}")

    return AuthContext(
        user=user,
        auth_type="jwt",
        scopes=["*"]  # JWT users have implicit full access
    )


def require_scope(required_scope: str):
    """
    Dependency factory that requires a specific scope.

    For JWT users: Always passes (implicit full access)
    For API tokens: Checks explicit scopes
    """
    async def check_scope(auth: AuthContext = Depends(get_auth_context)) -> AuthContext:
        if not auth.has_scope(required_scope):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required scope: {required_scope}"
            )
        return auth
    return check_scope
