import subprocess
import shutil
from pathlib import Path


def run_tests_in_repo(repo_path: Path, timeout: int = 600) -> dict:
    """
    Run backend tests in the given repo directory.

    For journalApp (Spring Boot), we try:
      1) ./mvnw test  (if Maven wrapper exists)
      2) mvn test     (if mvn is installed)

    Returns a dict with:
      - success: bool
      - exit_code: int
      - stdout: str (tail, truncated)
      - stderr: str (tail, truncated)
    """
    if not repo_path.exists():
        raise RuntimeError(f"Repo path does not exist: {repo_path}")

    # Prefer Maven wrapper if present
    if (repo_path / "mvnw").exists():
        cmd = ["./mvnw", "test"]
    elif shutil.which("mvn"):
        cmd = ["mvn", "test"]
    else:
        raise RuntimeError(
            "No Maven wrapper (mvnw) or mvn executable found. "
            "Install Maven or add a test runner script."
        )

    proc = subprocess.run(
        cmd,
        cwd=repo_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
    )

    success = proc.returncode == 0

    # Keep only the last N characters so response isn't huge
    max_len = 4000
    stdout_tail = proc.stdout[-max_len:] if proc.stdout else ""
    stderr_tail = proc.stderr[-max_len:] if proc.stderr else ""

    return {
        "success": success,
        "exit_code": proc.returncode,
        "stdout": stdout_tail,
        "stderr": stderr_tail,
    }
