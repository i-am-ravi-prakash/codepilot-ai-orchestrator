from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from src.agents.spec_agent import generate_task_spec
from src.services.task_storage import save_task, list_tasks, load_task

app = FastAPI()

@app.get("/health")
def health():
    return {"status": "CodePilot AI is up and running fine..."}

class MessageInput(BaseModel):
    message: str

@app.post("/tasks/from-message")
def create_task_from_message(payload: MessageInput):
    """
    Takes a plain message (like from WhatsApp) and returns a structured TaskSpec.
    """
    task = generate_task_spec(payload.message)
    file_path = save_task(task)
    return {
        "status": "task_created",
        "task_id": task["task_id"],
        "storage_path": file_path,
        "task": task
    }

@app.get("/tasks")
def get_all_tasks():
    """
    List all generated tasks (summary).
    """
    tasks = list_tasks()
    return {"count": len(tasks), "items": tasks}

@app.get("/tasks/{task_id}")
def get_task(task_id: str):
    """
    Get full details of one task by ID.
    """
    task = load_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task
