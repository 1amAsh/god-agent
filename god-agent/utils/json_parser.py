"""
utils/json_parser.py — Robust JSON extraction from LLM output.

Handles: markdown fences, leading/trailing prose, nested braces.
"""
from __future__ import annotations

import json
import re
from typing import Optional


def extract_json(text: str) -> Optional[dict]:
    """
    Extract the first complete JSON object from LLM text.
    Returns None if no valid JSON is found.
    """
    # Strip markdown code fences
    text = re.sub(r"```(?:json)?\s*", "", text)
    text = re.sub(r"```\s*", "", text).strip()

    # Direct parse attempt
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Brace-balanced extraction: walk character by character
    depth = 0
    start = None
    for i, ch in enumerate(text):
        if ch == "{":
            if start is None:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                candidate = text[start : i + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    start = None  # reset and keep scanning
    return None
