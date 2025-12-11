"""Board templates routes"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from ..services.database import Database, Q
from pathlib import Path
import os

router = APIRouter()

DATA_DIR = Path(os.getenv("DATA_DIR", "/app/data"))
db = Database(DATA_DIR / "db" / "team.json")

# Built-in templates
BUILTIN_TEMPLATES = [
    {
        "id": "basic-kanban",
        "name": "Basic Kanban",
        "description": "Simple To Do, In Progress, Done workflow",
        "builtin": True,
        "columns": [
            {"name": "To Do", "position": 0},
            {"name": "In Progress", "position": 1, "wip_limit": 3},
            {"name": "Done", "position": 2}
        ],
        "labels": [
            {"name": "Bug", "color": "red"},
            {"name": "Feature", "color": "green"},
            {"name": "Enhancement", "color": "blue"}
        ]
    },
    {
        "id": "scrum",
        "name": "Scrum Board",
        "description": "Sprint-based workflow with backlog",
        "builtin": True,
        "columns": [
            {"name": "Backlog", "position": 0},
            {"name": "Sprint Backlog", "position": 1},
            {"name": "In Progress", "position": 2, "wip_limit": 3},
            {"name": "Review", "position": 3, "wip_limit": 2},
            {"name": "Done", "position": 4}
        ],
        "labels": [
            {"name": "Story", "color": "green"},
            {"name": "Bug", "color": "red"},
            {"name": "Task", "color": "blue"},
            {"name": "Spike", "color": "purple"}
        ]
    },
    {
        "id": "software-dev",
        "name": "Software Development",
        "description": "Development workflow with testing and deployment",
        "builtin": True,
        "columns": [
            {"name": "Feature Request", "position": 0},
            {"name": "Backlog", "position": 1},
            {"name": "To Do", "position": 2},
            {"name": "Development", "position": 3, "wip_limit": 3},
            {"name": "Code Review", "position": 4, "wip_limit": 2},
            {"name": "Testing", "position": 5, "wip_limit": 2},
            {"name": "Done", "position": 6}
        ],
        "labels": [
            {"name": "Feature", "color": "green"},
            {"name": "Bug", "color": "red"},
            {"name": "Hotfix", "color": "orange"},
            {"name": "Tech Debt", "color": "yellow"},
            {"name": "Documentation", "color": "gray"}
        ]
    },
    {
        "id": "project-management",
        "name": "Project Management",
        "description": "General project tracking workflow",
        "builtin": True,
        "columns": [
            {"name": "Ideas", "position": 0},
            {"name": "Planning", "position": 1},
            {"name": "In Progress", "position": 2},
            {"name": "Blocked", "position": 3},
            {"name": "Completed", "position": 4}
        ],
        "labels": [
            {"name": "High Priority", "color": "red"},
            {"name": "Medium Priority", "color": "yellow"},
            {"name": "Low Priority", "color": "green"},
            {"name": "Milestone", "color": "purple"}
        ]
    },
    {
        "id": "bug-tracking",
        "name": "Bug Tracking",
        "description": "Comprehensive bug tracking workflow from report to resolution",
        "builtin": True,
        "columns": [
            {"name": "Bug Report", "position": 0},
            {"name": "Triage", "position": 1, "wip_limit": 5},
            {"name": "Analysis", "position": 2, "wip_limit": 3},
            {"name": "To Fix", "position": 3},
            {"name": "In Progress", "position": 4, "wip_limit": 3},
            {"name": "Code Review", "position": 5, "wip_limit": 3},
            {"name": "Verification", "position": 6, "wip_limit": 5},
            {"name": "Done", "position": 7}
        ],
        "labels": [
            {"name": "Critical", "color": "red"},
            {"name": "High", "color": "orange"},
            {"name": "Medium", "color": "yellow"},
            {"name": "Low", "color": "green"},
            {"name": "Regression", "color": "purple"},
            {"name": "UI/UX", "color": "pink"},
            {"name": "Performance", "color": "blue"},
            {"name": "Security", "color": "gray"}
        ]
    },
    {
        "id": "ideas-pipeline",
        "name": "Ideas Pipeline",
        "description": "Structured workflow to take ideas from raw concept to ready-for-development",
        "builtin": True,
        "columns": [
            {"name": "Idea Inbox", "position": 0},
            {"name": "Idea Triage", "position": 1, "wip_limit": 5},
            {"name": "Problem Framing", "position": 2, "wip_limit": 3},
            {"name": "User & UX Exploration", "position": 3, "wip_limit": 2},
            {"name": "Solution Exploration", "position": 4, "wip_limit": 3},
            {"name": "Discovery Spike", "position": 5, "wip_limit": 2},
            {"name": "Decision & Scope Lock", "position": 6, "wip_limit": 3},
            {"name": "Ready for Backlog", "position": 7}
        ],
        "labels": [
            {"name": "High Impact", "color": "green"},
            {"name": "Low Effort", "color": "blue"},
            {"name": "High Effort", "color": "orange"},
            {"name": "Needs Research", "color": "purple"},
            {"name": "User Request", "color": "pink"},
            {"name": "Internal Idea", "color": "gray"},
            {"name": "Quick Win", "color": "yellow"},
            {"name": "Strategic", "color": "red"}
        ]
    }
]


class TemplateCreate(BaseModel):
    name: str
    description: Optional[str] = None
    columns: List[dict] = []
    labels: List[dict] = []


@router.get("")
async def list_templates():
    """List all available templates (builtin + custom)"""
    db.initialize()

    custom_templates = db.templates.all()

    return {
        "builtin": BUILTIN_TEMPLATES,
        "custom": custom_templates
    }


@router.get("/{template_id}")
async def get_template(template_id: str):
    """Get a specific template"""
    db.initialize()

    # Check builtin templates first
    for template in BUILTIN_TEMPLATES:
        if template["id"] == template_id:
            return template

    # Check custom templates
    template = db.templates.get(Q.id == template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    return template


@router.post("")
async def create_template(data: TemplateCreate):
    """Create a custom template"""
    db.initialize()

    template = {
        "id": db.generate_id(),
        "name": data.name,
        "description": data.description,
        "builtin": False,
        "columns": data.columns,
        "labels": data.labels,
        "created_at": db.timestamp()
    }
    db.templates.insert(template)

    return template


@router.post("/from-board/{board_id}")
async def create_template_from_board(board_id: str, name: str, description: str = None):
    """Create a template from an existing board"""
    db.initialize()

    board = db.boards.get(Q.id == board_id)
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")

    # Get columns (without cards)
    columns = db.columns.search(Q.board_id == board_id)
    columns = sorted(columns, key=lambda x: x.get("position", 0))

    template_columns = [
        {
            "name": col["name"],
            "position": col.get("position", 0),
            "wip_limit": col.get("wip_limit")
        }
        for col in columns
    ]

    # Get labels
    labels = db.labels.search(Q.board_id == board_id)
    template_labels = [
        {"name": l["name"], "color": l["color"]}
        for l in labels
    ]

    template = {
        "id": db.generate_id(),
        "name": name,
        "description": description or f"Template created from {board['name']}",
        "builtin": False,
        "columns": template_columns,
        "labels": template_labels,
        "created_at": db.timestamp()
    }
    db.templates.insert(template)

    return template


@router.post("/{template_id}/apply")
async def apply_template(template_id: str, board_name: str, board_description: str = None):
    """Create a new board from a template"""
    db.initialize()

    # Find template
    template = None
    for t in BUILTIN_TEMPLATES:
        if t["id"] == template_id:
            template = t
            break

    if not template:
        template = db.templates.get(Q.id == template_id)

    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    # Create board
    board_id = db.generate_id()
    board = {
        "id": board_id,
        "name": board_name,
        "description": board_description,
        "created_at": db.timestamp(),
        "updated_at": db.timestamp()
    }
    db.boards.insert(board)

    # Create labels
    label_colors = {
        "red": {"bg": "#FEE2E2", "text": "#991B1B"},
        "orange": {"bg": "#FFEDD5", "text": "#9A3412"},
        "yellow": {"bg": "#FEF9C3", "text": "#854D0E"},
        "green": {"bg": "#DCFCE7", "text": "#166534"},
        "blue": {"bg": "#DBEAFE", "text": "#1E40AF"},
        "purple": {"bg": "#F3E8FF", "text": "#6B21A8"},
        "pink": {"bg": "#FCE7F3", "text": "#9D174D"},
        "gray": {"bg": "#F3F4F6", "text": "#374151"},
    }

    for label_data in template.get("labels", []):
        color = label_data.get("color", "blue")
        color_info = label_colors.get(color, label_colors["blue"])
        db.labels.insert({
            "id": db.generate_id(),
            "board_id": board_id,
            "name": label_data["name"],
            "color": color,
            "bg": color_info["bg"],
            "text": color_info["text"],
            "created_at": db.timestamp()
        })

    # Create columns
    for col_data in template.get("columns", []):
        db.columns.insert({
            "id": db.generate_id(),
            "board_id": board_id,
            "name": col_data["name"],
            "position": col_data.get("position", 0),
            "wip_limit": col_data.get("wip_limit"),
            "created_at": db.timestamp()
        })

    return board


@router.delete("/{template_id}")
async def delete_template(template_id: str):
    """Delete a custom template"""
    db.initialize()

    # Check if it's a builtin template
    for template in BUILTIN_TEMPLATES:
        if template["id"] == template_id:
            raise HTTPException(status_code=400, detail="Cannot delete builtin templates")

    template = db.templates.get(Q.id == template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    db.templates.remove(Q.id == template_id)

    return {"deleted": True}
