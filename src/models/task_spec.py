from typing import List
from uuid import uuid4
import os

from pydantic import BaseModel, Field


class TaskSpec(BaseModel):
    """
    Minimal Task specification model used by spec_agent to structure model output.
    The rest of the system stores tasks as plain JSON/dicts, so this model is only
    used at generation time.
    """

    task_id: str
    title: str
    description: str
    target_repo: str
    target_branch: str
    affected_files: List[str] = Field(default_factory=list)

    @staticmethod
    def create_default() -> "TaskSpec":
        return TaskSpec(
            task_id=str(uuid4()),
            title="",
            description="",
            target_repo=os.getenv("TARGET_REPO_URL", ""),
            target_branch=os.getenv("TARGET_REPO_BRANCH", "master"),
            affected_files=[],
        )
