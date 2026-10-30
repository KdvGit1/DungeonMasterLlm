"""
llm_utils.py — Robust JSON extraction from LLM responses.

Many models (especially cloud/API models like minimax) wrap JSON in extra text,
<think>...</think> blocks, markdown fences, or explanatory prose.
These utilities handle all those cases reliably.
"""

import json
import re


def strip_think_blocks(text):
    """Remove <think>...</think> reasoning blocks that some models prepend."""
    return re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()


def _clean_llm_response(text):
    """Common cleanup: strip think blocks, markdown fences, whitespace."""
    text = strip_think_blocks(text)
    # Remove markdown code fences (```json ... ``` or ``` ... ```)
    text = re.sub(r'```(?:json)?\s*', '', text)
    text = re.sub(r'```', '', text)
    return text.strip()


def extract_json_object(text):
    """
    Extract the first valid JSON object {...} from text.
    Handles nested braces correctly by trying json.loads on progressively larger substrings.

    Returns: parsed dict, or None if no valid JSON object was found.
    """
    text = _clean_llm_response(text)

    # Fast path: entire text is valid JSON
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, ValueError):
        pass

    # Find all '{' positions and try to parse from each one
    for i, ch in enumerate(text):
        if ch == '{':
            # Find matching closing brace by counting nesting
            depth = 0
            for j in range(i, len(text)):
                if text[j] == '{':
                    depth += 1
                elif text[j] == '}':
                    depth -= 1
                    if depth == 0:
                        candidate = text[i:j+1]
                        try:
                            data = json.loads(candidate)
                            if isinstance(data, dict):
                                return data
                        except (json.JSONDecodeError, ValueError):
                            pass
                        break  # This opening brace didn't work, try next one

    return None


def extract_json_array(text):
    """
    Extract the first valid JSON array [...] from text.
    Handles nested brackets correctly.

    Also handles the edge case where the model returns a single object {...}
    instead of an array [{...}] — wraps it in a list.

    Returns: parsed list, or None if no valid JSON was found.
    """
    text = _clean_llm_response(text)

    # Fast path: entire text is valid JSON array
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return [data]  # Single object → wrap in list
    except (json.JSONDecodeError, ValueError):
        pass

    # Find all '[' positions and try to parse from each one
    for i, ch in enumerate(text):
        if ch == '[':
            depth = 0
            for j in range(i, len(text)):
                if text[j] == '[':
                    depth += 1
                elif text[j] == ']':
                    depth -= 1
                    if depth == 0:
                        candidate = text[i:j+1]
                        try:
                            data = json.loads(candidate)
                            if isinstance(data, list):
                                return data
                        except (json.JSONDecodeError, ValueError):
                            pass
                        break

    # Fallback: maybe the model returned a single JSON object without array wrapper
    obj = extract_json_object(text)
    if obj is not None:
        return [obj]

    return None
