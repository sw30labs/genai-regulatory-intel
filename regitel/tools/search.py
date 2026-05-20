"""Web search tools for the Research Agent."""

from __future__ import annotations

import logging
import os
from typing import Optional

from openai import OpenAI

from regitel.utils.json_parse import parse_model_json
from regitel.utils.usage import merge_usage, openai_usage_from_response

logger = logging.getLogger(__name__)


def _parse_json_payload(text: str) -> list[dict]:
    """Parse a JSON array or ``{"results": [...]}`` object from model output."""
    payload = parse_model_json(text, logger=logger, context="OpenAI web search")
    if payload is None:
        return []

    if isinstance(payload, dict):
        payload = payload.get("results", [])
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


class OpenAIWebSearchTool:
    """Wrapper around OpenAI Responses API hosted web search."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        max_results: int = 10,
        base_url: Optional[str] = None,
    ):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.model = model or os.environ.get("OPENAI_MODEL", "gpt-5.5")
        self.max_results = max_results
        self.base_url = base_url or os.environ.get("OPENAI_BASE_URL") or None
        self.client: OpenAI | None = None
        self.last_usage: dict = {}
        self.total_usage: dict = {}

        if self.api_key:
            kwargs = {"api_key": self.api_key}
            if self.base_url:
                kwargs["base_url"] = self.base_url
            self.client = OpenAI(**kwargs)

    def search(
        self,
        query: str,
        max_results: Optional[int] = None,
        include_domains: Optional[list[str]] = None,
        search_depth: str = "advanced",
    ) -> list[dict]:
        """Execute a web search and return title/url/content/score rows."""
        if not self.client:
            logger.warning("No OpenAI API key set — returning empty results")
            return []

        # The research extractor only consumes the top five results. Keeping
        # search JSON compact avoids response truncation and malformed output.
        limit = min(max_results or self.max_results, 5)
        tool: dict[str, object] = {"type": "web_search"}
        if include_domains:
            tool["filters"] = {"allowed_domains": include_domains}

        domain_note = (
            f"\nOnly use these domains when possible: {', '.join(include_domains)}."
            if include_domains else ""
        )
        prompt = f"""Search the web for current regulatory sources matching this query:
{query}
{domain_note}

Return a compact JSON object with a results array of up to {limit} objects. Each object must have:
- title: source title
- url: canonical source URL
- content: one sentence, maximum 240 characters
- score: relevance score from 0 to 1

Prefer official regulators, statutes, supervisory authorities, and primary sources."""

        try:
            response = self.client.responses.create(
                model=self.model,
                tools=[tool],
                tool_choice="required",
                input=prompt,
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "web_search_results",
                        "strict": True,
                        "schema": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "results": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "additionalProperties": False,
                                        "properties": {
                                            "title": {"type": "string"},
                                            "url": {"type": "string"},
                                            "content": {"type": "string"},
                                            "score": {"type": "number"},
                                        },
                                        "required": ["title", "url", "content", "score"],
                                    },
                                },
                            },
                            "required": ["results"],
                        },
                    },
                },
                max_output_tokens=4000,
            )
        except Exception as e:
            logger.error("OpenAI web search failed for '%s': %s", query, e)
            return []

        self.last_usage = openai_usage_from_response(response, call_type="web_search")
        self.total_usage = merge_usage(self.total_usage, self.last_usage)
        if getattr(response, "status", None) == "incomplete":
            logger.warning(
                "OpenAI web search response was incomplete for %r: %s",
                query,
                getattr(response, "incomplete_details", None),
            )

        rows = _parse_json_payload(response.output_text)
        results = []
        for idx, item in enumerate(rows[:limit]):
            try:
                score = float(item.get("score", max(0.0, 1.0 - idx * 0.05)))
            except (TypeError, ValueError):
                score = max(0.0, 1.0 - idx * 0.05)

            results.append({
                "title": str(item.get("title", "")),
                "url": str(item.get("url", "")),
                "content": str(item.get("content", "")),
                "score": score,
            })
        return results

    def consume_usage(self) -> dict:
        """Return and reset usage from the most recent search call."""
        usage = self.last_usage
        self.last_usage = {}
        return usage

    def search_batch(self, queries: list[dict]) -> dict[str, list[dict]]:
        """Execute multiple search queries, return results keyed by query string."""
        results = {}
        for q in queries:
            query_str = q["query"] if isinstance(q, dict) else q
            domains = q.get("domains") if isinstance(q, dict) else None
            results[query_str] = self.search(
                query_str,
                include_domains=domains,
            )
        return results


class MockSearchTool:
    """Mock search tool for dry-run / testing without API calls."""

    def search(self, query: str, **kwargs) -> list[dict]:
        return [{
            "title": f"[MOCK] Result for: {query}",
            "url": "https://example.com/mock",
            "content": f"Mock search result for query: {query}. "
                       "No actual web search was performed (dry-run mode).",
            "score": 0.5,
        }]

    def search_batch(self, queries: list[dict]) -> dict[str, list[dict]]:
        results = {}
        for q in queries:
            query_str = q["query"] if isinstance(q, dict) else q
            results[query_str] = self.search(query_str)
        return results

    def consume_usage(self) -> dict:
        return {}
