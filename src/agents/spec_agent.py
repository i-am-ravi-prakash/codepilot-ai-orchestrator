import os
import json
from dotenv import load_dotenv
from openai import OpenAI
from src.models.task_spec import TaskSpec

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def _extract_json(content: str) -> str:
    """
    Try to extract a JSON object from the model output,
    even if it includes markdown fences or extra text.
    """
    content = content.strip()

    # If it starts with ``` remove code fences
    if content.startswith("```"):
        # Remove leading ``` or ```json
        lines = content.splitlines()
        # Drop first line (``` or ```json) and last line (```)
        if len(lines) >= 2:
            lines = lines[1:]
            if lines[-1].strip().startswith("```"):
                lines = lines[:-1]
        content = "\n".join(lines).strip()

    # Now find the first '{' and last '}'
    start = content.find("{")
    end = content.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"Could not find JSON object in content: {content!r}")

    json_str = content[start:end+1]
    return json_str


def generate_task_spec(raw_text: str) -> dict:
    """
    Takes a natural language request and returns a TaskSpec as a Python dict.
    """
    template_task = TaskSpec.create_default()

    system_prompt = """
You are CodePilot AI Spec Agent.

You receive a natural language request describing a code change, bug fix, or refactor
for a codebase (currently `journalApp`, a Java Spring Boot app).

Your job is to produce a JSON task specification with at least:

- title: short human-readable title
- description: clear explanation of what to change
- affected_files: array of relative file paths in the repo
    - If the user mentions specific file names or paths, use them.
    - If the user only describes the behavior or error, infer the most likely files
      based on the description (controllers, services, utilities, etc.).
    - If you are not sure, include a reasonable best guess and explain in description.

Do NOT include task_id, created_at, type, source, or target_repo in the JSON;
those will be added by the backend.

Return ONLY JSON.
""".strip()

    user_prompt = f"""
User request:
{raw_text}

Infer the task specification.
If file paths are not explicitly given, guess the most likely files
in the journalApp project.
""".strip()

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",  "content": user_prompt},
        ],
        temperature=0.2,
    )

    content = (response.choices[0].message.content or "").strip()
    print("🔍 RAW MODEL OUTPUT:\n", content)

    # Extract clean JSON and parse it
    json_str = _extract_json(content)
    data = json.loads(json_str)

    # Start from the default TaskSpec (which has all required fields)
    base = template_task.dict()

    # Overwrite with fields from the model (title, description, affected_files, etc.)
    base.update(data)

    # Force the correct source
    base["source"] = "CodePilot AI User Portal"

    # Validate using TaskSpec model
    task = TaskSpec(**base)
    return task.dict()


