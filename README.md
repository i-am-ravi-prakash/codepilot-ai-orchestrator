# CodePilot AI Orchestrator

Autonomous multi-agent backend for **CodePilot AI** – a personal project that turns natural language change requests into real code changes on a Git repository.

> Example:  
> “Add logging to `Utilities.java` and fix the null pointer issue in the save flow”  
> ⟶ becomes a structured task ⟶ AI updates your code ⟶ changes are pushed to a new branch.

---

## ✨ What this backend does (current state)

**Implemented modules:**

1. **Task Spec Agent**
   - Endpoint: `POST /tasks/from-message`
   - Input: natural language message (change request / bug / refactor).
   - Uses OpenAI (`gpt-4o`) to generate a **TaskSpec JSON**, including:
     - `task_id`, `created_at`
     - `title`, `description`
     - `type` (e.g., feature / bugfix / refactor)
     - `affected_files` (relative paths in the repo, or best guesses)
     - `target_repo`, `source`, `status` (managed by backend)
   - Persists each task as `tasks/{task_id}.json`.

2. **Task Management**
   - `GET /tasks`  
     Returns a list of all tasks with summary info (id, title, status).
   - `GET /tasks/{task_id}`  
     Returns full JSON for a single task, including:
     - metadata (`task_id`, `created_at`, `updated_at`)
     - `status` (`open` / `closed`)
     - `source: "CodePilot AI User Portal"`
     - `applied_branch` (after code is applied)
     - `run_history` (apply runs, etc.)

3. **Code Apply Agent (Git-integrated)**
   - Endpoint: `POST /tasks/{task_id}/apply-change`
   - For a given task:
     - Validates that the task exists and is **open**
     - Clones / updates the target repo to a local workspace
     - Creates a new feature branch:

       ```text
       cpai-<first_6_characters_of_task_id_without_dashes>
       # e.g. task_id = 4e864492-2359-4680-8793-918a40b1aa79
       # branch  = cpai-4e8644
       ```

     - For each `affected_file`:
       - If the path exists, it’s used directly
       - If not, it **auto-resolves by filename** (e.g. `Utilities.java`) by searching the repo
         - If exactly one match is found → uses that path
         - If multiple / none → returns a clear 400 error
     - Calls the Coding Agent (OpenAI) to generate updated file content based on the task description.
     - Writes changes to disk, commits, and pushes to remote.
     - Marks the task as:
       - `status: "closed"`
       - `applied_branch: "cpai-xxxxxx"`
       - Appends an entry to `run_history` with branch + paths modified.

4. **Health Check**
   - Endpoint: `GET /health`
   - Returns a **dynamic health report** for the orchestrator, including:
     - Backend status
     - OpenAI connectivity (basic check)
     - Tasks storage folder availability
     - Target repo configuration status

> WhatsApp / Twilio integration is **planned**, but intentionally not wired yet in this repo snapshot.

---

## 🧠 High-level architecture

At a high level, CodePilot AI Orchestrator looks like this:

```text
[User / Portal]
      |
      v
POST /tasks/from-message
      |
      v
[Spec Agent (gpt-4o)]
      |
      v
 TaskSpec JSON
      |
      v     (later)
POST /tasks/{task_id}/apply-change
      |
      v
[Code Apply Agent] --[Git]--> New branch (cpai-xxxxxx) on target repo

