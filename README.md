# CodePilot AI  (Task Spec Agent)

## Project in progress

CodePilot AI is an AI-powered developer assistant that turns natural language requests (e.g., from WhatsApp) into structured development tasks.

What is implemented?

- ✅ FastAPI backend
- ✅ Endpoint: `POST /tasks/from-message`
  - Input: Natural language text message (e.g. "Fix bug in /transactions API when amount is null")
  - Uses OpenAI (`gpt-4o`) to:
    - Analyse the message
    - Generate a structured TaskSpec JSON:
      - type (bugfix/feature/refactor)
      - title
      - description
      - priority
      - acceptance_criteria
  - Saves the TaskSpec into `tasks/{task_id}.json`

- ✅ Endpoint: `GET /tasks`
  - Lists all created tasks (summary view)

- ✅ Endpoint: `GET /tasks/{task_id}`
  - Returns full JSON details of a single task

## Tech Stack

- Backend: Python 3 + FastAPI
- AI: OpenAI `gpt-4o`
- Data storage: Local JSON files (`tasks/` folder)

<!--

## How to run

```bash
git clone <your-repo-url>
cd codepilot-ai-orchestrator

python -m venv venv
source venv/bin/activate  # on macOS / Linux
# OR venv\Scripts\activate on Windows

pip install -r requirements.txt

# Create .env file in project root:
# OPENAI_API_KEY=sk-...

uvicorn src.main:app --reload
-->
