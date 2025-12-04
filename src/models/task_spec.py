from __future__ import annotations

from datetime import datetime
from enum import Enum
import uuid
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    OPEN = "OPEN"
    CODE_APPLIED = "CODE_APPLIED"
    TESTS_PASSED = "TESTS_PASSED"
    TESTS_FAILED = "TESTS_FAILED"
    CLOSED = "CLOSED"


class TaskEvent(BaseModel):
    label: str
    at: datetime
    meta: Optional[Dict[str, Any]] = None


class TaskSpec(BaseModel):
    # Core task fields
    task_id: str
    type: str                  # "feature" | "bugfix" | "refactor" | "CODE_CHANGE"
    title: str                 # short summary
    description: str           # more detail
    target_repo: str
    affected_files: List[str] = []
    acceptance_criteria: List[str] = []
    priority: str = "medium"   # "low" | "medium" | "high"
    created_at: datetime
    source: str = "manual"     # we override to "CodePilot AI User Portal" in create_default

    # --- New fields for status & history ---
    status: TaskStatus = TaskStatus.OPEN
    timeline: List[TaskEvent] = Field(default_factory=list)

    last_applied_at: Optional[datetime] = None
    last_test_run_at: Optional[datetime] = None
    last_test_status: Optional[str] = None

    # Branch used by CodePilot AI (e.g. cpai-xxxxxx)
    branch_name: Optional[str] = None

    @staticmethod
    def create_default() -> "TaskSpec":
        """
        Create a base TaskSpec with sane defaults for CodePilot AI.
        """
        now = datetime.utcnow()

        task = TaskSpec(
            task_id=str(uuid.uuid4()),
            title="",
            description="",
            affected_files=[],
            acceptance_criteria=[],
            type="CODE_CHANGE",
            target_repo="journalApp",
            source="CodePilot AI User Portal",
            created_at=now,
            status=TaskStatus.OPEN,
        )

        # Seed timeline with creation event
        task.timeline.append(
            TaskEvent(
                label="Task created",
                at=task.created_at,
                meta={"source": task.source},
            )
        )

        return task
