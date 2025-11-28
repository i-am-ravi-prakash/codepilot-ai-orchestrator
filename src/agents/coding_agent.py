import os
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def _strip_code_fences(text: str) -> str:
    """
    If the model wraps the code in ```...``` fences, remove them.
    """
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        # Drop first fence line
        lines = lines[1:]
        # If last line is ``` drop it too
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def generate_updated_file_content(
    original_content: str,
    file_path: str,
    instruction: str,
    language_hint: str | None = None,
) -> str:
    lang_label = language_hint or ""
    system_prompt = (
        "You are CodePilot AI Coding Agent. "
        "You receive a source file and a requested change, and you must return the FULL updated file content. "
        "Do not explain. Do not add comments unless explicitly asked. "
        "Just return the updated code."
    )

    user_prompt = (
        f"File path: {file_path}\n"
        f"Language: {lang_label}\n\n"
        f"Current file content:\n"
        f"```{lang_label}\n"
        f"{original_content}\n"
        f"```\n\n"
        f"Change request:\n"
        f"{instruction}\n\n"
        "Return ONLY the updated file content. Do NOT wrap it in ``` or any extra text."
    )

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
    )

    content = response.choices[0].message.content or ""
    return _strip_code_fences(content)
