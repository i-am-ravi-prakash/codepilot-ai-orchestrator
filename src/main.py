import os
from src.services.git_service import create_feature_branch, commit_and_push, ensure_repo_cloned
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from pathlib import Path
from src.agents.coding_agent import generate_updated_file_content
from src.agents.spec_agent import generate_task_spec
from src.services.task_storage import save_task, list_tasks, load_task
from datetime import datetime, timezone

app = FastAPI(
    title="CodePilot AI Orchestrator",
    description="Task + Coding agent backend that converts natural language change requests into Git branches with code changes.",
    version="1.0.0",
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
      - If no match is found, raise 400.
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
        # We auto-resolved by filename
        return matches[0]

    if len(matches) > 1:
        # Too ambiguous
        rels = [str(m.relative_to(repo_path)) for m in matches]
        raise HTTPException(
            status_code=400,
            detail=(
                f"Multiple matches for file '{filename}' in repo. "
                f"Candidates: {', '.join(rels)}. "
                "Please specify a more precise path in affected_files."
            ),
        )

    # No matches at all
    raise HTTPException(
        status_code=400,
        detail=(
            f"Affected file does not exist in repo: {rel_path} "
            f"(and no file named '{filename}' found anywhere in the repo)."
        ),
    )

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
        # Resolve to an actual existing file in the repo
        target_file = resolve_repo_file(rel_path, repo_path)
        resolved_rel = str(target_file.relative_to(repo_path))

        original_content = target_file.read_text(encoding="utf-8")

        # Decide language hint (based on resolved path)
        lang_hint = req.language_hint or guess_language_from_extension(resolved_rel)

        updated_content = generate_updated_file_content(
            original_content=original_content,
            file_path=resolved_rel,
            instruction=description,
            language_hint=lang_hint,
        )

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

    return {
        "status": "ok",
        "task_id": task_id,
        "branch": branch_name,
        "files_modified": actual_modified_paths,
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
