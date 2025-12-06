"""Member models"""

from pydantic import BaseModel, Field
from typing import Optional


class MemberCreate(BaseModel):
    user_id: str
    email: str
    name: str
    role: str = "member"  # admin, member, viewer


class MemberUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None


class Member(BaseModel):
    id: str
    user_id: str
    email: str
    name: str
    role: str
    avatar_url: Optional[str] = None
    joined_at: str
