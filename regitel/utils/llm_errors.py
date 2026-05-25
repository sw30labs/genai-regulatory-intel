"""Provider error helpers for LLM-backed agents."""

from __future__ import annotations

from typing import Any


class LLMProviderError(RuntimeError):
    """Raised when an LLM-backed step cannot produce a trustworthy result."""

    def __init__(self, message: str, *, fatal: bool = False):
        super().__init__(message)
        self.fatal = fatal


def _error_text(value: Any) -> str:
    parts = [str(value)]
    for attr in ("code", "type", "message"):
        detail = getattr(value, attr, None)
        if detail:
            parts.append(str(detail))
    return " ".join(parts).lower()


def is_insufficient_quota_error(value: Any) -> bool:
    """Return True when an exception/message is an explicit provider quota failure."""
    text = _error_text(value)
    return "insufficient_quota" in text or "exceeded your current quota" in text

