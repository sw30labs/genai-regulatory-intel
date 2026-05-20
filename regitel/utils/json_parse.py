"""Robust JSON parsing for model outputs."""

from __future__ import annotations

import json
import logging
from typing import Any


def _strip_code_fences(text: str) -> str:
    lines = text.strip().splitlines()
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _extract_balanced_json(text: str) -> str | None:
    """Return the first balanced JSON object or array substring."""
    start = -1
    opener = ""
    for idx, char in enumerate(text):
        if char in "[{":
            start = idx
            opener = char
            break
    if start < 0:
        return None

    closer = "]" if opener == "[" else "}"
    stack = [closer]
    in_string = False
    escape = False

    for idx in range(start + 1, len(text)):
        char = text[idx]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char in "[{":
            stack.append("]" if char == "[" else "}")
        elif stack and char == stack[-1]:
            stack.pop()
            if not stack:
                return text[start:idx + 1]

    return None


def _salvage_array_items(text: str) -> list[Any]:
    """Parse complete top-level JSON values from a truncated array."""
    start = text.find("[")
    if start < 0:
        return []

    items = []
    idx = start + 1
    while idx < len(text):
        while idx < len(text) and text[idx] in " \r\n\t,":
            idx += 1
        if idx >= len(text) or text[idx] == "]":
            break
        if text[idx] not in "[{":
            break

        closer = "]" if text[idx] == "[" else "}"
        stack = [closer]
        in_string = False
        escape = False
        item_start = idx
        idx += 1

        while idx < len(text):
            char = text[idx]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                idx += 1
                continue

            if char == '"':
                in_string = True
            elif char in "[{":
                stack.append("]" if char == "[" else "}")
            elif stack and char == stack[-1]:
                stack.pop()
                if not stack:
                    item_text = text[item_start:idx + 1]
                    try:
                        items.append(json.loads(item_text))
                    except json.JSONDecodeError:
                        return items
                    idx += 1
                    break
            idx += 1

        if stack:
            break

    return items


def parse_model_json(text: str, *, logger: logging.Logger, context: str) -> Any:
    """Parse JSON from model text, tolerating fences and surrounding prose."""
    cleaned = _strip_code_fences(text)
    candidates = [cleaned]

    extracted = _extract_balanced_json(cleaned)
    if extracted and extracted != cleaned:
        candidates.append(extracted)

    last_error: json.JSONDecodeError | None = None
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = exc

    salvaged = _salvage_array_items(cleaned)
    if salvaged:
        logger.warning(
            "%s JSON was incomplete; salvaged %d complete array item(s); length=%s; tail=%r",
            context,
            len(salvaged),
            len(cleaned),
            cleaned[-240:],
        )
        return salvaged

    if last_error:
        logger.error(
            "%s JSON parse failed: %s at line %s column %s char %s; length=%s; "
            "head=%r; tail=%r",
            context,
            last_error.msg,
            last_error.lineno,
            last_error.colno,
            last_error.pos,
            len(cleaned),
            cleaned[:240],
            cleaned[-240:],
        )
    else:
        logger.error("%s JSON parse failed: no JSON object or array found; head=%r", context, cleaned[:240])

    return None
