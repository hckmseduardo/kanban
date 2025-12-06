"""Board models"""

from pydantic import BaseModel, Field
from typing import Optional, List, Literal
from datetime import datetime
from enum import Enum


class BoardVisibility(str, Enum):
    PRIVATE = "private"  # Only board creator can view
    TEAM = "team"        # All team members can view
    PUBLIC = "public"    # Anyone with link can view (read-only)


class ChecklistItem(BaseModel):
    id: str
    text: str
    completed: bool = False


class ChecklistItemCreate(BaseModel):
    text: str = Field(..., min_length=1, max_length=500)
    completed: bool = False


class ChecklistItemUpdate(BaseModel):
    text: Optional[str] = Field(None, min_length=1, max_length=500)
    completed: Optional[bool] = None


class BoardCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    visibility: BoardVisibility = BoardVisibility.TEAM


class BoardUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    visibility: Optional[BoardVisibility] = None


class Board(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    visibility: BoardVisibility = BoardVisibility.TEAM
    owner_id: Optional[str] = None
    created_at: str
    updated_at: str


class ColumnCreate(BaseModel):
    board_id: str
    name: str = Field(..., min_length=1, max_length=50)
    position: int = 0
    wip_limit: Optional[int] = None


class ColumnUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=50)
    position: Optional[int] = None
    wip_limit: Optional[int] = None


class Column(BaseModel):
    id: str
    board_id: str
    name: str
    position: int
    wip_limit: Optional[int] = None
    created_at: str


class CardCreate(BaseModel):
    column_id: str
    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    position: int = 0
    assignee_id: Optional[str] = None
    due_date: Optional[str] = None
    labels: list[str] = []
    priority: Optional[str] = None
    checklist: List[ChecklistItemCreate] = []


class CardUpdate(BaseModel):
    column_id: Optional[str] = None
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    position: Optional[int] = None
    assignee_id: Optional[str] = None
    due_date: Optional[str] = None
    labels: Optional[list[str]] = None
    priority: Optional[str] = None
    checklist: Optional[List[ChecklistItem]] = None


class Card(BaseModel):
    id: str
    column_id: str
    title: str
    description: Optional[str] = None
    position: int
    assignee_id: Optional[str] = None
    due_date: Optional[str] = None
    labels: list[str] = []
    priority: Optional[str] = None
    checklist: List[ChecklistItem] = []
    created_at: str
    updated_at: str
