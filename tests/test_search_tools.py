"""Tests for web search adapters."""

from types import SimpleNamespace

from regitel.tools.search import TavilySearchTool


class FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "results": [{
                "title": "EU AI Act",
                "url": "https://example.eu/ai-act",
                "content": "Official source summary",
                "score": 0.93,
            }]
        }


def test_tavily_search_maps_results_and_usage():
    calls = []

    def post(url, json):
        calls.append(SimpleNamespace(url=url, payload=json))
        return FakeResponse()

    tool = TavilySearchTool(
        api_key="test-key",
        max_results=10,
        client=SimpleNamespace(post=post),
    )

    results = tool.search("EU AI Act", include_domains=["example.eu"])

    assert calls[0].payload["max_results"] == 5
    assert calls[0].payload["include_domains"] == ["example.eu"]
    assert results == [{
        "title": "EU AI Act",
        "url": "https://example.eu/ai-act",
        "content": "Official source summary",
        "score": 0.93,
    }]
    assert tool.consume_usage() == {"web_search_calls": 1}
    assert tool.consume_usage() == {}

