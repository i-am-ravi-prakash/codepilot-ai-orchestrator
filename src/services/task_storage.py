import json
import os
from pathlib import Path

TASKS_DIR = Path("tasks")
TASKS_DIR.mkdir(exist_ok=True)

def save_task(task: dict):
    task_id = task.get("task_id", "unknown")
    file_path = TASKS_DIR / f"{task_id}.json"
    with open(file_path, "w") as f:
        json.dump(task, f, indent=4)
    return str(file_path)

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

def load_task(task_id: str):
    """Load full task JSON by task_id."""
    file_path = TASKS_DIR / f"{task_id}.json"
    if not file_path.exists():
        return None
    with open(file_path, "r") as f:
        return json.load(f)
