from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
import uuid

class TaskSpec(BaseModel):
    task_id: str
    type: str                  # "feature" | "bugfix" | "refactor"
    title: str                 # short summary
    description: str           # a bit more detail
    target_repo: str
    affected_files: List[str] = []
    acceptance_criteria: List[str] = []
    priority: str = "medium"   # "low" | "medium" | "high"
    created_at: str
    source: str = "manual"     # later: "WhatsApp"

    @staticmethod
    def create_default():
        """Helper to create a TaskSpec template with default values."""
        return TaskSpec(
            task_id=str(uuid.uuid4()),
            type="feature",
            title="",
            description="",
            target_repo="",
            affected_files=[],
            acceptance_criteria=[],
            priority="medium",
            created_at=datetime.utcnow().isoformat(),
            source="WhatsApp"
        )
