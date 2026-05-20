"""LLM factory — creates OpenAI Responses API clients."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, TYPE_CHECKING

from langchain_core.messages import AIMessage
from openai import OpenAI

from regitel.utils.usage import openai_usage_from_response

if TYPE_CHECKING:
    from regitel.config import LLMEndpointConfig, RegitelConfig


logger = logging.getLogger(__name__)


def _message_content(message: Any) -> str:
    """Extract text content from LangChain messages or OpenAI-style dicts."""
    if isinstance(message, dict):
        content = message.get("content", "")
    else:
        content = getattr(message, "content", "")

    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part)
    return str(content)


def _message_role(message: Any) -> str:
    """Normalize message role from LangChain messages or OpenAI-style dicts."""
    if isinstance(message, dict):
        return str(message.get("role", "user"))

    role = getattr(message, "type", None) or getattr(message, "role", None) or "user"
    if role == "human":
        return "user"
    if role == "ai":
        return "assistant"
    return str(role)


def _responses_input(messages: list[Any]) -> tuple[str | None, str]:
    """Split system instructions from conversation text for Responses API."""
    instructions = []
    conversation = []

    for message in messages:
        role = _message_role(message)
        content = _message_content(message)
        if not content:
            continue
        if role in {"system", "developer"}:
            instructions.append(content)
        else:
            conversation.append(f"{role.upper()}:\n{content}")

    return "\n\n".join(instructions) or None, "\n\n".join(conversation)


@dataclass
class OpenAIResponsesChatModel:
    """Minimal chat adapter around the OpenAI Responses API.

    The agents only require ``invoke(messages).content``. Keeping that small
    interface avoids a wider LangChain migration while still using Responses.
    """

    api_key: str
    model: str
    temperature: float | None = None
    max_output_tokens: int = 4096
    base_url: str | None = None
    max_retries: int = 3
    client: OpenAI = field(init=False, repr=False)

    def __post_init__(self) -> None:
        kwargs: dict[str, Any] = {
            "api_key": self.api_key,
            "max_retries": self.max_retries,
        }
        if self.base_url:
            kwargs["base_url"] = self.base_url
        self.client = OpenAI(**kwargs)

    def invoke(self, messages: list[Any]) -> AIMessage:
        instructions, input_text = _responses_input(messages)
        payload: dict[str, Any] = {
            "model": self.model,
            "input": input_text,
            "max_output_tokens": self.max_output_tokens,
        }
        if instructions:
            payload["instructions"] = instructions
        if self.temperature is not None:
            payload["temperature"] = self.temperature

        response = self.client.responses.create(**payload)
        return AIMessage(
            content=response.output_text,
            response_metadata={
                "id": getattr(response, "id", None),
                "model": getattr(response, "model", self.model),
                "status": getattr(response, "status", None),
                "incomplete_details": getattr(response, "incomplete_details", None),
                "usage": openai_usage_from_response(response, call_type="llm"),
            },
        )


@lru_cache(maxsize=None)
def _get_llm(
    api_key: str,
    model: str,
    temperature: float | None,
    max_tokens: int,
    base_url: str | None = None,
) -> OpenAIResponsesChatModel:
    """Create a cached OpenAI Responses API client.

    Cached globally so all agents share the same client.
    """
    logger.info("Creating OpenAI Responses client (model=%s)", model)
    return OpenAIResponsesChatModel(
        api_key=api_key,
        model=model,
        temperature=temperature,
        max_output_tokens=max_tokens,
        base_url=base_url,
    )


def create_llm(endpoint: "LLMEndpointConfig") -> OpenAIResponsesChatModel:
    """Create an OpenAI Responses API client from endpoint config."""
    return _get_llm(
        api_key=endpoint.api_key,
        model=endpoint.model,
        temperature=endpoint.temperature,
        max_tokens=endpoint.max_tokens,
        base_url=endpoint.base_url,
    )


def get_agent_llm(
    config: "RegitelConfig",
    agent_name: str = "research",
) -> OpenAIResponsesChatModel:
    """Get the OpenAI Responses LLM instance. All agents share the same model."""
    logger.debug("Creating OpenAI Responses LLM for agent '%s'", agent_name)
    return create_llm(config.llm)
