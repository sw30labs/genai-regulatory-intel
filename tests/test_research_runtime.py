"""Tests for research graph runtime controls."""

import json
from types import SimpleNamespace

from langgraph.graph import END, START, StateGraph

from regitel.agents.reflection import reflect_node
from regitel.agents.research import research_node
from regitel.config import RegitelConfig
from regitel.graphs import batch_orchestrator
from regitel.graphs.batch_orchestrator import run_batch_scan
from regitel.graphs.research_graph import (
    _apply_quick_scan_defaults,
    _route_after_reflection,
    _route_after_validation,
)
from regitel.models.state import ResearchState


def test_search_queries_and_structured_findings_are_replaceable():
    graph = StateGraph(ResearchState)

    def seed_node(state):
        return {
            "search_queries": [{"query": "old"}],
            "structured_findings": [{"regulation_id": "old"}],
        }

    def clear_node(state):
        return {"search_queries": [], "structured_findings": []}

    graph.add_node("seed", seed_node)
    graph.add_node("clear", clear_node)
    graph.add_edge(START, "seed")
    graph.add_edge("seed", "clear")
    graph.add_edge("clear", END)

    result = graph.compile().invoke({})

    assert result["search_queries"] == []
    assert result["structured_findings"] == []


def test_empty_reflection_queries_route_to_validation():
    assert _route_after_reflection({"search_queries": []}) == "validate"


def test_quality_gate_can_be_disabled():
    state = {
        "iteration_count": 0,
        "max_iterations": 3,
        "validation_passed": True,
        "structured_findings": [{"regulation_id": "eu-ai-act"}],
        "quality_gate_reflection": False,
    }

    assert _route_after_validation(state) == "persist"


def test_quick_scan_config_caps_expensive_fanout_without_mutating_original():
    cfg = RegitelConfig()

    quick = _apply_quick_scan_defaults(cfg)

    assert cfg.research.max_queries_per_jurisdiction == 8
    assert cfg.research.max_search_results_per_query == 10
    assert cfg.research.validator_batch_size == 4
    assert cfg.research.max_reflection_iterations == 3
    assert cfg.research.quality_gate_reflection is True
    assert quick.research.max_queries_per_jurisdiction == 3
    assert quick.research.max_search_results_per_query == 3
    assert quick.research.validator_batch_size == 3
    assert quick.research.max_reflection_iterations == 1
    assert quick.research.quality_gate_reflection is False


def test_research_node_respects_query_limit_and_keeps_existing_findings():
    class SearchTool:
        def __init__(self):
            self.calls = []

        def search(self, query):
            self.calls.append(query)
            return []

        def consume_usage(self):
            return {}

    search_tool = SearchTool()
    state = {
        "search_queries": [
            {"query": "q3", "priority": 3, "jurisdiction_id": "eu"},
            {"query": "q1", "priority": 1, "jurisdiction_id": "eu"},
            {"query": "q2", "priority": 2, "jurisdiction_id": "eu"},
        ],
        "structured_findings": [{"regulation_id": "existing"}],
    }

    result = research_node(
        state,
        llm=object(),
        search_tool=search_tool,
        seeds_map={"eu": {"name": "European Union"}},
        max_queries_per_jurisdiction=2,
    )

    assert search_tool.calls == ["q1", "q2"]
    assert result["structured_findings"] == [{"regulation_id": "existing"}]


def test_research_node_drops_cross_jurisdiction_extractions():
    class SearchTool:
        def search(self, query):
            return [{
                "title": "Result",
                "url": "https://example.com",
                "content": "Search result",
                "score": 1.0,
            }]

        def consume_usage(self):
            return {}

    class LLM:
        def invoke(self, messages):
            return SimpleNamespace(
                content=json.dumps([
                    {"regulation_id": "eu-cross", "jurisdiction_id": "eu"},
                    {"regulation_id": "usa-good", "jurisdiction_id": "usa"},
                ]),
                response_metadata={},
            )

    result = research_node(
        {"search_queries": [{"query": "q", "priority": 1, "jurisdiction_id": "usa"}]},
        llm=LLM(),
        search_tool=SearchTool(),
        seeds_map={"usa": {"name": "United States"}},
        max_queries_per_jurisdiction=1,
    )

    assert result["structured_findings"] == [
        {"regulation_id": "usa-good", "jurisdiction_id": "usa"}
    ]


def test_reflection_skips_queries_outside_active_jurisdiction():
    class LLM:
        def invoke(self, messages):
            return SimpleNamespace(
                content=json.dumps({
                    "analysis": "Repair needed",
                    "actions": [{
                        "regulation_id": "eu-ai-act",
                        "search_query": "official EU AI Act source",
                    }],
                    "drop_regulation_ids": [],
                    "keep_regulation_ids": [],
                }),
                response_metadata={},
            )

    result = reflect_node(
        {
            "jurisdictions": ["usa"],
            "structured_findings": [{"regulation_id": "usa-test", "jurisdiction_id": "usa"}],
            "validation_result": {"passed": False, "issues": []},
            "iteration_count": 0,
            "max_iterations": 3,
        },
        llm=LLM(),
    )

    assert result["search_queries"] == []


def test_batch_scan_all_has_enough_recursion_budget(monkeypatch):
    seeds = [
        {"id": f"j{i}", "name": f"Jurisdiction {i}", "research_priority": i}
        for i in range(16)
    ]

    def fake_run_research(*, config, jurisdictions, full_scan, dry_run, quick):
        return {
            "changes_detected": [],
            "structured_findings": [],
            "confidence_score": 1.0,
            "iteration_count": 0,
            "token_usage": {},
            "error": None,
        }

    monkeypatch.setattr(batch_orchestrator, "get_jurisdiction_seeds", lambda: seeds)
    import regitel.graphs.research_graph as research_graph
    monkeypatch.setattr(research_graph, "run_research", fake_run_research)

    result = run_batch_scan(RegitelConfig(), dry_run=True)

    assert result["summary"]["total_jurisdictions"] == 16
    assert result["summary"]["successful"] == 16
