import subprocess
from pathlib import Path
from typing import Optional, List
import os


def run_git_command(
    cmd: List[str],
    cwd: Optional[str] = None,
    allow_fail: bool = False,
) -> subprocess.CompletedProcess:
    """
    Runs a git command with pretty logs.
    If allow_fail=True, it won't raise even if command fails.
    """
    print(f"▶ {' '.join(cmd)} (cwd={cwd})")
    p = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True)

    if p.stdout:
        print("stdout:", p.stdout.strip())
    else:
        print("stdout:")

    if p.stderr:
        print("stderr:", p.stderr.strip())
    else:
        print("stderr:")

    if p.returncode != 0 and not allow_fail:
        raise RuntimeError(
            f"Git command failed: {' '.join(cmd)}\n"
            f"cwd={cwd}\n"
            f"stdout={p.stdout}\n"
            f"stderr={p.stderr}"
        )
    return p


def ensure_repo_cloned() -> Path:
    """
    Ensures repo exists locally. Clones if not present, otherwise pulls latest.
    Uses TARGET_REPO_URL and TARGET_REPO_LOCAL_PATH from env.
    """
    repo_url = os.getenv("TARGET_REPO_URL")
    repo_path_str = os.getenv("TARGET_REPO_LOCAL_PATH")

    if not repo_url or not repo_path_str:
        raise RuntimeError("TARGET_REPO_URL / TARGET_REPO_LOCAL_PATH not set")

    repo_path = Path(repo_path_str)

    if not repo_path.exists():
        print("📥 Cloning repo for the first time...")
        repo_path.parent.mkdir(parents=True, exist_ok=True)
        run_git_command(["git", "clone", repo_url, str(repo_path)], cwd=None)
    else:
        print("📁 Repo already cloned, pulling latest changes...")
        run_git_command(["git", "fetch", "origin"], cwd=str(repo_path), allow_fail=False)

    # Ensure base branch exists and pull
    base_branch = "master"  # you can make configurable later
    run_git_command(["git", "checkout", base_branch], cwd=str(repo_path), allow_fail=False)
    run_git_command(["git", "pull", "origin", base_branch], cwd=str(repo_path), allow_fail=False)

    return repo_path


def create_feature_branch(repo_path: Path, branch_name: str) -> None:
    """
    Creates or checks out a feature branch inside the repo.
    """
    branch_name = branch_name.strip()
    if not branch_name:
        raise ValueError("branch_name cannot be empty")

    # If branch exists locally, checkout works
    p = run_git_command(["git", "checkout", branch_name], cwd=str(repo_path), allow_fail=True)
    if p.returncode == 0:
        return

    # Otherwise create a new branch from current HEAD
    run_git_command(["git", "checkout", "-b", branch_name], cwd=str(repo_path), allow_fail=False)


def commit_and_push(repo_path: Path, branch_name: str, commit_message: str) -> None:
    """
    Commits changes and pushes the branch.
    """
    run_git_command(["git", "status"], cwd=str(repo_path))
    run_git_command(["git", "add", "."], cwd=str(repo_path))
    run_git_command(["git", "commit", "-m", commit_message], cwd=str(repo_path), allow_fail=False)
    run_git_command(["git", "push", "-u", "origin", branch_name], cwd=str(repo_path), allow_fail=False)
