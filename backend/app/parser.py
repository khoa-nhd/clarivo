import json
import re
from typing import Any


def _remove_reasoning_and_fences(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"^\s*```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```\s*$", "", text)
    return text.strip()


def _first_json_object(text: str) -> str:
    start = text.find("{")
    if start < 0:
        raise ValueError("The AI response did not contain a JSON object.")

    depth = 0
    in_string = False
    escaped = False

    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]

    raise ValueError("The AI response contained incomplete JSON.")


def parse_ai_json(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        raise ValueError(f"Unexpected AI response type: {type(raw).__name__}")

    cleaned = _remove_reasoning_and_fences(raw)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return json.loads(_first_json_object(cleaned))
