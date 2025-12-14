# src/agents/spec_agent.py

import json
from typing import Dict, Any, List
from pathlib import Path

from src.services.git_service import ensure_repo_cloned, run_git_command
from src.services.openai_client import chat_completion_json  # <-- adjust import if your project differs


SPEC_SCHEMA_EXAMPLE = {
    "title": "Short task title",
    "description": "Clear description of what to change",
    "affected_files": ["path/from/repo/root/File1.ext", "path/from/repo/root/File2.ext"],
}


def _get_repo_file_list(repo_path: Path, limit: int = 3000) -> List[str]:
    """
    Get tracked files from the repo using `git ls-files`.
    """
    p = run_git_command(["git", "ls-files"], cwd=str(repo_path), allow_fail=False)
    files = [line.strip() for line in (p.stdout or "").splitlines() if line.strip()]
    # Avoid sending extremely large lists to LLM
    return files[:limit]


def generate_task_spec(user_message: str) -> Dict[str, Any]:
    """
    Generates a task spec, including affected_files.
    IMPORTANT: affected_files MUST exist in current repo.
    """

    # 1) Ensure repo exists locally
    repo_path = ensure_repo_cloned()

    # 2) Extract real files list
    repo_files = _get_repo_file_list(repo_path)

    if not repo_files:
        raise RuntimeError("Repo file list is empty. Is the repo cloned correctly?")

    # 3) Build prompt that forces choosing from repo_files only
    system = (
        "You are CodePilot AI Spec Agent.\n"
        "Your job is to convert the user's request into a task specification JSON.\n"
        "CRITICAL RULES:\n"
        "1) 'affected_files' MUST ONLY contain file paths that exist in the repo file list provided.\n"
        "2) If you are not confident about file paths, choose the closest matching files from the list.\n"
        "3) Output MUST be valid JSON only (no markdown, no commentary).\n"
    )

    user = {
        "user_request": user_message,
        "repo_file_list": repo_files,
        "required_output_schema": SPEC_SCHEMA_EXAMPLE,
        "notes": "Choose 1-5 affected_files max. Prefer minimal changes.",
    }

    # 4) Call model (JSON-only)
    # chat_completion_json should return a Python dict (parsed JSON)
    spec = chat_completion_json(system_prompt=system, user_payload=user)

    # 5) Validate output minimally
    if not isinstance(spec, dict):
        raise RuntimeError("Spec agent returned non-dict output")

    spec.setdefault("title", "Untitled Task")
    spec.setdefault("description", user_message.strip())
    spec.setdefault("affected_files", [])

    # 6) Hard validation: affected_files must exist in repo_files
    cleaned = []
    repo_set = set(repo_files)
    for f in spec.get("affected_files", []) or []:
        if isinstance(f, str) and f.strip() in repo_set:
            cleaned.append(f.strip())

    if not cleaned:
        # fallback: pick at least ONE file to prevent breaking pipeline
        # (this makes the system demo-able even if LLM struggles)
        cleaned = [repo_files[0]]

    spec["affected_files"] = cleaned

    return spec
