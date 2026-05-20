"""Tests for OpenAI Responses adapters."""

from types import SimpleNamespace

from regitel.tools.search import OpenAIWebSearchTool
from regitel.utils.llm import OpenAIResponsesChatModel


class FakeResponses:
    def __init__(self, output_text: str, usage=None):
        self.output_text = output_text
        self.usage = usage
        self.payload = None

    def create(self, **kwargs):
        self.payload = kwargs
        return SimpleNamespace(
            output_text=self.output_text,
            id="resp_test",
            model=kwargs["model"],
            usage=self.usage,
        )


class FakeClient:
    def __init__(self, output_text: str, usage=None):
        self.responses = FakeResponses(output_text, usage=usage)


def test_responses_llm_preserves_invoke_content_interface():
    llm = OpenAIResponsesChatModel(api_key="test-key", model="gpt-5.5")
    llm.client = FakeClient('{"ok": true}')

    response = llm.invoke([
        {"role": "system", "content": "Return JSON only."},
        {"role": "user", "content": "Plan search queries."},
    ])

    assert response.content == '{"ok": true}'
    payload = llm.client.responses.payload
    assert payload["model"] == "gpt-5.5"
    assert payload["instructions"] == "Return JSON only."
    assert payload["input"] == "USER:\nPlan search queries."
    assert payload["max_output_tokens"] == 4096
    assert "temperature" not in payload
    assert response.response_metadata["usage"] == {"llm_calls": 1}


def test_responses_llm_extracts_token_usage():
    usage = SimpleNamespace(
        input_tokens=120,
        output_tokens=30,
        total_tokens=150,
        input_tokens_details=SimpleNamespace(cached_tokens=20),
        output_tokens_details=SimpleNamespace(reasoning_tokens=10),
    )
    llm = OpenAIResponsesChatModel(api_key="test-key", model="gpt-5.5")
    llm.client = FakeClient("{}", usage=usage)

    response = llm.invoke([{"role": "user", "content": "Summarize."}])

    assert response.response_metadata["usage"] == {
        "input_tokens": 120,
        "output_tokens": 30,
        "total_tokens": 150,
        "cached_input_tokens": 20,
        "reasoning_tokens": 10,
        "llm_calls": 1,
    }


def test_openai_web_search_returns_research_result_shape():
    output = """
    [
      {
        "title": "Official AI Rule",
        "url": "https://regulator.example/rule",
        "content": "Summary of the relevant rule.",
        "score": 0.91
      }
    ]
    """
    usage = SimpleNamespace(input_tokens=80, output_tokens=20, total_tokens=100)
    search = OpenAIWebSearchTool(api_key="test-key", model="gpt-5.5", max_results=5)
    search.client = FakeClient(output, usage=usage)

    results = search.search("AI regulation banks", include_domains=["regulator.example"])

    assert results == [{
        "title": "Official AI Rule",
        "url": "https://regulator.example/rule",
        "content": "Summary of the relevant rule.",
        "score": 0.91,
    }]
    payload = search.client.responses.payload
    assert payload["tools"] == [{
        "type": "web_search",
        "filters": {"allowed_domains": ["regulator.example"]},
    }]
    assert payload["tool_choice"] == "required"
    assert payload["text"]["format"]["type"] == "json_schema"
    assert payload["text"]["format"]["schema"]["required"] == ["results"]
    assert search.consume_usage() == {
        "input_tokens": 80,
        "output_tokens": 20,
        "total_tokens": 100,
        "web_search_calls": 1,
    }
