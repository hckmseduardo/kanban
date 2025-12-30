"""Authentication module"""

from app.auth.entra import EntraAuthService
from app.auth.jwt import create_access_token, verify_token, get_current_user
from app.auth.unified import AuthContext, get_auth_context, require_scope

__all__ = [
    "EntraAuthService",
    "create_access_token",
    "verify_token",
    "get_current_user",
    "AuthContext",
    "get_auth_context",
    "require_scope",
]
