import os
import subprocess
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

TARGET_REPO_URL = os.getenv("TARGET_REPO_URL")
TARGET_REPO_DEFAULT_BRANCH = os.getenv("TARGET_REPO_DEFAULT_BRANCH", "master")
TARGET_REPO_LOCAL_PATH = Path(os.getenv("TARGET_REPO_LOCAL_PATH", "./workspace/journalApp"))


def run_git_command(args, cwd=None):
    """
    Helper to run a git command and print output.
    Raises RuntimeError if git command fails.
    """
    print(f"▶ git {' '.join(args)} (cwd={cwd})")
    result = subprocess.run(
        ["git"] + args,
        cwd=cwd,
        text=True,
        capture_output=True,
    )
    print("stdout:", result.stdout)
    print("stderr:", result.stderr)
    if result.returncode != 0:
        raise RuntimeError(f"Git command failed: {' '.join(args)}")
    return result.stdout.strip()


def ensure_repo_cloned():
    """
    Ensure the target repo is cloned locally and on the default branch.

    If the repo already exists but has local modifications that block
    `git checkout <default branch>`, we aggressively clean the working tree
    (reset --hard + clean -fd) because this is a *workspace* clone managed
    by CodePilot, not a place for manual editing.
    """
    if not TARGET_REPO_LOCAL_PATH.exists():
        print("📥 Cloning repo for the first time...")
        TARGET_REPO_LOCAL_PATH.parent.mkdir(parents=True, exist_ok=True)

        run_git_command(
            ["clone", TARGET_REPO_URL, str(TARGET_REPO_LOCAL_PATH)],
            cwd=None,
        )
        run_git_command(
            ["checkout", TARGET_REPO_DEFAULT_BRANCH],
            cwd=TARGET_REPO_LOCAL_PATH,
        )
        run_git_command(
            ["pull", "origin", TARGET_REPO_DEFAULT_BRANCH],
            cwd=TARGET_REPO_LOCAL_PATH,
        )
    else:
        print("📁 Repo already cloned, pulling latest changes...")
        run_git_command(["fetch", "origin"], cwd=TARGET_REPO_LOCAL_PATH)

        # Try to checkout default branch; if it fails due to local changes, clean and retry
        try:
            run_git_command(
                ["checkout", TARGET_REPO_DEFAULT_BRANCH],
                cwd=TARGET_REPO_LOCAL_PATH,
            )
        except RuntimeError as e:
            print(
                f"⚠️ Checkout {TARGET_REPO_DEFAULT_BRANCH} failed, cleaning working tree: {e}"
            )

            # Discard all local changes in the current branch
            subprocess.run(
                ["git", "reset", "--hard"],
                cwd=TARGET_REPO_LOCAL_PATH,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            # Remove untracked files (e.g., .DS_Store, build artifacts)
            subprocess.run(
                ["git", "clean", "-fd"],
                cwd=TARGET_REPO_LOCAL_PATH,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            # Retry checkout; if this still fails, let it raise
            run_git_command(
                ["checkout", TARGET_REPO_DEFAULT_BRANCH],
                cwd=TARGET_REPO_LOCAL_PATH,
            )

        run_git_command(
            ["pull", "origin", TARGET_REPO_DEFAULT_BRANCH],
            cwd=TARGET_REPO_LOCAL_PATH,
        )


def create_feature_branch(branch_name: str):
    """
    Create and checkout a new feature branch from default branch.
    """
    ensure_repo_cloned()
    run_git_command(["checkout", TARGET_REPO_DEFAULT_BRANCH], cwd=TARGET_REPO_LOCAL_PATH)
    run_git_command(
        ["pull", "origin", TARGET_REPO_DEFAULT_BRANCH],
        cwd=TARGET_REPO_LOCAL_PATH,
    )
    run_git_command(["checkout", "-b", branch_name], cwd=TARGET_REPO_LOCAL_PATH)


def commit_and_push(branch_name: str, commit_message: str):
    """
    Commit all changes and push the given branch to origin.
    Always commits on the specified branch (not on default branch).
    """
    if not TARGET_REPO_LOCAL_PATH.exists():
        raise RuntimeError("Local repo does not exist. Call ensure_repo_cloned() first.")

    # Make sure we are on the correct branch
    run_git_command(["checkout", branch_name], cwd=TARGET_REPO_LOCAL_PATH)

    # Stage all changes
    run_git_command(["add", "."], cwd=TARGET_REPO_LOCAL_PATH)

    # If there's nothing to commit, git commit will fail; handle that gracefully
    try:
        run_git_command(["commit", "-m", commit_message], cwd=TARGET_REPO_LOCAL_PATH)
    except RuntimeError as e:
        # If commit fails due to "nothing to commit", just skip
        msg = str(e)
        if "nothing to commit" in msg or "no changes added to commit" in msg:
            print("ℹ️ No changes to commit; skipping commit step.")
        else:
            raise

    # Push the branch
    run_git_command(["push", "-u", "origin", branch_name], cwd=TARGET_REPO_LOCAL_PATH)
