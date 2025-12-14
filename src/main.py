import os
from typing import Optional
from pathlib import Path
from datetime import datetime, timezone

from pydantic import BaseModel
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from src.services.git_service import create_feature_branch, commit_and_push, ensure_repo_cloned
from src.services.test_service import run_tests_in_repo
from src.agents.coding_agent import generate_updated_file_content
from src.agents.spec_agent import generate_task_spec
from src.storage.task_storage import save_task, list_tasks, load_task, add_task_event


# -----------------------------------------------------------------------------
# App setup
# -----------------------------------------------------------------------------

app = FastAPI(
    title="CodePilot AI Orchestrator",
    description="Backend for orchestrating AI coding, testing, and git workflows.",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten later
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -----------------------------------------------------------------------------
# Request/Response models
# -----------------------------------------------------------------------------

class HealthStatus(BaseModel):
    status: str


class MessageInput(BaseModel):
    message: str


class ApplyTaskCodeRequest(BaseModel):
    """
    Optional inputs for apply-change.
    We keep this minimal and stable (AI infers file from task spec).
    """
    language_hint: Optional[str] = None
    branch_name: Optional[str] = None


class RunTestsRequest(BaseModel):
    branch_name: str


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_task_or_404(task_id: str) -> dict:
    task = load_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return task


def _pick_target_file_from_task(task: dict) -> str:
    """
    Picks a file to modify from the task spec.
    Expected: task contains 'affected_files': [ 'path/to/file', ... ]
    """
    affected = task.get("affected_files") or []
    if not affected:
        raise HTTPException(
            status_code=400,
            detail=(
                "Task has no affected_files. "
                "Please update your spec_agent to include affected_files, "
                "or send repo_relative_path in request (not recommended)."
            ),
        )
    return affected[0]


# -----------------------------------------------------------------------------
# Endpoints
# -----------------------------------------------------------------------------

@app.get("/health", response_model=HealthStatus)
def health():
    return {"status": "ok"}


@app.post("/tasks/from-message")
def create_task_from_message(payload: MessageInput):
    """
    Creates a task using Spec Agent based on natural language input.
    Persists it in JSON storage.
    """
    raw_message = payload.message.strip()
    if not raw_message:
        raise HTTPException(status_code=400, detail="message cannot be empty")

    now_iso = _utc_now_iso()

    task_spec_dict = generate_task_spec(raw_message)

    # Ensure a few defaults
    task_spec_dict.setdefault("status", "open")
    task_spec_dict.setdefault("source", "CodePilot AI UI")
    task_spec_dict.setdefault("timeline", [])

    # Add initial timeline event
    task_spec_dict["timeline"].append(
        {"at": now_iso, "event": "created", "details": f"Task created from message: {raw_message}"}
    )

    save_task(task_spec_dict)
    return task_spec_dict


@app.get("/tasks")
def get_all_tasks():
    """
    List all tasks, newest first.
    """
    tasks = list_tasks()
    return {"tasks": tasks}


@app.get("/tasks/{task_id}")
def get_task(task_id: str):
    """
    Fetch a single task by ID.
    """
    return _get_task_or_404(task_id)


@app.post("/tasks/{task_id}/apply-change")
def apply_change_for_task(task_id: str, req: Optional[ApplyTaskCodeRequest] = None):
    """
    Apply AI-generated code changes for a task.

    Flow:
      1. Load task
      2. Ensure target repo is cloned
      3. Create a feature branch
      4. Pick target file from task['affected_files']
      5. Generate updated content using Coding Agent
      6. Write file
      7. Commit & push
      8. Update task timeline
    """
    task = _get_task_or_404(task_id)

    # Optional inputs
    language_hint = None
    branch_name_override = None
    if req is not None:
        language_hint = req.language_hint
        branch_name_override = req.branch_name

    repo_path: Path = ensure_repo_cloned()
    add_task_event(task_id, "repo_ready", f"Repo ready at: {repo_path}")

    # Branch name
    branch_name = (branch_name_override or "").strip() or f"cpai-{task_id[:6]}"

    # Create branch
    create_feature_branch(repo_path, branch_name)
    add_task_event(task_id, "branch_created", f"Branch created/checked out: {branch_name}")

    # Decide which file to change
    repo_relative_path = _pick_target_file_from_task(task)
    file_path = repo_path / repo_relative_path

    if not file_path.exists():
        raise HTTPException(
            status_code=400,
            detail=f"Target file does not exist in repo: {repo_relative_path}",
        )

    original_content = file_path.read_text(encoding="utf-8", errors="ignore")

    # Call coding agent to generate new content
    new_content = generate_updated_file_content(
        task=task,
        file_relative_path=repo_relative_path,
        original_content=original_content,
        language_hint=language_hint,
    )

    if not isinstance(new_content, str) or not new_content.strip():
        raise HTTPException(
            status_code=500,
            detail="Coding agent returned empty/invalid content.",
        )

    # Write updated file
    file_path.write_text(new_content, encoding="utf-8")
    add_task_event(task_id, "file_updated", f"Updated file: {repo_relative_path}")

    # Commit and push
    commit_message = f"[CodePilot] Apply change for task {task_id}"
    commit_and_push(repo_path, branch_name, commit_message)
    add_task_event(task_id, "pushed", f"Committed & pushed changes on branch: {branch_name}")

    # Update task metadata and timeline
    now_iso = _utc_now_iso()
    task["last_applied_branch"] = branch_name
    task.setdefault("timeline", []).append(
        {
            "at": now_iso,
            "event": "code_change_applied",
            "details": f"Changes applied to {repo_relative_path} on branch {branch_name}",
        }
    )
    save_task(task)

    return {
        "status": "success",
        "task_id": task_id,
        "branch": branch_name,
        "updated_file": repo_relative_path,
    }


@app.post("/tasks/{task_id}/run-tests")
def run_tests_for_task(task_id: str, payload: RunTestsRequest):
    """
    Run tests on the target repo for a given branch.
    """
    task = _get_task_or_404(task_id)

    repo_path: Path = ensure_repo_cloned()
    branch_name = payload.branch_name.strip()
    if not branch_name:
        raise HTTPException(status_code=400, detail="branch_name cannot be empty")

    add_task_event(task_id, "tests_started", f"Running tests on branch: {branch_name}")

    result = run_tests_in_repo(repo_path, branch_name)

    now_iso = _utc_now_iso()
    task.setdefault("timeline", []).append(
        {
            "at": now_iso,
            "event": "tests_run",
            "details": f"Tests run on branch {branch_name} (exit_code={result.exit_code})",
        }
    )
    save_task(task)

    add_task_event(
        task_id,
        "tests_finished",
        f"Tests completed (exit_code={result.exit_code}) on branch: {branch_name}",
    )

    return {
        "status": "passed" if result.exit_code == 0 else "failed",
        "task_id": task_id,
        "branch": branch_name,
        "exit_code": result.exit_code,
        "stdout_tail": result.stdout_tail,
        "stderr_tail": result.stderr_tail,
    }
