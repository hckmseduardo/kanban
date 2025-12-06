"""Authentication routes"""

import logging
from datetime import timedelta
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import RedirectResponse

from app.auth.entra import entra_auth
from app.auth.jwt import create_access_token, create_cross_domain_token
from app.config import settings
from app.services.database_service import db_service

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/login")
async def login(
    redirect_url: str = Query(None, description="URL to redirect after login")
):
    """
    Initiate Entra ID login flow.
    Redirects user to Microsoft login page.
    """
    # Store redirect URL in state parameter
    state = redirect_url or f"https://app.{settings.domain}:{settings.port}"

    try:
        auth_url = entra_auth.get_authorization_url(state=state)
        return RedirectResponse(url=auth_url)
    except ValueError as e:
        logger.error(f"Login failed: {e}")
        raise HTTPException(
            status_code=500,
            detail="Authentication not configured. Please set Entra ID credentials."
        )


@router.get("/callback")
async def auth_callback(
    code: str = Query(..., description="Authorization code from Entra ID"),
    state: str = Query(None, description="Original redirect URL"),
    error: str = Query(None),
    error_description: str = Query(None)
):
    """
    OAuth callback from Entra ID.
    Exchanges code for token and creates user session.
    """
    if error:
        logger.error(f"Auth error: {error} - {error_description}")
        raise HTTPException(status_code=400, detail=error_description or error)

    try:
        # Authenticate with Entra ID
        entra_user = await entra_auth.authenticate(code)

        # Create or update user in database
        user = db_service.upsert_user_from_entra(entra_user)

        # Create JWT token
        access_token = create_access_token(
            data={"sub": user["id"], "email": user["email"]},
            expires_delta=timedelta(minutes=settings.access_token_expire_minutes)
        )

        # Redirect to frontend with token
        redirect_url = state or f"https://app.{settings.domain}:{settings.port}"
        separator = "&" if "?" in redirect_url else "?"
        final_url = f"{redirect_url}{separator}{urlencode({'token': access_token})}"

        logger.info(f"Auth success for user {user['id']}, redirecting to frontend")
        return RedirectResponse(url=final_url)

    except Exception as e:
        logger.error(f"Authentication failed: {e}", exc_info=True)
        raise HTTPException(status_code=401, detail="Authentication failed")


@router.post("/logout")
async def logout(response: Response):
    """
    Logout user.
    Clears session cookies.
    """
    # In a stateless JWT system, logout is handled client-side
    # by removing the token. This endpoint is for any server-side cleanup.
    return {"message": "Logged out successfully"}


@router.post("/exchange")
async def exchange_token(
    token: str = Query(..., description="One-time cross-domain token")
):
    """
    Exchange one-time token for JWT.
    Used for cross-domain SSO when navigating to team instances.
    """
    from app.auth.jwt import verify_cross_domain_token

    payload = verify_cross_domain_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user = db_service.get_user_by_id(payload["sub"])
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    # Create new access token
    access_token = create_access_token(
        data={"sub": user["id"], "email": user["email"]}
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": user["id"],
            "email": user["email"],
            "display_name": user["display_name"],
            "avatar_url": user.get("avatar_url")
        }
    }


@router.get("/cross-domain-token")
async def get_cross_domain_token(
    team_slug: str = Query(..., description="Team to access"),
    user_id: str = Query(..., description="Current user ID")  # In real app, get from JWT
):
    """
    Generate one-time token for cross-domain SSO.
    Used when redirecting user to team instance.
    """
    # Verify user has access to team
    membership = db_service.get_membership(
        team_id=db_service.get_team_by_slug(team_slug)["id"] if db_service.get_team_by_slug(team_slug) else None,
        user_id=user_id
    )

    if not membership:
        raise HTTPException(status_code=403, detail="Not a member of this team")

    token = create_cross_domain_token(user_id, team_slug)
    return {"token": token, "expires_in": 300}  # 5 minutes
