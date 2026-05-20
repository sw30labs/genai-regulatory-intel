"""Token usage helpers for OpenAI Responses API calls."""

from __future__ import annotations

from typing import Any


USAGE_KEYS = (
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "cached_input_tokens",
    "reasoning_tokens",
    "llm_calls",
    "web_search_calls",
)


def _to_dict(value: Any) -> dict:
    """Convert SDK objects, dicts, or simple objects to a plain dict."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    return {
        key: getattr(value, key)
        for key in dir(value)
        if not key.startswith("_") and not callable(getattr(value, key))
    }


def merge_usage(left: dict | None, right: dict | None) -> dict:
    """Sum token usage dictionaries."""
    merged: dict[str, int] = {}
    for key in set(left or {}) | set(right or {}) | set(USAGE_KEYS):
        value = int((left or {}).get(key, 0) or 0) + int((right or {}).get(key, 0) or 0)
        if value:
            merged[key] = value
    return merged


def openai_usage_from_response(response: Any, call_type: str | None = None) -> dict:
    """Extract normalized token usage from an OpenAI Responses API response."""
    usage = _to_dict(getattr(response, "usage", None))
    result: dict[str, int] = {}

    for key in ("input_tokens", "output_tokens", "total_tokens"):
        value = usage.get(key)
        if value:
            result[key] = int(value)

    input_details = _to_dict(usage.get("input_tokens_details"))
    cached = input_details.get("cached_tokens")
    if cached:
        result["cached_input_tokens"] = int(cached)

    output_details = _to_dict(usage.get("output_tokens_details"))
    reasoning = output_details.get("reasoning_tokens")
    if reasoning:
        result["reasoning_tokens"] = int(reasoning)

    if call_type == "llm":
        result["llm_calls"] = 1
    elif call_type == "web_search":
        result["web_search_calls"] = 1

    return result


def usage_from_message(message: Any) -> dict:
    """Extract token usage from a LangChain message response metadata."""
    metadata = getattr(message, "response_metadata", None) or {}
    usage = metadata.get("usage", {})
    return usage if isinstance(usage, dict) else {}
