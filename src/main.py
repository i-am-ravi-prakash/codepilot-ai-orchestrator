import subprocess
import os
from src.services.git_service import create_feature_branch, commit_and_push, ensure_repo_cloned
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from pathlib import Path
from src.agents.coding_agent import generate_updated_file_content
from src.agents.spec_agent import generate_task_spec
from src.storage.task_storage import save_task, list_tasks, load_task
from datetime import datetime, timezone
from src.storage.task_storage import load_task, save_task
#from src.services.git_service import ensure_repo_cloned
from src.services.test_service import run_tests_in_repo
from fastapi.middleware.cors import CORSMiddleware
from src.models.task_spec import TaskSpec, TaskStatus
from src.storage.task_storage import load_task, save_task, list_tasks, add_task_event

app = FastAPI(
    title="CodePilot AI Orchestrator",
    description="Task + Coding agent backend that converts natural language change requests into Git branches with code changes.",
    version="1.0.0",
)

# Allow your frontend to call the backend (dev-friendly config)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],      # for dev; later restrict to specific origin
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

TASKS_DIR = Path("tasks")

@app.get("/health", tags=["system"])
def health():
    checks = {}
    errors: list[str] = []

    # 1) OpenAI key configured
    openai_key_present = bool(os.getenv("OPENAI_API_KEY"))
    checks["openai_api_key"] = "configured" if openai_key_present else "missing"
    if not openai_key_present:
        errors.append("OPENAI_API_KEY is not configured")

    # 2) Task storage directory writable
    try:
        TASKS_DIR.mkdir(exist_ok=True)
        test_file = TASKS_DIR / ".healthcheck"
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink()
        checks["task_storage"] = "ok"
    except Exception as e:
        checks["task_storage"] = f"error: {e}"
        errors.append("Task storage directory is not writable")

    # 3) Target repo configuration
    target_repo_url = os.getenv("TARGET_REPO_URL")
    checks["target_repo_configured"] = bool(target_repo_url)
    if not target_repo_url:
        errors.append("TARGET_REPO_URL is not configured")

    status = "healthy" if not errors else "degraded"

    return {
        "status": status,
        "checks": checks,
        "errors": errors,
    }

class MessageInput(BaseModel):
    message: str

class CodeChangeRequest(BaseModel):
    branch_name: str
    file_relative_path: str
    content_to_append: str

class AICodeChangeRequest(BaseModel):
    branch_name: str
    file_relative_path: str      # e.g. "src/main/java/.../SomeService.java"
    instruction: str             # what change to apply
    language_hint: str | None = None

class ApplyTaskCodeRequest(BaseModel):
    language_hint: str | None = None  # same hint for all files; optional


def guess_language_from_extension(path: str) -> str | None:
    if path.endswith(".java"):
        return "java"
    if path.endswith(".py"):
        return "python"
    if path.endswith(".md"):
        return "markdown"
    if path.endswith(".js"):
        return "javascript"
    if path.endswith(".ts"):
        return "typescript"
    # Add more as needed
    return None

@app.post(
    "/tasks/from-message",
    tags=["tasks"],
    summary="Create Task From Message",
)
def create_task_from_message(payload: MessageInput):
    task = generate_task_spec(payload.message)
    # Force source to be CodePilot AI User Portal
    task["source"] = "CodePilot AI User Portal"
    now = datetime.now(timezone.utc).isoformat()

    # Ensure minimal fields
    task.setdefault("task_id", task.get("id"))
    task["status"] = "open"
    task["created_at"] = now
    task["updated_at"] = now

    save_task(task)
    return task

@app.post("/tasks/{task_id}/run-tests", tags=["tasks"])
def run_tests_for_task(task_id: str):
    """
    Run tests for the branch associated with a given task.

    Flow:
    - Load task by task_id
    - Ensure task has 'applied_branch' (i.e. /apply-change was already called)
    - Use local repo at TARGET_REPO_LOCAL_PATH
    - git checkout <applied_branch>
    - Run tests in the repo (mvn test / ./mvnw test)
    - Update task with last_test_status + run_history entry
    """

    # 1. Load the task
    task = load_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    applied_branch = task.get("applied_branch")
    if not applied_branch:
        raise HTTPException(
            status_code=400,
            detail=(
                "Task has no applied_branch. You must apply the code changes "
                "via /tasks/{task_id}/apply-change before running tests."
            ),
        )

    # 2. Use the existing local repo; it should already be cloned by apply-change
    repo_path = Path(os.getenv("TARGET_REPO_LOCAL_PATH", "./workspace/journalApp"))
    if not repo_path.exists():
        raise HTTPException(
            status_code=500,
            detail=(
                "Local repo not found at TARGET_REPO_LOCAL_PATH. "
                "Make sure /tasks/{task_id}/apply-change has been successfully called at least once."
            ),
        )

    # Checkout the branch where the code for this task lives
    try:
        proc = subprocess.run(
            ["git", "checkout", applied_branch],
            cwd=repo_path,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        print(f"✅ Checked out branch {applied_branch} for tests")
        if proc.stdout:
            print(proc.stdout)
        if proc.stderr:
            print(proc.stderr)
    except subprocess.CalledProcessError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to checkout branch {applied_branch}: {e.stderr or str(e)}",
        )

    # Optional: pull latest changes for that branch (non-fatal if it fails)
    try:
        subprocess.run(
            ["git", "pull", "origin", applied_branch],
            cwd=repo_path,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except Exception as e:
        print(f"⚠️ Could not pull branch {applied_branch}: {e}")

    # 3. Run tests
    try:
        result = run_tests_in_repo(repo_path)
    except Exception as e:
        now = datetime.now(timezone.utc).isoformat()
        error_message = str(e)

        # Update task with test error info
        history = task.get("run_history") or []
        history.append(
            {
                "type": "test_run",
                "test_status": "error",
                "error": error_message,
                "at": now,
                "branch": applied_branch,
            }
        )
        task["run_history"] = history
        task["last_test_status"] = "error"
        task["last_test_at"] = now
        save_task(task)

        raise HTTPException(
            status_code=500,
            detail=f"Error while running tests: {error_message}",
        )

    # 4. Interpret result
    now = datetime.now(timezone.utc).isoformat()
    test_status = "passed" if result["success"] else "failed"

    # Update task metadata
    task["last_test_status"] = test_status
    task["last_test_at"] = now

    history = task.get("run_history") or []
    history.append(
        {
            "type": "test_run",
            "test_status": test_status,
            "exit_code": result["exit_code"],
            "at": now,
            "branch": applied_branch,
        }
    )
    task["run_history"] = history

    save_task(task)

    # 5. Return a summary with logs (tail)
        # --- Update task status & timeline after successful apply-change ---

    task = load_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    # Ensure branch name is stored on task (even if not previously set)
    task.branch_name = task.branch_name or f"cpai-{task_id[:6]}"

    task.status = TaskStatus.CODE_APPLIED
    task.last_applied_at = datetime.utcnow()

    add_task_event(
        task,
        label="Code changes applied",
        meta={
            "branch": task.branch_name,
            "files": task.affected_files,
        },
    )

    save_task(task)

        # --- Update task status & timeline based on test result ---

    task = load_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    task.last_test_run_at = datetime.utcnow()

    overall_status = result.get("status")
    task.last_test_status = overall_status

    if overall_status == "passed":
        task.status = TaskStatus.TESTS_PASSED
        event_label = "Tests passed"
    else:
        task.status = TaskStatus.TESTS_FAILED
        event_label = "Tests failed"

    # Ensure branch_name is set on task for UI
    task.branch_name = task.branch_name or f"cpai-{task_id[:6]}"

    add_task_event(
        task,
        label=event_label,
        meta={
            "branch": task.branch_name,
            "exit_code": result.get("exit_code"),
        },
    )

    save_task(task)



    return {
        "task_id": task_id,
        "branch": task.branch_name,
        "status": task.status,
        "exit_code": result["exit_code"],
        "stdout_tail": result["stdout"],
        "stderr_tail": result["stderr"],
    }


@app.get("/tasks", tags=["tasks"])
def get_tasks():
    tasks = list_tasks()
    for t in tasks:
        if "status" not in t:
            t["status"] = "open"
    return tasks

@app.get("/tasks/{task_id}", tags=["tasks"])
def get_task(task_id: str):
    task = load_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if "status" not in task:
        task["status"] = "open"
    return task

@app.post("/codepilot/test-change", include_in_schema=False)
def create_test_change(req: CodeChangeRequest):
    """
    Test endpoint:
    - Clones/updates journalApp
    - Creates a new branch
    - Appends some text to a file
    - Commits and pushes the branch
    """

def resolve_repo_file(rel_path: str, repo_path: Path) -> Path:
    """
    Resolve a file path inside the repo.

    - If rel_path exists as-is, return it.
    - Otherwise, search by filename across the repo.
      - If exactly one match is found, return that path.
      - If multiple matches are found, raise 400 asking user to be more specific.
      - If no match is found, return the candidate path
        (caller may choose to create a new file there).
    """
    candidate = repo_path / rel_path
    if candidate.exists():
        return candidate

    filename = Path(rel_path).name
    matches: list[Path] = []

    for root, dirs, files in os.walk(repo_path):
        if filename in files:
            matches.append(Path(root) / filename)

    if len(matches) == 1:
        # Auto-resolved by filename
        return matches[0]

    if len(matches) > 1:
        # Too ambiguous: same filename in multiple locations
        rels = [str(m.relative_to(repo_path)) for m in matches]
        raise HTTPException(
            status_code=400,
            detail=(
                f"Multiple matches for file '{filename}' in repo. "
                f"Candidates: {', '.join(rels)}. "
                "Please specify a more precise path in affected_files."
            ),
        )

    # No matches at all:
    # instead of error, we allow the caller to treat this as a NEW file path.
    return candidate


@app.post("/tasks/{task_id}/apply-change", tags=["tasks"])
def apply_change_for_task(task_id: str, req: ApplyTaskCodeRequest):
    """
    Apply AI-generated code changes for a given TaskSpec.

    - Reads the task (description + affected_files)
    - Creates a feature branch: cpai-<first 6 chars of task_id without dashes>
    - Modifies the files via Coding Agent
    - Commits & pushes the branch
    - Updates the task to status='closed' and records applied_branch
    """

    # 1. Load the task
    task = load_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Default missing status to 'open'
    status = task.get("status", "open")
    if status == "closed":
        raise HTTPException(
            status_code=400,
            detail="Task is already closed. Create a new task for additional changes.",
        )

    description = task.get("description", "")
    affected_files = task.get("affected_files") or []

    if not description:
        raise HTTPException(status_code=400, detail="Task has no description")

    if not affected_files:
        raise HTTPException(
            status_code=400,
            detail="Task has no affected_files. Ensure the spec agent populates this list.",
        )

    # 2. Compute branch name: cpai-<first 6 chars of task_id without dashes>
    compact_id = task_id.replace("-", "")
    branch_name = f"cpai-{compact_id[:6]}"

    # 3. Ensure repo ready & create branch
    ensure_repo_cloned()
    create_feature_branch(branch_name)

    repo_path = Path(os.getenv("TARGET_REPO_LOCAL_PATH", "./workspace/journalApp"))

        # 4. Apply AI change per file
    actual_modified_paths: list[str] = []

    for rel_path in affected_files:
        # Resolve to a file path in the repo.
        # May or may not exist yet.
        target_file = resolve_repo_file(rel_path, repo_path)
        resolved_rel = str(target_file.relative_to(repo_path))

        if target_file.exists():
            original_content = target_file.read_text(encoding="utf-8")
        else:
            # New file: start from empty content
            original_content = ""

        # Decide language hint (based on resolved path)
        lang_hint = req.language_hint or guess_language_from_extension(resolved_rel)

        updated_content = generate_updated_file_content(
            original_content=original_content,
            file_path=resolved_rel,
            instruction=description,
            language_hint=lang_hint,
        )

        # Ensure parent directories exist for new files
        target_file.parent.mkdir(parents=True, exist_ok=True)

        target_file.write_text(updated_content, encoding="utf-8")
        actual_modified_paths.append(resolved_rel)


    # 5. Commit & push
    commit_message = f"CodePilot AI: {description[:60]}"
    commit_and_push(branch_name, commit_message)

    # 6. Update task metadata: status + applied_branch + updated_at
    now = datetime.now(timezone.utc).isoformat()
    task["status"] = "closed"
    task["applied_branch"] = branch_name
    task["updated_at"] = now

    # Optional small history log
    history_entry = {
        "applied_at": now,
        "branch": branch_name,
        "files_modified": actual_modified_paths,
    }
    history = task.get("run_history") or []
    history.append(history_entry)
    task["run_history"] = history

    save_task(task)

        # --- Update task status & timeline after successful apply-change ---

    task = load_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    # Ensure we store the branch name on the task for UI
    task.branch_name = task.branch_name or branch_name

    task.status = TaskStatus.CODE_APPLIED
    task.last_applied_at = datetime.utcnow()

    add_task_event(
        task,
        label="Code changes applied",
        meta={
            "branch": task.branch_name,
            "files": task.affected_files,
        },
    )

    save_task(task)


    return {
        "status": task.status,
        "task_id": task_id,
        "branch": task.branch_name,
    }

@app.post("/codepilot/apply-ai-change", include_in_schema=False)
def apply_ai_change(req: AICodeChangeRequest):
    """
    Use GPT-4o to modify a file in journalApp:
    - Creates/uses a feature branch
    - Reads the existing file
    - Asks Coding Agent to generate updated content
    - Writes updated file, commits and pushes
    """

    try:
        # 1. Ensure repo is cloned and up to date
        ensure_repo_cloned()

        # 2. Create branch (if it doesn't already exist)
        branch = req.branch_name
        create_feature_branch(branch)

        # 3. Read existing file content
        repo_path = Path(os.getenv("TARGET_REPO_LOCAL_PATH", "./workspace/journalApp"))
        target_file = repo_path / req.file_relative_path

        if not target_file.exists():
            raise HTTPException(
                status_code=400,
                detail=f"File {req.file_relative_path} does not exist in journalApp repo",
            )

        original_content = target_file.read_text(encoding="utf-8")

        # 4. Ask Coding Agent (GPT-4o) for updated content
        updated_content = generate_updated_file_content(
            original_content=original_content,
            file_path=req.file_relative_path,
            instruction=req.instruction,
            language_hint=req.language_hint,
        )

        # 5. Overwrite the file with updated content
        target_file.write_text(updated_content, encoding="utf-8")

        # 6. Commit & push
        commit_and_push(branch, f"CodePilot AI: {req.instruction[:60]}")

        return {
            "status": "ok",
            "branch": branch,
            "file_modified": req.file_relative_path,
        }

    except HTTPException:
        raise
    except Exception as e:
        print("❌ Error in apply_ai_change:", repr(e))
        raise HTTPException(status_code=500, detail=str(e))


    try:
        # 1. Ensure repo is cloned
        ensure_repo_cloned()

        # 2. Create branch
        branch = req.branch_name
        create_feature_branch(branch)

        # 3. Modify file inside journalApp repo
        repo_path = Path(os.getenv("TARGET_REPO_LOCAL_PATH", "./workspace/journalApp"))
        target_file = repo_path / req.file_relative_path

        target_file.parent.mkdir(parents=True, exist_ok=True)
        with open(target_file, "a") as f:
            f.write("\n" + req.content_to_append + "\n")

        # 4. Commit & push
        commit_and_push(branch, f"CodePilot AI test change on {req.file_relative_path}")

        return {
            "status": "ok",
            "branch": branch,
            "file_modified": req.file_relative_path,
        }
    except Exception as e:
        print("❌ Error in create_test_change:", repr(e))
        raise HTTPException(status_code=500, detail=str(e))
