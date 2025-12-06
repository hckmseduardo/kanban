"""Webhook models for AI agent integrations"""

from pydantic import BaseModel, Field, HttpUrl
from typing import Optional


class WebhookCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    url: str
    events: list[str] = ["card.created", "card.moved", "card.updated"]
    secret: Optional[str] = None
    active: bool = True


class WebhookUpdate(BaseModel):
    name: Optional[str] = None
    url: Optional[str] = None
    events: Optional[list[str]] = None
    secret: Optional[str] = None
    active: Optional[bool] = None


class Webhook(BaseModel):
    id: str
    name: str
    url: str
    events: list[str]
    secret: Optional[str] = None
    active: bool
    created_at: str
