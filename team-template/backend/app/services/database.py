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

    def generate_id(self) -> str:
        return str(uuid.uuid4())[:8]

    def timestamp(self) -> str:
        return datetime.utcnow().isoformat()


# Query helper
Q = Query()
