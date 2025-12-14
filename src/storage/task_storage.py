import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

TASKS_DIR = Path("tasks")


def _ensure_dir() -> None:
    TASKS_DIR.mkdir(parents=True, exist_ok=True)


def save_task(task: Dict[str, Any]) -> None:
    """
    Persist a task to disk. The task is stored as a plain JSON file named
    <task_id>.json inside the `tasks/` directory.

    This function expects a plain dict. If you are working with a Pydantic model,
    call `model_dump(mode="json")` before passing it here.
    """
    _ensure_dir()
    task_id = task.get("task_id")
    if not task_id:
        raise ValueError("Task dict must include a 'task_id' field")

    path = TASKS_DIR / f"{task_id}.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(task, f, indent=4)


def load_task(task_id: str) -> Optional[Dict[str, Any]]:
    """
    Load a single task by id. Returns None if the task file does not exist.
    """
    path = TASKS_DIR / f"{task_id}.json"
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def list_tasks() -> List[Dict[str, Any]]:
    """
    Return all tasks as a list of dicts, sorted by created_at (newest first).
    If created_at is missing, those tasks are placed at the end.
    """
    _ensure_dir()
    tasks: List[Dict[str, Any]] = []
    for path in TASKS_DIR.glob("*.json"):
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
                tasks.append(data)
        except json.JSONDecodeError:
            # Skip corrupt files instead of crashing the whole server
            continue

    def sort_key(t: Dict[str, Any]) -> str:
        return t.get("created_at", "")

    tasks.sort(key=sort_key, reverse=True)
    return tasks


def add_task_event(task_id: str, event: str, details: Optional[str] = None) -> None:
    """
    Append an event to a task's timeline. Timeline is stored as a simple list
    of dicts under the 'timeline' key:

        {
          "at": "<ISO timestamp>",
          "event": "<short event name>",
          "details": "<optional details>"
        }
    """
    task = load_task(task_id)
    if not task:
        return

    timeline = task.setdefault("timeline", [])
    timeline.append(
        {
            "at": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "details": details,
        }
    )
    save_task(task)
