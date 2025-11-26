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

    system_prompt = (
        "You are the Task Specification Agent for CodePilot AI. "
        "Your job is to convert a developer's free-text request into a clean JSON task."
    )

    user_prompt = f"""
User request:
\"\"\"{raw_text}\"\"\"

You must fill this JSON template (except task_id, created_at, source):

{{
  "type": "",
  "title": "",
  "description": "",
  "target_repo": "",
  "affected_files": [],
  "acceptance_criteria": [],
  "priority": ""
}}

Rules:
- type must be one of: "bugfix", "feature", "refactor".
- priority must be one of: "low", "medium", "high".
- Return ONLY valid JSON. Do NOT wrap it in ``` or any other text.
"""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",  "content": user_prompt},
        ],
        temperature=0.2,
    )

    content = response.choices[0].message.content.strip()
    print("🔍 RAW MODEL OUTPUT:\n", content)  # Helpful debug

    # Try to extract a clean JSON string
    json_str = _extract_json(content)
    data = json.loads(json_str)

    # Build final TaskSpec (which adds task_id, created_at, source)
    task = TaskSpec(
        task_id=template_task.task_id,
        created_at=template_task.created_at,
        source="WhatsApp",
        **data
    )
    return task.dict()
