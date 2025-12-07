"""TinyDB database service for team data"""

from pathlib import Path
from tinydb import TinyDB, Query
from datetime import datetime
import uuid


class Database:
    """Database service using TinyDB"""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db: TinyDB = None

    def initialize(self):
        """Initialize database connection"""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = TinyDB(str(self.db_path))

    @property
    def boards(self):
        return self.db.table("boards")

    @property
    def columns(self):
        return self.db.table("columns")

    @property
    def cards(self):
        return self.db.table("cards")

    @property
    def members(self):
        return self.db.table("members")

    @property
    def webhooks(self):
        return self.db.table("webhooks")

    @property
    def activity(self):
        return self.db.table("activity")

    @property
    def attachments(self):
        return self.db.table("attachments")

    @property
    def comments(self):
        return self.db.table("comments")

    @property
    def labels(self):
        return self.db.table("labels")

    @property
    def templates(self):
        return self.db.table("templates")

    @property
    def notifications(self):
        return self.db.table("notifications")

    @property
    def notification_preferences(self):
        return self.db.table("notification_preferences")

    @property
    def automations(self):
        return self.db.table("automations")

    @property
    def card_templates(self):
        return self.db.table("card_templates")

    @property
    def recurring_cards(self):
        return self.db.table("recurring_cards")

    @property
    def board_members(self):
        return self.db.table("board_members")

    def generate_id(self) -> str:
        return str(uuid.uuid4())[:8]

    def timestamp(self) -> str:
        return datetime.utcnow().isoformat()

    def log_activity(
        self,
        card_id: str,
        board_id: str,
        action: str,
        from_column_id: str = None,
        to_column_id: str = None,
        details: dict = None,
        user_id: str = None
    ):
        """Log card activity for analytics and history tracking"""
        self.activity.insert({
            "id": self.generate_id(),
            "card_id": card_id,
            "board_id": board_id,
            "action": action,
            "from_column_id": from_column_id,
            "to_column_id": to_column_id,
            "details": details or {},
            "user_id": user_id,
            "timestamp": self.timestamp()
        })


# Query helper
Q = Query()
