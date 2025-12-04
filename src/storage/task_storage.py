from datetime import datetime
from typing import Any, Dict, List, Optional

from src.models.task_spec import TaskSpec, TaskEvent

import json
import os
from pathlib import Path

TASKS_DIR = Path("tasks")
TASKS_DIR.mkdir(exist_ok=True)

def save_task(task: TaskSpec) -> None:
    """
    Persist a TaskSpec to disk as JSON.

    We use model_dump(mode="json") so that datetimes and nested models
    (like TaskEvent) are converted to JSON-serializable types.
    """
    path = TASKS_DIR / f"{task.task_id}.json"

    # task is a Pydantic model; convert to a pure dict with JSON-friendly types
    data = task.model_dump(mode="json")

    with open(path, "w") as f:
        json.dump(data, f, indent=4)


def list_tasks():
    """Return a list of {task_id, file_name} for all tasks."""
    items = []
    for file in TASKS_DIR.glob("*.json"):
        try:
            with open(file, "r") as f:
                data = json.load(f)
            items.append({
                "task_id": data.get("task_id"),
                "title": data.get("title"),
                "type": data.get("type"),
                "priority": data.get("priority"),
                "created_at": data.get("created_at"),
            })
        except Exception:
            # Skip corrupted files
            continue
    return items

def add_task_event(
    task: TaskSpec,
    label: str,
    meta: Optional[Dict[str, Any]] = None,
) -> TaskSpec:
    """
    Append a timeline event to the given task and return it.
    """
    event = TaskEvent(
        label=label,
        at=datetime.utcnow(),
        meta=meta,
    )
    task.timeline.append(event)
    return task


def load_task(task_id: str):
    """Load full task JSON by task_id."""
    file_path = TASKS_DIR / f"{task_id}.json"
    if not file_path.exists():
        return None
    with open(file_path, "r") as f:
        return json.load(f)

def add_task_event(
    task: TaskSpec,
    label: str,
    meta: Optional[Dict[str, Any]] = None,
) -> TaskSpec:
    """
    Append a timeline event to the given task and return it.
    """
    event = TaskEvent(
        label=label,
        at=datetime.utcnow(),
        meta=meta,
    )
    task.timeline.append(event)
    return task
