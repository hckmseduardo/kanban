"""JWT token handling"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt

from app.config import settings
from app.services.database_service import db_service

logger = logging.getLogger(__name__)

# Security scheme
security = HTTPBearer()

# JWT Configuration
ALGORITHM = "HS256"


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create JWT access token"""
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(
            minutes=settings.access_token_expire_minutes
        )

    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        to_encode,
        settings.portal_secret_key,
        algorithm=ALGORITHM
    )
    return encoded_jwt


def verify_token(token: str) -> Optional[dict]:
    """Verify and decode JWT token"""
    try:
        payload = jwt.decode(
            token,
            settings.portal_secret_key,
            algorithms=[ALGORITHM]
        )
        return payload
    except JWTError as e:
        logger.warning(f"JWT verification failed: {e}")
        return None


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> dict:
    """Get current user from JWT token"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    token = credentials.credentials
    payload = verify_token(token)

    if payload is None:
        raise credentials_exception

    user_id: str = payload.get("sub")
    if user_id is None:
        raise credentials_exception

    user = db_service.get_user_by_id(user_id)
    if user is None:
        raise credentials_exception

    return user


async def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(
        HTTPBearer(auto_error=False)
    )
) -> Optional[dict]:
    """Get current user if authenticated, None otherwise"""
    if not credentials:
        return None

    payload = verify_token(credentials.credentials)
    if payload is None:
        return None

    user_id: str = payload.get("sub")
    if user_id is None:
        return None

    return db_service.get_user_by_id(user_id)


def create_cross_domain_token(user_id: str, team_slug: str) -> str:
    """Create one-time token for cross-domain SSO"""
    data = {
        "sub": user_id,
        "team": team_slug,
        "type": "cross_domain",
        "exp": datetime.utcnow() + timedelta(minutes=5)
    }
    return jwt.encode(
        data,
        settings.cross_domain_secret,
        algorithm=ALGORITHM
    )


def verify_cross_domain_token(token: str) -> Optional[dict]:
    """Verify cross-domain SSO token"""
    try:
        payload = jwt.decode(
            token,
            settings.cross_domain_secret,
            algorithms=[ALGORITHM]
        )
        if payload.get("type") != "cross_domain":
            return None
        return payload
    except JWTError:
        return None
