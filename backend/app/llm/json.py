from __future__ import annotations

import json
from typing import Any


def extract_json_object(raw: str) -> dict[str, Any] | None:
    text = raw.strip()
    if not text:
        return None

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    start = text.find("{")
    if start < 0:
        return None

    depth = 0
    for idx in range(start, len(text)):
        char = text[idx]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                fragment = text[start : idx + 1]
                try:
                    parsed = json.loads(fragment)
                except Exception:
                    return None
                if isinstance(parsed, dict):
                    return parsed
                return None
    return None

