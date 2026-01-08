#!/usr/bin/env python3
"""Seed script for App Factory templates.

This script seeds the initial app templates into the portal database.
Run this after the portal is deployed to enable the App Factory feature.

Usage:
    python scripts/seed_app_templates.py

Or via docker:
    docker exec kanban-portal-api python /app/scripts/seed_app_templates.py
"""

import sys
import os

# Add the portal backend to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "portal", "backend"))

from datetime import datetime
import uuid


def get_database():
    """Get the database service."""
    try:
        from app.services.database_service import db_service
        return db_service
    except ImportError:
        # If running outside the container, create a local instance
        from tinydb import TinyDB
        db_path = os.path.join(
            os.path.dirname(__file__), "..", "data", "portal", "portal.json"
        )
        db = TinyDB(db_path)
        return db


def seed_app_templates():
    """Seed the app templates table with default templates."""

    templates = [
        {
            "id": str(uuid.uuid4()),
            "slug": "basic-app",
            "name": "Basic App",
            "description": "Full-stack React + FastAPI + PostgreSQL template with authentication, API endpoints, and modern UI components.",
            "github_template_owner": "hckmseduardo",
            "github_template_repo": "basic-app",
            "active": True,
            "created_at": datetime.utcnow().isoformat(),
        },
    ]

    try:
        db = get_database()

        # Check if we're using the database service or raw TinyDB
        if hasattr(db, "app_templates"):
            # Using database service
            app_templates = db.app_templates
        else:
            # Using raw TinyDB
            app_templates = db.table("app_templates")

        for template in templates:
            # Check if template already exists
            from tinydb import Query
            Template = Query()
            existing = app_templates.search(Template.slug == template["slug"])

            if existing:
                print(f"Template '{template['slug']}' already exists, skipping...")
                continue

            # Insert the template
            app_templates.insert(template)
            print(f"Created template: {template['name']} ({template['slug']})")

        print("\nApp templates seeded successfully!")
        print(f"Total templates: {len(app_templates.all())}")

    except Exception as e:
        print(f"Error seeding templates: {e}")
        sys.exit(1)


def list_templates():
    """List all app templates."""
    try:
        db = get_database()

        if hasattr(db, "app_templates"):
            app_templates = db.app_templates
        else:
            app_templates = db.table("app_templates")

        templates = app_templates.all()

        if not templates:
            print("No templates found.")
            return

        print("\nApp Templates:")
        print("-" * 60)
        for t in templates:
            status = "active" if t.get("active", True) else "inactive"
            print(f"  [{status}] {t['name']} ({t['slug']})")
            print(f"          GitHub: {t['github_template_owner']}/{t['github_template_repo']}")
            if t.get("description"):
                print(f"          {t['description'][:60]}...")
        print("-" * 60)

    except Exception as e:
        print(f"Error listing templates: {e}")
        sys.exit(1)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Manage App Factory templates")
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="List all templates"
    )
    parser.add_argument(
        "--seed", "-s",
        action="store_true",
        help="Seed default templates"
    )

    args = parser.parse_args()

    if args.list:
        list_templates()
    elif args.seed:
        seed_app_templates()
    else:
        # Default: seed templates
        seed_app_templates()
        list_templates()
